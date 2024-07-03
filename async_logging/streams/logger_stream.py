import asyncio
import datetime
import io
import os
import pathlib
import platform
import sys
import threading
import uuid
from collections import defaultdict
from typing import Dict, Set

import msgspec
import zstandard

from async_logging.models import Entry, LogLevel, NodeType
from async_logging.rotation import TimeParser
from async_logging.snowflake import Snowflake, SnowflakeGenerator

from .protocol import LoggerProtocol
from .stream_type import StreamType


def anchor():
    """
    Ordinarily we would use __file__ for this, but frozen modules don't always
    have __file__ set, for some reason (see Issue logging#21736). Thus, we get
    the filename from a handy code object from a function defined in this
    module.
    """
    raise NotImplementedError(
        "I shouldn't be called. My only purpose is to provide "
        "the filename from a handy code object."
    )


# _srcfile is used when walking the stack to check when we've got the first
# caller stack frame, by skipping frames whose filename is that of this
# module's source. It therefore should contain the filename of this module's
# source file.
_srcfile = anchor.__code__.co_filename


class LoggerStream:
    def __init__(self) -> None:
        self._stdout: io.TextIO | None = None
        self._stderr: io.TextIO | None = None
        self._init_lock = asyncio.Lock()
        self._stream_writer: asyncio.StreamWriter | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._generator: SnowflakeGenerator | None = None
        self._compressor: zstandard.ZstdCompressor | None = None

        self._files: Dict[str, io.FileIO] = {}
        self._file_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._cwd: str | None = None
        self._default_logfile_path: str | None = None
        self._rotation_schedules: Dict[str, float] = {}

    async def initialize(
        self,
        stream_type: StreamType = StreamType.STDOUT,
    ) -> asyncio.StreamWriter:
        if self._stdout is None:
            self._stdout = sys.stdout

        if self._stderr is None:
            self._stderr = sys.stderr

        if self._generator is None:
            self._generator = SnowflakeGenerator(
                (uuid.uuid1().int + threading.get_native_id()) >> 64
            )

        if self._compressor is None:
            self._compressor = zstandard.ZstdCompressor()

        if self._loop is None:
            self._loop = asyncio.get_event_loop()

        async with self._init_lock:
            if self._stream_writer is None:
                transport, protocol = await self._loop.connect_write_pipe(
                    lambda: LoggerProtocol(),
                    self._stdout if stream_type == StreamType.STDOUT else self._stderr,
                )

                self._stream_writer = asyncio.StreamWriter(
                    transport, protocol, None, self._loop
                )

            return self._stream_writer

    async def open_file(
        self,
        filename: str,
        directory: str | None = None,
        is_default: bool = False,
        rotation_schedule: str = None,
    ):
        if self._cwd is None:
            self._cwd = await asyncio.to_thread(os.getcwd)

        logfile_path = self._to_logfile_path(filename, directory=directory)
        await self._file_locks[logfile_path].acquire()

        await asyncio.to_thread(
            self._open_file,
            logfile_path,
        )

        self._file_locks[logfile_path].release()

        if rotation_schedule and self._rotation_schedules.get(logfile_path) is None:
            self._rotation_schedules[logfile_path] = TimeParser(rotation_schedule).time

        if is_default:
            self._default_logfile_path = logfile_path

    def _open_file(self, logfile_path: str):
        resolved_path = pathlib.Path(logfile_path).absolute().resolve()
        logfile_directory = str(resolved_path.parent)
        path = str(resolved_path)

        if not os.path.exists(logfile_directory):
            os.makedirs(logfile_directory)

        if not os.path.exists(path):
            resolved_path.touch()

        else:
            self._files[logfile_path] = open(path, "r+")

    def _get_creation_date(self, logfile_path: str):
        resolved_path = pathlib.Path(logfile_path)
        path = str(resolved_path.absolute().resolve())

        if not os.path.exists(logfile_path):
            return

        if platform.system() == "Windows":
            return os.path.getctime(path)
        else:
            stat = os.stat(path)
            try:
                return stat.st_birthtime
            except AttributeError:
                # We're probably on Linux. No easy way to get creation dates here,
                # so we'll settle for when its content was last modified.
                return stat.st_mtime

    def _rotate_logfile(
        self,
        rotation_max_age: float,
        logfile_path: str,
    ):
        created_time = self._get_creation_date(logfile_path)

        file_age_seconds = datetime.datetime.now().timestamp() - created_time
        resolved_path = pathlib.Path(logfile_path)
        path = str(resolved_path.absolute().resolve())
        logfile_data = b""

        if file_age_seconds >= rotation_max_age:
            self._files[logfile_path].close()

            with open(path, "rb") as logfile:
                logfile_data = self._compressor.compress(logfile.read())

        if len(logfile_data) > 0:
            timestamp = datetime.datetime.now().timestamp()
            archived_filename = f"{resolved_path.stem}_archived_{timestamp}.zst"
            archive_path = os.path.join(
                str(resolved_path.parent.absolute().resolve()),
                archived_filename,
            )

            with open(archive_path, "wb") as archived_file:
                archived_file.write(logfile_data)

            self._files[logfile_path] = open(path, "wb")

    async def close(self):
        await asyncio.gather(
            *[self._close_file(logfile_path) for logfile_path in self._files]
        )

        await self._stream_writer.drain()
        self._stream_writer.close()

    async def close_file(
        self,
        filename: str,
        directory: str | None = None,
    ):
        if self._cwd is None:
            self._cwd = await asyncio.to_thread(os.getcwd)

        logfile_path = self._to_logfile_path(filename, directory=directory)
        await self._close_file(logfile_path)

    async def _close_file(self, logfile_path: str):
        if file_lock := self._file_locks.get(logfile_path):
            await file_lock.acquire()
            await asyncio.to_thread(
                self._close_file_at_path,
                logfile_path,
            )

            file_lock.release()

    def _close_file_at_path(self, logfile_path: str):
        if logfile := self._files.get(logfile_path):
            logfile.close()

    def _to_logfile_path(
        self,
        filename: str,
        directory: str | None = None,
    ):
        filename_path = pathlib.Path(filename)

        assert (
            filename_path.suffix == ".json"
        ), "Err. - file must be JSON file for logs."

        if directory is None:
            directory: str = os.path.join(self._cwd, "logs")

        logfile_path: str = os.path.join(directory, filename_path)

        return logfile_path

    async def log(
        self,
        event: str,
        context: str,
        snowflake_id: int | None = None,
        test: str | None = None,
        workflow: str | None = None,
        hook: str | None = None,
        level: LogLevel = LogLevel.INFO,
        node_type: NodeType = NodeType.WORKER,
        location: str = "local",
        tags: Set[str] | None = None,
    ):
        """
        Actually log the specified logging record to the stream.
        """
        if self._stream_writer is None:
            self._stream_writer = await self.initialize()

        if snowflake_id is None:
            snowflake_id = self._generator.generate()

        if tags is None:
            tags = set()

        log_file, line_number, function_name = self.find_caller()
        snowlfake = Snowflake.parse(snowflake_id)

        try:
            record = Entry(
                level=level,
                node_type=node_type,
                timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
                node_id=snowlfake.instance,
                epoch=snowlfake.epoch,
                sequence=snowlfake.seq,
                thread_id=threading.get_native_id(),
                line_number=line_number,
                filename=log_file,
                function_name=function_name,
                event=event,
                context=context,
                test=test,
                workflow=workflow,
                hook=hook,
                location=location,
                tags=tags,
            )

            self._stream_writer.write(record.to_message())
            await self._stream_writer.drain()

        except Exception as err:
            record = Entry(
                level=LogLevel.ERROR,
                node_type=node_type,
                timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
                node_id=snowlfake.instance,
                epoch=snowlfake.epoch,
                sequence=snowlfake.seq,
                thread_id=threading.get_native_id(),
                line_number=line_number,
                filename=log_file,
                function_name=function_name,
                event="logging_error",
                context=str(err),
                test=test,
                workflow=workflow,
                hook=hook,
                location=location,
                tags=tags,
            )

            await asyncio.to_thread(sys.stderr.write, record.to_error_string())

    async def log_to_file(
        self,
        event: str,
        context: str,
        snowflake_id: int | None = None,
        test: str | None = None,
        workflow: str | None = None,
        hook: str | None = None,
        level: LogLevel = LogLevel.INFO,
        node_type: NodeType = NodeType.WORKER,
        location: str = "local",
        tags: Set[str] | None = None,
        filename: str | None = None,
        directory: str | None = None,
        rotation_schedule: str | None = None,
    ):
        if self._cwd is None:
            self._cwd = await asyncio.to_thread(os.getcwd)

        if filename and directory:
            logfile_path = self._to_logfile_path(
                filename,
                directory=directory,
            )

        elif self._default_logfile_path:
            logfile_path = self._default_logfile_path

        else:
            filename = "logs.json"
            directory = os.path.join(self._cwd, "logs")
            logfile_path = os.path.join(directory, filename)

        if snowflake_id is None:
            snowflake_id = self._generator.generate()

        if tags is None:
            tags = set()

        if self._files.get(logfile_path) is None:
            await self.open_file(
                filename,
                directory=directory,
            )

        if self._rotation_schedules.get(logfile_path):
            await asyncio.to_thread(
                self._rotate_logfile,
                self._rotation_schedules[logfile_path],
                logfile_path,
            )

        log_file, line_number, function_name = self.find_caller()
        snowlfake = Snowflake.parse(snowflake_id)

        try:
            record = Entry(
                level=level,
                node_type=node_type,
                timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
                node_id=snowlfake.instance,
                epoch=snowlfake.epoch,
                sequence=snowlfake.seq,
                thread_id=threading.get_native_id(),
                line_number=line_number,
                filename=log_file,
                function_name=function_name,
                event=event,
                context=context,
                test=test,
                workflow=workflow,
                hook=hook,
                location=location,
                tags=tags,
            )

            await asyncio.to_thread(
                self._write_to_file,
                record,
                logfile_path,
            )

        except Exception as err:
            record = Entry(
                level=LogLevel.ERROR,
                node_type=node_type,
                timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
                node_id=snowlfake.instance,
                epoch=snowlfake.epoch,
                sequence=snowlfake.seq,
                thread_id=threading.get_native_id(),
                line_number=line_number,
                filename=log_file,
                function_name=function_name,
                event="logging_error",
                context=str(err),
                test=test,
                workflow=workflow,
                hook=hook,
                location=location,
                tags=tags,
            )

            await asyncio.to_thread(sys.stderr.write, record.to_error_string())

    def _write_to_file(
        self,
        entry: Entry,
        logfile_path: str,
    ):
        if logfile := self._files.get(logfile_path):
            logfile.write(msgspec.json.encode(entry) + b"\n")

    def find_caller(self):
        """
        Find the stack frame of the caller so that we can note the source
        file name, line number and function name.
        """
        frame = sys._getframe(2)
        code = frame.f_code

        return (
            code.co_filename,
            frame.f_lineno,
            code.co_name,
        )

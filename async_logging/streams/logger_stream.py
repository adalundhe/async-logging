import asyncio
import datetime
import io
import os
import pathlib
import sys
import threading
import uuid
from collections import defaultdict
from typing import Dict

import msgspec
import zstandard

from async_logging.config.logging_config import LoggingConfig
from async_logging.models import Entry, LogLevel
from async_logging.rotation import TimeParser
from async_logging.snowflake import SnowflakeGenerator

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
    def __init__(self, name: str | None = None) -> None:
        if name is None:
            name = "default"

        self._name = name
        self._stdout: io.TextIO | None = None
        self._stderr: io.TextIO | None = None
        self._init_lock = asyncio.Lock()
        self._stream_writers: Dict[StreamType, asyncio.StreamWriter] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._generator: SnowflakeGenerator | None = None
        self._compressor: zstandard.ZstdCompressor | None = None

        self._files: Dict[str, io.FileIO] = {}
        self._file_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._cwd: str | None = None
        self._default_logfile_path: str | None = None
        self._rotation_schedules: Dict[str, float] = {}
        self._config = LoggingConfig()
        self._initialized: bool = False

    async def initialize(self) -> asyncio.StreamWriter:
        if self._generator is None:
            self._generator = SnowflakeGenerator(
                (uuid.uuid1().int + threading.get_native_id()) >> 64
            )

        if self._compressor is None:
            self._compressor = zstandard.ZstdCompressor()

        if self._loop is None:
            self._loop = asyncio.get_event_loop()

        async with self._init_lock:
            if self._stream_writers.get(StreamType.STDOUT) is None:
                transport, protocol = await self._loop.connect_write_pipe(
                    lambda: LoggerProtocol(), sys.stdout
                )

                self._stream_writers[StreamType.STDOUT] = asyncio.StreamWriter(
                    transport,
                    protocol,
                    None,
                    self._loop,
                )

            if self._stream_writers.get(StreamType.STDERR) is None:
                transport, protocol = await self._loop.connect_write_pipe(
                    lambda: LoggerProtocol(), sys.stderr
                )

                self._stream_writers[StreamType.STDERR] = asyncio.StreamWriter(
                    transport,
                    protocol,
                    None,
                    self._loop,
                )

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

        self._files[logfile_path] = open(path, "ab+")

    async def _rotate(
        self,
        logfile_path: str,
    ):
        await self._file_locks[logfile_path].acquire()
        await asyncio.to_thread(
            self._rotate_logfile,
            self._rotation_schedules[logfile_path],
            logfile_path,
        )

        self._file_locks[logfile_path].release()

    def _get_logfile_metadata(self, logfile_path: str) -> Dict[str, float]:
        resolved_path = pathlib.Path(logfile_path)

        logfile_metadata_path = os.path.join(
            str(resolved_path.parent.absolute().resolve()), ".logging.json"
        )

        if os.path.exists(logfile_metadata_path):
            metadata_file = open(logfile_metadata_path, "+rb")
            return msgspec.json.decode(metadata_file.read())

        return {}

    def _update_logfile_metadata(
        self,
        logfile_path: str,
        logfile_metadata: Dict[str, float],
    ):
        resolved_path = pathlib.Path(logfile_path)

        logfile_metadata_path = os.path.join(
            str(resolved_path.parent.absolute().resolve()), ".logging.json"
        )

        with open(logfile_metadata_path, "+wb") as metadata_file:
            metadata_file.write(msgspec.json.encode(logfile_metadata))

    def _rotate_logfile(
        self,
        rotation_max_age: float,
        logfile_path: str,
    ):
        resolved_path = pathlib.Path(logfile_path)
        path = str(resolved_path.absolute().resolve())

        logfile_metadata = self._get_logfile_metadata(logfile_path)

        created_time = logfile_metadata.get(
            logfile_path, datetime.datetime.now().timestamp()
        )

        file_age_seconds = datetime.datetime.now().timestamp() - created_time
        logfile_data = b""

        if file_age_seconds >= rotation_max_age:
            self._files[logfile_path].close()

            with open(path, "rb") as logfile:
                logfile_data = self._compressor.compress(logfile.read())

        if len(logfile_data) > 0:
            timestamp = datetime.datetime.now().timestamp()
            archived_filename = f"{resolved_path.stem}_{timestamp}_archived.zst"
            archive_path = os.path.join(
                str(resolved_path.parent.absolute().resolve()),
                archived_filename,
            )

            with open(archive_path, "wb") as archived_file:
                archived_file.write(logfile_data)

            self._files[logfile_path] = open(path, "wb+")
            created_time = datetime.datetime.now().timestamp()

        logfile_metadata[logfile_path] = created_time

        self._update_logfile_metadata(logfile_path, logfile_metadata)

    async def close(self):
        await asyncio.gather(
            *[self._close_file(logfile_path) for logfile_path in self._files]
        )

        await asyncio.gather(
            *[writer.drain() for writer in self._stream_writers.values()]
        )

        for writer in self._stream_writers.values():
            writer.close()

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
        entry: Entry,
        template: str | None = None,
        filename: str | None = None,
        directory: str | None = None,
        rotation_schedule: str | None = None,
    ):
        if filename:
            await self._log_to_file(
                entry,
                filename=filename,
                directory=directory,
                rotation_schedule=rotation_schedule,
            )

        else:
            await self._log(
                entry,
                template=template,
            )

    async def _log(
        self,
        entry: Entry,
        template: str | None = None,
    ):
        stream = (
            StreamType.STDOUT
            if entry.level
            in [
                LogLevel.DEBUG,
                LogLevel.INFO,
                LogLevel.ERROR,
            ]
            else StreamType.STDERR
        )

        if self._config.enabled(self._name, entry.level) is False:
            return

        if self._initialized is None:
            await self.initialize()

        stream_writer = self._stream_writers[stream]

        if template is None:
            template = "{timestamp} - {level} - {thread_id} - {filename}:{function_name}.{line_number} - {message}"

        log_file, line_number, function_name = self.find_caller()

        try:
            stream_writer.write(
                entry.to_template(
                    template,
                    context={
                        "filename": log_file,
                        "function_name": function_name,
                        "line_number": line_number,
                    },
                ).encode()
                + b"\n"
            )
            await stream_writer.drain()

        except Exception as err:
            error_template = "{timestamp} - {level} - {thread_id}.{filename}:{function_name}.{line_number} - {error}"

            await asyncio.to_thread(
                sys.stderr.write,
                entry.to_template(
                    error_template,
                    context={
                        "filename": log_file,
                        "function_name": function_name,
                        "line_number": line_number,
                        "error": str(err),
                    },
                ),
            )

    async def _log_to_file(
        self,
        entry: Entry,
        filename: str | None = None,
        directory: str | None = None,
        rotation_schedule: str | None = None,
    ):
        if self._config.enabled(self._name, entry.level) is False:
            return

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

        if self._files.get(logfile_path) is None:
            await self.open_file(
                filename,
                directory=directory,
            )

        if rotation_schedule:
            self._rotation_schedules[logfile_path] = TimeParser(rotation_schedule).time

        if self._rotation_schedules.get(logfile_path):
            await self._rotate(logfile_path)

        log_file, line_number, function_name = self.find_caller()

        try:
            entry_dict = entry.to_dict()
            entry_dict.update(
                {
                    "filename": log_file,
                    "function_name": function_name,
                    "line_number": line_number,
                }
            )

            await asyncio.to_thread(
                self._write_to_file,
                entry,
                logfile_path,
            )

        except Exception as err:
            error_template = "{timestamp} - {level} - {thread_id}.{filename}:{function_name}.{line_number} - {error}"

            await asyncio.to_thread(
                sys.stderr.write,
                entry.to_template(
                    error_template,
                    context={
                        "filename": log_file,
                        "function_name": function_name,
                        "line_number": line_number,
                        "error": str(err),
                    },
                ),
            )

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

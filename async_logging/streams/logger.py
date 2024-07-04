from collections import defaultdict
from typing import Dict

from async_logging.models import Entry, LogLevel

from .logger_context import LoggerContext
from .logger_stream import LoggerStream
from .stream_type import StreamType


class Logger:
    def __init__(self) -> None:
        self._streams: Dict[str, LoggerStream] = defaultdict(LoggerStream)

    def __getitem__(self, logger_name: str):
        return self._streams[logger_name]

    def create_context(
        self,
        filename: str | None = None,
        directory: str | None = None,
        rotation_schedule: str | None = None,
    ):
        context = LoggerContext(
            filename=filename,
            directory=directory,
            rotation_schedule=rotation_schedule,
        )

        return context

    async def log(
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

        return await self._streams["default"].log(
            entry,
            template=template,
            stream=stream,
        )

    async def log_to_file(
        self,
        entry: Entry,
        filename: str | None = None,
        directory: str | None = None,
        rotation_schedule: str | None = None,
    ):
        return await self._streams["default"].log_to_file(
            entry,
            filename=filename,
            directory=directory,
            rotation_schedule=rotation_schedule,
        )

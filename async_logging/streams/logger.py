from collections import defaultdict
from typing import Dict, Set

from async_logging.models import LogLevel, NodeType

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
        stream_type: StreamType = StreamType.STDOUT,
        rotation_schedule: str | None = None,
    ):
        context = LoggerContext(
            filename=filename,
            directory=directory,
            stream_type=stream_type,
            rotation_schedule=rotation_schedule,
        )

        return context

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
        return await self._streams["default"].log(
            event,
            context,
            snowflake_id=snowflake_id,
            test=test,
            workflow=workflow,
            hook=hook,
            level=level,
            node_type=node_type,
            location=location,
            tags=tags,
        )

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
        return await self._streams["default"].log_to_file(
            event,
            context,
            snowflake_id=snowflake_id,
            test=test,
            workflow=workflow,
            hook=hook,
            level=level,
            node_type=node_type,
            location=location,
            tags=tags,
            filename=filename,
            directory=directory,
            rotation_schedule=rotation_schedule,
        )

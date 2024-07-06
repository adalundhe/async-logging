from __future__ import annotations
import asyncio
from collections import defaultdict
from typing import (
    Dict, 
    TypeVar, 
)
import pathlib
from async_logging.models import Entry
from .logger_stream import LoggerStream
from .logger_context import LoggerContext


T = TypeVar('T', bound=Entry)


class Logger:
    def __init__(self) -> None:
        self._streams: Dict[str, LoggerStream] = defaultdict(LoggerStream)
        self._contexts: Dict[str, LoggerContext] = {}

    def __getitem__(self, logger_name: str):
        return self._streams[logger_name]

    def create_context(
        self,
        name: str | None = None,
        template: str | None = None,
        path: str | None = None,
        rotation_schedule: str | None = None,
    ):
        if name is None:
            name = 'default'

        filename: str | None = None
        directory: str | None = None

        if path:
            logfile_path = pathlib.Path(path)
            is_logfile = len(logfile_path.suffix) > 0 

            filename = logfile_path.name if is_logfile else None
            directory = str(logfile_path.parent.absolute()) if is_logfile else str(logfile_path.absolute())

        if self._contexts.get(name) is None:

            self._contexts[name] = LoggerContext(
                name=name,
                template=template,
                filename=filename,
                directory=directory,
                rotation_schedule=rotation_schedule,
            )

        return self._contexts[name]
    
    async def create(
        self,
        name: str | None = None,
        template: str | None = None,
        path: str | None = None,
        rotation_schedule: str | None = None,
    ):
        if name is None:
            name = 'default'

        filename: str | None = None
        directory: str | None = None

        if path:
            logfile_path = pathlib.Path(path)
            is_logfile = len(logfile_path.suffix) > 0 

            filename = logfile_path.name if is_logfile else None
            directory = str(logfile_path.parent.absolute()) if is_logfile else str(logfile_path.absolute())

        stream = LoggerStream(
            name=name,
            template=template,
            filename=filename,
            directory=directory,
            rotation_schedule=rotation_schedule
            
        )
        
        await stream.initialize()

        self._streams[name] = stream

        return stream
    
    async def subscribe(
        self, 
        logger: Logger,
        name: str | None = None,
        template: str | None = None,
        path: str | None = None,
        rotation_schedule: str | None = None,
    ):
        filename: str | None = None
        directory: str | None = None

        if name is None:
            name = 'default'

        if path:
            logfile_path = pathlib.Path(path)
            is_logfile = len(logfile_path.suffix) > 0 

            filename = logfile_path.name if is_logfile else None
            directory = str(logfile_path.parent.absolute()) if is_logfile else str(logfile_path.absolute())

        if self._streams.get(name) is None:
            stream = LoggerStream(
                name=name,
                template=template,
                filename=filename,
                directory=directory,
                rotation_schedule=rotation_schedule
            )
            await stream.initialize()
            self._streams[name] = stream

        if logger._streams.get(name) is None:
            stream = LoggerStream(
                name=name,
                template=template,
                filename=filename,
                directory=directory,
                rotation_schedule=rotation_schedule
            )

            await stream.initialize()
            logger._streams[name] = stream

        if self._contexts.get(name) is None:
            self._contexts[name] = LoggerContext(
                name=name,
                template=template,
                filename=filename,
                directory=directory,
                rotation_schedule=rotation_schedule,
            )

            await self._contexts[name].stream.initialize()

        if logger._contexts.get(name) is None:
            logger._contexts[name] = LoggerContext(
                name=name,
                template=template,
                filename=filename,
                directory=directory,
                rotation_schedule=rotation_schedule,
            )

            await logger._contexts[name].stream.initialize()

        logger._streams[name]._provider.subscribe(self._streams[name]._consumer)
        logger._contexts[name].stream._provider.subscribe(self._contexts[name].stream._consumer)

    async def close(self):

        streams_count = len(self._streams)

        if streams_count > 0:
            await asyncio.gather(*[
                stream.close() for stream in self._streams.values()
            ])

        contexts_count = len(self._contexts)

        if contexts_count > 0:
            await asyncio.gather(*[
                context.stream.close() for context in self._contexts.values()
            ])

    def abort(self):

        for stream in self._streams.values():
            stream.abort()

        for context in self._contexts.values():
            context.stream.abort()



    
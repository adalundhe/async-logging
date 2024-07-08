from __future__ import annotations
import asyncio
from collections import defaultdict
from typing import (
    Dict, 
    TypeVar,
    Callable,
)
import pathlib
from async_logging.models import Entry
from .logger_stream import LoggerStream
from .logger_context import LoggerContext
from .retention_policy import RetentionPolicyConfig


T = TypeVar('T', bound=Entry)


class Logger:
    def __init__(self) -> None:
        self._streams: Dict[str, LoggerStream] = defaultdict(LoggerStream)
        self._contexts: Dict[str, LoggerContext] = {}
        self._watch_tasks: Dict[str, asyncio.Task] = {}

    def __getitem__(self, logger_name: str):
        return self._streams[logger_name]

    def create_context(
        self,
        name: str | None = None,
        template: str | None = None,
        path: str | None = None,
        retention_policy: RetentionPolicyConfig | None = None,
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
                retention_policy=retention_policy,
            )

        else:
            self._contexts[name].name = name if name else self._contexts[name].name
            self._contexts[name].template = template if template else self._contexts[name].template
            self._contexts[name].filename = filename if filename else self._contexts[name].filename
            self._contexts[name].directory = directory if directory else self._contexts[name].directory
            self._contexts[name].retention_policy = retention_policy if retention_policy else self._contexts[name].retention_policy

        return self._contexts[name]
    
    async def create(
        self,
        name: str | None = None,
        template: str | None = None,
        path: str | None = None,
        retention_policy: RetentionPolicyConfig | None = None,
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
            retention_policy=retention_policy,
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
        retention_policy: RetentionPolicyConfig | None = None,
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
                retention_policy=retention_policy,
            )
            await stream.initialize()
            self._streams[name] = stream

        if logger._streams.get(name) is None:
            stream = LoggerStream(
                name=name,
            )

            await stream.initialize()
            logger._streams[name] = stream

        if self._contexts.get(name) is None:
            self._contexts[name] = LoggerContext(
                name=name,
                template=template,
                filename=filename,
                directory=directory,
                retention_policy=retention_policy
            )

            await self._contexts[name].stream.initialize()

        if logger._contexts.get(name) is None:
            logger._contexts[name] = LoggerContext(
                name=name,
            )

            await logger._contexts[name].stream.initialize()

        logger._streams[name]._provider.subscribe(self._streams[name]._consumer)
        logger._contexts[name].stream._provider.subscribe(self._contexts[name].stream._consumer)

    def watch(
        self, 
        name: str | None = None,
        filter: Callable[[T], bool] | None = None,
    ):

        if name is None:
            name = 'default'

        if self._watch_tasks.get(name):
            try:
                self._watch_tasks[name].cancel()

            except (
                asyncio.CancelledError,
                asyncio.InvalidStateError
            ):
                pass

        self._watch_tasks[name] = asyncio.create_task(
            self._watch(
                name,
                filter=filter,
            )
        )

    async def _watch(
        self, 
        name: str,
        filter: Callable[[T], bool] | None = None,
    ):
        async with self._contexts[name] as ctx:
            async for log in ctx.get(
                filter=filter
            ):
                await ctx.log(log)

    async def stop_watch(
        self,
        name: str | None = None
    ):
        
        if name is None:
            name = 'default'
            
        if (
            context := self._contexts.get(name)
        ) and (
            watch_task := self._watch_tasks.get(name)
        ):
            await context.stream.close(shutdown_subscribed=True)
            
            try:
                await watch_task

            except (
                asyncio.CancelledError,
                asyncio.InvalidStateError,
            ):
                pass

    async def close(self):
    
        if len(self._watch_tasks) > 0:
            await asyncio.gather(*[
                self.stop_watch(name) for name in self._watch_tasks
            ])

        streams_count = len(self._streams)

        shutdown_subscribed = len([
            stream for stream in self._streams.values() if stream.has_active_subscriptions
        ]) > 0 or len([
            context for context in self._contexts.values() if context.stream.has_active_subscriptions
        ])

        if streams_count > 0:
            await asyncio.gather(*[
                stream.close(
                    shutdown_subscribed=shutdown_subscribed
                ) for stream in self._streams.values()
            ])

        contexts_count = len(self._contexts)


        if contexts_count > 0:
            await asyncio.gather(*[
                context.stream.close(
                    shutdown_subscribed=shutdown_subscribed
                ) for context in self._contexts.values()
            ])

    def abort(self):

        for stream in self._streams.values():
            stream.abort()

        for context in self._contexts.values():
            context.stream.abort()
            



    
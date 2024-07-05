from collections import defaultdict
from typing import (
    Dict, 
    TypeVar, 
    Callable,
    Generic,
)
import pathlib
from async_logging.models import Entry, LogLevel
from .logger_stream import LoggerStream
from .logger_context import LoggerContext
from .logger_stream import LoggerStream
from .stream_type import StreamType


T = TypeVar('T', bound=Entry)


class Logger:
    def __init__(self) -> None:
        self._streams: Dict[str, LoggerStream] = defaultdict(LoggerStream)

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


        context = LoggerContext(
            name=name,
            template=template,
            filename=filename,
            directory=directory,
            rotation_schedule=rotation_schedule,
        )

        return context
    
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

        if name is None:
            name = 'default'

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

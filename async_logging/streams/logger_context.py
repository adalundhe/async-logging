import asyncio
import os

from async_logging.rotation import TimeParser

from .logger_stream import LoggerStream


class LoggerContext:
    def __init__(
        self,
        filename: str | None = None,
        directory: str | None = None,
        rotation_schedule: str | None = None,
    ) -> None:
        self.filename = filename
        self.directory = directory
        self.rotation_schedule = rotation_schedule
        self.stream = LoggerStream()

    async def __aenter__(self):
        await self.stream.initialize()

        if self.stream._cwd is None:
            self.stream._cwd = await asyncio.to_thread(os.getcwd)

        if self.filename:
            await self.stream.open_file(
                self.filename,
                directory=self.directory,
                is_default=True,
                rotation_schedule=self.rotation_schedule,
            )

        if self.rotation_schedule and self.filename is None:
            filename = "logs.json"
            directory = os.path.join(self.stream._cwd, "logs")
            logfile_path = os.path.join(directory, filename)

            self.stream._rotation_schedules[logfile_path] = TimeParser(
                self.rotation_schedule
            ).time

        return self.stream

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stream.close()

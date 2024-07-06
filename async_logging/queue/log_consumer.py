import asyncio
from async_logging.models import Log
from typing import AsyncGenerator


class LogConsumer:

    def __init__(self) -> None:
        self._running = False
        self._queue = asyncio.Queue()
        self._wait_task: asyncio.Task | None = None
        self._loop = asyncio.get_event_loop()
        self._shutdown = False

    async def __aiter__(self) -> AsyncGenerator[Log, None]:
        self._running = True
        while self._running:
            self._wait_task = asyncio.create_task(self._queue.get())

            yield await self._wait_task

        remaining = self._queue.qsize()

        for _ in range(remaining):
            self._wait_task = asyncio.create_task(self._queue.get())
            yield await self._wait_task


    def put(self, log: Log):
        self._queue.put_nowait(log)

    def abort(self):
        if self._wait_task:
            
            try:
                self._wait_task.cancel()

            except asyncio.CancelledError:
                pass

            except asyncio.InvalidStateError:
                pass

        remaining = self._queue.qsize()
        for _ in range(remaining):
            self._queue.get_nowait()
        
        self._running = False
   
    def stop(self):
        self._running = False

    
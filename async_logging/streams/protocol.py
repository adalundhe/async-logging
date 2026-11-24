from __future__ import annotations

import asyncio
import collections


class LoggerProtocol(asyncio.Protocol):
    """Asyncio protocol with flow-control support for StreamWriter.drain()."""

    def __init__(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self._loop = loop
        self._paused = False
        self._connection_lost = False
        self._drain_waiters: collections.deque[asyncio.Future[None]] = collections.deque()

    def pause_writing(self) -> None:
        self._paused = True

    def resume_writing(self) -> None:
        self._paused = False
        for waiter in self._drain_waiters:
            if not waiter.done():
                waiter.set_result(None)

    def connection_lost(self, exc: BaseException | None) -> None:
        self._connection_lost = True
        if not self._paused:
            return
        for waiter in self._drain_waiters:
            if not waiter.done():
                if exc is None:
                    waiter.set_result(None)
                else:
                    waiter.set_exception(exc)

    async def _drain_helper(self) -> None:
        if self._connection_lost:
            raise ConnectionResetError("Connection lost")
        if not self._paused:
            return
        loop = self._loop if self._loop is not None else asyncio.get_running_loop()
        waiter: asyncio.Future[None] = loop.create_future()
        self._drain_waiters.append(waiter)
        try:
            await waiter
        finally:
            try:
                self._drain_waiters.remove(waiter)
            except ValueError:
                pass

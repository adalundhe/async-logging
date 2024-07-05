import asyncio
import msgspec
import sys
import threading
import datetime
from async_logging.models import Entry, Log
from typing import TypeVar


T = TypeVar('T', bound=Entry)


class LogQueue:

    def __init__(self) -> None:
        self._waiters: asyncio.Queue[asyncio.Future] = asyncio.Queue()

    
    def subscribe(self):
        waiter = asyncio.Future()
        self._waiters.put_nowait(waiter)

        return waiter
    

    async def put(self, entry: T):

        log_file, line_number, function_name = self._find_caller()

        log = Log(
            entry=entry,
            filename=log_file,
            function_name=function_name,
            line_number=line_number,
            thread_id=threading.get_native_id(),
            timestamp=datetime.datetime.now(datetime.UTC).isoformat()
        )
        
        waiters = await asyncio.gather(*[
            self._waiters.get() for _ in range(self._waiters.qsize())
        ])

        [
            waiter.set_result(log) for waiter in waiters
        ]


    def _find_caller(self):
        """
        Find the stack frame of the caller so that we can note the source
        file name, line number and function name.
        """
        frame = sys._getframe(3)
        code = frame.f_code

        return (
            code.co_filename,
            frame.f_lineno,
            code.co_name,
        )


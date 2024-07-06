import asyncio
from async_logging.models import Log
from typing import List
from .log_consumer import LogConsumer


class LogProvider:

    def __init__(self) -> None:
        self._close_waiter: asyncio.Future | None = None
        self.closing: bool = False
        self._consumers: List[LogConsumer] = []

    def subscribe(self, consumer: LogConsumer):
        self._consumers.append(consumer)
    
    def put(self, log: Log):
        for consumer in self._consumers:
            consumer.put(log)

    async def signal_shutdown(self):

        for consumer in self._consumers:
            consumer.stop()




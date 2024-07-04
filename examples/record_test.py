import asyncio

from async_logging.models import Entry, LogLevel
from async_logging.streams import Logger


class TestLog(Entry, kw_only=True):
    value: int
    level: LogLevel = LogLevel.INFO


async def test_entry(hours: int):
    logger = Logger()

    async with logger.create_context(rotation_schedule="1h") as ctx:
        await ctx.log(
            TestLog(message="Hello!", value=10),
            "{timestamp} - {level} - {thread_id} - {filename}:{function_name}.{line_number} - {message} and {value}",
        )


asyncio.run(test_entry(24))

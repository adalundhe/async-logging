import asyncio
from async_logging.models import Entry, LogLevel
from async_logging.streams import Logger


class TestLog(Entry, kw_only=True):
    value: int
    level: LogLevel = LogLevel.INFO


async def test_entry():
    logger = Logger()

    async with logger.create_context(
        path="/logs",
        template="{timestamp} - {level} - {thread_id} - {filename}:{function_name}.{line_number} - {message} and {value}"
    ) as ctx:
        await ctx.log(TestLog(message="Hello!", value=10))


asyncio.run(test_entry())

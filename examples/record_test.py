import asyncio
from async_logging.models import Entry, LogLevel
from async_logging.streams import Logger


class TestLog(Entry, kw_only=True):
    value: int
    level: LogLevel = LogLevel.INFO


async def test_entry():
    try:
        provider = Logger()
        consumer = Logger()

        await consumer.subscribe(
            provider,
            template="{timestamp} - {level} - {thread_id} - {filename}:{function_name}.{line_number} - {message} and {value}",
            path="/logs",
            retention_policy={
                "max_age": "1h",
                "max_size": "100mb",
                "rotation_time": "12:27"
            }
        )

        consumer.watch()

        async with provider.create_context() as ctx:
            for _ in range(10):
                await ctx.put(TestLog(message="Hello!", value=20))

        await provider.close()

    except KeyboardInterrupt:
        provider.abort()
        consumer.abort()


if __name__ == "__main__":
    
    try:
        asyncio.run(test_entry())

    except KeyboardInterrupt:
        pass
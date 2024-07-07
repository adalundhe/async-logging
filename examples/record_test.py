import asyncio
from async_logging.models import Entry, LogLevel
from async_logging.streams import Logger


class TestLog(Entry, kw_only=True):
    value: int
    level: LogLevel = LogLevel.INFO

def filter_test_log(log: TestLog):
    return log.value > 10

async def read_from_consumer(logger: Logger):


    async with logger.create_context(
        template="{timestamp} - {level} - {thread_id} - {filename}:{function_name}.{line_number} - {message} and {value}"
    ) as ctx:
        async for log in ctx.receive(
            filter=filter_test_log
        ):
            await ctx.log(log.entry)

async def provide(logger: Logger):


    async with logger.create_context() as ctx:
        await ctx.enqueue(TestLog(message="Hello!", value=10))
        await ctx.enqueue(TestLog(message="Hello!", value=20))
        await ctx.enqueue(TestLog(message="Hello!", value=10))

    await logger.close(shutdown_subscribed=True)

async def test_entry():
    try:
        provider = Logger()
        consumer = Logger()

        await consumer.subscribe(provider)

        consumer_task = asyncio.create_task(
            read_from_consumer(consumer)
        )

        provider_task = asyncio.create_task(
            provide(provider)
        )

        
        await asyncio.gather(*[
            consumer_task,
            provider_task,
        ])

    except KeyboardInterrupt:
        provider.abort()
        consumer.abort()

        consumer_task.cancel()
        provider_task.cancel()


    

if __name__ == "__main__":
    
    try:
        asyncio.run(test_entry())

    except KeyboardInterrupt:
        print('EEE')
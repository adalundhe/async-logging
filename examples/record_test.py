import asyncio

from async_logging.streams import Logger


async def test_entry():
    logger = Logger()

    async with logger.create_context(rotation_schedule="1s") as ctx:
        await ctx.log_to_file("test", "This is a test")


asyncio.run(test_entry())

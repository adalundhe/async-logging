import asyncio
import json
from async_logging.models import Entry, LogLevel
from async_logging.streams import Logger


class WorkflowUpdate(Entry, kw_only=True):
    level: LogLevel = LogLevel.INFO


async def run():
    logger = Logger()
    logger.configure(
        path="test.log.json",
        template="{timestamp} - {level} - {thread_id} - {filename}:{function_name}.{line_number} - {message}",
    )

    await logger.log(
        WorkflowUpdate(
            message="Workflow Test entered status RUNNING",
        )
    )

    async with logger.context(
        name="stdout_logger",
        template="{timestamp} - {level} - {thread_id} - {filename}:{function_name}.{line_number} - {message}",
    ) as ctx:
        await ctx.log(
            WorkflowUpdate(
                message="Workflow Test entered status RUNNING",
            )
        )

    loop = asyncio.get_event_loop()

    with open("test.log.json") as logfile:
        log_lines = await loop.run_in_executor(
            None,
            logfile.readlines,
        )

        logs = [json.loads(log) for log in log_lines]


if __name__ == "__main__":
    asyncio.run(run())

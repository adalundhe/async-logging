# async-logging

Structured asynchronous logging for Python 3.11+ built on `asyncio`, `msgspec`, and `zstandard`.

## Features

- **Structured log entries** defined with `msgspec.Struct` (`Entry`)
- **Async stdout / stderr streaming** with full support for interactive terminals, shell pipes, and shell file redirection across **Linux/Unix, macOS, and Windows**
- **Async JSON file logging** with size-, age-, and time-based rotation archived with `zstandard`
- **Pub/sub log streaming** (`subscribe`, `watch`, `batch`, `put`) for decoupled log producers and consumers
- **Context-scoped configuration** via `LoggingConfig` (`contextvars`-backed log level, output stream, and log directory)

## Requirements

- Python `>= 3.11`
- `msgspec`
- `zstandard`

## Installation

```bash
pip install async-logging
```

Or install from source:

```bash
pip install -e .
```

## Quick Start

### Logging to stdout / stderr and JSON files

```python
import asyncio
from async_logging import Entry, LogLevel, Logger, LoggingConfig


class WorkflowUpdate(Entry, kw_only=True):
    level: LogLevel = LogLevel.INFO


async def main():
    logger = Logger()

    # Configure a JSON log file for the default context
    logger.configure(
        path="test.log.json",
        template="{timestamp} - {level} - {thread_id} - {filename}:{function_name}.{line_number} - {message}",
    )

    await logger.log(
        WorkflowUpdate(message="Workflow Test entered status RUNNING")
    )

    # Stream formatted logs to stdout (or stderr via LoggingConfig)
    async with logger.context(
        name="stdout_logger",
        template="{timestamp} - {level} - {thread_id} - {filename}:{function_name}.{line_number} - {message}",
    ) as ctx:
        await ctx.log(
            WorkflowUpdate(message="Workflow Test entered status RUNNING")
        )

    await logger.close()


if __name__ == "__main__":
    asyncio.run(main())
```

### Selecting `stdout` vs `stderr`

By default, console/stream logs are written to `stdout`. Use `LoggingConfig` to switch output to `stderr`, set the log level, or set a default log directory:

```python
from async_logging import LoggingConfig

config = LoggingConfig()
config.update(
    log_level="info",
    log_output="stderr",  # "stdout" (default) or "stderr"
)
```

## Shell Redirection & Piping (Linux, macOS, and Windows)

`async-logging` uses a cross-platform asynchronous stdio writer (`StdioStreamWriter`) that works identically across **Linux/Unix, macOS, and Windows** without relying on OS-specific pipe transports (`connect_write_pipe`) or mutating `O_NONBLOCK` on `sys.stdout` / `sys.stderr`.

Supported targets on all platforms:

- **Interactive terminals / consoles** (POSIX TTY/PTY, macOS Terminal, Windows Terminal / `cmd.exe` / PowerShell)
- **Shell file redirection** (`>`, `>>`, `2>`, `2>>`, `2>&1`, `&>`)
- **Shell pipes & subprocesses** (`|`, `2>&1 |`, PowerShell pipelines, `subprocess.PIPE`, slow readers with backpressure)
- **Null & closed streams** (`/dev/null`, `NUL`, `pythonw.exe` where stdio is `None`, closed file descriptors such as `2>&-`, early-closing pipe consumers like `| head -n 1`)
- **Unbuffered mode & Python streams** (`python -u`, `contextlib.redirect_stdout(io.StringIO())`, `pytest` capture)

### Unix / macOS (bash, zsh, sh)

```bash
# Redirect stdout logs to a file
python app.py > app.log

# Redirect stderr logs to a file
python app.py 2> error.log

# Redirect both stdout and stderr to the same file
python app.py > combined.log 2>&1

# Pipe stdout logs to another command
python app.py | grep ERROR
python app.py | tee app.log

# Pipe both stdout and stderr
python app.py 2>&1 | tee combined.log
```

### Windows (PowerShell & Command Prompt)

```powershell
# PowerShell: redirect stdout / stderr to files
python app.py > app.log
python app.py 2> error.log
python app.py *> combined.log

# PowerShell: pipe logs to another command
python app.py | Select-String "ERROR"
python app.py 2>&1 | Tee-Object -FilePath combined.log
```

```cmd
:: Command Prompt (cmd.exe)
python app.py > app.log 2> error.log
python app.py > combined.log 2>&1
python app.py | findstr ERROR
```

## Pub/Sub Streaming (`subscribe` & `watch`)

```python
import asyncio
from async_logging import Entry, LogLevel, Logger


class TestLog(Entry, kw_only=True):
    value: int
    level: LogLevel = LogLevel.INFO


async def main():
    provider = Logger()
    consumer = Logger()

    await consumer.subscribe(
        provider,
        template="{timestamp} - {level} - {thread_id} - {filename}:{function_name}.{line_number} - {message} and {value}",
    )

    consumer.watch()

    await provider.batch(
        *[TestLog(message="Hello!", value=i) for i in range(1000)]
    )

    await provider.close()
    await consumer.close()


if __name__ == "__main__":
    asyncio.run(main())
```

## Log Rotation

When logging to a `.json` file, pass a `retention_policy` dictionary to archive rotated logs with `zstandard` (`.zst`):

```python
logger.configure(
    path="logs/app.json",
    retention_policy={
        "max_size": "10MB",
        "max_age": "7d",
        "rotation_time": "00:00",
    },
)
```

## Running Tests

```bash
python -m unittest discover -s tests -v
```

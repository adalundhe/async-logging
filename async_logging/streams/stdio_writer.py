from __future__ import annotations

import asyncio
import errno
import io
import select
import sys
import threading
import time
from typing import Any, Callable, Iterable


_STDOUT_WRITE_LOCK = threading.Lock()
_STDERR_WRITE_LOCK = threading.Lock()

# Win32 error codes indicating a closed/broken pipe or invalid stdio handle:
#   6   = ERROR_INVALID_HANDLE
#   109 = ERROR_BROKEN_PIPE
#   232 = ERROR_NO_DATA
_WIN32_CLOSED_STREAM_ERRORS = frozenset((6, 109, 232))


def is_closed_or_broken_stream_error(exc: BaseException) -> bool:
    """Return True if *exc* indicates a closed or broken stdio stream across Unix, macOS, and Windows."""
    if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
        return True
    if isinstance(exc, OSError):
        if exc.errno in (errno.EPIPE, errno.EBADF):
            return True
        if sys.platform == "win32" and (
            exc.errno == errno.EINVAL
            or getattr(exc, "winerror", None) in _WIN32_CLOSED_STREAM_ERRORS
        ):
            return True
    return False


def _wait_writable(target: Any) -> None:
    """Wait briefly for a non-blocking stream to become writable without busy-spinning."""
    fileno_fn = getattr(target, "fileno", None)
    if callable(fileno_fn) and sys.platform != "win32":
        try:
            fd = fileno_fn()
            if fd >= 0:
                select.select([], [fd], [], 0.05)
                return
        except (OSError, ValueError, io.UnsupportedOperation):
            pass
    time.sleep(0.001)


def _write_bytes_all(target: Any, data: bytes) -> None:
    """Write all bytes in *data* to a binary stream, handling short writes and BlockingIOError."""
    view = memoryview(data)
    total = len(view)
    written = 0
    while written < total:
        try:
            n = target.write(view[written:])
        except BlockingIOError as exc:
            if exc.characters_written:
                written += exc.characters_written
            _wait_writable(target)
            continue

        if n is None:
            _wait_writable(target)
            continue
        if n == 0:
            raise BrokenPipeError("Underlying stream accepted 0 bytes")
        written += n

    flush_fn = getattr(target, "flush", None)
    if callable(flush_fn):
        flush_fn()


def write_bytes_to_stream(stream: Any, data: bytes) -> None:
    """Synchronously write UTF-8 *data* to *stream* (TTY, pipe, file, StringIO, or None)."""
    if not data or stream is None or getattr(stream, "closed", False):
        return

    buffer = getattr(stream, "buffer", None)
    if buffer is not None and not getattr(buffer, "closed", False):
        flush_fn = getattr(stream, "flush", None)
        if callable(flush_fn):
            flush_fn()
        # Prefer writing directly to the underlying raw stream (FileIO / _WindowsConsoleIO)
        # after flushing the wrapper so a BrokenPipeError never leaves unflushed bytes in
        # BufferedWriter (which would trigger CPython exit code 120 during Py_FinalizeEx).
        raw = getattr(buffer, "raw", None)
        target = raw if (raw is not None and not getattr(raw, "closed", False)) else buffer
        _write_bytes_all(target, data)
        return

    if isinstance(stream, (io.RawIOBase, io.BufferedIOBase)) or "b" in str(
        getattr(stream, "mode", "")
    ):
        _write_bytes_all(stream, data)
        return

    # Pure text stream without .buffer (e.g. io.StringIO, pytest capsys)
    stream.write(data.decode("utf-8", errors="replace"))
    flush_fn = getattr(stream, "flush", None)
    if callable(flush_fn):
        flush_fn()


def write_bytes_to_stream_safe(
    stream: Any,
    data: bytes,
    lock: threading.Lock | None = None,
) -> None:
    """Best-effort write used for internal error reporting to stderr."""
    try:
        if lock is not None:
            with lock:
                write_bytes_to_stream(stream, data)
        else:
            write_bytes_to_stream(stream, data)
    except Exception:
        pass


class StdioStreamWriter:
    """Cross-platform async writer for stdout/stderr across Unix, macOS, and Windows.

    Supports interactive consoles/TTYs, shell pipes (|), regular file redirections
    (>, >>, 2>, 2>&1), /dev/null and NUL, closed file descriptors, unbuffered mode
    (python -u), pythonw.exe (None stdio), and Python-level streams (io.StringIO).

    Writes are coalesced in memory and executed off the event loop via the loop's
    executor without mutating O_NONBLOCK on stdout/stderr or taking ownership of
    closing sys.stdout/sys.stderr.
    """

    def __init__(
        self,
        stream_getter: Callable[[], Any],
        loop: asyncio.AbstractEventLoop | None = None,
        write_lock: threading.Lock | None = None,
    ) -> None:
        self._stream_getter = stream_getter
        self._loop = loop
        self._write_lock = write_lock if write_lock is not None else threading.Lock()

        self._buffer = bytearray()
        self._closing = False
        self._broken = False

        self._write_seq = 0
        self._flushed_seq = 0
        self._flush_task: asyncio.Task[None] | None = None
        self._flush_waiters: list[tuple[int, asyncio.Future[None]]] = []

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        try:
            running = asyncio.get_running_loop()
            self._loop = running
            return running
        except RuntimeError:
            if self._loop is not None and not self._loop.is_closed():
                return self._loop
            raise

    def is_closing(self) -> bool:
        return self._closing or self._broken

    def write(self, data: bytes | bytearray | memoryview) -> None:
        if not data or self._closing or self._broken:
            return
        self._buffer.extend(data)
        self._write_seq += len(data)
        self._ensure_flushing()

    def writelines(self, lines: Iterable[bytes | bytearray | memoryview]) -> None:
        if self._closing or self._broken:
            return
        added = 0
        for line in lines:
            if line:
                self._buffer.extend(line)
                added += len(line)
        if added > 0:
            self._write_seq += added
            self._ensure_flushing()

    async def drain(self) -> None:
        if self._broken:
            return
        target_seq = self._write_seq
        if self._flushed_seq >= target_seq:
            return

        self._ensure_flushing()
        waiter = self._get_loop().create_future()
        entry = (target_seq, waiter)
        self._flush_waiters.append(entry)
        try:
            await waiter
        finally:
            try:
                self._flush_waiters.remove(entry)
            except ValueError:
                pass

    def close(self) -> None:
        self._closing = True
        if self._buffer and not self._broken:
            self._ensure_flushing()

    async def wait_closed(self) -> None:
        while self._flush_task is not None:
            task = self._flush_task
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                raise
            except Exception:
                break

    def abort(self) -> None:
        self._closing = True
        self._broken = True
        self._buffer.clear()
        if self._flush_task is not None and not self._flush_task.done():
            self._flush_task.cancel()
        self._resolve_all_waiters()

    def _ensure_flushing(self) -> None:
        if self._flush_task is None or self._flush_task.done():
            loop = self._get_loop()
            self._flush_task = loop.create_task(self._flush_loop())

    def _write_chunk_sync(self, chunk: bytes) -> None:
        stream = self._stream_getter()
        if stream is None or getattr(stream, "closed", False):
            return
        with self._write_lock:
            try:
                write_bytes_to_stream(stream, chunk)
            except ValueError as exc:
                # e.g. "I/O operation on closed file" if stream closed concurrently
                if getattr(stream, "closed", False) or "closed file" in str(exc).lower():
                    raise BrokenPipeError(str(exc)) from exc
                raise

    async def _flush_loop(self) -> None:
        loop = self._get_loop()
        try:
            while self._buffer and not self._broken:
                chunk = bytes(self._buffer)
                target_seq = self._write_seq
                self._buffer.clear()

                try:
                    await loop.run_in_executor(None, self._write_chunk_sync, chunk)
                except asyncio.CancelledError:
                    self._resolve_all_waiters()
                    return
                except Exception as exc:
                    if is_closed_or_broken_stream_error(exc):
                        self._broken = True
                        self._buffer.clear()
                        err = (
                            exc
                            if isinstance(exc, (BrokenPipeError, ConnectionResetError))
                            else BrokenPipeError(str(exc))
                        )
                        self._fail_all_waiters(err)
                        return
                    self._fail_waiters_up_to(target_seq, exc)
                    continue

                self._flushed_seq = target_seq
                self._wake_waiters_up_to(target_seq)
        finally:
            self._flush_task = None
            if self._broken:
                self._resolve_all_waiters()
            elif self._buffer:
                self._ensure_flushing()

    def _wake_waiters_up_to(self, seq: int) -> None:
        for target_seq, waiter in list(self._flush_waiters):
            if target_seq <= seq and not waiter.done():
                waiter.set_result(None)

    def _fail_waiters_up_to(self, seq: int, exc: BaseException) -> None:
        for target_seq, waiter in list(self._flush_waiters):
            if target_seq <= seq and not waiter.done():
                waiter.set_exception(exc)

    def _fail_all_waiters(self, exc: BaseException) -> None:
        for _, waiter in list(self._flush_waiters):
            if not waiter.done():
                waiter.set_exception(exc)

    def _resolve_all_waiters(self) -> None:
        for _, waiter in list(self._flush_waiters):
            if not waiter.done():
                waiter.set_result(None)

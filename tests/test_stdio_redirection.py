import asyncio
import contextlib
import errno
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

from async_logging import Entry, LogLevel, Logger, LoggingConfig
from async_logging.streams.protocol import LoggerProtocol


REPO_ROOT = Path(__file__).resolve().parent.parent


class SampleEntry(Entry, kw_only=True):
    level: LogLevel = LogLevel.INFO


def _run_child(
    code: str,
    *,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    python_args: list[str] | None = None,
    cwd: str | None = None,
    timeout: float = 15.0,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{REPO_ROOT}{os.pathsep}{existing}" if existing else str(REPO_ROOT)
    )
    cmd = [sys.executable, *(python_args or []), "-c", textwrap.dedent(code)]
    return subprocess.run(
        cmd,
        stdout=stdout,
        stderr=stderr,
        env=env,
        cwd=cwd,
        timeout=timeout,
    )


def _popen_child(
    code: str,
    *,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    python_args: list[str] | None = None,
) -> subprocess.Popen:
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{REPO_ROOT}{os.pathsep}{existing}" if existing else str(REPO_ROOT)
    )
    cmd = [sys.executable, *(python_args or []), "-c", textwrap.dedent(code)]
    return subprocess.Popen(
        cmd,
        stdout=stdout,
        stderr=stderr,
        env=env,
    )


class TestShellRedirectionAndPipes(unittest.TestCase):
    def test_stdout_redirect_to_regular_file(self):
        script = """
        import asyncio
        from async_logging import Entry, LogLevel, Logger, LoggingConfig

        class Msg(Entry, kw_only=True):
            level: LogLevel = LogLevel.INFO

        async def main():
            LoggingConfig().update(log_output="stdout")
            logger = Logger()
            async with logger.context(name="stdout_ctx") as ctx:
                await ctx.log(Msg(message="HELLO_STDOUT_FILE"))

        asyncio.run(main())
        """
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.log"
            err_path = Path(tmp) / "err.log"
            with open(out_path, "wb") as out_f, open(err_path, "wb") as err_f:
                res = _run_child(script, stdout=out_f, stderr=err_f)

            self.assertEqual(
                res.returncode,
                0,
                f"Process failed. stderr={err_path.read_text(errors='replace')}",
            )
            self.assertIn("HELLO_STDOUT_FILE", out_path.read_text(encoding="utf-8"))
            self.assertEqual(err_path.read_text(encoding="utf-8"), "")

    def test_stderr_redirect_to_regular_file(self):
        script = """
        import asyncio
        from async_logging import Entry, LogLevel, Logger, LoggingConfig

        class Msg(Entry, kw_only=True):
            level: LogLevel = LogLevel.INFO

        async def main():
            LoggingConfig().update(log_output="stderr")
            logger = Logger()
            async with logger.context(name="stderr_ctx") as ctx:
                await ctx.log(Msg(message="HELLO_STDERR_FILE"))

        asyncio.run(main())
        """
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.log"
            err_path = Path(tmp) / "err.log"
            with open(out_path, "wb") as out_f, open(err_path, "wb") as err_f:
                res = _run_child(script, stdout=out_f, stderr=err_f)

            self.assertEqual(
                res.returncode,
                0,
                f"Process failed. stderr={err_path.read_text(errors='replace')}",
            )
            self.assertEqual(out_path.read_text(encoding="utf-8"), "")
            self.assertIn("HELLO_STDERR_FILE", err_path.read_text(encoding="utf-8"))

    def test_combined_redirect_stdout_and_stderr_same_file(self):
        script = """
        import asyncio
        from async_logging import Entry, LogLevel, Logger, LoggingConfig

        class Msg(Entry, kw_only=True):
            level: LogLevel = LogLevel.INFO

        async def main():
            logger = Logger()
            async with logger.context(name="both") as ctx:
                LoggingConfig().update(log_output="stdout")
                await ctx.log(Msg(message="LINE_ON_STDOUT"))
                LoggingConfig().update(log_output="stderr")
                await ctx.log(Msg(message="LINE_ON_STDERR"))

        asyncio.run(main())
        """
        with tempfile.TemporaryDirectory() as tmp:
            combined_path = Path(tmp) / "combined.log"
            with open(combined_path, "wb") as combined_f:
                res = _run_child(script, stdout=combined_f, stderr=subprocess.STDOUT)

            self.assertEqual(res.returncode, 0)
            content = combined_path.read_text(encoding="utf-8")
            self.assertIn("LINE_ON_STDOUT", content)
            self.assertIn("LINE_ON_STDERR", content)

    def test_stdout_pipe_routes_to_stdout_not_stderr(self):
        script = """
        import asyncio
        from async_logging import Entry, LogLevel, Logger, LoggingConfig

        class Msg(Entry, kw_only=True):
            level: LogLevel = LogLevel.INFO

        async def main():
            LoggingConfig().update(log_output="stdout")
            logger = Logger()
            async with logger.context(name="pipe_out") as ctx:
                await ctx.log(Msg(message="ONLY_IN_STDOUT_PIPE"))

        asyncio.run(main())
        """
        res = _run_child(script, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(res.returncode, 0, res.stderr.decode(errors="replace"))
        self.assertIn("ONLY_IN_STDOUT_PIPE", res.stdout.decode("utf-8"))
        self.assertEqual(res.stderr.decode("utf-8"), "")

    def test_stderr_pipe_routes_to_stderr_not_stdout(self):
        script = """
        import asyncio
        from async_logging import Entry, LogLevel, Logger, LoggingConfig

        class Msg(Entry, kw_only=True):
            level: LogLevel = LogLevel.INFO

        async def main():
            LoggingConfig().update(log_output="stderr")
            logger = Logger()
            async with logger.context(name="pipe_err") as ctx:
                await ctx.log(Msg(message="ONLY_IN_STDERR_PIPE"))

        asyncio.run(main())
        """
        res = _run_child(script, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(res.returncode, 0, res.stderr.decode(errors="replace"))
        self.assertEqual(res.stdout.decode("utf-8"), "")
        self.assertIn("ONLY_IN_STDERR_PIPE", res.stderr.decode("utf-8"))

    def test_mixed_pipe_and_file_redirect(self):
        script = """
        import asyncio, sys
        from async_logging import Entry, LogLevel, Logger, LoggingConfig

        class Msg(Entry, kw_only=True):
            level: LogLevel = LogLevel.INFO

        async def main():
            LoggingConfig().update(log_output="stdout")
            logger = Logger()
            async with logger.context(name="mixed") as ctx:
                await ctx.log(Msg(message="MIXED_STDOUT_MSG"))

        asyncio.run(main())
        """
        with tempfile.TemporaryDirectory() as tmp:
            err_path = Path(tmp) / "err.log"
            with open(err_path, "wb") as err_f:
                res = _run_child(script, stdout=subprocess.PIPE, stderr=err_f)
            self.assertEqual(
                res.returncode,
                0,
                f"Process failed. stderr={err_path.read_text(errors='replace')}",
            )
            self.assertIn("MIXED_STDOUT_MSG", res.stdout.decode("utf-8"))
            self.assertEqual(err_path.read_text(encoding="utf-8"), "")

            out_path = Path(tmp) / "out.log"
            with open(out_path, "wb") as out_f:
                res2 = _run_child(script, stdout=out_f, stderr=subprocess.PIPE)
            self.assertEqual(res2.returncode, 0, res2.stderr.decode(errors="replace"))
            self.assertIn("MIXED_STDOUT_MSG", out_path.read_text(encoding="utf-8"))
            self.assertEqual(res2.stderr.decode("utf-8"), "")

    def test_redirect_to_devnull(self):
        script = """
        import asyncio
        from async_logging import Entry, LogLevel, Logger, LoggingConfig

        class Msg(Entry, kw_only=True):
            level: LogLevel = LogLevel.INFO

        async def main():
            logger = Logger()
            async with logger.context(name="null_ctx") as ctx:
                LoggingConfig().update(log_output="stdout")
                await ctx.log(Msg(message="TO_NULL_1"))
                LoggingConfig().update(log_output="stderr")
                await ctx.log(Msg(message="TO_NULL_2"))

        asyncio.run(main())
        """
        res = _run_child(script, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.assertEqual(res.returncode, 0)

    def test_file_logging_still_works_when_stdio_redirected(self):
        script = """
        import asyncio
        from async_logging import Entry, LogLevel, Logger

        class Msg(Entry, kw_only=True):
            level: LogLevel = LogLevel.INFO

        async def main():
            logger = Logger()
            logger.configure(path="app.log.json")
            await logger.log(Msg(message="JSON_FILE_LINE"))
            await logger.close()

        asyncio.run(main())
        """
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.log"
            err_path = Path(tmp) / "err.log"
            with open(out_path, "wb") as out_f, open(err_path, "wb") as err_f:
                res = _run_child(script, stdout=out_f, stderr=err_f, cwd=tmp)

            self.assertEqual(
                res.returncode,
                0,
                f"Process failed. stderr={err_path.read_text(errors='replace')}",
            )
            log_file = Path(tmp) / "app.log.json"
            self.assertTrue(log_file.exists())
            records = [
                json.loads(line)
                for line in log_file.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["entry"]["message"], "JSON_FILE_LINE")

    def test_high_volume_slow_pipe_reader_no_data_loss(self):
        count = 3000
        script = f"""
        import asyncio
        from async_logging import Entry, LogLevel, Logger, LoggingConfig

        class Msg(Entry, kw_only=True):
            level: LogLevel = LogLevel.INFO

        async def main():
            LoggingConfig().update(log_output="stdout")
            logger = Logger()
            async with logger.context(name="bulk") as ctx:
                for i in range({count}):
                    await ctx.log(Msg(message=f"SEQ_{{i}}_" + "x" * 100))

        asyncio.run(main())
        """
        proc = _popen_child(script, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            # Delay reading so the OS pipe buffer fills up and backpressure triggers
            time.sleep(0.25)
            out_bytes, err_bytes = proc.communicate(timeout=20)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

        self.assertEqual(proc.returncode, 0, err_bytes.decode(errors="replace"))
        self.assertEqual(err_bytes.decode("utf-8"), "")
        lines = out_bytes.decode("utf-8").splitlines()
        self.assertEqual(len(lines), count)
        self.assertIn("SEQ_0_", lines[0])
        self.assertIn(f"SEQ_{count - 1}_", lines[-1])

    def test_high_volume_concurrent_redirected_file_no_interleaving(self):
        count = 2000
        script = f"""
        import asyncio
        from async_logging import Entry, LogLevel, Logger, LoggingConfig

        class Msg(Entry, kw_only=True):
            level: LogLevel = LogLevel.INFO

        async def main():
            LoggingConfig().update(log_output="stdout")
            logger = Logger()
            async with logger.context(name="conc", template="{{message}}") as ctx:
                await asyncio.gather(*[
                    ctx.log(Msg(message=f"START_{{i}}_END"))
                    for i in range({count})
                ])

        asyncio.run(main())
        """
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "conc.log"
            err_path = Path(tmp) / "conc.err"
            with open(out_path, "wb") as out_f, open(err_path, "wb") as err_f:
                res = _run_child(script, stdout=out_f, stderr=err_f)

            self.assertEqual(
                res.returncode,
                0,
                f"Process failed. stderr={err_path.read_text(errors='replace')}",
            )
            lines = out_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), count)
            expected = {f"START_{i}_END" for i in range(count)}
            self.assertEqual(set(lines), expected)

    def test_broken_pipe_reader_exits_early_gracefully(self):
        script = """
        import asyncio
        from async_logging import Entry, LogLevel, Logger, LoggingConfig

        class Msg(Entry, kw_only=True):
            level: LogLevel = LogLevel.INFO

        async def main():
            LoggingConfig().update(log_output="stdout")
            logger = Logger()
            async with logger.context(name="epipe", template="{message}") as ctx:
                for i in range(3000):
                    await ctx.log(Msg(message=f"LINE_{i}_" + "A" * 200))

        asyncio.run(main())
        """
        proc = _popen_child(script, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            assert proc.stdout is not None
            first_line = proc.stdout.readline()
            proc.stdout.close()
            _, err_bytes = proc.communicate(timeout=15)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()

        self.assertIn(b"LINE_0_", first_line)
        self.assertEqual(proc.returncode, 0, err_bytes.decode(errors="replace"))
        self.assertEqual(err_bytes.decode("utf-8"), "")

    def test_unbuffered_python_u_over_pipe_and_file(self):
        script = """
        import asyncio
        from async_logging import Entry, LogLevel, Logger, LoggingConfig

        class Msg(Entry, kw_only=True):
            level: LogLevel = LogLevel.INFO

        async def main():
            LoggingConfig().update(log_output="stdout")
            logger = Logger()
            async with logger.context(name="unbuf", template="{message}") as ctx:
                for i in range(200):
                    await ctx.log(Msg(message=f"UNBUF_{i}"))

        asyncio.run(main())
        """
        res = _run_child(
            script,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            python_args=["-u"],
        )
        self.assertEqual(res.returncode, 0, res.stderr.decode(errors="replace"))
        lines = res.stdout.decode("utf-8").splitlines()
        self.assertEqual(lines, [f"UNBUF_{i}" for i in range(200)])

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "unbuf.log"
            err_path = Path(tmp) / "unbuf.err"
            with open(out_path, "wb") as out_f, open(err_path, "wb") as err_f:
                res2 = _run_child(
                    script, stdout=out_f, stderr=err_f, python_args=["-u"]
                )
            self.assertEqual(res2.returncode, 0, err_path.read_text(errors="replace"))
            self.assertEqual(
                out_path.read_text(encoding="utf-8").splitlines(),
                [f"UNBUF_{i}" for i in range(200)],
            )

    def test_direct_logger_log_without_close_flushes(self):
        script = """
        import asyncio
        from async_logging import Entry, LogLevel, Logger, LoggingConfig

        class Msg(Entry, kw_only=True):
            level: LogLevel = LogLevel.INFO

        async def main():
            LoggingConfig().update(log_output="stdout")
            logger = Logger()
            await logger.log(Msg(message="NO_CLOSE_FLUSHED"), template="{message}")

        asyncio.run(main())
        """
        res = _run_child(script, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(res.returncode, 0, res.stderr.decode(errors="replace"))
        self.assertEqual(res.stdout.decode("utf-8").strip(), "NO_CLOSE_FLUSHED")

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.log"
            err_path = Path(tmp) / "err.log"
            with open(out_path, "wb") as out_f, open(err_path, "wb") as err_f:
                res2 = _run_child(script, stdout=out_f, stderr=err_f)
            self.assertEqual(res2.returncode, 0, err_path.read_text(errors="replace"))
            self.assertEqual(out_path.read_text(encoding="utf-8").strip(), "NO_CLOSE_FLUSHED")

    def test_print_and_logger_ordering_when_redirected(self):
        script = """
        import asyncio
        from async_logging import Entry, LogLevel, Logger, LoggingConfig

        class Msg(Entry, kw_only=True):
            level: LogLevel = LogLevel.INFO

        async def main():
            LoggingConfig().update(log_output="stdout")
            logger = Logger()
            print("BEFORE_LOG")
            async with logger.context(name="order", template="{message}") as ctx:
                await ctx.log(Msg(message="MIDDLE_LOG"))
            print("AFTER_LOG")

        asyncio.run(main())
        """
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "order.log"
            err_path = Path(tmp) / "order.err"
            with open(out_path, "wb") as out_f, open(err_path, "wb") as err_f:
                res = _run_child(script, stdout=out_f, stderr=err_f)
            self.assertEqual(res.returncode, 0, err_path.read_text(errors="replace"))
            self.assertEqual(
                out_path.read_text(encoding="utf-8").splitlines(),
                ["BEFORE_LOG", "MIDDLE_LOG", "AFTER_LOG"],
            )

    @unittest.skipIf(sys.platform == "win32", "os.get_blocking is Unix/macOS only")
    def test_does_not_mutate_stdio_blocking_mode(self):
        script = """
        import asyncio, os, sys
        from async_logging import Entry, LogLevel, Logger, LoggingConfig

        class Msg(Entry, kw_only=True):
            level: LogLevel = LogLevel.INFO

        async def main():
            LoggingConfig().update(log_output="stdout")
            assert os.get_blocking(sys.stdout.fileno()) is True
            assert os.get_blocking(sys.stderr.fileno()) is True
            logger = Logger()
            async with logger.context(name="blocking_check") as ctx:
                await ctx.log(Msg(message="CHECK_BLOCKING"))
                assert os.get_blocking(sys.stdout.fileno()) is True
                assert os.get_blocking(sys.stderr.fileno()) is True
            assert os.get_blocking(sys.stdout.fileno()) is True
            assert os.get_blocking(sys.stderr.fileno()) is True

        asyncio.run(main())
        """
        res = _run_child(script, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(res.returncode, 0, res.stderr.decode(errors="replace"))
        self.assertIn("CHECK_BLOCKING", res.stdout.decode("utf-8"))

    @unittest.skipIf(sys.platform == "win32", "POSIX closed fd redirect (2>&-)")
    def test_closed_stderr_fd_does_not_crash_stdout_logging(self):
        env = os.environ.copy()
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            f"{REPO_ROOT}{os.pathsep}{existing}" if existing else str(REPO_ROOT)
        )
        script = textwrap.dedent("""
            import asyncio
            from async_logging import Entry, LogLevel, Logger, LoggingConfig

            class M(Entry, kw_only=True):
                level: LogLevel = LogLevel.INFO

            async def main():
                LoggingConfig().update(log_output="stdout")
                l = Logger()
                async with l.context(name="c", template="{message}") as ctx:
                    await ctx.log(M(message="OK_WITH_CLOSED_STDERR"))

            asyncio.run(main())
        """)
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.txt"
            res = subprocess.run(
                ["/bin/sh", "-c", f'"{sys.executable}" -c "$SCRIPT" > "{out_path}" 2>&-'],
                env={**env, "SCRIPT": script},
                timeout=15,
            )
            self.assertEqual(res.returncode, 0)
            self.assertEqual(
                out_path.read_text(encoding="utf-8").strip(),
                "OK_WITH_CLOSED_STDERR",
            )


class TestCrossPlatformAndEdgeCases(unittest.IsolatedAsyncioTestCase):
    async def test_redirect_stdout_stringio(self):
        LoggingConfig().update(log_output="stdout")
        buf = io.StringIO()
        logger = Logger()
        with contextlib.redirect_stdout(buf):
            async with logger.context(name="str_io", template="{message}") as ctx:
                await ctx.log(SampleEntry(message="STRINGIO_OK"))

        self.assertEqual(buf.getvalue().strip(), "STRINGIO_OK")

    async def test_none_stdio_simulates_windows_pythonw(self):
        LoggingConfig().update(log_output="stdout")
        logger = Logger()
        with mock.patch.object(sys, "stdout", None), mock.patch.object(sys, "stderr", None):
            async with logger.context(name="pythonw", template="{message}") as ctx:
                await ctx.log(SampleEntry(message="NO_CONSOLE"))

    async def test_utf8_unicode_on_cp1252_text_wrapper(self):
        """Simulates Windows redirected stdout where TextIOWrapper uses cp1252."""
        LoggingConfig().update(log_output="stdout")
        raw = io.BytesIO()
        wrapper = io.TextIOWrapper(raw, encoding="cp1252")
        logger = Logger()
        with contextlib.redirect_stdout(wrapper):
            async with logger.context(name="win_utf8", template="{message}") as ctx:
                await ctx.log(SampleEntry(message="Unicode ok: 🚀 日本語"))

        self.assertEqual(raw.getvalue().decode("utf-8").strip(), "Unicode ok: 🚀 日本語")

    async def test_raw_stream_short_writes_and_blocking_io(self):
        """Simulates python -u / Windows _WindowsConsoleIO short writes and BlockingIOError."""
        LoggingConfig().update(log_output="stdout")

        class ChunkedRawStream(io.RawIOBase):
            def __init__(self):
                self.received = bytearray()
                self._blocked_once = False

            def writable(self):
                return True

            def write(self, b):
                if not self._blocked_once:
                    self._blocked_once = True
                    raise BlockingIOError(errno.EAGAIN, "temporarily unavailable", 0)
                chunk = bytes(b[:7])
                self.received.extend(chunk)
                return len(chunk)

        raw = ChunkedRawStream()
        wrapper = io.TextIOWrapper(raw, encoding="utf-8")
        logger = Logger()
        payload = "SHORT_WRITE_" + ("Z" * 50)
        with contextlib.redirect_stdout(wrapper):
            async with logger.context(name="short", template="{message}") as ctx:
                await ctx.log(SampleEntry(message=payload))

        self.assertEqual(raw.received.decode("utf-8").strip(), payload)

    async def test_windows_broken_pipe_and_invalid_handle_errors(self):
        """Simulates Win32 ERROR_BROKEN_PIPE (109), ERROR_NO_DATA (232), ERROR_INVALID_HANDLE (6), and CRT EINVAL."""
        LoggingConfig().update(log_output="stdout")

        def make_win_error(err_no: int, winerror: int | None = None) -> OSError:
            exc = OSError(err_no, "simulated windows pipe error")
            if winerror is not None:
                exc.winerror = winerror
            return exc

        cases = [
            make_win_error(errno.EPIPE, 109),
            make_win_error(errno.EPIPE, 232),
            make_win_error(errno.EBADF, 6),
            make_win_error(errno.EINVAL, None),
        ]

        for simulated_exc in cases:
            class FailingStream(io.RawIOBase):
                def writable(self):
                    return True

                def write(self, b):
                    raise simulated_exc

            fake_out = io.TextIOWrapper(FailingStream(), encoding="utf-8")
            fake_err = io.StringIO()
            logger = Logger()
            with (
                mock.patch.object(sys, "platform", "win32"),
                contextlib.redirect_stdout(fake_out),
                contextlib.redirect_stderr(fake_err),
            ):
                async with logger.context(name="win_err", template="{message}") as ctx:
                    await ctx.log(SampleEntry(message="FIRST"))
                    await ctx.log(SampleEntry(message="SECOND"))

            self.assertEqual(fake_err.getvalue(), "")

    async def test_logger_close_with_uninitialized_context(self):
        logger = Logger()
        logger.configure(name="never_used")
        await logger.close()

    async def test_direct_get_stream_log_auto_initializes(self):
        LoggingConfig().update(log_output="stdout")
        buf = io.StringIO()
        logger = Logger()
        stream = logger.get_stream(name="direct", template="{message}")
        with contextlib.redirect_stdout(buf):
            await stream.log(SampleEntry(message="DIRECT_STREAM_OK"))
            await stream.close()

        self.assertEqual(buf.getvalue().strip(), "DIRECT_STREAM_OK")

    async def test_context_reentry_reinitializes_cleanly(self):
        LoggingConfig().update(log_output="stdout")
        buf = io.StringIO()
        logger = Logger()
        with contextlib.redirect_stdout(buf):
            async with logger.context(name="reenter", template="{message}") as ctx:
                await ctx.log(SampleEntry(message="FIRST_RUN"))
            async with logger.context(name="reenter", template="{message}") as ctx:
                await ctx.log(SampleEntry(message="SECOND_RUN"))

        self.assertEqual(buf.getvalue().splitlines(), ["FIRST_RUN", "SECOND_RUN"])

    async def test_protocol_flow_control_drain(self):
        protocol = LoggerProtocol()
        protocol.pause_writing()
        drain_task = asyncio.create_task(protocol._drain_helper())
        await asyncio.sleep(0.02)
        self.assertFalse(drain_task.done())
        protocol.resume_writing()
        await asyncio.wait_for(drain_task, timeout=1.0)
        self.assertTrue(drain_task.done())


class TestMultiLoopAndPty(unittest.TestCase):
    def test_reuse_logger_across_multiple_event_loops(self):
        LoggingConfig().update(log_output="stdout")
        logger = Logger()
        buf1 = io.StringIO()
        buf2 = io.StringIO()

        async def log_once(msg: str):
            await logger.log(SampleEntry(message=msg), template="{message}")

        with contextlib.redirect_stdout(buf1):
            asyncio.run(log_once("LOOP_ONE"))
        with contextlib.redirect_stdout(buf2):
            asyncio.run(log_once("LOOP_TWO"))

        self.assertEqual(buf1.getvalue().strip(), "LOOP_ONE")
        self.assertEqual(buf2.getvalue().strip(), "LOOP_TWO")

    @unittest.skipIf(sys.platform == "win32", "pty module is Unix/macOS only")
    def test_interactive_pty_tty_device(self):
        import pty
        import select

        master_fd, slave_fd = pty.openpty()
        script = """
        import asyncio
        from async_logging import Entry, LogLevel, Logger, LoggingConfig

        class Msg(Entry, kw_only=True):
            level: LogLevel = LogLevel.INFO

        async def main():
            LoggingConfig().update(log_output="stdout")
            logger = Logger()
            async with logger.context(name="pty_test", template="{message}") as ctx:
                await ctx.log(Msg(message="HELLO_FROM_PTY"))

        asyncio.run(main())
        """
        proc = _popen_child(script, stdout=slave_fd, stderr=slave_fd)
        os.close(slave_fd)
        captured = bytearray()
        try:
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                ready, _, _ = select.select([master_fd], [], [], 0.1)
                if ready:
                    try:
                        chunk = os.read(master_fd, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    captured.extend(chunk)
                elif proc.poll() is not None:
                    break
            proc.wait(timeout=5)
        finally:
            os.close(master_fd)
            if proc.poll() is None:
                proc.kill()
                proc.wait()

        self.assertEqual(proc.returncode, 0)
        self.assertIn("HELLO_FROM_PTY", captured.decode("utf-8", errors="replace"))


if __name__ == "__main__":
    unittest.main()

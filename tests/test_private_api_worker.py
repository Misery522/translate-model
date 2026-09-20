"""通过实际 Python 子进程验证监督、硬取消与回收，不启动 Ollama。"""

import asyncio
import json
import multiprocessing
import signal
import time

import pytest

import yijing_api.worker as worker_module
from yijing_api.worker import ProcessRunner


def controlled_child(connection):
    try:
        while True:
            request = json.loads(connection.recv_bytes())
            if request.get("hold"):
                time.sleep(20)
            connection.send_bytes(json.dumps({"ok": True, "result": {"value": "ready"}}).encode())
    except EOFError:
        pass
    finally:
        connection.close()


def crashed_child(connection):
    connection.close()


class EndOfInputConnection:
    def __init__(self, before_receive):
        self.before_receive = before_receive
        self.closed = False

    def recv_bytes(self, _maximum):
        self.before_receive()
        raise EOFError

    def close(self):
        self.closed = True


def test_worker_ignores_supervisor_sigint_before_waiting(monkeypatch):
    configured = []

    monkeypatch.setattr(
        worker_module.signal,
        "signal",
        lambda signum, handler: configured.append((signum, handler)),
    )
    monkeypatch.setattr("yijing.service.create_default_service", object)

    def assert_signal_is_configured():
        assert configured == [(signal.SIGINT, signal.SIG_IGN)]

    connection = EndOfInputConnection(assert_signal_is_configured)

    worker_module.worker_main(connection)

    assert configured == [(signal.SIGINT, signal.SIG_IGN)]
    assert connection.closed


def test_real_worker_cancel_reaps_before_restart_and_shutdown():
    async def check():
        runner = ProcessRunner(target=controlled_child)
        try:
            assert await asyncio.wait_for(runner.run({}), 5) == {"value": "ready"}
            first_pid = runner.pid
            pending = asyncio.create_task(runner.run({"hold": True}))
            await asyncio.sleep(0.05)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert runner.pid is None
            assert first_pid not in {process.pid for process in multiprocessing.active_children()}
            assert await asyncio.wait_for(runner.run({}), 5) == {"value": "ready"}
            assert runner.pid != first_pid
        finally:
            await runner.close()
        assert runner.pid is None and runner.closed

    asyncio.run(check())


def test_real_worker_crash_is_detected_and_reaped():
    async def check():
        runner = ProcessRunner(target=crashed_child)
        try:
            with pytest.raises((RuntimeError, EOFError, OSError)):
                await asyncio.wait_for(runner.run({}), 5)
            assert runner.pid is None
        finally:
            await runner.close()

    asyncio.run(check())

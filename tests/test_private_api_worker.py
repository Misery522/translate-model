"""通过实际 Python 子进程验证监督、硬取消与回收，不启动 Ollama。"""

import asyncio
import json
import multiprocessing
import time

import pytest

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

"""精确控制调度次序，覆盖尚未启动协程与迟到取消等待者的竞态。"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from uuid import uuid4

import pytest

from yijing_api.config import ApiSettings
from yijing_api.jobs import JobManager


class FakeAuth:
    def active_device_ids(self):
        return {"first", "second"}


class ControlledRunner:
    def __init__(self):
        self.started = defaultdict(asyncio.Event)
        self.release = defaultdict(asyncio.Event)
        self.calls = []
        self.active = self.max_active = 0

    async def run(self, request):
        text = request["text"]
        self.calls.append(text)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.started[text].set()
        try:
            await self.release[text].wait()
            return {
                "route": "translate_text",
                "detected_language": "en",
                "detection_status": "detected",
                "preserved_source": text,
                "translated_text": "测试",
            }
        finally:
            self.active -= 1

    async def close(self):
        assert self.active == 0


def submit(manager, owner, session, text):
    return manager.submit(
        owner, session, str(uuid4()), {"text": text, "target_language": "zh-Hans"}
    )


@pytest.mark.parametrize("delete_session", [False, True])
def test_cancel_before_first_coroutine_step_releases_slot(delete_session):
    async def check():
        async with asyncio.timeout(2):
            runner = ControlledRunner()
            manager = JobManager(ApiSettings(), FakeAuth(), runner)
            first_session = manager.new_session("first")["session_id"]
            second_session = manager.new_session("second")["session_id"]
            manager.start()
            try:
                first = submit(manager, "first", first_session, "first")
                # monitor 在取消任务之前被调度，但新建的 _execute 排在取消任务后。
                cancellation = (
                    manager.delete_session("first", first_session)
                    if delete_session
                    else manager.cancel("first", first.job_id)
                )
                await asyncio.create_task(cancellation)
                assert first.status == "cancelled"
                assert manager.active_id is None and manager._active_task is None
                assert first.request is None and not runner.calls

                runner.release["second"].set()
                second = submit(manager, "second", second_session, "second")
                await runner.started["second"].wait()
                assert second.status == "succeeded"
                assert runner.calls == ["second"] and runner.max_active == 1
            finally:
                await manager.close()

    asyncio.run(check())


def test_two_late_cancel_waiters_do_not_release_new_active_task(monkeypatch):
    async def check():
        async with asyncio.timeout(2):
            runner = ControlledRunner()
            manager = JobManager(ApiSettings(), FakeAuth(), runner)
            first_session = manager.new_session("first")["session_id"]
            second_session = manager.new_session("second")["session_id"]
            manager.start()
            try:
                first = submit(manager, "first", first_session, "first")
                await runner.started["first"].wait()
                old_task = manager._active_task
                second = submit(manager, "second", second_session, "second")
                waiters_ready = asyncio.Event()
                release_waiters = asyncio.Event()
                waiting = 0
                original_shield = asyncio.shield

                async def delayed_shield(task):
                    nonlocal waiting
                    try:
                        return await original_shield(task)
                    except asyncio.CancelledError:
                        if task is old_task:
                            waiting += 1
                            if waiting == 2:
                                waiters_ready.set()
                            # 旧 worker 已回收，但两个 HTTP 取消请求还未收到确认。
                            await release_waiters.wait()
                        raise

                with monkeypatch.context() as patch:
                    patch.setattr(asyncio, "shield", delayed_shield)
                    cancel = asyncio.create_task(manager.cancel("first", first.job_id))
                    clear = asyncio.create_task(manager.delete_session("first", first_session))
                    await waiters_ready.wait()
                    await runner.started["second"].wait()
                    replacement = manager._active_task
                    assert old_task.done() and replacement is not old_task
                    assert manager.active_id == second.job_id
                    release_waiters.set()
                    await asyncio.gather(cancel, clear)
                    assert manager._active_task is replacement and not replacement.done()
                    assert manager.active_id == second.job_id
                    assert runner.max_active == 1 and runner.active == 1
            finally:
                await manager.close()

    asyncio.run(check())

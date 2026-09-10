"""内存任务队列：所有索引由认证设备约束，取消后不接受迟到结果。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from yijing.workflow import AgentResult

from .auth import AuthStore, timestamp
from .config import ApiSettings
from .errors import ApiError, missing
from .worker import Runner

TERMINAL = frozenset({"succeeded", "failed", "cancelled", "timed_out"})


@dataclass
class WorkSession:
    session_id: str
    owner: str
    touched: float
    generation: int = 0


@dataclass
class Job:
    job_id: str
    session_id: str
    owner: str
    client_request_id: str
    generation: int
    digest: str
    created: float
    created_at: str
    request: dict | None
    status: str = "queued"
    result: dict | None = None
    error: dict | None = None
    finished: float | None = None


class JobManager:
    def __init__(
        self,
        settings: ApiSettings,
        auth: AuthStore,
        runner: Runner,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.settings, self.auth, self.runner, self.clock = settings, auth, runner, clock
        self.sessions: dict[str, WorkSession] = {}
        self.jobs: dict[str, Job] = {}
        self.queue: deque[str] = deque()
        self._submission_times: dict[str, deque[float]] = {}
        self.active_id: str | None = None
        self._active_task: asyncio.Task | None = None
        self._monitor: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self.closed = False

    def start(self) -> None:
        self._monitor = asyncio.create_task(self._watch())

    def new_session(self, owner: str) -> dict:
        if self.closed:
            raise ApiError(503, "SHUTTING_DOWN", "服务正在关闭。", retryable=True)
        if (
            sum(session.owner == owner for session in self.sessions.values())
            >= self.settings.sessions_per_device
        ):
            empty = [
                session
                for session in self.sessions.values()
                if session.owner == owner and session.generation == 0
            ]
            if not empty:
                raise ApiError(429, "SESSION_LIMIT", "请先关闭其他工作会话。")
            # 刷新页面遗留的空白会话可回收；已提交过任务的会话不受影响。
            oldest = min(empty, key=lambda session: session.touched)
            self.sessions.pop(oldest.session_id)
        session = WorkSession(str(uuid4()), owner, self.clock())
        self.sessions[session.session_id] = session
        return {
            "session_id": session.session_id,
            "generation": session.generation,
            "expires_at": timestamp(self.settings.session_ttl),
        }

    def session(self, owner: str, session_id: str) -> WorkSession:
        session = self.sessions.get(session_id)
        if (
            not session
            or session.owner != owner
            or self.clock() - session.touched >= self.settings.session_ttl
        ):
            raise missing()
        return session

    def job(self, owner: str, job_id: str) -> Job:
        job = self.jobs.get(job_id)
        if not job or job.owner != owner:
            raise missing()
        self.session(owner, job.session_id)
        if job.finished is not None and self.clock() - job.finished >= self.settings.result_ttl:
            self.jobs.pop(job_id, None)
            raise missing()
        return job

    def submit(self, owner: str, session_id: str, client_request_id: str, request: dict) -> Job:
        if self.closed:
            raise ApiError(503, "SHUTTING_DOWN", "服务正在关闭。", retryable=True)
        session = self.session(owner, session_id)
        digest = hashlib.sha256(
            json.dumps(request, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        for job in self.jobs.values():
            if (job.owner, job.session_id, job.client_request_id) == (
                owner,
                session_id,
                client_request_id,
            ):
                if job.digest != digest:
                    raise ApiError(409, "REQUEST_ID_CONFLICT", "同一请求编号不能用于不同内容。")
                return self.job(owner, job.job_id)
        if any(job.owner == owner and job.status not in TERMINAL for job in self.jobs.values()):
            raise ApiError(409, "DEVICE_BUSY", "当前设备仍有任务，请先等待或取消。", retryable=True)
        queued = sum(job.status == "queued" for job in self.jobs.values())
        # 空闲时首个任务占运行位置，其后的请求才占等待队列。
        capacity = self.settings.max_queued + (1 if self.active_id is None else 0)
        if queued >= capacity:
            raise ApiError(429, "QUEUE_FULL", "当前任务较多，请稍后重试。", retryable=True)
        recent = self._submission_times.setdefault(owner, deque())
        while recent and recent[0] <= self.clock() - 60:
            recent.popleft()
        if len(recent) >= self.settings.submissions_per_minute:
            raise ApiError(429, "REQUEST_RATE_LIMIT", "提交较频繁，请稍后再试。", retryable=True)
        while len(self.jobs) >= self.settings.max_jobs:
            terminal = [job for job in self.jobs.values() if job.status in TERMINAL]
            if not terminal:
                raise ApiError(429, "QUEUE_FULL", "当前任务较多，请稍后重试。", retryable=True)
            oldest = min(terminal, key=lambda job: job.finished or job.created)
            self.jobs.pop(oldest.job_id)
        session.generation += 1
        session.touched = self.clock()
        recent.append(self.clock())
        job = Job(
            str(uuid4()),
            session_id,
            owner,
            client_request_id,
            session.generation,
            digest,
            self.clock(),
            timestamp(),
            request,
        )
        self.jobs[job.job_id] = job
        self.queue.append(job.job_id)
        self._wake.set()
        return job

    def view(self, job: Job) -> dict:
        expires = (
            (job.finished + self.settings.result_ttl)
            if job.finished is not None
            else (job.created + self.settings.queue_timeout + self.settings.run_timeout)
        )
        return {
            "job_id": job.job_id,
            "session_id": job.session_id,
            "client_request_id": job.client_request_id,
            "generation": job.generation,
            "status": job.status,
            "created_at": job.created_at,
            "expires_at": timestamp(expires - self.clock()),
            "result": job.result,
            "error": job.error,
        }

    def _finish(self, job: Job, status: str, *, error: ApiError | None = None) -> None:
        job.status = status
        job.finished = self.clock()
        job.request = None
        job.error = error.detail if error else None
        if status != "succeeded":
            job.result = None

    async def cancel(self, owner: str, job_id: str) -> Job:
        job = self.job(owner, job_id)
        if job.status == "cancelled":
            return job
        self._finish(job, "cancelled")
        if self.active_id == job_id and self._active_task:
            await self._cancel_active()
        self._wake.set()
        return job

    async def _cancel_active(self) -> None:
        task = self._active_task
        if task is None:
            return
        # 重复取消不能再次打断正在进行的 terminate/join 资源回收。
        if not task.done() and task.cancelling() == 0:
            task.cancel()
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current and current.cancelling():
                raise
        finally:
            # 首次调度前取消时，协程体及其 finally 都不会运行。
            # 只在旧任务真正结束后释放其运行位；迟到的取消等待者不能清掉新任务。
            if task.done():
                self._release_active(task)

    def _release_active(self, task: asyncio.Task | None) -> None:
        if self._active_task is task:
            self.active_id = None
            self._active_task = None
            self._wake.set()

    async def delete_session(self, owner: str, session_id: str, *, expired: bool = False) -> None:
        session = self.sessions.get(session_id)
        if not session or session.owner != owner:
            if expired:
                return
            raise missing()
        # 先移除会话，保证运行结束的回调无法重新发布结果。
        self.sessions.pop(session_id, None)
        if self.active_id and self.active_id in self.jobs:
            active = self.jobs[self.active_id]
            if active.session_id == session_id and self._active_task:
                self._finish(active, "cancelled")
                await self._cancel_active()
        for job_id in [key for key, job in self.jobs.items() if job.session_id == session_id]:
            self.jobs.pop(job_id, None)
        self._wake.set()

    async def revoke(self, owner: str) -> None:
        for session in list(self.sessions.values()):
            if session.owner == owner:
                await self.delete_session(owner, session.session_id, expired=True)
        self._submission_times.pop(owner, None)

    async def sweep(self) -> None:
        now = self.clock()
        owners = self.auth.active_device_ids()
        for owner in list(self._submission_times):
            if owner not in owners:
                self._submission_times.pop(owner, None)
        for session in list(self.sessions.values()):
            if session.owner not in owners or now - session.touched >= self.settings.session_ttl:
                await self.delete_session(session.owner, session.session_id, expired=True)
        for job in list(self.jobs.values()):
            if job.status == "queued" and now - job.created >= self.settings.queue_timeout:
                self._finish(
                    job,
                    "timed_out",
                    error=ApiError(408, "QUEUE_TIMEOUT", "排队时间过长，请重试。", retryable=True),
                )
            if job.finished is not None and now - job.finished >= self.settings.result_ttl:
                self.jobs.pop(job.job_id, None)

    async def _execute(self, job: Job) -> None:
        try:
            job.status = "running"
            async with asyncio.timeout(self.settings.run_timeout):
                result = AgentResult.model_validate(await self.runner.run(job.request or {}))
            if job.status == "running" and job.session_id in self.sessions:
                job.result = result.model_dump(mode="json")
                self._finish(job, "succeeded")
        except TimeoutError:
            self._finish(
                job,
                "timed_out",
                error=ApiError(504, "TASK_TIMEOUT", "本次处理超时，请重试。", retryable=True),
            )
        except asyncio.CancelledError:
            self._finish(job, "cancelled")
            raise
        except Exception:
            self._finish(
                job,
                "failed",
                error=ApiError(
                    503,
                    "MODEL_REQUEST_FAILED",
                    "本地处理失败，请检查 Ollama 与词库。",
                    retryable=True,
                ),
            )
        finally:
            job.request = None
            self._release_active(asyncio.current_task())

    async def _watch(self) -> None:
        while not self.closed:
            await self.sweep()
            if self.active_id is None:
                while self.queue:
                    job = self.jobs.get(self.queue.popleft())
                    if job and job.status == "queued":
                        self.active_id = job.job_id
                        self._active_task = asyncio.create_task(self._execute(job))
                        break
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), 0.1)
            except TimeoutError:
                pass

    async def close(self) -> None:
        self.closed = True
        self._wake.set()
        if self._monitor:
            self._monitor.cancel()
            try:
                await self._monitor
            except asyncio.CancelledError:
                pass
        if self._active_task:
            await self._cancel_active()
        try:
            await self.runner.close()
        finally:
            self.queue.clear()
            self.jobs.clear()
            self.sessions.clear()
            self._submission_times.clear()

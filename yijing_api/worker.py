"""一个受监督的推理子进程；停止只针对本 API 创建的 Python 进程。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import multiprocessing
import os
from typing import Protocol

MAX_RESULT_BYTES = 1024 * 1024


class Runner(Protocol):
    async def run(self, request: dict) -> dict: ...
    async def close(self) -> None: ...


def worker_main(connection) -> None:
    # 第三方日志不能把用户内容带回 API 控制台；业务异常转换为固定错误码。
    with (
        open(os.devnull, "w", encoding="utf-8") as sink,
        contextlib.redirect_stdout(sink),
        contextlib.redirect_stderr(sink),
    ):
        from yijing.service import create_default_service
        from yijing.workflow import AgentRequest

        service = create_default_service()
        try:
            while True:
                payload = result = None
                try:
                    payload = json.loads(connection.recv_bytes(32768))
                    result = service.run(AgentRequest.model_validate(payload))
                    encoded = json.dumps(
                        {"ok": True, "result": result.model_dump(mode="json")},
                        ensure_ascii=False,
                    ).encode("utf-8")
                    if len(encoded) > MAX_RESULT_BYTES:
                        encoded = b'{"ok":false,"code":"RESULT_TOO_LARGE"}'
                except EOFError:
                    break
                except Exception:
                    encoded = b'{"ok":false,"code":"MODEL_REQUEST_FAILED"}'
                finally:
                    payload = result = None
                connection.send_bytes(encoded)
                encoded = b""
        finally:
            connection.close()


class ProcessRunner:
    def __init__(self, *, target=worker_main):
        self._context = multiprocessing.get_context("spawn")
        self._target = target
        self._process = None
        self._connection = None
        self._lock = asyncio.Lock()
        self.closed = False

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    def _start(self) -> None:
        parent, child = self._context.Pipe()
        process = self._context.Process(target=self._target, args=(child,), daemon=True)
        process.start()
        child.close()
        self._connection = parent
        self._process = process

    async def _stop(self) -> None:
        process = self._process
        connection = self._connection
        if process is not None:
            if process.is_alive():
                process.terminate()
            await asyncio.to_thread(process.join, 2)
            if process.is_alive():
                process.kill()
                await asyncio.to_thread(process.join, 2)
            if process.is_alive():
                self.closed = True
                raise RuntimeError("Worker could not be reaped")
            process.close()
        if connection is not None:
            connection.close()
        self._process = self._connection = None

    async def run(self, request: dict) -> dict:
        async with self._lock:
            if self.closed:
                raise RuntimeError("Runner closed")
            try:
                if self._process is None:
                    self._start()
                encoded = json.dumps(request, ensure_ascii=False).encode("utf-8")
                await asyncio.to_thread(self._connection.send_bytes, encoded)
                while not self._connection.poll():
                    if not self._process.is_alive():
                        raise RuntimeError("Worker exited")
                    await asyncio.sleep(0.02)
                answer = json.loads(
                    await asyncio.to_thread(self._connection.recv_bytes, MAX_RESULT_BYTES)
                )
                if not answer.get("ok"):
                    raise RuntimeError("Model request failed")
                return answer["result"]
            except BaseException:
                await self._stop()
                raise

    async def close(self) -> None:
        self.closed = True
        async with self._lock:
            await self._stop()

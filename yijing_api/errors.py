from __future__ import annotations

from uuid import uuid4


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, *, retryable: bool = False):
        super().__init__(code)
        self.status = status
        self.detail = {
            "code": code,
            "message": message,
            "retryable": retryable,
            "request_id": str(uuid4()),
        }


def missing() -> ApiError:
    return ApiError(404, "NOT_FOUND", "会话或任务不存在，可能已经过期。")

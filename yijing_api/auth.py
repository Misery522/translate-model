"""认证凭据仅保存在内存；配对码只能由本机控制台生成。"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from .config import ApiSettings
from .errors import ApiError


def timestamp(seconds: float = 0) -> str:
    return (datetime.now(UTC) + timedelta(seconds=max(0, seconds))).isoformat()


@dataclass
class Principal:
    device_id: str
    device_name: str
    auth_mode: str
    digest: str
    csrf_token: str
    created: float
    last_seen: float
    recent_requests: deque[float] = field(default_factory=deque)
    credit: float = 0.0
    credit_updated: float = 0.0


class AuthStore:
    def __init__(self, settings: ApiSettings, clock: Callable[[], float] = time.monotonic):
        self.settings = settings
        self.clock = clock
        self._lock = threading.RLock()
        self._credentials: dict[str, Principal] = {}
        self._pair_hash = ""
        self._pair_expires = 0.0
        self._global_attempts: deque[float] = deque()
        self._peer_attempts: OrderedDict[str, deque[float]] = OrderedDict()

    def issue_pair_code(self) -> str:
        with self._lock:
            code = base64.b32encode(secrets.token_bytes(8)).decode("ascii")[:12]
            self._pair_hash = hashlib.sha256(code.encode()).hexdigest()
            self._pair_expires = self.clock() + self.settings.pairing_ttl
            return code

    def _rate_limit(self, peer: str) -> None:
        now = self.clock()
        while self._global_attempts and self._global_attempts[0] <= now - 300:
            self._global_attempts.popleft()
        attempts = self._peer_attempts.setdefault(peer, deque())
        self._peer_attempts.move_to_end(peer)
        while len(self._peer_attempts) > 64:
            self._peer_attempts.popitem(last=False)
        while attempts and attempts[0] <= now - 60:
            attempts.popleft()
        if len(attempts) >= 5 or len(self._global_attempts) >= 30:
            raise ApiError(429, "PAIR_RATE_LIMIT", "配对尝试较多，请稍后再试。", retryable=True)
        attempts.append(now)
        self._global_attempts.append(now)

    def active_device_ids(self) -> set[str]:
        with self._lock:
            now = self.clock()
            self._credentials = {
                digest: user
                for digest, user in self._credentials.items()
                if now - user.created < self.settings.auth_absolute_ttl
                and now - user.last_seen < self.settings.auth_idle_ttl
            }
            return {user.device_id for user in self._credentials.values()}

    def exchange(self, code: str, device_name: str, mode: str, peer: str) -> tuple[str, Principal]:
        with self._lock:
            self._rate_limit(peer)
            provided = hashlib.sha256(code.upper().encode()).hexdigest()
            if self.clock() >= self._pair_expires or not secrets.compare_digest(
                provided, self._pair_hash
            ):
                raise ApiError(401, "INVALID_PAIR_CODE", "配对码无效或已过期。")
            if len(self.active_device_ids()) >= self.settings.max_devices:
                raise ApiError(429, "DEVICE_LIMIT", "已达到设备数量上限。")
            self._pair_hash = ""
            self._pair_expires = 0
            token = secrets.token_urlsafe(32)
            digest = hashlib.sha256(token.encode()).hexdigest()
            user = Principal(
                str(uuid4()),
                device_name,
                mode,
                digest,
                secrets.token_urlsafe(32),
                self.clock(),
                self.clock(),
                credit=float(self.settings.authenticated_burst),
                credit_updated=self.clock(),
            )
            self._credentials[digest] = user
            return token, user

    def authenticate(self, token: str, mode: str) -> Principal:
        with self._lock:
            self.active_device_ids()
            digest = hashlib.sha256(token.encode()).hexdigest()
            user = self._credentials.get(digest)
            if (
                user is None
                or user.auth_mode != mode
                or not secrets.compare_digest(user.digest, digest)
            ):
                raise ApiError(401, "UNAUTHENTICATED", "请在本机获取配对码并重新连接。")
            now = self.clock()
            user.credit = min(
                self.settings.authenticated_burst,
                user.credit
                + (now - user.credit_updated) * self.settings.authenticated_per_minute / 60,
            )
            user.credit_updated = now
            while user.recent_requests and user.recent_requests[0] <= now - 60:
                user.recent_requests.popleft()
            if (
                user.credit < 1
                or len(user.recent_requests) >= self.settings.authenticated_per_minute
            ):
                raise ApiError(429, "AUTH_RATE_LIMIT", "请求较频繁，请稍后再试。", retryable=True)
            user.credit -= 1
            user.recent_requests.append(now)
            user.last_seen = self.clock()
            return user

    def view(self, user: Principal) -> dict:
        remaining = min(
            self.settings.auth_absolute_ttl - (self.clock() - user.created),
            self.settings.auth_idle_ttl,
        )
        return {
            "device_id": user.device_id,
            "device_name": user.device_name,
            "auth_mode": user.auth_mode,
            "expires_at": timestamp(remaining),
            "csrf_token": user.csrf_token if user.auth_mode == "cookie" else None,
        }

    def revoke(self, user: Principal) -> None:
        with self._lock:
            self._credentials.pop(user.digest, None)

    def clear(self) -> None:
        with self._lock:
            self._credentials.clear()
            self._pair_hash = ""
            self._pair_expires = 0
            self._global_attempts.clear()
            self._peer_attempts.clear()

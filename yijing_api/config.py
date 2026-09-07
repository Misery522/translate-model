"""私人 API 的显式部署边界与资源上限。"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import urlsplit


def normalized_origin(value: str, *, client: bool = False) -> str:
    if not value or value != value.strip() or value == "null" or "*" in value:
        raise ValueError("Origin 必须是明确的可信地址")
    parsed = urlsplit(value)
    schemes = {"http", "https", "tauri", "capacitor"} if client else {"http", "https"}
    if (
        parsed.scheme not in schemes
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Origin 不能包含用户凭据、路径或查询参数")
    port = parsed.port
    host = parsed.hostname.lower()
    if not client and parsed.scheme == "http":
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = host == "localhost"
        if not local:
            raise ValueError("非本机访问必须使用 HTTPS")
    authority = f"[{host}]" if ":" in host else host
    if port and (parsed.scheme, port) not in {("http", 80), ("https", 443)}:
        authority += f":{port}"
    return f"{parsed.scheme}://{authority}"


@dataclass(frozen=True)
class ApiSettings:
    port: int = 8765
    public_origin: str = "http://127.0.0.1:8765"
    client_origins: tuple[str, ...] = ()
    pairing_ttl: float = 300
    auth_idle_ttl: float = 1800
    auth_absolute_ttl: float = 86400
    session_ttl: float = 1800
    queue_timeout: float = 30
    run_timeout: float = 180
    result_ttl: float = 300
    max_devices: int = 16
    sessions_per_device: int = 4
    max_queued: int = 8
    max_jobs: int = 64
    submissions_per_minute: int = 10
    authenticated_per_minute: int = 120
    authenticated_burst: int = 30
    request_bytes: int = 32768
    glossary_bytes: int = 524288

    def __post_init__(self) -> None:
        if not 1 <= self.port <= 65535:
            raise ValueError("端口必须在 1–65535 之间")
        object.__setattr__(self, "public_origin", normalized_origin(self.public_origin))
        object.__setattr__(
            self,
            "client_origins",
            tuple(normalized_origin(origin, client=True) for origin in self.client_origins),
        )
        for field in (
            "pairing_ttl",
            "auth_idle_ttl",
            "auth_absolute_ttl",
            "session_ttl",
            "queue_timeout",
            "run_timeout",
            "result_ttl",
            "max_devices",
            "sessions_per_device",
            "max_queued",
            "max_jobs",
            "submissions_per_minute",
            "authenticated_per_minute",
            "authenticated_burst",
            "request_bytes",
            "glossary_bytes",
        ):
            value = getattr(self, field)
            if not isinstance(value, (int, float)) or not 0 < value < float("inf"):
                raise ValueError(f"{field} 必须为有限正数")

    @property
    def secure(self) -> bool:
        return self.public_origin.startswith("https://")

    @property
    def cookie_name(self) -> str:
        return "__Host-yijing_session" if self.secure else "yijing_dev_session"

    @property
    def authority(self) -> str:
        return urlsplit(self.public_origin).netloc

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        return (self.public_origin, *self.client_origins)

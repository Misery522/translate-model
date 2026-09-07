"""私人 HTTP 契约、设备认证、CSRF 与原文生命周期管理。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException

from yijing.glossary import DOMAINS, TARGET_LANGUAGES, GlossaryDocument, GlossaryEntry
from yijing.service import create_default_service
from yijing.workflow import AgentRequest

from .auth import AuthStore, Principal
from .config import ApiSettings
from .errors import ApiError
from .jobs import JobManager
from .models import (
    AuthView,
    CapabilitiesView,
    ErrorEnvelope,
    GlossaryView,
    HealthView,
    JobView,
    PairView,
    SessionView,
)
from .worker import ProcessRunner, Runner


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PairRequest(InputModel):
    code: str = Field(min_length=12, max_length=12, pattern=r"^[A-Za-z2-7]{12}$")
    device_name: str = Field(min_length=1, max_length=64)
    auth_mode: Literal["cookie", "bearer"] = "cookie"


class EmptyRequest(InputModel):
    pass


class TranslationSubmission(InputModel):
    session_id: UUID
    client_request_id: UUID
    request: AgentRequest


class GlossaryUpdate(InputModel):
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    entries: list[GlossaryEntry] = Field(max_length=500)


def error_response(error: ApiError) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    if error.status == 429:
        headers["Retry-After"] = "5"
    return JSONResponse({"error": error.detail}, status_code=error.status, headers=headers)


class BoundaryMiddleware:
    """在路由执行前拒绝未知 Host/Origin，并限制实际接收的正文总量。"""

    def __init__(self, app, settings: ApiSettings):
        self.app, self.settings = app, settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {}
        response_started = response_complete = False
        duplicate_security_header = False
        protected = {
            b"host",
            b"origin",
            b"authorization",
            b"cookie",
            b"content-length",
            b"x-csrf-token",
        }
        for key, value in scope.get("headers", []):
            if key in protected and key in headers:
                duplicate_security_header = True
            headers[key] = value.decode("latin1")
        try:
            if (
                duplicate_security_header
                or headers.get(b"host", "").lower() != self.settings.authority
            ):
                raise ApiError(400, "INVALID_HOST", "服务地址不符合配置。")
            origin = headers.get(b"origin")
            if origin is not None and origin not in self.settings.allowed_origins:
                raise ApiError(403, "ORIGIN_REJECTED", "请求来源未获授权。")
            if scope["path"].startswith("/api/") and scope.get("query_string"):
                raise ApiError(400, "QUERY_NOT_ALLOWED", "请使用指定的 JSON 请求格式。")
            body = bytearray()
            if scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
                if headers.get(b"content-encoding", "identity").lower() != "identity":
                    raise ApiError(415, "UNSUPPORTED_CONTENT_TYPE", "请求正文不支持压缩编码。")
                if (
                    scope["method"] in {"POST", "PUT", "PATCH"}
                    and headers.get(b"content-type", "").split(";", 1)[0].strip().lower()
                    != "application/json"
                ):
                    raise ApiError(
                        415, "UNSUPPORTED_CONTENT_TYPE", "请发送 application/json 正文。"
                    )
                limit = (
                    self.settings.glossary_bytes
                    if scope["path"] == "/api/v1/glossary"
                    else self.settings.request_bytes
                )
                length = headers.get(b"content-length")
                if length is not None and (not length.isascii() or not length.isdecimal()):
                    raise ApiError(400, "INVALID_CONTENT_LENGTH", "请求长度无效。")
                if length is not None and int(length) > limit:
                    raise ApiError(413, "PAYLOAD_TOO_LARGE", "请求内容超过容量限制。")
                async with asyncio.timeout(5):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        body.extend(message.get("body", b""))
                        if len(body) > limit:
                            raise ApiError(413, "PAYLOAD_TOO_LARGE", "请求内容超过容量限制。")
                        if not message.get("more_body", False):
                            break
                if length is not None and int(length) != len(body):
                    raise ApiError(400, "INVALID_CONTENT_LENGTH", "请求长度不一致。")
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered and scope["method"] not in {"GET", "HEAD", "OPTIONS"}:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            async def secure_send(message):
                nonlocal response_started, response_complete
                if message["type"] == "http.response.start":
                    response_started = True
                    extra = [
                        (b"x-content-type-options", b"nosniff"),
                        (b"referrer-policy", b"same-origin"),
                    ]
                    if scope["path"].startswith("/api/"):
                        extra.append((b"cache-control", b"no-store"))
                    message = {**message, "headers": [*message.get("headers", []), *extra]}
                if message["type"] == "http.response.body" and not message.get("more_body", False):
                    response_complete = True
                await send(message)

            await self.app(scope, replay, secure_send)
        except ApiError as error:
            await error_response(error)(scope, receive, send)
        except TimeoutError:
            await error_response(ApiError(408, "BODY_TIMEOUT", "请求接收超时。"))(
                scope, receive, send
            )
        except Exception:
            # Starlette 的全局 500 handler 在响应后仍会重新抛出异常；在此截断，
            # 防止 Uvicorn 输出可能包含原文的异常正文或回溯。
            logging.getLogger(__name__).warning("API_HANDLER_FAILED")
            if not response_started:
                await error_response(
                    ApiError(500, "INTERNAL_ERROR", "服务处理失败，请稍后重试。", retryable=True)
                )(scope, receive, send)
            elif not response_complete:
                await send({"type": "http.response.body", "body": b"", "more_body": False})


def create_app(
    settings: ApiSettings | None = None,
    *,
    runner: Runner | None = None,
    service=None,
    clock: Callable[[], float] = time.monotonic,
) -> FastAPI:
    settings = settings or ApiSettings()
    auth = AuthStore(settings, clock)
    jobs = JobManager(settings, auth, runner or ProcessRunner(), clock)
    service = service or create_default_service()
    glossary_lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(_app):
        jobs.start()
        try:
            yield
        finally:
            try:
                await jobs.close()
            finally:
                auth.clear()
                _app.state.pairing_code = None

    app = FastAPI(
        title="译境私人 API",
        version="1",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        responses={
            status: {"model": ErrorEnvelope}
            for status in (400, 401, 403, 404, 409, 413, 415, 422, 429, 500, 503)
        },
    )
    app.state.auth = auth
    app.state.jobs = jobs
    app.state.settings = settings
    # 只有启动方读取并打印；一次兑换后立即移除明文引用。
    app.state.pairing_code = auth.issue_pair_code()

    @app.exception_handler(ApiError)
    async def handle_api_error(_request, error):
        return error_response(error)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_request, _error):
        return error_response(ApiError(422, "INVALID_REQUEST", "请求参数无效，请检查内容与选项。"))

    @app.exception_handler(HTTPException)
    async def handle_http(_request, error):
        return error_response(ApiError(error.status_code, "HTTP_ERROR", "请求路径或方法不受支持。"))

    @app.exception_handler(Exception)
    async def handle_unknown(_request, _error):
        return error_response(
            ApiError(500, "INTERNAL_ERROR", "服务处理失败，请稍后重试。", retryable=True)
        )

    def browser_origin(request: Request) -> bool:
        origin = request.headers.get("origin")
        if origin is not None:
            return origin == settings.public_origin
        referer = request.headers.get("referer", "")
        try:
            parsed = urlsplit(referer)
            return f"{parsed.scheme}://{parsed.netloc}" == settings.public_origin
        except ValueError:
            return False

    async def principal(request: Request) -> Principal:
        authorization = request.headers.get("authorization")
        cookie = request.cookies.get(settings.cookie_name)
        if authorization and cookie:
            raise ApiError(400, "AMBIGUOUS_AUTH", "请仅使用一种认证方式。")
        if authorization:
            scheme, _, token = authorization.partition(" ")
            if scheme.lower() != "bearer" or not token or len(token) > 128:
                raise ApiError(401, "UNAUTHENTICATED", "认证信息无效。")
            user = auth.authenticate(token, "bearer")
        elif cookie and len(cookie) <= 128:
            if request.headers.get("cookie", "").count(settings.cookie_name + "=") > 1:
                raise ApiError(400, "AMBIGUOUS_AUTH", "认证 Cookie 重复。")
            user = auth.authenticate(cookie, "cookie")
            origin = request.headers.get("origin")
            if origin is not None and origin != settings.public_origin:
                raise ApiError(403, "ORIGIN_REJECTED", "浏览器会话只允许同源访问。")
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                csrf = request.headers.get("x-csrf-token", "")
                if not browser_origin(request) or not secrets.compare_digest(
                    csrf.encode(), user.csrf_token.encode()
                ):
                    raise ApiError(403, "CSRF_REJECTED", "页面会话无效，请刷新后重试。")
        else:
            raise ApiError(401, "UNAUTHENTICATED", "请先输入本机配对码。")
        return user

    auth_dependency = Depends(principal)

    @app.get("/api/v1/health", response_model=HealthView)
    async def health():
        return {"status": "ok", "api_version": "1"}

    @app.post("/api/v1/pair/exchange", status_code=201, response_model=PairView)
    async def exchange(payload: PairRequest, request: Request, response: Response):
        if payload.auth_mode == "cookie" and not browser_origin(request):
            raise ApiError(403, "ORIGIN_REJECTED", "请从可信的译境页面配对。")
        if not payload.device_name.strip():
            raise ApiError(422, "INVALID_REQUEST", "设备名称不能为空。")
        token, user = auth.exchange(
            payload.code,
            payload.device_name.strip(),
            payload.auth_mode,
            request.client.host if request.client else "unknown",
        )
        app.state.pairing_code = None
        if user.auth_mode == "cookie":
            response.set_cookie(
                settings.cookie_name,
                token,
                httponly=True,
                secure=settings.secure,
                samesite="strict",
                path="/",
                max_age=int(settings.auth_absolute_ttl),
            )
        return {
            **auth.view(user),
            "access_token": token if user.auth_mode == "bearer" else None,
            "token_type": "Bearer" if user.auth_mode == "bearer" else None,
        }

    @app.get("/api/v1/auth/session", response_model=AuthView)
    async def current_auth(user: Principal = auth_dependency):
        return auth.view(user)

    @app.delete("/api/v1/auth/session", status_code=204)
    async def logout(response: Response, user: Principal = auth_dependency):
        auth.revoke(user)
        await jobs.revoke(user.device_id)
        response.delete_cookie(
            settings.cookie_name, path="/", secure=settings.secure, httponly=True, samesite="strict"
        )

    @app.get("/api/v1/capabilities", response_model=CapabilitiesView)
    async def capabilities(_user: Principal = auth_dependency):
        return {
            "api_version": "1",
            "target_languages": list(TARGET_LANGUAGES),
            "styles": ["standard", "formal", "colloquial"],
            "domains": [domain for domain in DOMAINS if domain != "all"],
            "task_modes": ["auto", "translate", "annotate_code", "annotate_special"],
            "limits": {
                "text_characters": 4000,
                "queued_jobs": settings.max_queued,
                "active_jobs_per_device": 1,
                "queue_timeout_seconds": settings.queue_timeout,
                "run_timeout_seconds": settings.run_timeout,
            },
            "model": {"provider": "ollama", "status": "unknown"},
        }

    @app.post("/api/v1/sessions", status_code=201, response_model=SessionView)
    async def new_session(_payload: EmptyRequest, user: Principal = auth_dependency):
        return jobs.new_session(user.device_id)

    @app.delete("/api/v1/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str, user: Principal = auth_dependency):
        await jobs.delete_session(user.device_id, session_id)

    @app.post("/api/v1/translations", status_code=202, response_model=JobView)
    async def submit(payload: TranslationSubmission, user: Principal = auth_dependency):
        job = jobs.submit(
            user.device_id,
            str(payload.session_id),
            str(payload.client_request_id),
            payload.request.model_dump(mode="json"),
        )
        return jobs.view(job)

    @app.get("/api/v1/translations/{job_id}", response_model=JobView)
    async def get_job(job_id: str, user: Principal = auth_dependency):
        return jobs.view(jobs.job(user.device_id, job_id))

    @app.post("/api/v1/translations/{job_id}/cancel", response_model=JobView)
    async def cancel_job(job_id: str, _payload: EmptyRequest, user: Principal = auth_dependency):
        return jobs.view(await jobs.cancel(user.device_id, job_id))

    def glossary_view(document: GlossaryDocument) -> dict:
        revision = hashlib.sha256(
            json.dumps(
                document.model_dump(mode="json"), sort_keys=True, ensure_ascii=False
            ).encode()
        ).hexdigest()
        return {
            "revision": revision,
            "entries": [entry.model_dump(mode="json") for entry in document.entries],
        }

    @app.get("/api/v1/glossary", response_model=GlossaryView)
    async def list_glossary(_user: Principal = auth_dependency):
        async with glossary_lock:
            try:
                return glossary_view(service.list_glossary())
            except Exception:
                raise ApiError(503, "GLOSSARY_UNAVAILABLE", "词库不可用，请在本机检查。") from None

    @app.put("/api/v1/glossary", response_model=GlossaryView)
    async def save_glossary(payload: GlossaryUpdate, _user: Principal = auth_dependency):
        if any(len(entry.source) > 500 or len(entry.target) > 500 for entry in payload.entries):
            raise ApiError(422, "INVALID_REQUEST", "单个术语内容不能超过 500 个字符。")
        async with glossary_lock:
            try:
                current = glossary_view(service.list_glossary())
                if not secrets.compare_digest(current["revision"], payload.revision):
                    raise ApiError(409, "GLOSSARY_CONFLICT", "词库已经更新，请重新加载后编辑。")
                return glossary_view(
                    service.save_glossary(GlossaryDocument(entries=payload.entries))
                )
            except ApiError:
                raise
            except Exception:
                raise ApiError(
                    422, "GLOSSARY_INVALID", "词库内容冲突或无法保存，请检查词条。"
                ) from None

    @app.get("/api/v1/openapi.json", include_in_schema=False)
    async def authenticated_schema(_user: Principal = auth_dependency):
        return app.openapi()

    def schema():
        if app.openapi_schema is None:
            result = get_openapi(title=app.title, version=app.version, routes=app.routes)
            result["components"]["securitySchemes"] = {
                "SessionCookie": {"type": "apiKey", "in": "cookie", "name": settings.cookie_name},
                "BearerAuth": {"type": "http", "scheme": "bearer"},
            }
            for path, operations in result["paths"].items():
                if path not in {"/api/v1/health", "/api/v1/pair/exchange"}:
                    for operation in operations.values():
                        operation["security"] = [{"SessionCookie": []}, {"BearerAuth": []}]
            app.openapi_schema = result
        return app.openapi_schema

    app.openapi = schema

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
        expose_headers=["Retry-After"],
        max_age=600,
    )
    app.add_middleware(BoundaryMiddleware, settings=settings)
    return app

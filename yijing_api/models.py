"""稳定的公开响应类型，同时用于 OpenAPI 与运行时响应校验。"""

from typing import Literal

from pydantic import BaseModel

from yijing.glossary import GlossaryEntry
from yijing.workflow import AgentResult


class ApiErrorView(BaseModel):
    code: str
    message: str
    retryable: bool
    request_id: str


class ErrorEnvelope(BaseModel):
    error: ApiErrorView


class HealthView(BaseModel):
    status: Literal["ok"]
    api_version: Literal["1"]


class AuthView(BaseModel):
    device_id: str
    device_name: str
    auth_mode: Literal["cookie", "bearer"]
    expires_at: str
    csrf_token: str | None


class PairView(AuthView):
    access_token: str | None
    token_type: Literal["Bearer"] | None


class SessionView(BaseModel):
    session_id: str
    generation: int
    expires_at: str


class JobView(BaseModel):
    job_id: str
    session_id: str
    client_request_id: str
    generation: int
    status: Literal["queued", "running", "succeeded", "failed", "cancelled", "timed_out"]
    created_at: str
    expires_at: str
    result: AgentResult | None
    error: ApiErrorView | None


class LimitsView(BaseModel):
    text_characters: int
    queued_jobs: int
    active_jobs_per_device: int
    queue_timeout_seconds: float
    run_timeout_seconds: float


class ModelView(BaseModel):
    provider: Literal["ollama"]
    status: Literal["unknown"]


class CapabilitiesView(BaseModel):
    api_version: Literal["1"]
    target_languages: list[str]
    styles: list[str]
    domains: list[str]
    task_modes: list[str]
    limits: LimitsView
    model: ModelView


class GlossaryView(BaseModel):
    revision: str
    entries: list[GlossaryEntry]

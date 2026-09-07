"""与界面无关的翻译服务：统一请求串行化、术语快照和本地推理适配。"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from langsmith import tracing_context
from pydantic import ValidationError

from yijing.glossary import GlossaryDocument, GlossaryError, GlossaryStore
from yijing.paths import data_directory
from yijing.translation import TranslationError, Translator
from yijing.workflow import AgentRequest, AgentResult, TranslationWorkflow


@runtime_checkable
class WorkflowPort(Protocol):
    def run(self, request: AgentRequest) -> AgentResult: ...


@runtime_checkable
class GlossaryRepository(Protocol):
    def load(self) -> GlossaryDocument: ...

    def save(self, document: GlossaryDocument) -> GlossaryDocument: ...


@runtime_checkable
class InferenceProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    def create_workflow(self, *, glossary_repository: GlossaryRepository) -> WorkflowPort: ...


class OllamaProvider:
    """将既有本机推理实现接入服务；首次使用才创建模型适配器。"""

    def __init__(
        self,
        *,
        translator: Translator | None = None,
        model_name: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        keep_alive: int | str | None = None,
    ) -> None:
        if translator is not None and any(
            value is not None for value in (model_name, base_url, timeout, keep_alive)
        ):
            raise ValueError("传入已配置的 Translator 时不能同时指定模型配置。")
        self._translator = translator
        self._model_name = model_name
        self._base_url = base_url
        self._timeout = timeout
        self._keep_alive = keep_alive
        self._initialization_lock = threading.Lock()

    @property
    def provider_id(self) -> Literal["ollama"]:
        return "ollama"

    def create_workflow(self, *, glossary_repository: GlossaryRepository) -> WorkflowPort:
        with self._initialization_lock:
            if self._translator is None:
                self._translator = Translator(
                    model_name=self._model_name,
                    base_url=self._base_url,
                    timeout=self._timeout,
                    keep_alive=self._keep_alive,
                )
            return TranslationWorkflow(
                translator=self._translator,
                glossary_store=glossary_repository,
            )


class _RequestGlossarySnapshot:
    """工作流固定持有的只读入口，快照仅在持有服务请求锁期间有效。"""

    def __init__(self) -> None:
        self._document: GlossaryDocument | None = None

    def bind(self, document: GlossaryDocument) -> None:
        self._document = document

    def clear(self) -> None:
        self._document = None

    def load(self) -> GlossaryDocument:
        if self._document is None:
            raise GlossaryError("当前没有正在执行的翻译请求。")
        return self._document.model_copy(deep=True)

    def save(self, document: GlossaryDocument) -> GlossaryDocument:
        raise GlossaryError("翻译请求内的术语快照只读，请通过术语管理入口保存。")


class TranslationService:
    """每个服务实例串行执行整轮工作流，术语管理可在推理期间独立进行。

    一个服务实例应由其 UI/API 入口共享。工作流及客户端安全复用，避免每轮
    创建路由或注解客户端；请求原文、结果和术语快照不在轮次结束后留存。
    """

    def __init__(
        self,
        provider: InferenceProvider,
        glossary_repository: GlossaryRepository,
    ) -> None:
        self._provider = provider
        self._provider_id = provider.provider_id
        self._glossary_repository = glossary_repository
        self._request_lock = threading.Lock()
        self._glossary_lock = threading.Lock()
        self._snapshot = _RequestGlossarySnapshot()
        self._workflow: WorkflowPort | None = None

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @tracing_context(enabled=False)
    def run(self, request: AgentRequest) -> AgentResult:
        try:
            try:
                normalized = AgentRequest.model_validate(request).model_copy(deep=True)
            except ValidationError:
                raise TranslationError(
                    "INVALID_REQUEST", "处理请求参数无效，请检查输入、语言、风格和任务模式。"
                ) from None

            # 快照在排队请求取得执行权时建立；随后词库保存不影响本轮。
            with self._request_lock:
                with self._glossary_lock:
                    snapshot = self._glossary_repository.load().model_copy(deep=True)
                self._snapshot.bind(snapshot)
                try:
                    if self._workflow is None:
                        self._workflow = self._provider.create_workflow(
                            glossary_repository=self._snapshot
                        )
                    result = self._workflow.run(normalized)
                    return AgentResult.model_validate(result).model_copy(deep=True)
                finally:
                    self._snapshot.clear()
        except (TranslationError, GlossaryError):
            raise
        except Exception:
            # 未知依赖异常可能包含原文、译文或私有路径，不能暴露异常正文。
            raise TranslationError(
                "SERVICE_REQUEST_FAILED", "本地处理失败，请检查模型与词库状态后重试。",
                retryable=True,
            ) from None

    def list_glossary(self) -> GlossaryDocument:
        try:
            with self._glossary_lock:
                return self._glossary_repository.load().model_copy(deep=True)
        except (TranslationError, GlossaryError):
            raise
        except Exception:
            raise TranslationError(
                "GLOSSARY_READ_FAILED", "读取术语库失败，请检查本地词库状态。"
            ) from None

    def save_glossary(self, document: GlossaryDocument) -> GlossaryDocument:
        try:
            with self._glossary_lock:
                saved = self._glossary_repository.save(document.model_copy(deep=True))
                return saved.model_copy(deep=True)
        except (TranslationError, GlossaryError):
            raise
        except Exception:
            raise TranslationError(
                "GLOSSARY_SAVE_FAILED", "保存术语库失败，请检查本地词库状态。"
            ) from None


def create_default_service(
    *, glossary_path: str | os.PathLike[str] | None = None
) -> TranslationService:
    """从本机配置创建服务；不连接模型、不创建目录，也不记录任何路径。"""

    path = Path(glossary_path) if glossary_path is not None else data_directory() / "glossary.json"
    return TranslationService(OllamaProvider(), GlossaryStore(path))


__all__ = [
    "GlossaryRepository",
    "InferenceProvider",
    "OllamaProvider",
    "TranslationService",
    "WorkflowPort",
    "create_default_service",
]

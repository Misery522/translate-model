from __future__ import annotations

import subprocess
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
from langsmith import tracing_context
from langsmith.utils import tracing_is_enabled

from yijing import service as application_service
from yijing.glossary import (
    GlossaryConflictError,
    GlossaryDocument,
    GlossaryEntry,
    GlossaryError,
    GlossaryFormatError,
    GlossaryStore,
)
from yijing.service import (
    GlossaryRepository,
    InferenceProvider,
    OllamaProvider,
    TranslationService,
    WorkflowPort,
    create_default_service,
)
from yijing.translation import TranslationError, Translator
from yijing.workflow import AgentRequest, AgentResult


def document(target="接口"):
    return GlossaryDocument(entries=[
        GlossaryEntry(source="API", target=target, target_language="zh-Hans")
    ])


def request(text="Hello"):
    return AgentRequest(text=text, target_language="zh-Hans", task_mode="translate")


def result(source):
    return AgentResult(
        route="translate_text", detected_language="en", detection_status="detected",
        preserved_source=source.text, translated_text="你好",
    )


class MemoryRepository:
    def __init__(self):
        self.document = document()
        self.load_count = 0

    def load(self):
        self.load_count += 1
        return self.document

    def save(self, saved):
        self.document = saved
        return self.document


class FakeWorkflow:
    def __init__(self, repository, callback=None):
        self.repository = repository
        self.callback = callback

    def run(self, source):
        return self.callback(source, self.repository) if self.callback else result(source)


class FakeProvider:
    def __init__(self, callback=None):
        self.callback = callback
        self.create_count = 0
        self.workflow = None

    @property
    def provider_id(self):
        return "fake"

    def create_workflow(self, *, glossary_repository):
        self.create_count += 1
        self.workflow = FakeWorkflow(glossary_repository, self.callback)
        return self.workflow


def test_provider_can_be_replaced_without_ui_or_ollama():
    provider = FakeProvider()
    repository = MemoryRepository()
    service = TranslationService(provider, repository)
    assert isinstance(provider, InferenceProvider)
    assert isinstance(repository, GlossaryRepository)
    assert service.run(request()).translated_text == "你好"
    assert isinstance(provider.workflow, WorkflowPort)
    assert service.provider_id == "fake"


@pytest.mark.parametrize("owner", ["provider", "service"])
def test_provider_id_is_read_only(owner):
    provider = OllamaProvider()
    target = provider if owner == "provider" else TranslationService(provider, MemoryRepository())
    with pytest.raises(AttributeError):
        target.provider_id = "changed"
    assert target.provider_id == "ollama"


@pytest.mark.parametrize("configuration", [
    {},
    {"model_name": "qwen3.5:4b"},
    {"base_url": "http://localhost:11434"},
    {"timeout": 7.5},
    {"keep_alive": "12m"},
    {"keep_alive": 0},
])
def test_ollama_configuration_is_forwarded_lazily(configuration, monkeypatch):
    captured = []

    def make_translator(**kwargs):
        captured.append(kwargs)
        return object()

    monkeypatch.setattr(application_service, "Translator", make_translator)
    monkeypatch.setattr(
        application_service, "TranslationWorkflow",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    provider = OllamaProvider(**configuration)
    assert captured == []
    repository = MemoryRepository()
    workflow = provider.create_workflow(glossary_repository=repository)
    assert captured == [{
        "model_name": configuration.get("model_name"),
        "base_url": configuration.get("base_url"),
        "timeout": configuration.get("timeout"),
        "keep_alive": configuration.get("keep_alive"),
    }]
    assert workflow.glossary_store is repository
    second = provider.create_workflow(glossary_repository=repository)
    assert second.translator is workflow.translator
    assert len(captured) == 1


def test_existing_translator_is_reused_for_startup_diagnostics(monkeypatch):
    translator = Translator(model=object())

    def must_not_construct(**_kwargs):
        raise AssertionError("Injected translator must be reused")

    monkeypatch.setattr(application_service, "Translator", must_not_construct)
    workflow = OllamaProvider(translator=translator).create_workflow(
        glossary_repository=MemoryRepository()
    )
    assert workflow.translator is translator


@pytest.mark.parametrize("configuration", [
    {"model_name": "configured"}, {"base_url": "http://localhost:11434"},
    {"timeout": 5}, {"keep_alive": 0},
])
def test_injected_translator_does_not_silently_ignore_configuration(configuration):
    with pytest.raises(ValueError, match="不能同时"):
        OllamaProvider(translator=Translator(model=object()), **configuration)


def test_ollama_provider_uses_existing_environment_precedence(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:4b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://LOCALHOST:11434/")
    monkeypatch.setenv("OLLAMA_TIMEOUT", "8")
    monkeypatch.setenv("TRANSLATOR_KEEP_ALIVE", "14m")
    workflow = OllamaProvider().create_workflow(glossary_repository=MemoryRepository())
    assert workflow.translator.model_name == "qwen3.5:4b"
    assert workflow.translator.base_url == "http://localhost:11434"
    assert workflow.translator.timeout == 8
    assert workflow.translator.keep_alive == "14m"
    assert workflow.translator._model is None


def test_remote_ollama_configuration_remains_rejected():
    service = TranslationService(
        OllamaProvider(base_url="https://example.invalid"), MemoryRepository()
    )
    with pytest.raises(TranslationError) as captured:
        service.run(request())
    assert captured.value.code == "OLLAMA_BASE_URL_INVALID"


def test_service_reuses_workflow_and_clears_snapshot_after_every_request():
    provider = FakeProvider()
    repository = MemoryRepository()
    service = TranslationService(provider, repository)
    assert provider.create_count == 0
    for _ in range(3):
        service.run(request())
        with pytest.raises(GlossaryError, match="没有正在执行"):
            provider.workflow.repository.load()
    assert provider.create_count == 1
    assert repository.load_count == 3


def test_default_factory_is_lazy_and_creates_no_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("YIJING_DATA_DIR", str(tmp_path / "private-data"))
    service = create_default_service()
    assert service.provider_id == "ollama"
    assert service.list_glossary().entries == []
    assert not (tmp_path / "private-data").exists()


def test_default_factory_accepts_explicit_glossary_location(tmp_path):
    path = tmp_path / "custom" / "terms.json"
    service = create_default_service(glossary_path=path)
    service.save_glossary(document())
    assert GlossaryStore(path).load().entries[0].target == "接口"


def test_glossary_listing_is_deep_copied():
    repository = MemoryRepository()
    service = TranslationService(FakeProvider(), repository)
    listed = service.list_glossary()
    listed.entries[0].target = "changed"
    listed.entries.clear()
    assert repository.document.entries[0].target == "接口"


def test_glossary_save_copies_both_argument_and_return_value():
    repository = MemoryRepository()
    service = TranslationService(FakeProvider(), repository)
    incoming = document("saved")
    saved = service.save_glossary(incoming)
    incoming.entries[0].target = "mutated input"
    saved.entries[0].target = "mutated output"
    assert repository.document.entries[0].target == "saved"


def test_workflow_receives_isolated_request_and_returns_isolated_result():
    source = request()
    retained_result = result(source)

    def mutate(received, _repository):
        received.text = "modified by test provider"
        return retained_result

    service = TranslationService(FakeProvider(mutate), MemoryRepository())
    returned = service.run(source)
    returned.warnings.append("caller mutation")
    assert source.text == "Hello"
    assert retained_result.warnings == []


def test_snapshot_copies_each_read_and_disallows_write():
    def process(source, repository):
        first = repository.load()
        first.entries[0].target = "changed"
        assert repository.load().entries[0].target == "接口"
        with pytest.raises(GlossaryError, match="只读"):
            repository.save(document("forbidden"))
        return result(source)

    TranslationService(FakeProvider(process), MemoryRepository()).run(request())


def test_whole_workflow_is_serial_and_each_started_request_gets_its_snapshot():
    entered = threading.Event()
    release = threading.Event()
    observations = []
    active = 0
    peak_active = 0

    def process(source, repository):
        nonlocal active, peak_active
        active += 1
        peak_active = max(peak_active, active)
        before = repository.load().entries[0].target
        if source.text == "first":
            entered.set()
            assert release.wait(3)
        after = repository.load().entries[0].target
        observations.append((source.text, before, after))
        active -= 1
        return result(source)

    service = TranslationService(FakeProvider(process), MemoryRepository())
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(service.run, request("first"))
        try:
            assert entered.wait(3)
            second = executor.submit(service.run, request("second"))
            service.save_glossary(document("updated"))
        finally:
            release.set()
        first.result(timeout=3)
        second.result(timeout=3)
    assert peak_active == 1
    assert observations == [("first", "接口", "接口"), ("second", "updated", "updated")]


@pytest.mark.parametrize("stage", ["load", "create", "run", "list", "save"])
def test_unexpected_errors_are_redacted(stage, capsys):
    secret = "synthetic-private-request-and-path"

    def fail(*_args, **_kwargs):
        raise RuntimeError(secret)

    provider = FakeProvider()
    repository = MemoryRepository()
    if stage in {"load", "list"}:
        repository.load = fail
    elif stage == "save":
        repository.save = fail
    elif stage == "create":
        provider.create_workflow = fail
    else:
        provider.callback = fail
    service = TranslationService(provider, repository)
    with pytest.raises(TranslationError) as captured:
        if stage == "list":
            service.list_glossary()
        elif stage == "save":
            service.save_glossary(document())
        else:
            service.run(request())
    assert secret not in "".join(traceback.format_exception(captured.value))
    assert captured.value.__suppress_context__ is True
    output = capsys.readouterr()
    assert output.out == output.err == ""


@pytest.mark.parametrize("operation", ["run", "list", "save"])
@pytest.mark.parametrize("kind", ["translation", "glossary"])
def test_known_errors_keep_identity(operation, kind):
    error = (
        TranslationError("MODEL_TIMEOUT", "已知超时", retryable=True)
        if kind == "translation" else GlossaryFormatError("已知格式错误")
    )

    def fail(*_args, **_kwargs):
        raise error

    repository = MemoryRepository()
    provider = FakeProvider(fail)
    if operation == "list":
        repository.load = fail
    elif operation == "save":
        repository.save = fail
    service = TranslationService(provider, repository)
    with pytest.raises(type(error)) as captured:
        if operation == "run":
            service.run(request())
        elif operation == "list":
            service.list_glossary()
        else:
            service.save_glossary(document())
    assert captured.value is error


def test_real_repository_conflicts_are_preserved(tmp_path):
    service = create_default_service(glossary_path=tmp_path / "glossary.json")
    duplicated = document()
    duplicated.entries.append(duplicated.entries[0].model_copy(deep=True))
    with pytest.raises(GlossaryConflictError):
        service.save_glossary(duplicated)


def test_failed_workflow_releases_lock_and_clears_snapshot():
    calls = 0

    def process(source, _repository):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic failure")
        return result(source)

    provider = FakeProvider(process)
    service = TranslationService(provider, MemoryRepository())
    with pytest.raises(TranslationError):
        service.run(request())
    with pytest.raises(GlossaryError, match="没有正在执行"):
        provider.workflow.repository.load()
    assert service.run(request()).translated_text == "你好"
    assert provider.create_count == 1


def test_failed_factory_can_be_retried_without_retaining_request_snapshot():
    provider = FakeProvider()
    original = provider.create_workflow
    attempts = 0
    snapshots = []

    def create(*, glossary_repository):
        nonlocal attempts
        attempts += 1
        snapshots.append(glossary_repository)
        if attempts == 1:
            raise RuntimeError("temporary initialization failure")
        return original(glossary_repository=glossary_repository)

    provider.create_workflow = create
    service = TranslationService(provider, MemoryRepository())
    with pytest.raises(TranslationError):
        service.run(request())
    with pytest.raises(GlossaryError):
        snapshots[0].load()
    assert service.run(request()).translated_text == "你好"


def test_invalid_request_never_reaches_repository_or_provider():
    provider = FakeProvider()
    repository = MemoryRepository()
    service = TranslationService(provider, repository)
    with pytest.raises(TranslationError) as captured:
        service.run({"text": "", "target_language": "zh-Hans"})
    assert captured.value.code == "INVALID_REQUEST"
    assert provider.create_count == repository.load_count == 0


def test_provider_execution_disables_inherited_tracing():
    def process(source, _repository):
        assert tracing_is_enabled() is False
        return result(source)

    service = TranslationService(FakeProvider(process), MemoryRepository())
    with tracing_context(enabled=True):
        service.run(request())
        assert tracing_is_enabled() is True


def test_service_import_does_not_require_gradio():
    root = Path(application_service.__file__).resolve().parent.parent
    code = (
        "import builtins,sys; "
        f"sys.path.insert(0,{str(root)!r}); "
        "original=builtins.__import__; "
        "exec(\"def guard(name, *args, **kwargs):\\n"
        "    if name == 'gradio' or name.startswith('gradio.'):\\n"
        "        raise AssertionError('Gradio must not be imported')\\n"
        "    return original(name, *args, **kwargs)\\n\"); "
        "builtins.__import__=guard; import yijing.service; "
        "assert 'gradio' not in sys.modules"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=20,
    )
    assert completed.returncode == 0, completed.stderr

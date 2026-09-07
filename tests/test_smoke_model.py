from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from langsmith import tracing_context
from langsmith.utils import tracing_is_enabled

import smoke_model
from glossary_store import GlossaryDocument

# 仅在测试运行时构造合成地址，避免源码看起来像静态凭据。
SYNTHETIC_CREDENTIAL_URL = "".join(("http://", "user:", "private-secret", "@localhost:11434"))


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)


@pytest.mark.parametrize(
    "address",
    [
        "https://example.com",
        "http://192.168.1.2:11434",
        "http://0.0.0.0:11434",
        SYNTHETIC_CREDENTIAL_URL,
        "http://localhost:11434/private-secret",
        "http://localhost:11434?token=private-secret",
        "http://localhost:11434#private-secret",
        "file:///private-secret",
    ],
)
def test_invalid_address_is_rejected_before_model_construction(address, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(smoke_model, "ChatOllama", lambda **kwargs: calls.append(kwargs))

    with pytest.raises(SystemExit) as error:
        smoke_model.main(["--base-url", address])

    assert error.value.code == 2
    assert calls == []
    output = capsys.readouterr()
    assert address not in output.err
    assert "private-secret" not in output.err


def test_invalid_environment_address_is_also_rejected(monkeypatch, capsys):
    monkeypatch.setenv("OLLAMA_BASE_URL", SYNTHETIC_CREDENTIAL_URL)
    with pytest.raises(SystemExit) as error:
        smoke_model.parse_args([])
    assert error.value.code == 2
    assert "private-secret" not in capsys.readouterr().err


@pytest.mark.parametrize(
    ("address", "normalized"),
    [
        ("http://LOCALHOST:11434/", "http://localhost:11434"),
        ("http://127.0.0.1:11434", "http://127.0.0.1:11434"),
        ("https://[::1]:11434/", "https://[::1]:11434"),
    ],
)
def test_loopback_address_is_normalized(address, normalized):
    assert smoke_model.parse_args(["--base-url", address]).base_url == normalized


@pytest.mark.parametrize("value", ["0", "-1", "61", "nan", "inf", "-inf", "private-secret"])
def test_invalid_timeout_is_rejected_without_echoing_value(value, capsys):
    with pytest.raises(SystemExit) as error:
        smoke_model.parse_args([f"--timeout={value}"])
    assert error.value.code == 2
    assert "private-secret" not in capsys.readouterr().err


@pytest.mark.parametrize("value", ["0.5", "30", "60"])
def test_valid_timeout(value):
    assert smoke_model.parse_args(["--timeout", value]).timeout == float(value)


def test_success_uses_private_transport_options_and_returns_zero(monkeypatch, capsys):
    constructor_calls = []
    prompts = []

    class FakeModel:
        def __init__(self, **kwargs):
            constructor_calls.append(kwargs)

        def invoke(self, prompt):
            prompts.append(prompt)
            return SimpleNamespace(
                content="  Ready.  ",
                response_metadata={"eval_count": 2, "prompt": "private-secret"},
            )

    monkeypatch.setattr(smoke_model, "ChatOllama", FakeModel)
    assert smoke_model.main(["--prompt", "example", "--timeout", "5"]) == 0
    assert constructor_calls[0]["client_kwargs"] == {
        "timeout": 5.0,
        "trust_env": False,
        "follow_redirects": False,
    }
    assert constructor_calls[0]["base_url"] == smoke_model.DEFAULT_BASE_URL
    assert prompts == ["example"]
    output = capsys.readouterr()
    assert "Ready." in output.out
    assert "private-secret" not in output.out
    assert not output.err


@pytest.mark.parametrize("failure_at", ["construction", "invocation"])
def test_sdk_errors_do_not_echo_prompt_or_credentials(failure_at, monkeypatch, capsys):
    secret = "private-original-text " + SYNTHETIC_CREDENTIAL_URL

    class FailingModel:
        def __init__(self, **_kwargs):
            if failure_at == "construction":
                raise ValueError(secret)

        def invoke(self, _prompt):
            raise RuntimeError(secret)

    monkeypatch.setattr(smoke_model, "ChatOllama", FailingModel)
    assert smoke_model.main(["--prompt", "private-original-text"]) == 1
    output = capsys.readouterr()
    assert not output.out
    assert "private-original-text" not in output.err
    assert "private-secret" not in output.err
    assert "调用失败" in output.err


def test_empty_model_output_fails_normally(monkeypatch, capsys):
    model = SimpleNamespace(
        invoke=lambda _prompt: SimpleNamespace(content=" \n", response_metadata={})
    )
    monkeypatch.setattr(smoke_model, "ChatOllama", lambda **_kwargs: model)
    assert smoke_model.main([]) == 1
    assert "空内容" in capsys.readouterr().err


def test_example_glossary_matches_application_schema():
    example_path = Path(__file__).resolve().parents[1] / "data" / "glossary.example.json"
    document = GlossaryDocument.model_validate(json.loads(example_path.read_text(encoding="utf-8")))
    assert len(document.entries) == 1
    assert document.entries[0].target_language == "zh-Hans"


def test_smoke_disables_inherited_tracing_and_restores_caller(monkeypatch, capsys):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")

    class FakeModel:
        def __init__(self, **_kwargs):
            assert tracing_is_enabled() is False

        def invoke(self, _prompt):
            assert tracing_is_enabled() is False
            return SimpleNamespace(content="Ready.", response_metadata={})

    monkeypatch.setattr(smoke_model, "ChatOllama", FakeModel)
    with tracing_context(enabled=True):
        assert smoke_model.main([]) == 0
        assert tracing_is_enabled() is True
    assert "Ready." in capsys.readouterr().out

from __future__ import annotations

import io
import json
from types import SimpleNamespace
from urllib.error import URLError
from urllib.request import Request

import gradio as gr
import pytest

import agent
from yijing.glossary import GlossaryDocument, GlossaryValidationError
from yijing.translation import AppliedTerm, TranslationError
from yijing.workflow import AgentResult, AnnotationItem


def test_build_app_constructs_without_starting_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent.service, "list_glossary", lambda: GlossaryDocument())

    app = agent.build_app()

    assert isinstance(app, gr.Blocks)
    assert app.title == agent.APP_TITLE


def test_build_app_has_valid_queue_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent.service, "list_glossary", lambda: GlossaryDocument())

    app = agent.build_app()

    app.validate_queue_settings()


@pytest.mark.parametrize(
    ("raw_port", "expected"),
    [
        (None, None),
        ("1", 1),
        ("7860", 7860),
        ("65535", 65535),
    ],
)
def test_server_port_from_env_accepts_absent_or_valid_values(
    monkeypatch: pytest.MonkeyPatch,
    raw_port: str | None,
    expected: int | None,
) -> None:
    if raw_port is None:
        monkeypatch.delenv("TRANSLATOR_PORT", raising=False)
    else:
        monkeypatch.setenv("TRANSLATOR_PORT", raw_port)

    assert agent._server_port_from_env() == expected


@pytest.mark.parametrize(
    "raw_port",
    ["", "0", "65536", "-1", "+7860", "7860.0", " 7860", "7860 ", "７８６０", "abc"],
)
def test_server_port_from_env_rejects_invalid_values_in_chinese(
    monkeypatch: pytest.MonkeyPatch,
    raw_port: str,
) -> None:
    monkeypatch.setenv("TRANSLATOR_PORT", raw_port)

    with pytest.raises(
        ValueError,
        match="环境变量 TRANSLATOR_PORT 必须是 1 到 65535 之间的十进制整数",
    ):
        agent._server_port_from_env()


def test_select_server_port_skips_occupied_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TRANSLATOR_PORT", raising=False)
    monkeypatch.setattr(agent, "_is_port_available", lambda port: port == 7862)

    assert agent._select_server_port() == 7862


def test_select_server_port_rejects_occupied_explicit_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRANSLATOR_PORT", "54321")
    monkeypatch.setattr(agent, "_is_port_available", lambda _port: False)

    with pytest.raises(OSError, match="端口 54321 已被占用"):
        agent._select_server_port()


@pytest.mark.parametrize(("raw_port", "expected"), [(None, 7860), ("54321", 54321)])
def test_main_passes_port_policy_to_gradio(
    monkeypatch: pytest.MonkeyPatch,
    raw_port: str | None,
    expected: int | None,
) -> None:
    captured: dict[str, object] = {}

    class FakeDemo:
        def launch(self, **kwargs: object) -> None:
            captured.update(kwargs)

    if raw_port is None:
        monkeypatch.delenv("TRANSLATOR_PORT", raising=False)
    else:
        monkeypatch.setenv("TRANSLATOR_PORT", raw_port)
    monkeypatch.setenv("TRANSLATOR_INBROWSER", "0")
    monkeypatch.setattr(agent, "build_app", FakeDemo)
    monkeypatch.setattr(agent, "_is_port_available", lambda _port: True)
    monkeypatch.setattr(agent, "_startup_diagnostics", lambda _port: "模型可用")

    agent.main()

    assert captured["server_port"] == expected
    assert captured["server_name"] == "127.0.0.1"
    assert captured["share"] is False
    assert captured["run_history"] is False


def test_main_reports_port_exhaustion_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TRANSLATOR_PORT", raising=False)
    monkeypatch.setattr(agent, "_is_port_available", lambda _port: False)

    with pytest.raises(SystemExit, match="启动失败：端口 7860 到 7959 均被占用"):
        agent.main()


def test_model_status_reports_available_model(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    payload = {"models": [{"name": agent.MODEL_NAME}, {"model": "other:latest"}]}

    def fake_urlopen(request: Request, *, timeout: int) -> io.BytesIO:
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(agent, "urlopen", fake_urlopen)

    status = agent._model_status()

    assert captured == {
        "url": f"{agent.OLLAMA_BASE_URL}/api/tags",
        "timeout": 3,
    }
    assert agent.MODEL_NAME in status
    assert "可用" in status
    assert "本机" in status


def test_model_status_maps_missing_model_and_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        agent,
        "urlopen",
        lambda *_args, **_kwargs: io.BytesIO(b'{"models": []}'),
    )
    assert "未找到" in agent._model_status()

    def raise_offline(*_args: object, **_kwargs: object) -> None:
        raise URLError("offline")

    monkeypatch.setattr(agent, "urlopen", raise_offline)
    assert "未连接" in agent._model_status()


def test_agent_rejects_remote_ollama_url_and_falls_back_with_warning() -> None:
    base_url, warning = agent._resolve_ollama_base_url(
        "http://remote.example.com:11434"
    )

    assert base_url == "http://127.0.0.1:11434"
    assert warning is not None
    assert "隐私警告" in warning
    assert "已拒绝" in warning


def test_agent_accepts_local_ollama_url_without_warning() -> None:
    base_url, warning = agent._resolve_ollama_base_url("http://[::1]:11434")

    assert base_url == "http://[::1]:11434"
    assert warning is None


def test_model_status_includes_invalid_configuration_privacy_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warning = "隐私警告：测试回退"
    monkeypatch.setattr(agent, "OLLAMA_BASE_URL_WARNING", warning)
    monkeypatch.setattr(
        agent,
        "urlopen",
        lambda *_args, **_kwargs: io.BytesIO(b'{"models": []}'),
    )

    assert warning in agent._model_status()


def test_startup_diagnostics_reports_verified_online_state(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(agent, "translator", SimpleNamespace(keep_alive="30m"))
    monkeypatch.setattr(
        agent,
        "_model_status",
        lambda: f"Ollama 已连接 · {agent.MODEL_NAME} 可用 · 文本仅在本机处理",
    )

    status = agent._startup_diagnostics(7861)
    output = capsys.readouterr().out

    assert status == f"Ollama 已连接 · {agent.MODEL_NAME} 可用 · 文本仅在本机处理"
    assert str(agent.Path(agent.__file__).resolve()) in output
    assert agent.sys.executable in output
    assert f"Ollama 地址：{agent.OLLAMA_BASE_URL}" in output
    assert f"翻译模型：{agent.MODEL_NAME}" in output
    assert "模型驻留：30m" in output
    assert "模型状态：Ollama 已连接" in output
    assert "Web 地址：http://127.0.0.1:7861" in output


def test_startup_diagnostics_keeps_privacy_warning_visible(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    warning = "隐私警告：已拒绝非本机配置"
    monkeypatch.setattr(agent, "OLLAMA_BASE_URL_WARNING", warning)
    monkeypatch.setattr(agent, "translator", SimpleNamespace(keep_alive="30m"))
    monkeypatch.setattr(agent, "_model_status", lambda: "Ollama 未连接")

    status = agent._startup_diagnostics(7860)
    output = capsys.readouterr().out

    assert warning in status
    assert warning in output


def test_main_starts_ui_when_startup_diagnostics_reports_ollama_offline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    captured: dict[str, object] = {}

    class FakeDemo:
        def launch(self, **kwargs: object) -> None:
            captured.update(kwargs)

    monkeypatch.delenv("TRANSLATOR_PORT", raising=False)
    monkeypatch.setenv("TRANSLATOR_INBROWSER", "0")
    monkeypatch.setattr(agent, "translator", SimpleNamespace(keep_alive="30m"))
    monkeypatch.setattr(agent, "_is_port_available", lambda _port: True)
    monkeypatch.setattr(agent, "_model_status", lambda: "Ollama 未连接 · 请先启动本地 Ollama 服务")
    monkeypatch.setattr(agent, "build_app", FakeDemo)

    agent.main()
    output = capsys.readouterr().out

    assert "模型状态：Ollama 未连接" in output
    assert "Web 地址：http://127.0.0.1:7860" in output
    assert captured["server_port"] == 7860


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (None, "0 / 4000 字符"),
        ("", "0 / 4000 字符"),
        ("你好🙂", "3 / 4000 字符"),
        ("a\nb", "3 / 4000 字符"),
    ],
)
def test_character_count(text: str | None, expected: str) -> None:
    assert agent._count_characters(text) == expected


def test_warning_and_term_rendering_is_readable_and_deduplicated() -> None:
    warnings = agent._format_warnings(
        [
            "MIXED_LANGUAGE",
            SimpleNamespace(code="LEGAL_REVIEW"),
            "MIXED_LANGUAGE",
            "CUSTOM_WARNING",
        ]
    )
    terms = agent._format_terms(
        [
            AppliedTerm(source="API", target="应用程序接口", count=2),
            {"source": "cloud", "target": "云", "count": 1},
            "固定译法",
        ]
    )

    assert warnings.count("检测到多种语言") == 1
    assert "法律内容" in warnings
    assert "CUSTOM_WARNING" in warnings
    assert "API → 应用程序接口 ×2" in terms
    assert "cloud → 云" in terms
    assert "固定译法" in terms
    assert agent._format_warnings([]) == "无告警"
    assert agent._format_terms([]) == "本次未命中自定义术语"


def test_warning_notification_escapes_untrusted_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[str, str]] = []
    monkeypatch.setattr(
        agent.gr,
        "Warning",
        lambda text, *, title: captured.append((text, title)),
    )

    agent._warning("<img src=x onerror=alert(1)>", title="<b>失败</b>")

    assert captured == [
        ("&lt;img src=x onerror=alert(1)&gt;", "&lt;b&gt;失败&lt;/b&gt;")
    ]


def test_annotation_result_uses_chinese_route_and_explanation_labels() -> None:
    result = AgentResult(
        route="annotate_code",
        detected_language="en",
        detection_status="detected",
        preserved_source="# explain",
        annotated_copy="# 说明",
        annotations=[
            AnnotationItem(
                kind="comment",
                source_fragment="# explain",
                explanation="解释这条注释。",
                location="第 1 行",
            )
        ],
    )

    output = agent._result_values(result)

    assert output[2] == "# 说明"
    assert "【代码注释】 · 第 1 行" in output[3]
    assert "说明：解释这条注释。" in output[3]
    assert output[4] == "代码注释"


def _fake_agent_result() -> AgentResult:
    return AgentResult(
        route="translate_text",
        detected_language="en",
        detection_status="mixed",
        preserved_source="Hello API",
        translated_text="你好，应用程序接口",
        annotated_copy=None,
        annotations=[],
        applied_terms=[AppliedTerm(source="API", target="应用程序接口", count=1)],
        warnings=["MIXED_LANGUAGE", "LEGAL_REVIEW"],
        elapsed_ms=12,
    )


def test_mixed_language_detection_uses_readable_mul_label() -> None:
    result = AgentResult(
        route="translate_text",
        detected_language="mul",
        detection_status="mixed",
        preserved_source="Hello 世界",
        translated_text="你好，世界",
        elapsed_ms=7,
    )

    assert agent._format_detection(result) == (
        "检测语言：多语言（mul） · 混合语言 · 7 ms"
    )


def _begin_test_request(session_id: str = "test-session") -> agent.PendingAgentRequest:
    output = agent._begin_request(
        session_id,
        "Hello API",
        "auto",
        "auto",
        "zh-Hans",
        "formal",
        "technology",
    )
    return output[0]


def test_workflow_request_and_result_are_rendered_without_gradio_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeWorkflow:
        def run(self, request: object) -> SimpleNamespace:
            captured["request"] = request
            return _fake_agent_result()

    monkeypatch.setattr(agent, "service", FakeWorkflow())
    pending = _begin_test_request("successful-session")

    outcome = agent._execute_workflow(pending)
    output = agent._commit_workflow_outcome(outcome)

    request = captured["request"]
    assert request.text == "Hello API"
    assert request.task_mode == "auto"
    assert request.source_language == "auto"
    assert request.target_language == "zh-Hans"
    assert request.style == "formal"
    assert request.domain == "technology"
    assert output[0] == "Hello API"
    assert output[1] == "你好，应用程序接口"
    assert output[2] == ""
    assert output[3] == agent.EMPTY_EXPLANATION
    assert output[4] == "文本翻译"
    assert output[5] == "检测语言：英语（en） · 混合语言 · 12 ms"
    assert "检测到多种语言" in output[6]
    assert output[7] == "API → 应用程序接口"
    assert all(item["interactive"] is True for item in output[8:])


def test_glossary_save_error_is_rendered_inline_without_failing_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingService:
        def save_glossary(self, document: object) -> None:
            raise GlossaryValidationError("第 2 行的目标语言不能为空")

        def list_glossary(self) -> GlossaryDocument:
            raise AssertionError("保存失败后不得重新加载")

    monkeypatch.setattr(agent, "service", FailingService())
    notifications: list[tuple[str, str]] = []
    monkeypatch.setattr(
        agent.gr,
        "Warning",
        lambda text, *, title: notifications.append((text, title)),
    )

    output = agent._save_glossary_rows([["API", "接口", "zh-Hans", "all", False]])

    assert output[0] == gr.skip()
    assert "第 2 行的目标语言不能为空" in output[1]
    assert notifications == [
        ("第 2 行的目标语言不能为空", "词库保存失败")
    ]


def test_character_count_uses_immediate_unicode_client_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent.service, "list_glossary", lambda: GlossaryDocument())

    app = agent.build_app()
    dependencies = app.config["dependencies"]
    counter_events = [
        dependency
        for dependency in dependencies
        if dependency.get("js") == agent.CHARACTER_COUNT_JS
    ]

    assert "Array.from" in agent.CHARACTER_COUNT_JS
    assert len(counter_events) == 1
    assert counter_events[0]["backend_fn"] is False
    assert counter_events[0]["queue"] is False
    assert counter_events[0]["trigger_mode"] == "always_last"
    assert counter_events[0]["api_name"] == "character_count"
    reset_events = [
        dependency
        for dependency in dependencies
        if dependency.get("api_name") == "reset_agent"
    ]
    assert len(reset_events) == 1
    assert reset_events[0]["backend_fn"] is True
    assert reset_events[0]["js"] is None

    empty_reset_events = [
        dependency
        for dependency in dependencies
        if dependency.get("api_name") == "_reset_if_empty"
    ]
    assert len(empty_reset_events) == 1
    assert empty_reset_events[0]["trigger_mode"] == "always_last"

    cancellable_ids = {
        dependency["id"]
        for dependency in dependencies
        if dependency.get("api_name") == "_execute_workflow"
    }
    assert len(cancellable_ids) == 1
    for reset_event in (reset_events[0], empty_reset_events[0]):
        cancel_events = [
            dependency
            for dependency in dependencies
            if dependency.get("targets") == reset_event.get("targets")
            and set(dependency.get("cancels", [])) == cancellable_ids
        ]
        assert len(cancel_events) == 1


def test_reset_restores_every_main_field_and_advances_generation() -> None:
    session_id = "reset-session"
    first_generation = agent.request_generations.advance(session_id)

    output = agent._reset_ui(session_id)

    assert len(output) == 18
    assert output[0] is None
    assert output[1:7] == (
        "",
        "auto",
        "auto",
        "zh-Hans",
        "standard",
        "general",
    )
    assert output[7:10] == ("", "", "")
    assert output[10:16] == (
        agent.EMPTY_EXPLANATION,
        agent.EMPTY_ROUTE,
        agent.EMPTY_DETECTION,
        "0 / 4000 字符",
        agent.EMPTY_WARNINGS,
        agent.EMPTY_TERMS,
    )
    assert output[16]["interactive"] is True
    assert output[17]["interactive"] is True
    assert not agent.request_generations.is_current(session_id, first_generation)


def test_manual_empty_input_reuses_full_reset() -> None:
    session_id = "manual-empty-session"

    skipped = agent._reset_if_empty("仍有内容", session_id)
    reset = agent._reset_if_empty("", session_id)

    assert len(skipped) == 18
    assert all(item == gr.skip() for item in skipped)
    assert reset[1] == ""
    assert reset[13] == "0 / 4000 字符"
    assert reset[14] == agent.EMPTY_WARNINGS


def test_begin_request_freezes_input_and_disables_duplicate_submission() -> None:
    output = agent._begin_request(
        "busy-session",
        "print('hello')",
        "annotate_code",
        "auto",
        "zh-Hans",
        "standard",
        "technology",
    )

    pending = output[0]
    assert pending.text == "print('hello')"
    assert pending.task_mode == "annotate_code"
    assert output[1] == pending.text
    assert len(output) == 12
    assert all(item["interactive"] is False for item in output[9:])


def test_expected_workflow_error_is_rendered_as_normal_inline_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = "模型改变了段落、空行或 Markdown 结构，请重试。"

    class FailingWorkflow:
        def run(self, _request: object) -> None:
            raise TranslationError("FORMAT_CHANGED", message, retryable=True)

    notifications: list[tuple[str, str]] = []
    monkeypatch.setattr(agent, "service", FailingWorkflow())
    monkeypatch.setattr(
        agent.gr,
        "Warning",
        lambda text, *, title: notifications.append((text, title)),
    )
    pending = _begin_test_request("expected-error-session")

    outcome = agent._execute_workflow(pending)
    output = agent._commit_workflow_outcome(outcome)

    assert outcome.error_message == message
    assert output[0] == "Hello API"
    assert output[1:3] == ("", "")
    assert output[4] == "任务未完成"
    assert output[5] == "处理失败"
    assert message in output[6]
    assert output[7] == agent.EMPTY_TERMS
    assert notifications == [(message, "处理未完成")]


def test_request_validation_error_does_not_echo_sensitive_input() -> None:
    sensitive_text = "secret-value-" * 400
    session_id = "validation-session"
    pending = agent._begin_request(
        session_id,
        sensitive_text,
        "auto",
        "auto",
        "zh-Hans",
        "standard",
        "general",
    )[0]

    outcome = agent._execute_workflow(pending)

    assert outcome.error_message is not None
    assert "4000" in outcome.error_message
    assert "secret-value" not in outcome.error_message


def test_reset_invalidates_completed_old_request() -> None:
    session_id = "stale-session"
    pending = _begin_test_request(session_id)
    outcome = agent.WorkflowOutcome(pending=pending, result=_fake_agent_result())

    agent._reset_ui(session_id)
    output = agent._commit_workflow_outcome(outcome)

    assert len(output) == 11
    assert all(item == gr.skip() for item in output)


def test_new_submission_skips_obsolete_work_before_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "superseded-session"
    obsolete = _begin_test_request(session_id)
    _begin_test_request(session_id)

    class MustNotRunWorkflow:
        def run(self, _request: object) -> None:
            raise AssertionError("旧请求不得调用模型")

    monkeypatch.setattr(agent, "service", MustNotRunWorkflow())
    outcome = agent._execute_workflow(obsolete)

    assert outcome.result is None
    assert outcome.error_message is None
    assert all(item == gr.skip() for item in agent._commit_workflow_outcome(outcome))


def test_unexpected_backend_error_is_hidden_and_does_not_raise_gradio_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingWorkflow:
        def run(self, _request: object) -> None:
            raise RuntimeError("backend leaked original: highly-sensitive-text")

    monkeypatch.setattr(agent, "service", FailingWorkflow())
    pending = _begin_test_request("unexpected-error-session")

    outcome = agent._execute_workflow(pending)

    assert outcome.error_message == "处理失败，请检查本地 Ollama 状态后重试。"
    assert "highly-sensitive-text" not in outcome.error_message

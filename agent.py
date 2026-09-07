"""译境：基于 Gradio 与本地 Ollama 的智能翻译界面。"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

import gradio as gr
from pydantic import ValidationError

from app_paths import data_directory
from glossary_store import GlossaryError, GlossaryStore
from translation_agent import (
    DEFAULT_BASE_URL,
    TranslationError,
    Translator,
    validate_local_ollama_base_url,
)
from translation_workflow import AgentRequest, AgentResult, TranslationWorkflow

APP_TITLE = "译境 · 本地智能翻译"
BASE_DIR = Path(__file__).resolve().parent
GLOSSARY_PATH = data_directory() / "glossary.json"
MODEL_NAME = os.getenv("OLLAMA_MODEL", "qwen3.5:4b")


def _resolve_ollama_base_url(configured: str | None) -> tuple[str, str | None]:
    """界面入口拒绝远端地址，并以显式警告安全回退到本机默认值。"""

    candidate = DEFAULT_BASE_URL if configured is None else configured
    try:
        return validate_local_ollama_base_url(candidate), None
    except TranslationError:
        return (
            DEFAULT_BASE_URL,
            "隐私警告：已拒绝非本机或格式无效的 OLLAMA_BASE_URL，"
            f"并回退到 {DEFAULT_BASE_URL}",
        )


OLLAMA_BASE_URL, OLLAMA_BASE_URL_WARNING = _resolve_ollama_base_url(
    os.getenv("OLLAMA_BASE_URL")
)
MAX_INPUT_LENGTH = 4000
DEFAULT_PORT = 7860
LAST_AUTO_PORT = 7959

TASK_MODE_CHOICES = [
    ("智能判断", "auto"),
    ("文本翻译", "translate"),
    ("代码注释", "annotate_code"),
    ("符号与结构说明", "annotate_special"),
]

ROUTE_LABELS = {
    "translate_text": "文本翻译",
    "annotate_code": "代码注释",
    "annotate_special": "符号与结构说明",
    "mixed_document": "混合文档处理",
}

ANNOTATION_KIND_LABELS = {
    "comment": "代码注释",
    "docstring": "文档字符串",
    "code_summary": "代码摘要",
    "code": "代码说明",
    "python": "Python 代码",
    "json": "JSON 结构",
    "url": "网址",
    "email": "电子邮箱",
    "command": "命令",
    "path": "文件路径",
    "regex": "正则表达式",
    "number": "数字",
    "variable": "模板变量",
    "formula": "公式",
    "special_content": "特殊内容",
    "mixed_document_code": "混合文档代码块",
    "symbol": "符号说明",
    "structure": "结构说明",
    "risk": "风险提示",
}

CODE_LANGUAGE_LABELS = {
    "python": "Python",
    "py": "Python",
    "javascript": "JavaScript",
    "js": "JavaScript",
    "typescript": "TypeScript",
    "ts": "TypeScript",
    "html": "HTML",
    "css": "CSS",
    "shell": "Shell",
    "bash": "Bash",
    "text": "文本",
}

EMPTY_EXPLANATION = "本次任务暂无额外说明"
EMPTY_ROUTE = "等待判断任务类型"
EMPTY_DETECTION = "等待处理"
EMPTY_WARNINGS = "无告警"
EMPTY_TERMS = "本次未命中自定义术语"
CHARACTER_COUNT_JS = (
    f'(text) => `${{Array.from(text ?? "").length}} / {MAX_INPUT_LENGTH} 字符`'
)

LANGUAGE_CHOICES = [
    ("自动检测", "auto"),
    ("简体中文", "zh-Hans"),
    ("繁体中文", "zh-Hant"),
    ("英语", "en"),
    ("日语", "ja"),
    ("韩语", "ko"),
    ("法语", "fr"),
    ("德语", "de"),
    ("西班牙语", "es"),
    ("俄语", "ru"),
    ("葡萄牙语（巴西）", "pt-BR"),
    ("阿拉伯语", "ar"),
    ("意大利语", "it"),
]
TARGET_LANGUAGE_CHOICES = LANGUAGE_CHOICES[1:]
LANGUAGE_LABELS = {code: label for label, code in LANGUAGE_CHOICES}
LANGUAGE_LABELS.update({"mul": "多语言", "und": "未确定"})

STYLE_CHOICES = [
    ("标准", "standard"),
    ("正式", "formal"),
    ("口语", "colloquial"),
]

DOMAIN_CHOICES = [
    ("通用", "general"),
    ("技术", "technology"),
    ("商务", "business"),
    ("金融", "finance"),
    ("法律", "legal"),
    ("医疗", "medical"),
    ("学术", "academic"),
]

DETECTION_LABELS = {
    "detected": "已检测",
    "uncertain": "不确定",
    "ambiguous": "不确定",
    "mixed": "混合语言",
}

WARNING_MESSAGES = {
    "LOW_DETECTION_CONFIDENCE": "源语言较短或特征不足，检测结果可能不准确。",
    "MIXED_LANGUAGE": "检测到多种语言，已统一翻译为目标语言。",
    "SOURCE_EQUALS_TARGET": "检测到源语言与目标语言相同，请更换目标语言。",
    "FORMAT_CHANGED": "部分排版可能发生变化，请检查列表与段落结构。",
    "LEGAL_REVIEW": "法律内容应由具备资质的专业人员复核。",
    "MEDICAL_REVIEW": "医疗内容应由具备资质的专业人员复核。",
}

APP_CSS = """
:root {
  --yijing-ink: #172033;
  --yijing-muted: #657086;
  --yijing-line: #dce3ef;
  --yijing-accent: #3157d5;
  --yijing-accent-2: #19a08d;
}
.gradio-container {
  max-width: 1440px !important;
  margin: 0 auto !important;
  padding: 24px 24px 42px !important;
  color: var(--yijing-ink);
}
.yijing-hero {
  padding: 22px 24px;
  margin-bottom: 18px;
  border: 1px solid var(--yijing-line);
  border-radius: 20px;
  background:
    radial-gradient(circle at 92% 18%, rgba(25,160,141,.18), transparent 26%),
    linear-gradient(135deg, #ffffff 0%, #eef3ff 100%);
  box-shadow: 0 12px 34px rgba(42, 64, 113, .08);
}
.yijing-hero h1 { margin: 0 0 8px; font-size: clamp(26px, 4vw, 42px); letter-spacing: -.04em; }
.yijing-hero p { margin: 0; color: var(--yijing-muted); font-size: 15px; }
.local-badge {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  margin-bottom: 12px;
  padding: 5px 10px;
  border-radius: 999px;
  color: #087665;
  background: #ddf7f1;
  font-size: 12px;
  font-weight: 700;
}
.local-badge::before { content: ""; width: 7px; height: 7px; border-radius: 50%; background: #12a98e; }
.yijing-card {
  border: 1px solid var(--yijing-line) !important;
  border-radius: 18px !important;
  background: rgba(255,255,255,.96) !important;
  box-shadow: 0 8px 28px rgba(42, 64, 113, .06) !important;
  padding: 8px !important;
}
#translate-button { min-height: 44px; font-weight: 700; }
#source-text textarea, #target-text textarea { line-height: 1.72; font-size: 15px; }
#target-text textarea { background: #f8faff; }
.status-strip textarea { font-size: 13px !important; color: var(--yijing-muted) !important; }
.glossary-help { color: var(--yijing-muted); font-size: 13px; }
@media (max-width: 760px) {
  .gradio-container { padding: 14px 12px 28px !important; }
  .yijing-hero { padding: 18px; border-radius: 16px; }
  .yijing-card { border-radius: 14px !important; }
}
"""


glossary_store = GlossaryStore(GLOSSARY_PATH)
translator = Translator(model_name=MODEL_NAME, base_url=OLLAMA_BASE_URL)
workflow = TranslationWorkflow(translator=translator, glossary_store=glossary_store)


@dataclass(frozen=True, slots=True)
class PendingAgentRequest:
    """一次已冻结的 UI 请求，避免运行期间控件变化污染本次结果。"""

    session_id: str
    generation: int
    text: str
    task_mode: str
    source_language: str
    target_language: str
    style: str
    domain: str


@dataclass(frozen=True, slots=True)
class WorkflowOutcome:
    """工作流结果信封；预期错误也作为普通结果交给 UI 渲染。"""

    pending: PendingAgentRequest
    result: AgentResult | None = None
    error_message: str | None = None


class SessionGenerationRegistry:
    """按 Gradio 会话隔离请求代次，并阻止迟到结果覆盖新状态。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._generations: dict[str, int] = {}

    def advance(self, session_id: str) -> int:
        with self._lock:
            generation = self._generations.get(session_id, 0) + 1
            self._generations[session_id] = generation
            return generation

    def is_current(self, session_id: str, generation: int) -> bool:
        with self._lock:
            return self._generations.get(session_id, 0) == generation

    def discard(self, session_id: str) -> None:
        with self._lock:
            self._generations.pop(session_id, None)


request_generations = SessionGenerationRegistry()


def _new_session_id() -> str:
    return uuid4().hex


def _friendly_error(exc: Exception) -> str:
    """只向界面暴露可行动的简短错误，不返回堆栈或敏感内容。"""

    for attribute in ("user_message", "message"):
        value = getattr(exc, attribute, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    text = str(exc).strip()
    return text or "操作失败，请稍后重试。"


def _warning(message: str, *, title: str) -> None:
    """Gradio 通知支持 HTML，因此显示前必须转义不可信文本。"""

    gr.Warning(escape(message), title=escape(title))


def _validation_error_message(exc: ValidationError) -> str:
    """提取安全的校验消息，避免把原始输入回显到错误详情。"""

    errors = exc.errors(include_input=False, include_url=False)
    if not errors:
        return "翻译参数无效，请检查输入与选项。"
    message = str(errors[0].get("msg", "翻译参数无效"))
    return message.removeprefix("Value error, ")


def _format_warnings(warnings: Iterable[Any]) -> str:
    messages: list[str] = []
    for warning in warnings:
        code = getattr(warning, "code", warning)
        code_text = str(code)
        message = WARNING_MESSAGES.get(code_text, code_text)
        if message and message not in messages:
            messages.append(message)
    return "\n".join(f"• {message}" for message in messages) or "无告警"


def _format_terms(terms: Iterable[Any]) -> str:
    rendered: list[str] = []
    for term in terms:
        if isinstance(term, str):
            rendered.append(term)
            continue
        if isinstance(term, dict):
            source = term.get("source", "")
            target = term.get("target", "")
            count = term.get("count")
        else:
            source = getattr(term, "source", "")
            target = getattr(term, "target", "")
            count = getattr(term, "count", None)
        suffix = f" ×{count}" if count not in (None, 1) else ""
        rendered.append(f"{source} → {target}{suffix}".strip())
    return "\n".join(rendered) or "本次未命中自定义术语"


def _count_characters(text: str | None) -> str:
    return f"{len(text or '')} / {MAX_INPUT_LENGTH} 字符"


def _with_ollama_privacy_warning(status: str) -> str:
    if OLLAMA_BASE_URL_WARNING and OLLAMA_BASE_URL_WARNING not in status:
        return f"{status} · {OLLAMA_BASE_URL_WARNING}"
    return status


def _model_status() -> str:
    request = Request(f"{OLLAMA_BASE_URL}/api/tags", method="GET")
    try:
        with urlopen(request, timeout=3) as response:  # noqa: S310 - 已强制限制为回环地址
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, OSError):
        return _with_ollama_privacy_warning(
            "Ollama 未连接 · 请先启动本地 Ollama 服务"
        )

    model_names = {
        item.get("name") or item.get("model")
        for item in payload.get("models", [])
        if isinstance(item, dict)
    }
    if MODEL_NAME not in model_names:
        return _with_ollama_privacy_warning(
            f"Ollama 已连接 · 未找到 {MODEL_NAME}"
        )
    return _with_ollama_privacy_warning(
        f"Ollama 已连接 · {MODEL_NAME} 可用 · 文本仅在本机处理"
    )


def _load_glossary_rows() -> tuple[Any, str]:
    try:
        rows = glossary_store.load_rows()
    except GlossaryError as exc:
        message = _friendly_error(exc)
        _warning(message, title="词库载入失败")
        return gr.skip(), f"重新载入失败：{message}"
    except Exception:
        message = "词库载入失败，请检查本地词库文件。"
        _warning(message, title="词库载入失败")
        return gr.skip(), message
    return rows, f"已载入 {len(rows)} 条本地术语"


def _save_glossary_rows(rows: Any) -> tuple[Any, str]:
    try:
        glossary_store.save_rows(rows or [])
        normalized_rows = glossary_store.load_rows()
    except GlossaryError as exc:
        message = _friendly_error(exc)
        _warning(message, title="词库保存失败")
        return gr.skip(), f"保存失败：{message}"
    except Exception:
        message = "词库保存失败，请检查本地词库文件。"
        _warning(message, title="词库保存失败")
        return gr.skip(), message
    return normalized_rows, f"已保存 {len(normalized_rows)} 条术语到本地词库"


def _enum_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw)


def _format_route(result: AgentResult) -> str:
    route_code = _enum_value(result.route)
    return ROUTE_LABELS.get(route_code, route_code)


def _format_detection(result: AgentResult) -> str:
    detected_code = _enum_value(result.detected_language)
    detected_name = LANGUAGE_LABELS.get(detected_code)
    detected_display = (
        f"{detected_name}（{detected_code}）" if detected_name else detected_code
    )
    status_key = _enum_value(result.detection_status)
    status = DETECTION_LABELS.get(status_key, status_key)
    elapsed = int(round(result.elapsed_ms))
    return f"检测语言：{detected_display} · {status} · {elapsed} ms"


def _format_annotations(annotations: Iterable[Any]) -> str:
    rendered: list[str] = []
    for index, annotation in enumerate(annotations, start=1):
        kind = _enum_value(getattr(annotation, "kind", "说明"))
        base_kind = kind.removesuffix("_fallback").removesuffix("_code_block")
        kind_label = ANNOTATION_KIND_LABELS.get(base_kind, base_kind)
        if kind.endswith("_code_block"):
            language_label = CODE_LANGUAGE_LABELS.get(base_kind, base_kind)
            kind_label = f"{language_label} 代码块"
        if kind.endswith("_fallback"):
            kind_label = f"{kind_label}（安全回退）"
        location = getattr(annotation, "location", None)
        source_fragment = str(getattr(annotation, "source_fragment", "")).strip()
        explanation = str(getattr(annotation, "explanation", "")).strip()
        risk = getattr(annotation, "risk", None)

        heading = f"{index}. 【{kind_label}】"
        if location:
            heading += f" · {location}"
        lines = [heading]
        if source_fragment:
            lines.append(f"对象：{source_fragment}")
        if explanation:
            lines.append(f"说明：{explanation}")
        if risk:
            lines.append(f"风险：{risk}")
        rendered.append("\n".join(lines))
    return "\n\n".join(rendered) or EMPTY_EXPLANATION


def _result_values(result: AgentResult) -> tuple[str, ...]:
    """把领域结果转换为稳定的 UI 值，所有结果组件均保持普通状态。"""

    return (
        result.preserved_source,
        result.translated_text or "",
        result.annotated_copy or "",
        _format_annotations(result.annotations),
        _format_route(result),
        _format_detection(result),
        _format_warnings(result.warnings),
        _format_terms(result.applied_terms),
    )


def _begin_request(
    session_id: str,
    text: str,
    task_mode: str,
    source_language: str,
    target_language: str,
    style: str,
    domain: str,
) -> tuple[Any, ...]:
    """先冻结输入并推进代次，再异步执行耗时工作流。"""

    pending = PendingAgentRequest(
        session_id=session_id,
        generation=request_generations.advance(session_id),
        text=text,
        task_mode=task_mode,
        source_language=source_language,
        target_language=target_language,
        style=style,
        domain=domain,
    )
    disabled = gr.update(interactive=False)
    return (
        pending,
        text,
        "",
        "",
        "正在分析输入并执行任务…",
        "正在判断任务类型…",
        "正在检测语言…",
        "正在处理，请稍候…",
        EMPTY_TERMS,
        disabled,
        disabled,
        disabled,
    )


def _execute_workflow(pending: PendingAgentRequest) -> WorkflowOutcome:
    """执行工作流并把所有失败转换为可提交的普通结果。"""

    if not request_generations.is_current(pending.session_id, pending.generation):
        return WorkflowOutcome(pending=pending)

    try:
        request = AgentRequest(
            text=pending.text,
            target_language=pending.target_language,
            source_language=pending.source_language,
            style=pending.style,
            domain=pending.domain,
            task_mode=pending.task_mode,
        )
        result = workflow.run(request)
    except ValidationError as exc:
        return WorkflowOutcome(
            pending=pending,
            error_message=_validation_error_message(exc),
        )
    except (TranslationError, GlossaryError) as exc:
        return WorkflowOutcome(pending=pending, error_message=_friendly_error(exc))
    except Exception:  # UI 不暴露内部异常、堆栈或原始内容
        return WorkflowOutcome(
            pending=pending,
            error_message="处理失败，请检查本地 Ollama 状态后重试。",
        )
    return WorkflowOutcome(pending=pending, result=result)


def _commit_workflow_outcome(outcome: WorkflowOutcome | None) -> tuple[Any, ...]:
    """仅提交当前代次；被清空或替代的旧请求不能写回界面。"""

    output_count = 11
    if outcome is None or not request_generations.is_current(
        outcome.pending.session_id,
        outcome.pending.generation,
    ):
        return tuple(gr.skip() for _ in range(output_count))

    enabled = gr.update(interactive=True)
    if outcome.error_message:
        _warning(outcome.error_message, title="处理未完成")
        result_values = (
            outcome.pending.text,
            "",
            "",
            EMPTY_EXPLANATION,
            "任务未完成",
            "处理失败",
            f"• {outcome.error_message}",
            EMPTY_TERMS,
        )
    elif outcome.result is not None:
        result_values = _result_values(outcome.result)
    else:
        return tuple(gr.skip() for _ in range(output_count))

    return (*result_values, enabled, enabled, enabled)


def _reset_ui(session_id: str) -> tuple[Any, ...]:
    """使当前请求失效，并以一次原子更新恢复所有主界面字段。"""

    request_generations.advance(session_id)
    enabled = gr.update(interactive=True)
    return (
        None,
        "",
        "auto",
        "auto",
        "zh-Hans",
        "standard",
        "general",
        "",
        "",
        "",
        EMPTY_EXPLANATION,
        EMPTY_ROUTE,
        EMPTY_DETECTION,
        _count_characters(""),
        EMPTY_WARNINGS,
        EMPTY_TERMS,
        enabled,
        enabled,
    )


def _reset_if_empty(text: str, session_id: str) -> tuple[Any, ...]:
    """用户手动删空原文时，复用与清空按钮完全相同的状态转换。"""

    if text != "":
        return tuple(gr.skip() for _ in range(18))
    return _reset_ui(session_id)


def build_app() -> gr.Blocks:
    """创建应用但不启动服务器，便于自动化测试。"""

    try:
        initial_rows = glossary_store.load_rows()
        initial_glossary_status = f"已载入 {len(initial_rows)} 条本地术语"
    except GlossaryError as exc:
        initial_rows = []
        initial_glossary_status = f"词库需要修复：{_friendly_error(exc)}"
    except Exception:
        initial_rows = []
        initial_glossary_status = "词库载入失败，请检查本地词库文件。"

    with gr.Blocks(
        title=APP_TITLE,
        fill_width=True,
        analytics_enabled=False,
    ) as demo:
        gr.HTML(
            """
            <section class="yijing-hero">
              <span class="local-badge">仅本机运行</span>
              <h1>译境</h1>
              <p>理解语境，再准确表达。自动检测语言、适配表达风格，并严格执行你的专业术语。</p>
            </section>
            """
        )

        model_status = gr.Textbox(
            value="正在检查本地模型…",
            label="运行状态",
            interactive=False,
            container=True,
            elem_classes="status-strip",
        )

        session_id = gr.State(
            value=_new_session_id,
            delete_callback=request_generations.discard,
        )
        pending_request_state = gr.State(value=None)
        completed_outcome_state = gr.State(value=None)

        with gr.Row(equal_height=True):
            task_mode = gr.Dropdown(
                choices=TASK_MODE_CHOICES,
                value="auto",
                label="任务模式",
                info="智能判断可自动选择翻译、代码注释或结构说明",
                scale=2,
            )
            source_language = gr.Dropdown(
                choices=LANGUAGE_CHOICES,
                value="auto",
                label="源语言",
                info="默认由模型自动检测，也可手动指定",
                scale=2,
            )
            target_language = gr.Dropdown(
                choices=TARGET_LANGUAGE_CHOICES,
                value="zh-Hans",
                label="目标语言",
                scale=2,
            )
            style = gr.Radio(
                choices=STYLE_CHOICES,
                value="standard",
                label="翻译风格",
                scale=3,
            )
            domain = gr.Dropdown(
                choices=DOMAIN_CHOICES,
                value="general",
                label="专业领域",
                scale=2,
            )

        with gr.Row(equal_height=True):
            with gr.Column(elem_classes="yijing-card"):
                source_text = gr.Textbox(
                    label="原文",
                    placeholder="输入或粘贴需要翻译的文本…",
                    lines=16,
                    max_lines=24,
                    max_length=MAX_INPUT_LENGTH,
                    autofocus=True,
                    elem_id="source-text",
                )
                character_count = gr.Textbox(
                    value=_count_characters(""),
                    label="输入长度",
                    interactive=False,
                    container=False,
                    elem_classes="status-strip",
                )
            with gr.Column(elem_classes="yijing-card"):
                translation_output = gr.Textbox(
                    label="译文",
                    placeholder="文本翻译结果将在这里显示",
                    lines=16,
                    max_lines=24,
                    interactive=False,
                    buttons=["copy"],
                    elem_id="target-text",
                )

        with gr.Row():
            translate_button = gr.Button(
                "开始处理",
                variant="primary",
                elem_id="translate-button",
                scale=3,
            )
            retry_button = gr.Button("重试", variant="secondary", scale=1)
            clear_button = gr.Button(
                value="清空",
                variant="secondary",
                scale=1,
            )

        with gr.Row(equal_height=True):
            preserved_source_output = gr.Textbox(
                value="",
                label="本次处理原文（不可编辑）",
                placeholder="开始处理后，将在此冻结本次使用的原文",
                lines=10,
                max_lines=18,
                interactive=False,
                buttons=["copy"],
                elem_classes="yijing-card",
            )
            annotated_copy_output = gr.Textbox(
                value="",
                label="注释副本（不可编辑）",
                placeholder="代码注释或结构说明任务会在此生成独立副本",
                lines=10,
                max_lines=18,
                interactive=False,
                buttons=["copy"],
                elem_classes="yijing-card",
            )

        explanation_output = gr.Textbox(
            value=EMPTY_EXPLANATION,
            label="说明",
            lines=7,
            max_lines=16,
            interactive=False,
            buttons=["copy"],
        )

        with gr.Row():
            route_output = gr.Textbox(
                value=EMPTY_ROUTE,
                label="实际路由",
                interactive=False,
                container=False,
                elem_classes="status-strip",
            )
            detection_output = gr.Textbox(
                value=EMPTY_DETECTION,
                label="检测结果",
                interactive=False,
                container=False,
                elem_classes="status-strip",
            )

        with gr.Row():
            warnings_output = gr.Textbox(
                value=EMPTY_WARNINGS,
                label="提示",
                lines=3,
                interactive=False,
                scale=1,
            )
            terms_output = gr.Textbox(
                value=EMPTY_TERMS,
                label="已应用术语",
                lines=3,
                interactive=False,
                scale=1,
            )

        with gr.Accordion("专业术语词库", open=False):
            gr.Markdown(
                "词条仅保存在本机 `data/glossary.json`。可直接新增、编辑或删除表格行，"
                "然后点击保存。目标语言与领域请填写下方列出的代码。",
                elem_classes="glossary-help",
            )
            glossary_table = gr.Dataframe(
                value=initial_rows,
                headers=["原词", "指定译法", "目标语言", "领域", "区分大小写"],
                datatype=["str", "str", "str", "str", "bool"],
                type="array",
                row_count=max(5, len(initial_rows) + 1),
                column_count=5,
                interactive=True,
                wrap=True,
                buttons=["fullscreen", "copy"],
                label="术语条目",
            )
            gr.Markdown(
                "目标语言：`zh-Hans`、`zh-Hant`、`en`、`ja`、`ko`、`fr`、`de`、"
                "`es`、`ru`、`pt-BR`、`ar`、`it` 　|　领域：`all`、`general`、"
                "`technology`、`business`、`finance`、`legal`、`medical`、`academic`",
                elem_classes="glossary-help",
            )
            with gr.Row():
                save_glossary_button = gr.Button("保存词库", variant="primary")
                refresh_glossary_button = gr.Button("重新载入", variant="secondary")
            glossary_status = gr.Textbox(
                value=initial_glossary_status,
                label="词库状态",
                interactive=False,
                container=False,
                elem_classes="status-strip",
            )

        gr.Markdown(
            "**隐私说明：** 原文、译文与术语仅在本机处理。法律、医疗和其他高风险内容"
            "不能替代专业翻译或专业意见。",
            elem_classes="glossary-help",
        )

        request_inputs = [
            session_id,
            source_text,
            task_mode,
            source_language,
            target_language,
            style,
            domain,
        ]
        begin_outputs = [
            pending_request_state,
            preserved_source_output,
            translation_output,
            annotated_copy_output,
            explanation_output,
            route_output,
            detection_output,
            warnings_output,
            terms_output,
            source_text,
            translate_button,
            retry_button,
        ]
        commit_outputs = begin_outputs[1:]
        reset_outputs = [
            pending_request_state,
            source_text,
            task_mode,
            source_language,
            target_language,
            style,
            domain,
            preserved_source_output,
            translation_output,
            annotated_copy_output,
            explanation_output,
            route_output,
            detection_output,
            character_count,
            warnings_output,
            terms_output,
            translate_button,
            retry_button,
        ]

        source_text.input(
            fn=None,
            inputs=source_text,
            outputs=character_count,
            js=CHARACTER_COUNT_JS,
            queue=False,
            trigger_mode="always_last",
            api_name="character_count",
            api_visibility="private",
        )

        begin_event = gr.on(
            triggers=[
                translate_button.click,
                retry_button.click,
                source_text.submit,
            ],
            fn=_begin_request,
            inputs=request_inputs,
            outputs=begin_outputs,
            queue=False,
            api_name="run_agent",
            trigger_mode="always_last",
        )
        workflow_event = begin_event.then(
            fn=_execute_workflow,
            inputs=pending_request_state,
            outputs=completed_outcome_state,
            queue=True,
            api_visibility="private",
            concurrency_id="translation_workflow",
            concurrency_limit=1,
        )
        workflow_event.then(
            fn=_commit_workflow_outcome,
            inputs=completed_outcome_state,
            outputs=commit_outputs,
            queue=False,
            api_visibility="private",
        )

        clear_button.click(
            fn=_reset_ui,
            inputs=session_id,
            outputs=reset_outputs,
            queue=False,
            cancels=[workflow_event],
            api_name="reset_agent",
        )
        source_text.input(
            fn=_reset_if_empty,
            inputs=[source_text, session_id],
            outputs=reset_outputs,
            queue=False,
            cancels=[workflow_event],
            trigger_mode="always_last",
            api_visibility="private",
        )
        save_glossary_button.click(
            fn=_save_glossary_rows,
            inputs=glossary_table,
            outputs=[glossary_table, glossary_status],
        )
        refresh_glossary_button.click(
            fn=_load_glossary_rows,
            outputs=[glossary_table, glossary_status],
            queue=False,
        )
        demo.load(fn=_model_status, outputs=model_status, queue=False)

    return demo.queue(default_concurrency_limit=1, max_size=8)


def _server_port_from_env() -> int | None:
    raw_port = os.getenv("TRANSLATOR_PORT")
    if raw_port is None:
        return None

    error_message = "环境变量 TRANSLATOR_PORT 必须是 1 到 65535 之间的十进制整数。"
    if not raw_port.isascii() or not raw_port.isdecimal():
        raise ValueError(error_message)

    port = int(raw_port)
    if not 1 <= port <= 65535:
        raise ValueError(error_message)
    return port


def _is_port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _select_server_port() -> int:
    configured_port = _server_port_from_env()
    if configured_port is not None:
        if not _is_port_available(configured_port):
            raise OSError(
                f"端口 {configured_port} 已被占用，请关闭旧进程或设置其他 TRANSLATOR_PORT。"
            )
        return configured_port

    for port in range(DEFAULT_PORT, LAST_AUTO_PORT + 1):
        if _is_port_available(port):
            return port
    raise OSError(
        f"端口 {DEFAULT_PORT} 到 {LAST_AUTO_PORT} 均被占用，请设置 TRANSLATOR_PORT。"
    )


def _startup_diagnostics(port: int) -> str:
    """输出可核验的启动信息；Ollama 离线时也不得中断 UI 启动。"""

    model_status = _with_ollama_privacy_warning(_model_status())
    keep_alive = getattr(translator, "keep_alive", None)
    keep_alive_display = str(keep_alive) if keep_alive is not None else "未配置"
    lines = [
        "启动诊断：",
        f"- 应用脚本：{Path(__file__).resolve()}",
        f"- Python 解释器：{sys.executable}",
        f"- Ollama 地址：{OLLAMA_BASE_URL}",
        f"- 翻译模型：{MODEL_NAME}",
        f"- 模型驻留：{keep_alive_display}",
        f"- 模型状态：{model_status}",
        f"- Web 地址：http://127.0.0.1:{port}",
    ]
    print("\n".join(lines), flush=True)
    return model_status


def main() -> None:
    try:
        port = _select_server_port()
    except (OSError, ValueError) as exc:
        raise SystemExit(f"启动失败：{exc}") from None
    if os.getenv("TRANSLATOR_PORT") is None and port != DEFAULT_PORT:
        print(f"提示：端口 {DEFAULT_PORT} 已被占用，已自动使用 {port}。")
    open_browser = os.getenv("TRANSLATOR_INBROWSER", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    _startup_diagnostics(port)
    demo = build_app()
    demo.launch(
        server_name="127.0.0.1",
        server_port=port,
        inbrowser=open_browser,
        share=False,
        show_error=False,
        strict_cors=True,
        enable_monitoring=False,
        run_history=False,
        footer_links=[],
        theme=gr.themes.Soft(
            primary_hue="indigo",
            secondary_hue="teal",
            neutral_hue="slate",
            font=["Inter", "Microsoft YaHei", "sans-serif"],
        ),
        css=APP_CSS,
        blocked_paths=[str(BASE_DIR), str(GLOSSARY_PATH.parent)],
    )


if __name__ == "__main__":
    main()

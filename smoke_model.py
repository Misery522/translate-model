"""通过 LangChain 调用一次本地 Ollama 聊天模型。

该脚本不是 Agent：不包含工具调用、记忆、RAG 或 OpenAI API 调用。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import Any

from langchain_ollama import ChatOllama
from langsmith import tracing_context

from translation_agent import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    TranslationError,
    validate_local_ollama_base_url,
)

DEFAULT_PROMPT = "请把“环境已经准备完成”翻译成英文，只输出译文。"


def local_base_url(value: str) -> str:
    """复用应用的隐私边界，参数错误也不回显可能包含凭据的值。"""

    try:
        return validate_local_ollama_base_url(value)
    except TranslationError as exc:
        raise argparse.ArgumentTypeError(
            "仅允许无用户信息、路径、查询参数和片段的本机回环 HTTP(S) 地址"
        ) from exc


def timeout_seconds(value: str) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError("超时必须为大于 0 且不超过 60 的秒数") from exc
    if not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise argparse.ArgumentTypeError("超时必须为大于 0 且不超过 60 的秒数")
    return timeout


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LangChain + Ollama 最小调用测试")
    parser.add_argument(
        "--model",
        default=os.getenv("OLLAMA_MODEL", DEFAULT_MODEL),
        help=f"Ollama 模型名称，默认：{DEFAULT_MODEL}",
    )
    parser.add_argument(
        "--base-url",
        type=local_base_url,
        default=os.getenv("OLLAMA_BASE_URL", DEFAULT_BASE_URL),
        help=f"Ollama 服务地址，默认：{DEFAULT_BASE_URL}",
    )
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="无敏感信息的测试文本")
    parser.add_argument(
        "--timeout", type=timeout_seconds, default=60.0, help="调用超时秒数，范围 (0, 60]"
    )
    return parser.parse_args(argv)


def selected_metadata(raw: dict[str, Any]) -> dict[str, Any]:
    """只输出有助于验收且不包含提示词或密钥的元数据。"""

    keys = (
        "model_name",
        "done_reason",
        "total_duration",
        "load_duration",
        "prompt_eval_count",
        "eval_count",
    )
    return {key: raw[key] for key in keys if key in raw}


# 冒烟测试同样遵循应用的本地数据边界，不继承全局远程追踪开关。
@tracing_context(enabled=False)
def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        model = ChatOllama(
            model=args.model,
            base_url=args.base_url,
            temperature=0,
            num_ctx=4096,
            reasoning=False,
            client_kwargs={
                "timeout": args.timeout,
                "trust_env": False,
                "follow_redirects": False,
            },
        )
        response = model.invoke(args.prompt)
    except Exception:  # SDK 错误可能含完整提示词和地址，统一使用脱敏说明。
        print("调用失败：请检查本机 Ollama 服务、模型名称与超时配置。", file=sys.stderr)
        return 1

    text = response.content if isinstance(response.content, str) else str(response.content)
    if not text.strip():
        print("调用失败：模型返回了空内容。", file=sys.stderr)
        return 1

    print("LangChain 调用成功")
    print(f"模型：{args.model}")
    print(f"服务：{args.base_url}")
    print(f"结果：{text.strip()}")
    print("元数据：")
    print(json.dumps(selected_metadata(response.response_metadata), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

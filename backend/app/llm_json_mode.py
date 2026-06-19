"""
Configuration helpers for JSON object responses from chat completions.
"""

from __future__ import annotations

import json
import os
from typing import Any


JSON_OBJECT_RESPONSE_FORMAT_ENV = "LLM_RESPONSE_FORMAT_JSON_OBJECT_SUPPORTED"

JSON_OBJECT_OUTPUT_INSTRUCTION = (
    "你必须只输出一个合法 JSON object。不要输出 Markdown 代码块、解释文字、注释或多余前后缀。"
    "所有字符串必须正确转义；未知字段使用 null，空列表使用 []。"
)


def llm_response_format_json_object_supported() -> bool:
    """Whether the configured chat service supports response_format=json_object."""
    return _env_bool(JSON_OBJECT_RESPONSE_FORMAT_ENV, default=True)


def json_object_response_format() -> dict[str, str] | None:
    if llm_response_format_json_object_supported():
        return {"type": "json_object"}
    return None


def json_object_response_format_kwargs() -> dict[str, dict[str, str]]:
    response_format = json_object_response_format()
    return {"response_format": response_format} if response_format else {}


def add_json_object_output_instruction(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a copy of messages with a JSON-only system instruction prepended."""
    copied_messages = [dict(message) for message in messages]
    if _messages_already_contain_json_instruction(copied_messages):
        return copied_messages

    if copied_messages and copied_messages[0].get("role") == "system":
        content = str(copied_messages[0].get("content") or "")
        copied_messages[0]["content"] = f"{JSON_OBJECT_OUTPUT_INSTRUCTION}\n\n{content}".strip()
        return copied_messages

    return [
        {"role": "system", "content": JSON_OBJECT_OUTPUT_INSTRUCTION},
        *copied_messages,
    ]


def prepare_json_object_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if llm_response_format_json_object_supported():
        return [dict(message) for message in messages]
    return add_json_object_output_instruction(messages)


def build_json_repair_messages(
    *,
    original_messages: list[dict[str, Any]],
    invalid_content: str,
    parse_error: Exception,
) -> list[dict[str, str]]:
    original_excerpt = json.dumps(original_messages, ensure_ascii=False)[:6000]
    invalid_excerpt = invalid_content[:12000]
    return [
        {"role": "system", "content": JSON_OBJECT_OUTPUT_INSTRUCTION},
        {
            "role": "user",
            "content": (
                "下面的模型输出不是可解析的 JSON object。请根据原始任务意图修复它，"
                "只返回修复后的 JSON object，不要解释。\n\n"
                f"解析错误：{parse_error}\n\n"
                f"原始任务消息：\n{original_excerpt}\n\n"
                f"待修复输出：\n{invalid_excerpt}"
            ),
        },
    ]


def strip_unsupported_json_object_response_format(kwargs: dict[str, Any]) -> bool:
    """Remove response_format=json_object when the configured provider cannot accept it."""
    if llm_response_format_json_object_supported():
        return False

    response_format = kwargs.get("response_format")
    if _response_format_type(response_format) != "json_object":
        return False

    kwargs.pop("response_format", None)
    return True


def _messages_already_contain_json_instruction(messages: list[dict[str, Any]]) -> bool:
    return any(
        message.get("role") == "system"
        and JSON_OBJECT_OUTPUT_INSTRUCTION in str(message.get("content") or "")
        for message in messages
    )


def _response_format_type(response_format: Any) -> str | None:
    if isinstance(response_format, dict):
        value = response_format.get("type")
        return str(value) if value is not None else None

    model_dump = getattr(response_format, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(exclude_none=True)
        if isinstance(dumped, dict):
            value = dumped.get("type")
            return str(value) if value is not None else None

    value = getattr(response_format, "type", None)
    return str(value) if value is not None else None


def _env_bool(name: str, *, default: bool) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on", "y"}:
        return True
    if normalized in {"0", "false", "no", "off", "n"}:
        return False
    return default

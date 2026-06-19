"""
Ollama native /api/chat compatibility for OpenAI-style chat calls.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import urlparse, urlunparse

from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
from openai.types.completion_usage import CompletionUsage

from ..llm_protocol import (
    chat_protocol_requires_api_key,
    llm_api_key_or_dummy as protocol_llm_api_key_or_dummy,
    looks_like_ollama_native_chat_url,
)
from .structured_output import (
    extract_prompt_json_schema,
    normalize_ollama_format_schema,
    normalize_response_content,
    repair_structured_response_content,
    rewrite_prompt_json_schema_messages,
)

_LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_DEFAULT_TIMEOUT_SECONDS = 600


class OllamaChatRequestError(RuntimeError):
    """Raised when Ollama returns an HTTP error for a chat request."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def is_ollama_native_chat_base_url(base_url: str | None) -> bool:
    """Return True when LLM_BASE_URL points at Ollama's native chat API."""
    return looks_like_ollama_native_chat_url(base_url)


def llm_api_key_or_dummy(api_key: str | None, base_url: str | None) -> str | None:
    """OpenAI SDK and Camel still require a non-empty API key string."""
    return protocol_llm_api_key_or_dummy(api_key, base_url, "auto")


def llm_requires_api_key(base_url: str | None) -> bool:
    return chat_protocol_requires_api_key("auto", base_url)


def normalize_ollama_chat_url(base_url: str) -> str:
    """Resolve a native Ollama base URL to the concrete /api/chat endpoint."""
    parsed = urlparse(base_url)
    path = (parsed.path or "").rstrip("/")
    if path == "/api/chat":
        normalized_path = "/api/chat"
    elif path == "/api":
        normalized_path = "/api/chat"
    elif path == "":
        normalized_path = "/api/chat"
    else:
        normalized_path = path
    return urlunparse(parsed._replace(path=normalized_path, params="", query="", fragment=""))


def create_ollama_chat_completion(base_url: str, kwargs: dict[str, Any]) -> ChatCompletion:
    """Post an OpenAI-style chat completion request to Ollama native /api/chat."""
    url = normalize_ollama_chat_url(base_url)
    payload = build_ollama_chat_payload(kwargs)
    timeout = _extract_timeout(kwargs)
    response = _post_json_sync(url, payload, timeout)
    return build_chat_completion_response(
        response,
        request_model=str(payload["model"]),
        request_messages=payload.get("messages"),
        response_schema=payload.get("format"),
    )


def build_ollama_chat_payload(kwargs: dict[str, Any]) -> dict[str, Any]:
    model = kwargs.get("model")
    if _is_omitted(model) or not model:
        raise ValueError("Ollama chat 请求缺少 model，请配置 LLM_MODEL_NAME")

    messages = kwargs.get("messages")
    if _is_omitted(messages) or messages is None:
        raise ValueError("Ollama chat 请求缺少 messages")

    if _is_streaming_enabled(kwargs.get("stream")):
        raise ValueError("当前 Ollama /api/chat 兼容层不支持 stream=True")

    payload: dict[str, Any] = {
        "model": str(model),
        "messages": _normalize_messages(messages),
        "stream": False,
    }

    _apply_response_format(payload, kwargs.get("response_format"), payload["messages"])
    _apply_tools(payload, kwargs)
    _apply_options(payload, kwargs)
    _apply_extra_body(payload, kwargs.get("extra_body"))
    return payload


def build_chat_completion_response(
    response: dict[str, Any],
    *,
    request_model: str,
    request_messages: list[dict[str, Any]] | None = None,
    response_schema: dict[str, Any] | str | None = None,
) -> ChatCompletion:
    message = response.get("message") if isinstance(response.get("message"), dict) else {}
    content = normalize_response_content(
        str(message.get("content") or response.get("response") or "")
    )
    content = repair_structured_response_content(
        content,
        request_messages=request_messages,
        response_schema=response_schema,
    )
    role = str(message.get("role") or "assistant")

    chat_message_kwargs: dict[str, Any] = {
        "role": role,
        "content": content,
    }
    if message.get("tool_calls") is not None:
        chat_message_kwargs["tool_calls"] = _normalize_response_tool_calls(
            message.get("tool_calls")
        )

    choice = Choice(
        index=0,
        finish_reason=_map_finish_reason(response),
        message=ChatCompletionMessage(**chat_message_kwargs),
    )

    return ChatCompletion(
        id=str(response.get("id") or f"chatcmpl-ollama-{uuid.uuid4().hex[:12]}"),
        choices=[choice],
        created=_parse_created_at(response.get("created_at")),
        model=str(response.get("model") or request_model),
        object="chat.completion",
        usage=_build_usage(response),
    )


def _apply_response_format(
    payload: dict[str, Any],
    response_format: Any,
    messages: list[dict[str, Any]] | None = None,
) -> None:
    if _is_omitted(response_format) or not response_format:
        return
    response_format = _to_plain(response_format)
    if not isinstance(response_format, dict):
        return

    format_type = response_format.get("type")
    if format_type == "json_object":
        schema = extract_prompt_json_schema(messages or [])
        if schema:
            payload["format"] = normalize_ollama_format_schema(schema)
            rewrite_prompt_json_schema_messages(messages or [], schema)
        else:
            payload["format"] = "json"
    elif format_type == "json_schema":
        json_schema = response_format.get("json_schema")
        if isinstance(json_schema, dict) and isinstance(json_schema.get("schema"), dict):
            payload["format"] = normalize_ollama_format_schema(json_schema["schema"])

def _apply_tools(payload: dict[str, Any], kwargs: dict[str, Any]) -> None:
    tools = kwargs.get("tools")
    if not _is_omitted(tools) and tools:
        payload["tools"] = _to_plain(tools)


def _apply_options(payload: dict[str, Any], kwargs: dict[str, Any]) -> None:
    option_mappings = {
        "temperature": "temperature",
        "top_p": "top_p",
        "seed": "seed",
        "max_tokens": "num_predict",
        "max_completion_tokens": "num_predict",
    }
    options: dict[str, Any] = {}
    for source_key, target_key in option_mappings.items():
        value = kwargs.get(source_key)
        if not _is_omitted(value) and value is not None:
            options[target_key] = _to_plain(value)

    stop = kwargs.get("stop")
    if not _is_omitted(stop) and stop:
        options["stop"] = _to_plain(stop)

    if options:
        payload["options"] = options


def _apply_extra_body(payload: dict[str, Any], extra_body: Any) -> None:
    if _is_omitted(extra_body) or not isinstance(extra_body, dict):
        return

    plain_extra = _to_plain(extra_body)
    if not isinstance(plain_extra, dict):
        return

    if isinstance(plain_extra.get("options"), dict):
        payload.setdefault("options", {}).update(plain_extra["options"])

    for key in ("format", "keep_alive", "think"):
        if key in plain_extra:
            payload[key] = plain_extra[key]


def _normalize_messages(messages: Any) -> list[dict[str, Any]]:
    plain_messages = _to_plain(messages)
    if not isinstance(plain_messages, list):
        raise ValueError("Ollama chat messages 必须是列表")

    normalized: list[dict[str, Any]] = []
    tool_call_names_by_id: dict[str, str] = {}
    for message in plain_messages:
        if not isinstance(message, dict):
            raise ValueError("Ollama chat message 必须是对象")
        item: dict[str, Any] = {
            "role": str(message.get("role") or "user"),
            "content": _normalize_content(message.get("content")),
        }

        for key in ("images",):
            value = message.get(key)
            if value is not None:
                item[key] = value

        tool_calls = message.get("tool_calls")
        if tool_calls is not None:
            normalized_tool_calls, call_names = _normalize_request_tool_calls(tool_calls)
            if normalized_tool_calls:
                item["tool_calls"] = normalized_tool_calls
            tool_call_names_by_id.update(call_names)

        tool_name = _resolve_tool_name(message, tool_call_names_by_id)
        if tool_name:
            item["tool_name"] = tool_name

        normalized.append(item)
    return normalized


def _normalize_request_tool_calls(tool_calls: Any) -> tuple[list[dict[str, Any]], dict[str, str]]:
    plain_tool_calls = _to_plain(tool_calls)
    if not isinstance(plain_tool_calls, list):
        return [], {}

    normalized: list[dict[str, Any]] = []
    names_by_id: dict[str, str] = {}
    for index, tool_call in enumerate(plain_tool_calls):
        if not isinstance(tool_call, dict):
            continue

        function = tool_call.get("function")
        function = function if isinstance(function, dict) else {}
        name = function.get("name") or tool_call.get("name")
        arguments = _normalize_tool_arguments(function.get("arguments", tool_call.get("arguments", {})))
        function_index = _as_int(function.get("index"))

        native_function: dict[str, Any] = {
            "index": function_index if function_index is not None else index,
            "arguments": arguments,
        }
        if name:
            native_function["name"] = str(name)

        normalized.append(
            {
                "type": str(tool_call.get("type") or "function"),
                "function": native_function,
            }
        )

        tool_call_id = tool_call.get("id")
        if tool_call_id and name:
            names_by_id[str(tool_call_id)] = str(name)

    return normalized, names_by_id


def _normalize_response_tool_calls(tool_calls: Any) -> list[dict[str, Any]]:
    plain_tool_calls = _to_plain(tool_calls)
    if not isinstance(plain_tool_calls, list):
        return []

    normalized: list[dict[str, Any]] = []
    for index, tool_call in enumerate(plain_tool_calls):
        if not isinstance(tool_call, dict):
            continue

        function = tool_call.get("function")
        function = function if isinstance(function, dict) else {}
        name = function.get("name") or tool_call.get("name") or ""
        arguments = function.get("arguments", tool_call.get("arguments", {}))
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments if arguments is not None else {}, ensure_ascii=False)

        normalized.append(
            {
                "id": str(tool_call.get("id") or f"call_{index}"),
                "type": "function",
                "function": {
                    "name": str(name),
                    "arguments": arguments,
                },
            }
        )

    return normalized


def _resolve_tool_name(message: dict[str, Any], tool_call_names_by_id: dict[str, str]) -> str | None:
    tool_name = message.get("tool_name") or message.get("name")
    if tool_name:
        return str(tool_name)

    tool_call_id = message.get("tool_call_id")
    if tool_call_id is not None:
        return tool_call_names_by_id.get(str(tool_call_id))
    return None


def _normalize_tool_arguments(arguments: Any) -> Any:
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return arguments
        return parsed
    return arguments if arguments is not None else {}


def _normalize_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text" and part.get("text") is not None:
                    text_parts.append(str(part["text"]))
                elif part.get("text") is not None:
                    text_parts.append(str(part["text"]))
            elif part is not None:
                text_parts.append(str(part))
        return "\n".join(text_parts)
    return str(content)


def _post_json_sync(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with _open_request(request, timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise OllamaChatRequestError(
            _format_ollama_http_error(url, str(payload.get("model", "")), exc.code, error_body),
            status_code=exc.code,
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            "Ollama chat 请求失败: 无法连接本地 Ollama。"
            f"url={url}, error={exc.reason}。请确认 Ollama 已启动，例如执行 `ollama serve`，"
            "并确认 LLM_BASE_URL 指向 http://localhost:11434/api/chat。"
        ) from exc

    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise ValueError("Ollama chat response is not a JSON object")
    return parsed


def _open_request(request: urllib.request.Request, timeout: int):
    if _is_loopback_url(request.full_url):
        return _LOCAL_OPENER.open(request, timeout=timeout)
    return urllib.request.urlopen(request, timeout=timeout)


def _is_loopback_url(url: str) -> bool:
    hostname = urlparse(url).hostname
    return hostname in {"localhost", "127.0.0.1", "::1"}


def _format_ollama_http_error(url: str, model: str, code: int, body: str) -> str:
    body_message = _extract_ollama_error_message(body)
    details = f"HTTP {code}"
    if body_message:
        details = f"{details}: {body_message}"

    suggestions = [
        "确认 Ollama 正在运行：`ollama serve`",
        "查看本地已安装模型：`ollama list` 或 GET /api/tags",
        "确认 LLM_BASE_URL=http://localhost:11434/api/chat",
        f"如果模型未安装，执行：`ollama pull {model}`",
        "如果本地模型带 tag，请把 LLM_MODEL_NAME 设置为完整名称，例如 qwen3.5:2b-mlx",
    ]
    return (
        "Ollama chat 请求失败。"
        f"url={url}, model={model}, error={details}。"
        "处理建议：" + "；".join(suggestions)
    )


def _extract_ollama_error_message(body: str) -> str:
    if not body:
        return ""
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return body.strip()
    if isinstance(parsed, dict) and parsed.get("error"):
        return str(parsed["error"])
    return body.strip()


def _build_usage(response: dict[str, Any]) -> CompletionUsage | None:
    prompt_tokens = _as_int(response.get("prompt_eval_count"))
    completion_tokens = _as_int(response.get("eval_count"))
    if prompt_tokens is None and completion_tokens is None:
        return None

    prompt_tokens = prompt_tokens or 0
    completion_tokens = completion_tokens or 0
    return CompletionUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )


def _map_finish_reason(response: dict[str, Any]) -> str | None:
    reason = response.get("done_reason")
    if reason == "length":
        return "length"
    if reason in {"stop", "unload"}:
        return "stop"
    if response.get("done") is True:
        return "stop"
    return str(reason) if reason else None


def _parse_created_at(value: Any) -> int:
    if isinstance(value, str) and value:
        normalized = value.replace("Z", "+00:00")
        try:
            return int(datetime.fromisoformat(normalized).timestamp())
        except ValueError:
            pass
    return int(time.time())


def _extract_timeout(kwargs: dict[str, Any]) -> int:
    timeout = kwargs.get("timeout")
    if isinstance(timeout, (int, float)) and timeout > 0:
        return int(timeout)
    return _DEFAULT_TIMEOUT_SECONDS


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_streaming_enabled(value: Any) -> bool:
    return not _is_omitted(value) and bool(value)


def _is_omitted(value: Any) -> bool:
    if value is None:
        return False
    return value.__class__.__name__ in {"NotGiven", "Omit"}


def _to_plain(value: Any) -> Any:
    if _is_omitted(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _to_plain(v) for k, v in value.items() if not _is_omitted(v)}
    if isinstance(value, (list, tuple, set)):
        return [_to_plain(item) for item in value if not _is_omitted(item)]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _to_plain(model_dump(exclude_none=True))
    return value

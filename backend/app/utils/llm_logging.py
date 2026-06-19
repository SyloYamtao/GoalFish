"""
OpenAI-compatible completions request/response logging.
"""

import inspect
import asyncio
import json
import logging
import os
import time
import traceback
import uuid
from typing import Any, Dict

try:
    from openai import Omit
    from openai._types import NOT_GIVEN
    from openai.resources.chat.completions import AsyncCompletions, Completions
except Exception:  # pragma: no cover - import availability depends on runtime deps
    Omit = None
    NOT_GIVEN = object()
    AsyncCompletions = None
    Completions = None

from .logger import get_logger
from ..llm_json_mode import (
    add_json_object_output_instruction,
    strip_unsupported_json_object_response_format,
)
from ..llm_protocol import resolve_chat_protocol
from .ollama_chat import (
    create_ollama_chat_completion,
)
from .structured_output import (
    extract_prompt_json_schema,
    normalize_structured_output_schema,
    normalize_response_content,
    repair_structured_response_content,
    rewrite_prompt_json_schema_messages,
    to_plain_data,
)


logger = get_logger("goalfish.llm")

_PATCHED = False
_ORIGINAL_SYNC_CREATE = None
_ORIGINAL_ASYNC_CREATE = None

_SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "access_token",
    "refresh_token",
    "id_token",
    "secret",
    "password",
)


def _is_logging_enabled() -> bool:
    value = os.environ.get("LLM_LOG_COMPLETIONS", "true").lower()
    return value not in {"0", "false", "no", "off"}


def _is_omitted(value: Any) -> bool:
    if value is NOT_GIVEN:
        return True
    if Omit is not None and isinstance(value, Omit):
        return True
    return False


def _is_secret_key(key: Any) -> bool:
    normalized = str(key).lower().replace("-", "_")
    return any(part in normalized for part in _SECRET_KEY_PARTS)


def _safe_to_plain(value: Any) -> Any:
    if _is_omitted(value):
        return None

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value

    if isinstance(value, dict):
        return {
            str(k): ("<redacted>" if _is_secret_key(k) else _safe_to_plain(v))
            for k, v in value.items()
            if not _is_omitted(v)
        }

    if isinstance(value, (list, tuple, set)):
        return [_safe_to_plain(item) for item in value if not _is_omitted(item)]

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _safe_to_plain(model_dump(exclude_none=True))

    if hasattr(value, "__dict__"):
        attrs = {
            k: v for k, v in vars(value).items()
            if not k.startswith("_") and not callable(v)
        }
        if not attrs:
            attrs = {}
            for key in dir(value):
                if key.startswith("_"):
                    continue
                try:
                    attr_value = getattr(value, key)
                except Exception:
                    continue
                if not callable(attr_value):
                    attrs[key] = attr_value
        return _safe_to_plain(attrs)

    return repr(value)


def _sanitize_for_logging(value: Any) -> Any:
    return _safe_to_plain(value)


def _dumps(value: Any) -> str:
    return json.dumps(_sanitize_for_logging(value), ensure_ascii=False, indent=2)


def _get_client_base_url(completions_resource: Any) -> str:
    client = getattr(completions_resource, "_client", None)
    base_url = getattr(client, "base_url", None)
    return str(base_url) if base_url is not None else ""


def _chat_protocol_for_base_url(base_url: str) -> str:
    configured_protocol = _configured_chat_protocol_for_base_url(base_url)
    return resolve_chat_protocol(configured_protocol, base_url)


def _configured_chat_protocol_for_base_url(base_url: str) -> str:
    graphiti_base_url = os.environ.get("GRAPHITI_LLM_BASE_URL") or os.environ.get("LLM_BASE_URL")
    graphiti_protocol = os.environ.get("GRAPHITI_LLM_CHAT_PROTOCOL")
    if graphiti_protocol and _same_base_url(base_url, graphiti_base_url):
        return graphiti_protocol
    return os.environ.get("LLM_CHAT_PROTOCOL", "auto")


def _same_base_url(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return str(left).rstrip("/") == str(right).rstrip("/")


def _should_disable_thinking(model: Any, base_url: str) -> bool:
    setting = os.environ.get("LLM_DISABLE_THINKING", "disabled").lower()
    if setting in {"1", "true", "yes", "on", "disabled", "disable"}:
        return True
    if setting in {"0", "false", "no", "off", "enabled", "enable"}:
        return False
    if setting != "auto":
        return True
    return (
        "deepseek" in base_url.lower()
        and str(model).startswith("deepseek-v4")
    ) or _is_minimax_m3(model, base_url)


def _is_minimax_m3(model: Any, base_url: str) -> bool:
    normalized_model = str(model or "").lower().replace("_", "-")
    return "minimax" in base_url.lower() and normalized_model == "minimax-m3"


def _default_thinking_extra_body(
    model: Any,
    base_url: str,
    chat_protocol: str | None = None,
) -> Dict[str, Any] | None:
    setting = os.environ.get("LLM_DISABLE_THINKING", "disabled").lower()
    if setting in {"0", "false", "no", "off", "enabled", "enable"}:
        return None

    protocol = resolve_chat_protocol(chat_protocol, base_url) if chat_protocol else _chat_protocol_for_base_url(base_url)
    if protocol == "ollama":
        model_name = str(model or "").lower()
        if setting in {"1", "true", "yes", "on", "disabled", "disable"} or (
            setting == "auto" and "qwen3" in model_name
        ):
            return {"think": False}
        return None

    if _should_disable_thinking(model, base_url):
        return {"thinking": {"type": "disabled"}}
    return None


def _apply_provider_defaults(
    kwargs: Dict[str, Any],
    base_url: str,
    chat_protocol: str | None = None,
) -> None:
    if "extra_body" in kwargs:
        return

    extra_body = _default_thinking_extra_body(kwargs.get("model", ""), base_url, chat_protocol)
    if extra_body is not None:
        kwargs["extra_body"] = extra_body


def _apply_json_object_response_format_support(kwargs: Dict[str, Any]) -> None:
    if not strip_unsupported_json_object_response_format(kwargs):
        return

    messages = kwargs.get("messages")
    if _is_omitted(messages) or messages is None:
        return

    plain_messages = to_plain_data(messages)
    if isinstance(plain_messages, list):
        kwargs["messages"] = add_json_object_output_instruction(plain_messages)


def _format_completion_request(kwargs: Dict[str, Any], base_url: str = "") -> Dict[str, Any]:
    request = {
        key: value
        for key, value in kwargs.items()
        if not _is_omitted(value)
    }
    if base_url:
        request["base_url"] = base_url
    return _sanitize_for_logging(request)


def _prepare_openai_compatible_structured_request(kwargs: Dict[str, Any]) -> Dict[str, Any] | None:
    """Rewrite Graphiti schema prompts for providers that only get JSON object mode.

    Graphiti embeds the expected JSON Schema after "Respond with a JSON object in
    the following format". Some OpenAI-compatible providers echo that schema as
    the answer. Native Ollama avoids this by moving the schema into its `format`
    field; for `/v1` providers we cannot assume JSON Schema support, so replace
    the schema block with a concise result-only instruction and keep the schema
    locally for response repair.
    """
    response_format = to_plain_data(kwargs.get("response_format"))
    if not isinstance(response_format, dict):
        return None
    if response_format.get("type") != "json_object":
        return None

    messages = kwargs.get("messages")
    if _is_omitted(messages) or messages is None:
        return None

    plain_messages = to_plain_data(messages)
    if not isinstance(plain_messages, list):
        return None

    schema = extract_prompt_json_schema(plain_messages)
    if schema is None:
        return None

    rewrite_prompt_json_schema_messages(plain_messages, schema)
    kwargs["messages"] = plain_messages
    return normalize_structured_output_schema(schema)


def _repair_openai_compatible_structured_response(
    response: Any,
    *,
    request_messages: list[dict[str, Any]] | None,
    response_schema: Dict[str, Any] | None,
) -> Any:
    if response_schema is None:
        return response

    content = _get_first_response_message_content(response)
    if not isinstance(content, str):
        return response

    normalized_content = normalize_response_content(content)
    repaired_content = repair_structured_response_content(
        normalized_content,
        request_messages=request_messages,
        response_schema=response_schema,
    )
    if repaired_content != content:
        _set_first_response_message_content(response, repaired_content)
    return response


def _get_first_response_message_content(response: Any) -> str | None:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return None
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)
    return content if isinstance(content, str) else None


def _set_first_response_message_content(response: Any, content: str) -> None:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return
    message = getattr(choices[0], "message", None)
    if message is None:
        return
    try:
        message.content = content
        return
    except Exception:
        pass

    model_copy = getattr(message, "model_copy", None)
    if callable(model_copy):
        try:
            choices[0].message = model_copy(update={"content": content})
        except Exception:
            return


def _format_message(message: Any) -> Dict[str, Any]:
    details = {
        "role": getattr(message, "role", None),
        "content": getattr(message, "content", None),
    }

    for attr in ("reasoning_content", "tool_calls", "function_call", "refusal"):
        value = getattr(message, attr, None)
        if value is not None:
            details[attr] = value

    return _sanitize_for_logging(details)


def _format_completion_response(response: Any) -> Dict[str, Any]:
    if inspect.isgenerator(response) or hasattr(response, "__iter__") and response.__class__.__name__.lower().endswith("stream"):
        return {
            "stream": True,
            "response_type": response.__class__.__name__,
        }

    details = {
        "id": getattr(response, "id", None),
        "model": getattr(response, "model", None),
        "created": getattr(response, "created", None),
        "object": getattr(response, "object", None),
        "system_fingerprint": getattr(response, "system_fingerprint", None),
    }

    choices = []
    for choice in getattr(response, "choices", []) or []:
        choice_details = {
            "index": getattr(choice, "index", None),
            "finish_reason": getattr(choice, "finish_reason", None),
        }
        message = getattr(choice, "message", None)
        if message is not None:
            choice_details["message"] = _format_message(message)
        delta = getattr(choice, "delta", None)
        if delta is not None:
            choice_details["delta"] = _format_message(delta)
        choices.append(choice_details)
    details["choices"] = choices

    usage = getattr(response, "usage", None)
    if usage is not None:
        details["usage"] = usage

    return _sanitize_for_logging(details)


def _extract_usage_value(usage: Any, key: str) -> int | None:
    if usage is None:
        return None
    if isinstance(usage, dict):
        value = usage.get(key)
    else:
        value = getattr(usage, key, None)
    return int(value) if value is not None else None


def _extract_response_text(response_details: Dict[str, Any]) -> str | None:
    choices = response_details.get("choices") or []
    if not choices:
        return None
    first = choices[0] or {}
    message = first.get("message") or first.get("delta") or {}
    content = message.get("content")
    return content if isinstance(content, str) else None


def _build_llm_audit_payload(
    *,
    request_id: str,
    request_details: Dict[str, Any],
    provider: str = "openai-compatible",
    response_details: Dict[str, Any] | None = None,
    elapsed_ms: float | None = None,
    error: Exception | None = None,
) -> Dict[str, Any]:
    request_params = {
        key: value
        for key, value in request_details.items()
        if key not in {"messages", "model", "base_url"}
    }
    usage = (response_details or {}).get("usage")
    payload = {
        "request_id": request_id,
        "provider": provider,
        "base_url": request_details.get("base_url"),
        "model": request_details.get("model"),
        "operation": None,
        "messages": request_details.get("messages"),
        "request_params": request_params,
        "response": response_details,
        "response_text": _extract_response_text(response_details or {}),
        "status": "failed" if error else "succeeded",
        "error_message": str(error) if error else None,
        "error_traceback": traceback.format_exc() if error else None,
        "prompt_tokens": _extract_usage_value(usage, "prompt_tokens"),
        "completion_tokens": _extract_usage_value(usage, "completion_tokens"),
        "total_tokens": _extract_usage_value(usage, "total_tokens"),
        "latency_ms": int(elapsed_ms) if elapsed_ms is not None else None,
    }
    return _sanitize_for_logging(payload)


def _record_llm_audit(payload: Dict[str, Any]) -> None:
    try:
        from app.services.llm_audit import get_current_llm_context
        from app.services.task_workflow import TaskWorkflowService

        context = get_current_llm_context()
        operation = context.operation or payload.get("operation")
        TaskWorkflowService().record_llm_interaction(
            **{**payload, "operation": operation}
        )
    except Exception as exc:
        logger.warning("LLM 审计写入数据库失败: %s", exc)


def _log_completion_request(request_id: str, request_details: Dict[str, Any]) -> None:
    logger.info("LLM completions request [%s]:\n%s", request_id, _dumps(request_details))


def _log_completion_response(request_id: str, response_details: Dict[str, Any], elapsed_ms: float) -> None:
    logger.info(
        "LLM completions response [%s] (%.0fms):\n%s",
        request_id,
        elapsed_ms,
        _dumps(response_details),
    )


def _log_completion_error(request_id: str, error: Exception, elapsed_ms: float) -> None:
    logger.exception(
        "LLM completions error [%s] (%.0fms): %s",
        request_id,
        elapsed_ms,
        error,
    )


def create_logged_ollama_chat_completion(base_url: str, kwargs: Dict[str, Any]) -> Any:
    """Run an Ollama native chat request with the same logging/audit as SDK calls."""
    request_kwargs = dict(kwargs)
    _apply_provider_defaults(request_kwargs, base_url, chat_protocol="ollama")

    if not _is_logging_enabled():
        return create_ollama_chat_completion(base_url, request_kwargs)

    request_id = uuid.uuid4().hex[:12]
    start = time.perf_counter()
    request_details = _format_completion_request(request_kwargs, base_url)
    _log_completion_request(request_id, request_details)

    try:
        response = create_ollama_chat_completion(base_url, request_kwargs)
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        _log_completion_error(request_id, exc, elapsed_ms)
        _record_llm_audit(
            _build_llm_audit_payload(
                request_id=request_id,
                request_details=request_details,
                provider="ollama-native",
                elapsed_ms=elapsed_ms,
                error=exc,
            )
        )
        raise

    elapsed_ms = (time.perf_counter() - start) * 1000
    response_details = _format_completion_response(response)
    _log_completion_response(request_id, response_details, elapsed_ms)
    _record_llm_audit(
        _build_llm_audit_payload(
            request_id=request_id,
            request_details=request_details,
            provider="ollama-native",
            response_details=response_details,
            elapsed_ms=elapsed_ms,
        )
    )
    return response


def install_llm_completion_logging() -> None:
    """Install process-wide logging around OpenAI chat completions calls."""
    global _PATCHED, _ORIGINAL_SYNC_CREATE, _ORIGINAL_ASYNC_CREATE

    if _PATCHED or Completions is None:
        return

    _ORIGINAL_SYNC_CREATE = Completions.create
    _ORIGINAL_ASYNC_CREATE = AsyncCompletions.create if AsyncCompletions is not None else None

    def logged_sync_create(self, *args, **kwargs):
        base_url = _get_client_base_url(self)
        _apply_provider_defaults(kwargs, base_url)
        protocol = _chat_protocol_for_base_url(base_url)
        if protocol == "anthropic":
            raise NotImplementedError("LLM_CHAT_PROTOCOL=anthropic 暂未实现原生 Anthropic /v1/messages 适配器")
        response_schema = None
        if protocol == "openai":
            response_schema = _prepare_openai_compatible_structured_request(kwargs)
        _apply_json_object_response_format_support(kwargs)

        if not _is_logging_enabled():
            if protocol == "ollama":
                return create_ollama_chat_completion(base_url, kwargs)
            response = _ORIGINAL_SYNC_CREATE(self, *args, **kwargs)
            return _repair_openai_compatible_structured_response(
                response,
                request_messages=kwargs.get("messages"),
                response_schema=response_schema,
            )

        request_id = uuid.uuid4().hex[:12]
        start = time.perf_counter()
        request_details = _format_completion_request(kwargs, base_url)
        _log_completion_request(request_id, request_details)

        try:
            if protocol == "ollama":
                response = create_ollama_chat_completion(base_url, kwargs)
            else:
                response = _ORIGINAL_SYNC_CREATE(self, *args, **kwargs)
                response = _repair_openai_compatible_structured_response(
                    response,
                    request_messages=kwargs.get("messages"),
                    response_schema=response_schema,
                )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            _log_completion_error(request_id, exc, elapsed_ms)
            _record_llm_audit(
                _build_llm_audit_payload(
                    request_id=request_id,
                    request_details=request_details,
                    elapsed_ms=elapsed_ms,
                    error=exc,
                )
            )
            raise

        elapsed_ms = (time.perf_counter() - start) * 1000
        response_details = _format_completion_response(response)
        _log_completion_response(
            request_id,
            response_details,
            elapsed_ms,
        )
        _record_llm_audit(
            _build_llm_audit_payload(
                request_id=request_id,
                request_details=request_details,
                response_details=response_details,
                elapsed_ms=elapsed_ms,
            )
        )
        return response

    async def logged_async_create(self, *args, **kwargs):
        base_url = _get_client_base_url(self)
        _apply_provider_defaults(kwargs, base_url)
        protocol = _chat_protocol_for_base_url(base_url)
        if protocol == "anthropic":
            raise NotImplementedError("LLM_CHAT_PROTOCOL=anthropic 暂未实现原生 Anthropic /v1/messages 适配器")
        response_schema = None
        if protocol == "openai":
            response_schema = _prepare_openai_compatible_structured_request(kwargs)
        _apply_json_object_response_format_support(kwargs)

        if not _is_logging_enabled():
            if protocol == "ollama":
                return await asyncio.to_thread(create_ollama_chat_completion, base_url, kwargs)
            response = await _ORIGINAL_ASYNC_CREATE(self, *args, **kwargs)
            return _repair_openai_compatible_structured_response(
                response,
                request_messages=kwargs.get("messages"),
                response_schema=response_schema,
            )

        request_id = uuid.uuid4().hex[:12]
        start = time.perf_counter()
        request_details = _format_completion_request(kwargs, base_url)
        _log_completion_request(request_id, request_details)

        try:
            if protocol == "ollama":
                response = await asyncio.to_thread(create_ollama_chat_completion, base_url, kwargs)
            else:
                response = await _ORIGINAL_ASYNC_CREATE(self, *args, **kwargs)
                response = _repair_openai_compatible_structured_response(
                    response,
                    request_messages=kwargs.get("messages"),
                    response_schema=response_schema,
                )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            _log_completion_error(request_id, exc, elapsed_ms)
            _record_llm_audit(
                _build_llm_audit_payload(
                    request_id=request_id,
                    request_details=request_details,
                    elapsed_ms=elapsed_ms,
                    error=exc,
                )
            )
            raise

        elapsed_ms = (time.perf_counter() - start) * 1000
        response_details = _format_completion_response(response)
        _log_completion_response(
            request_id,
            response_details,
            elapsed_ms,
        )
        _record_llm_audit(
            _build_llm_audit_payload(
                request_id=request_id,
                request_details=request_details,
                response_details=response_details,
                elapsed_ms=elapsed_ms,
            )
        )
        return response

    Completions.create = logged_sync_create
    if AsyncCompletions is not None and _ORIGINAL_ASYNC_CREATE is not None:
        AsyncCompletions.create = logged_async_create

    _PATCHED = True
    logger.info("LLM completions request/response logging enabled")

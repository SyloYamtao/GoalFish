"""
LLM chat request/response protocol selection.
"""

from __future__ import annotations

from urllib.parse import urlparse

SUPPORTED_CHAT_PROTOCOLS = {"auto", "openai", "ollama", "anthropic"}
_PROTOCOL_ALIASES = {
    "openai-compatible": "openai",
    "openai_compatible": "openai",
    "ollama-native": "ollama",
    "ollama_native": "ollama",
    "authripic": "anthropic",
}
_OLLAMA_DUMMY_API_KEY = "ollama-local"


def normalize_chat_protocol(value: str | None) -> str:
    protocol = (value or "auto").strip().lower()
    return _PROTOCOL_ALIASES.get(protocol, protocol)


def resolve_chat_protocol(protocol: str | None, base_url: str | None) -> str:
    normalized = normalize_chat_protocol(protocol)
    if normalized != "auto":
        return normalized
    return "ollama" if looks_like_ollama_native_chat_url(base_url) else "openai"


def looks_like_ollama_native_chat_url(base_url: str | None) -> bool:
    if not base_url:
        return False

    parsed = urlparse(str(base_url))
    path = (parsed.path or "").rstrip("/")
    if path == "/api/chat":
        return True
    if path.startswith("/v1"):
        return False
    return parsed.port == 11434 and path in {"", "/api"}


def is_ollama_chat_protocol(protocol: str | None, base_url: str | None) -> bool:
    return resolve_chat_protocol(protocol, base_url) == "ollama"


def chat_protocol_requires_api_key(protocol: str | None, base_url: str | None) -> bool:
    return resolve_chat_protocol(protocol, base_url) != "ollama"


def llm_api_key_or_dummy(
    api_key: str | None,
    base_url: str | None,
    protocol: str | None = "auto",
) -> str | None:
    if api_key:
        return api_key
    if is_ollama_chat_protocol(protocol, base_url):
        return _OLLAMA_DUMMY_API_KEY
    return api_key


def unsupported_chat_protocol_error(protocol: str, config_name: str = "LLM_CHAT_PROTOCOL") -> str | None:
    if protocol not in SUPPORTED_CHAT_PROTOCOLS:
        return f"{config_name} 必须是 auto、openai、ollama 或 anthropic"
    if protocol == "anthropic":
        return f"{config_name}=anthropic 暂未实现原生 Anthropic /v1/messages 适配器"
    return None

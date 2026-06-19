"""
Graphiti embedder for Ollama's native /api/embed endpoint.
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable, Iterable
from typing import Any
from urllib.parse import urlparse

from graphiti_core.embedder.client import EmbedderClient, EmbedderConfig

from ..utils.logger import get_logger

PostJson = Callable[[str, dict[str, Any], int], Awaitable[dict[str, Any]]]
logger = get_logger(__name__)
_LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class OllamaEmbeddingRequestError(RuntimeError):
    """Raised when Ollama returns an HTTP error for an embedding request."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class OllamaEmbedderConfig(EmbedderConfig):
    embedding_model: str = "qwen3-embedding"
    embed_url: str = "http://127.0.0.1:11434/api/embed"
    timeout: int = 60
    max_concurrency: int = 1
    max_retries: int = 3
    retry_delay: float = 0.5


class OllamaEmbedder(EmbedderClient):
    """EmbedderClient implementation for Ollama native embedding API."""

    def __init__(
        self,
        config: OllamaEmbedderConfig | None = None,
        post_json: PostJson | None = None,
    ):
        self.config = config or OllamaEmbedderConfig()
        self._post_json = post_json or _post_json
        self._request_semaphore = asyncio.Semaphore(max(1, self.config.max_concurrency))

    async def create(
        self, input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]]
    ) -> list[float]:
        response = await self._embed(input_data)
        embeddings = _extract_embeddings(response)
        if not embeddings:
            raise ValueError("Ollama embedding response did not include embeddings")
        return _trim_embedding(embeddings[0], self.config.embedding_dim)

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        response = await self._embed(input_data_list)
        embeddings = _extract_embeddings(response)
        if len(embeddings) != len(input_data_list):
            raise ValueError(
                f"Ollama returned {len(embeddings)} embeddings for {len(input_data_list)} inputs"
            )
        return [_trim_embedding(embedding, self.config.embedding_dim) for embedding in embeddings]

    async def _embed(
        self, input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]]
    ) -> dict[str, Any]:
        payload = {
            "model": self.config.embedding_model,
            "input": _normalize_input(input_data),
        }
        async with self._request_semaphore:
            return await self._post_json_with_retries(payload)

    async def _post_json_with_retries(self, payload: dict[str, Any]) -> dict[str, Any]:
        max_attempts = max(1, self.config.max_retries)
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                logger.debug(
                    "Ollama embedding request: model=%s, url=%s, attempt=%s/%s, %s",
                    self.config.embedding_model,
                    self.config.embed_url,
                    attempt,
                    max_attempts,
                    _summarize_input(payload.get("input")),
                )
                if attempt > 1:
                    logger.warning(
                        "Ollama embedding request retry: model=%s, attempt=%s/%s, url=%s",
                        self.config.embedding_model,
                        attempt,
                        max_attempts,
                        self.config.embed_url,
                    )
                response = await self._post_json(self.config.embed_url, payload, self.config.timeout)
                logger.debug(
                    "Ollama embedding response: model=%s, attempt=%s/%s, %s",
                    self.config.embedding_model,
                    attempt,
                    max_attempts,
                    _summarize_embedding_response(response),
                )
                return response
            except Exception as exc:
                last_error = exc
                if attempt >= max_attempts or not _is_transient_ollama_error(exc):
                    raise
                await asyncio.sleep(self.config.retry_delay * (2 ** (attempt - 1)))

        if last_error:
            raise last_error
        raise RuntimeError("Ollama embedding request failed without an exception")


def _normalize_input(input_data: str | list[str] | Iterable[int] | Iterable[Iterable[int]]) -> Any:
    if isinstance(input_data, str):
        return input_data
    if isinstance(input_data, list):
        return input_data
    return list(input_data)


def _extract_embeddings(response: dict[str, Any]) -> list[list[float]]:
    embeddings = response.get("embeddings")
    if isinstance(embeddings, list):
        return [_as_float_list(embedding) for embedding in embeddings]

    embedding = response.get("embedding")
    if isinstance(embedding, list):
        return [_as_float_list(embedding)]

    raise ValueError("Ollama embedding response missing 'embeddings' or 'embedding'")


def _as_float_list(value: Any) -> list[float]:
    if not isinstance(value, list):
        raise ValueError("Ollama embedding item is not a list")
    return [float(item) for item in value]


def _trim_embedding(embedding: list[float], embedding_dim: int) -> list[float]:
    return embedding[:embedding_dim]


def _summarize_input(value: Any) -> str:
    if isinstance(value, str):
        return f"input_count=1, input_chars={len(value)}"
    if isinstance(value, list):
        char_count = sum(len(item) for item in value if isinstance(item, str))
        return f"input_count={len(value)}, input_chars={char_count}"
    return f"input_type={type(value).__name__}"


def _summarize_embedding_response(response: dict[str, Any]) -> str:
    try:
        embeddings = _extract_embeddings(response)
    except ValueError:
        return "embedding_count=0"
    dimensions = [len(embedding) for embedding in embeddings]
    return f"embedding_count={len(embeddings)}, dimensions={dimensions}"


async def _post_json(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    return await asyncio.to_thread(_post_json_sync, url, payload, timeout)


def _post_json_sync(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
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
        raise OllamaEmbeddingRequestError(
            _format_ollama_http_error(url, str(payload.get("model", "")), exc.code, error_body),
            status_code=exc.code,
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            "Ollama embedding 请求失败: 无法连接本地 Ollama。"
            f"url={url}, error={exc.reason}。请确认 Ollama 已启动，例如执行 `ollama serve`，"
            "并确认 GRAPHITI_OLLAMA_EMBED_URL 指向正确地址。"
        ) from exc

    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise ValueError("Ollama embedding response is not a JSON object")
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
        "本地 Ollama 地址建议使用 http://127.0.0.1:11434/api/embed，避免 localhost 被系统代理截走",
        f"如果模型未安装，执行：`ollama pull {model}`",
        "如果本地模型带 tag，请把 GRAPHITI_EMBEDDING_MODEL 设置为完整名称，例如 qwen3-embedding:0.6b",
    ]

    if code == 502:
        suggestions.insert(
            0,
            "502 通常表示 Ollama 服务、代理、模型加载或并发处理失败；请先把 GRAPHITI_OLLAMA_MAX_CONCURRENCY 设为 1 后再试",
        )

    return (
        "Ollama embedding 请求失败。"
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
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if error:
            return str(error)
    return body.strip()


def _is_transient_ollama_error(exc: Exception) -> bool:
    if isinstance(exc, OllamaEmbeddingRequestError):
        return exc.status_code in {408, 429, 500, 502, 503, 504}

    message = str(exc)
    transient_markers = (
        "HTTP 408",
        "HTTP 429",
        "HTTP 500",
        "HTTP 502",
        "HTTP 503",
        "HTTP 504",
    )
    return any(marker in message for marker in transient_markers)

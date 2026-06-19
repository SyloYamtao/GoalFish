import asyncio

import pytest

from app.services.graphiti_ollama_embedder import (
    OllamaEmbedder,
    OllamaEmbedderConfig,
    _format_ollama_http_error,
)
from app.services import graphiti_ollama_embedder as embedder_module


@pytest.mark.asyncio
async def test_ollama_embedder_parses_single_embedding_response():
    calls = []

    async def post_json(url, payload, timeout):
        calls.append((url, payload, timeout))
        return {"embeddings": [[0.1, 0.2, 0.3, 0.4]]}

    embedder = OllamaEmbedder(
        OllamaEmbedderConfig(
            embed_url="http://localhost:11434/api/embed",
            embedding_model="qwen3-embedding",
            embedding_dim=3,
        ),
        post_json=post_json,
    )

    result = await embedder.create("Why is the sky blue?")

    assert result == [0.1, 0.2, 0.3]
    assert calls == [
        (
            "http://localhost:11434/api/embed",
            {"model": "qwen3-embedding", "input": "Why is the sky blue?"},
            60,
        )
    ]


@pytest.mark.asyncio
async def test_ollama_embedder_parses_batch_embedding_response():
    async def post_json(url, payload, timeout):
        return {"embeddings": [[0.1, 0.2], [0.3, 0.4]]}

    embedder = OllamaEmbedder(
        OllamaEmbedderConfig(
            embed_url="http://localhost:11434/api/embed",
            embedding_model="qwen3-embedding",
            embedding_dim=2,
        ),
        post_json=post_json,
    )

    result = await embedder.create_batch(["first", "second"])

    assert result == [[0.1, 0.2], [0.3, 0.4]]


@pytest.mark.asyncio
async def test_ollama_embedder_uses_configured_model_verbatim():
    calls = []

    async def post_json(url, payload, timeout):
        calls.append((url, payload, timeout))
        return {"embeddings": [[0.1, 0.2]]}

    embedder = OllamaEmbedder(
        OllamaEmbedderConfig(
            embed_url="http://localhost:11434/api/embed",
            embedding_model="qwen3-embedding:0.6b",
            embedding_dim=2,
        ),
        post_json=post_json,
    )

    result = await embedder.create("hello")

    assert result == [0.1, 0.2]
    assert calls[0][1]["model"] == "qwen3-embedding:0.6b"


@pytest.mark.asyncio
async def test_ollama_embedder_retries_transient_gateway_failure():
    calls = []

    async def post_json(url, payload, timeout):
        calls.append(payload)
        if len(calls) == 1:
            raise RuntimeError("Ollama embedding 请求失败。error=HTTP 502")
        return {"embeddings": [[0.1, 0.2]]}

    embedder = OllamaEmbedder(
        OllamaEmbedderConfig(
            embed_url="http://localhost:11434/api/embed",
            embedding_model="qwen3-embedding:0.6b",
            embedding_dim=2,
            max_retries=2,
            retry_delay=0,
        ),
        post_json=post_json,
    )

    result = await embedder.create("hello")

    assert result == [0.1, 0.2]
    assert len(calls) == 2
    assert all(call["model"] == "qwen3-embedding:0.6b" for call in calls)


@pytest.mark.asyncio
async def test_ollama_embedder_serializes_concurrent_requests_by_default():
    active_requests = 0
    max_active_requests = 0

    async def post_json(url, payload, timeout):
        nonlocal active_requests, max_active_requests
        active_requests += 1
        max_active_requests = max(max_active_requests, active_requests)
        await asyncio.sleep(0.01)
        active_requests -= 1
        return {"embeddings": [[0.1, 0.2]]}

    embedder = OllamaEmbedder(
        OllamaEmbedderConfig(
            embed_url="http://localhost:11434/api/embed",
            embedding_model="qwen3-embedding:0.6b",
            embedding_dim=2,
        ),
        post_json=post_json,
    )

    results = await asyncio.gather(*(embedder.create(f"text {index}") for index in range(5)))

    assert results == [[0.1, 0.2]] * 5
    assert max_active_requests == 1


def test_format_ollama_http_error_explains_model_not_found():
    message = _format_ollama_http_error(
        url="http://localhost:11434/api/embed",
        model="qwen3-embedding",
        code=404,
        body='{"error":"model \\"qwen3-embedding\\" not found, try pulling it first"}',
    )

    assert "qwen3-embedding" in message
    assert "ollama pull qwen3-embedding" in message
    assert "GRAPHITI_EMBEDDING_MODEL" in message


def test_format_ollama_http_error_explains_bad_gateway():
    message = _format_ollama_http_error(
        url="http://localhost:11434/api/embed",
        model="qwen3-embedding:0.6b",
        code=502,
        body="",
    )

    assert "502" in message
    assert "ollama serve" in message
    assert "qwen3-embedding:0.6b" in message


def test_loopback_ollama_requests_bypass_system_proxy(monkeypatch):
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"embeddings":[[1.0,2.0]]}'

    def local_open(request, timeout):
        calls.append(("local", request.full_url, timeout))
        return FakeResponse()

    def proxy_urlopen(request, timeout):
        calls.append(("proxy", request.full_url, timeout))
        raise AssertionError("loopback Ollama requests must not use urllib proxy opener")

    monkeypatch.setattr(embedder_module._LOCAL_OPENER, "open", local_open)
    monkeypatch.setattr(embedder_module.urllib.request, "urlopen", proxy_urlopen)

    response = embedder_module._post_json_sync(
        "http://localhost:11434/api/embed",
        {"model": "qwen3-embedding:0.6b", "input": ["2026世界杯"]},
        60,
    )

    assert response == {"embeddings": [[1.0, 2.0]]}
    assert calls == [("local", "http://localhost:11434/api/embed", 60)]

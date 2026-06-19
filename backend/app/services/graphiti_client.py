"""
Graphiti 客户端与同步包装工具。
"""

from __future__ import annotations

import asyncio
import atexit
import threading
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, TypeVar

from graphiti_core import Graphiti
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient

from ..config import Config
from .graphiti_ollama_embedder import OllamaEmbedder, OllamaEmbedderConfig
from .graphiti_property_sanitizer import install_graphiti_neo4j_property_sanitizer


T = TypeVar("T")


class _GraphitiAsyncRunner:
    """Run Graphiti async work on a process-scoped event loop.

    Graphiti owns async httpx clients. Creating and closing those clients inside
    a short-lived ``asyncio.run`` loop can leave transport cleanup callbacks
    scheduled after the loop has already closed. Keeping one loop alive for the
    process avoids the noisy ``RuntimeError: Event loop is closed`` cleanup path
    without sharing Graphiti client instances across calls.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def run(self, awaitable: Awaitable[T]) -> T:
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(awaitable, loop)
        return future.result()

    def close(self) -> None:
        with self._lock:
            loop = self._loop
            thread = self._thread
            self._loop = None
            self._thread = None
        if loop and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if thread and thread.is_alive():
            thread.join(timeout=2)

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop and self._loop.is_running():
                return self._loop

            ready = threading.Event()
            loop = asyncio.new_event_loop()

            def _run_loop() -> None:
                asyncio.set_event_loop(loop)
                ready.set()
                loop.run_forever()
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()

            thread = threading.Thread(
                target=_run_loop,
                name="goalfish-graphiti-async-loop",
                daemon=True,
            )
            thread.start()
            ready.wait(timeout=5)
            self._loop = loop
            self._thread = thread
            return loop


_ASYNC_RUNNER = _GraphitiAsyncRunner()
atexit.register(_ASYNC_RUNNER.close)


def run_async(awaitable: Awaitable[T]) -> T:
    """在当前同步 Flask 代码中执行 Graphiti async 调用。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError("Graphiti 同步包装不能在已有事件循环中调用")
    return _ASYNC_RUNNER.run(awaitable)


def create_graphiti() -> Graphiti:
    install_graphiti_neo4j_property_sanitizer()

    llm_config = LLMConfig(
        api_key=Config.GRAPHITI_LLM_API_KEY,
        model=Config.GRAPHITI_LLM_MODEL,
        base_url=Config.GRAPHITI_LLM_BASE_URL,
        temperature=0,
    )

    return Graphiti(
        uri=Config.GRAPHITI_NEO4J_URI,
        user=Config.GRAPHITI_NEO4J_USER,
        password=Config.GRAPHITI_NEO4J_PASSWORD,
        llm_client=OpenAIGenericClient(config=llm_config),
        embedder=create_graphiti_embedder(),
        cross_encoder=OpenAIRerankerClient(config=llm_config),
    )


def create_graphiti_embedder():
    provider = (Config.GRAPHITI_EMBEDDING_PROVIDER or "openai").lower()
    if provider == "ollama":
        return OllamaEmbedder(
            OllamaEmbedderConfig(
                embed_url=Config.GRAPHITI_OLLAMA_EMBED_URL,
                embedding_model=Config.GRAPHITI_EMBEDDING_MODEL,
                embedding_dim=Config.GRAPHITI_EMBEDDING_DIM,
                max_concurrency=Config.GRAPHITI_OLLAMA_MAX_CONCURRENCY,
                max_retries=Config.GRAPHITI_OLLAMA_MAX_RETRIES,
                retry_delay=Config.GRAPHITI_OLLAMA_RETRY_DELAY,
            )
        )
    if provider == "openai":
        embedder_config = OpenAIEmbedderConfig(
            api_key=Config.GRAPHITI_EMBEDDING_API_KEY,
            base_url=Config.GRAPHITI_EMBEDDING_BASE_URL,
            embedding_model=Config.GRAPHITI_EMBEDDING_MODEL,
            embedding_dim=Config.GRAPHITI_EMBEDDING_DIM,
        )
        return OpenAIEmbedder(config=embedder_config)
    raise ValueError("GRAPHITI_EMBEDDING_PROVIDER 必须是 openai 或 ollama")


@asynccontextmanager
async def graphiti_session() -> AsyncIterator[Graphiti]:
    graphiti = create_graphiti()
    try:
        yield graphiti
    finally:
        await graphiti.close()


async def execute_graphiti(coro_factory):
    async with graphiti_session() as graphiti:
        return await coro_factory(graphiti)

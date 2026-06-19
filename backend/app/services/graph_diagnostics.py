"""
Graph backend diagnostics and user-facing error formatting.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Any

try:
    from neo4j.exceptions import AuthError, ServiceUnavailable
except Exception:  # pragma: no cover - depends on optional graph backend deps
    AuthError = None
    ServiceUnavailable = None

from ..config import Config


@dataclass(frozen=True)
class GraphBuildDiagnostics:
    summary: str
    detail: str
    traceback_text: str


def graph_backend_label() -> str:
    backend = (Config.GRAPH_BACKEND or "").lower()
    if backend == "graphiti":
        return "Graphiti"
    return backend or "unknown"


def creating_graph_message() -> str:
    return f"创建{graph_backend_label()}图谱..."


def waiting_graph_process_message() -> str:
    return "Graphiti 数据写入已完成，准备读取图谱..."


def graph_build_context(project_id: str | None = None, graph_id: str | None = None) -> dict[str, Any]:
    context: dict[str, Any] = {
        "backend": Config.GRAPH_BACKEND,
        "llm_base_url": Config.GRAPHITI_LLM_BASE_URL,
        "llm_model": Config.GRAPHITI_LLM_MODEL,
        "llm_chat_protocol": Config.GRAPHITI_LLM_CHAT_PROTOCOL,
    }

    if project_id:
        context["project_id"] = project_id
    if graph_id:
        context["graph_id"] = graph_id

    context.update(
        {
            "neo4j_uri": Config.GRAPHITI_NEO4J_URI,
            "neo4j_user": Config.GRAPHITI_NEO4J_USER,
            "neo4j_password_set": bool(Config.GRAPHITI_NEO4J_PASSWORD),
            "embedding_provider": Config.GRAPHITI_EMBEDDING_PROVIDER,
            "embedding_model": Config.GRAPHITI_EMBEDDING_MODEL,
            "embedding_dim": Config.GRAPHITI_EMBEDDING_DIM,
        }
    )
    if Config.GRAPHITI_EMBEDDING_PROVIDER == "ollama":
        context["ollama_embed_url"] = Config.GRAPHITI_OLLAMA_EMBED_URL
    else:
        context["embedding_base_url"] = Config.GRAPHITI_EMBEDDING_BASE_URL

    return context


def format_graph_exception(exc: Exception) -> GraphBuildDiagnostics:
    traceback_text = traceback.format_exc()
    raw_error = str(exc)

    if AuthError is not None and isinstance(exc, AuthError):
        summary = "Neo4j认证失败：用户名或密码不正确"
        detail = (
            f"{summary}。当前后端为 Graphiti，连接地址 {Config.GRAPHITI_NEO4J_URI}，"
            f"用户 {Config.GRAPHITI_NEO4J_USER}。请确认 .env 中的 GRAPHITI_NEO4J_PASSWORD "
            "与正在运行的 Neo4j 实例一致。若使用 docker compose 且复用了旧 neo4j_data 数据卷，"
            "修改 NEO4J_AUTH/GRAPHITI_NEO4J_PASSWORD 不会自动改掉旧数据库密码；请改回旧密码，"
            "或停止容器后删除 neo4j_data 数据卷再用新密码初始化。"
        )
        return GraphBuildDiagnostics(summary=summary, detail=detail, traceback_text=traceback_text)

    if ServiceUnavailable is not None and isinstance(exc, ServiceUnavailable):
        summary = "Neo4j连接失败：服务不可用或地址不可达"
        detail = (
            f"{summary}。当前连接地址 {Config.GRAPHITI_NEO4J_URI}。请确认 Neo4j 已启动，"
            "bolt 端口 7687 可访问，并且源码启动时使用 localhost，容器内启动时使用 neo4j 服务名。"
        )
        return GraphBuildDiagnostics(summary=summary, detail=detail, traceback_text=traceback_text)

    return GraphBuildDiagnostics(summary=raw_error, detail=raw_error, traceback_text=traceback_text)

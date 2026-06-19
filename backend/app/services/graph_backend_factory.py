"""Graphiti 图谱后端工厂。"""

from __future__ import annotations

from ..config import Config


def get_backend_name() -> str:
    backend = (Config.GRAPH_BACKEND or "graphiti").lower()
    if backend != "graphiti":
        raise ValueError("GRAPH_BACKEND 必须是 graphiti")
    return backend


def get_graph_builder():
    get_backend_name()
    from .graphiti_graph_builder import GraphitiGraphBuilderService

    return GraphitiGraphBuilderService()


def get_entity_reader():
    get_backend_name()
    from .graphiti_entity_reader import GraphitiEntityReader

    return GraphitiEntityReader()


def get_graph_tools():
    get_backend_name()
    from .graphiti_tools import GraphitiToolsService

    return GraphitiToolsService()


def get_graph_memory_manager():
    get_backend_name()
    from .graphiti_graph_memory_updater import GraphitiGraphMemoryManager

    return GraphitiGraphMemoryManager

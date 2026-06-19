"""
Graphiti 图谱元数据持久化。

Graphiti 使用 group_id 隔离图谱；本模块保存 group_id 对应的名称、
ontology 和转换辅助信息。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict

from ..config import Config
from ..db.models import GraphMetadataRecord, utc_now
from ..db.session import get_session, init_db


GRAPHITI_META_DIR = os.path.join(Config.UPLOAD_FOLDER, "graphiti")


def _ensure_dir() -> None:
    os.makedirs(GRAPHITI_META_DIR, exist_ok=True)


def _meta_path(graph_id: str) -> str:
    _ensure_dir()
    return os.path.join(GRAPHITI_META_DIR, f"{graph_id}.json")


def _ensure_db() -> None:
    if Config.TASK_WORKFLOW_AUTO_CREATE_TABLES:
        init_db()


def _parse_datetime(value: Any):
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def save_graph_metadata(graph_id: str, data: Dict[str, Any]) -> None:
    _ensure_db()
    existing = load_graph_metadata(graph_id)
    now = utc_now()
    merged = {
        **existing,
        **data,
        "graph_id": graph_id,
        "updated_at": now.isoformat(),
    }
    if "created_at" not in merged:
        merged["created_at"] = merged["updated_at"]

    with get_session() as session:
        record = session.get(GraphMetadataRecord, graph_id)
        if record is None:
            record = GraphMetadataRecord(
                graph_id=graph_id,
                name=merged.get("name"),
                backend=merged.get("backend") or "graphiti",
                graph_metadata=merged,
                created_at=_parse_datetime(merged.get("created_at")) or now,
                updated_at=now,
            )
            session.add(record)
        else:
            record.name = merged.get("name") or record.name
            record.backend = merged.get("backend") or record.backend or "graphiti"
            record.graph_metadata = merged
            record.updated_at = now


def load_graph_metadata(graph_id: str) -> Dict[str, Any]:
    _ensure_db()
    with get_session() as session:
        record = session.get(GraphMetadataRecord, graph_id)
        return dict(record.graph_metadata or {}) if record else {}


def delete_graph_metadata(graph_id: str) -> None:
    _ensure_db()
    with get_session() as session:
        record = session.get(GraphMetadataRecord, graph_id)
        if record is not None:
            session.delete(record)


def load_legacy_graph_metadata(graph_id: str) -> Dict[str, Any]:
    path = _meta_path(graph_id)
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

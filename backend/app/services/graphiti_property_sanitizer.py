"""
Neo4j property sanitizer for Graphiti entity writes.

Graphiti writes ``EntityNode.attributes`` directly into Neo4j node properties.
Some OpenAI-compatible models occasionally return schema-shaped objects instead
of primitive values, and Neo4j cannot store nested maps as properties.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date, datetime, time
from typing import Any

from ..utils.logger import get_logger
from .graphiti_ontology import GRAPHITI_RESERVED_FIELDS


logger = get_logger("goalfish.graphiti_property_sanitizer")

_MISSING = object()
_PATCH_MARKER = "_goalfish_neo4j_property_sanitizer"
_RESERVED_ATTRIBUTE_KEYS = GRAPHITI_RESERVED_FIELDS | {"labels"}


def sanitize_graphiti_entity_nodes_for_neo4j(entity_nodes: list[Any]) -> int:
    """Mutate Graphiti entity nodes so attributes are valid Neo4j properties."""
    changed_count = 0
    for node in entity_nodes or []:
        if sanitize_graphiti_entity_node_for_neo4j(node):
            changed_count += 1
    return changed_count


def sanitize_graphiti_entity_node_for_neo4j(node: Any) -> bool:
    changed = False

    raw_summary = getattr(node, "summary", None)
    clean_summary = _coerce_summary(raw_summary)
    if raw_summary != clean_summary:
        setattr(node, "summary", clean_summary)
        changed = True

    raw_attributes = getattr(node, "attributes", None)
    if not raw_attributes:
        return changed

    if not isinstance(raw_attributes, Mapping):
        setattr(node, "attributes", {})
        logger.debug(
            "Dropped non-mapping Graphiti node attributes: node=%s, attributes_type=%s",
            getattr(node, "name", ""),
            type(raw_attributes).__name__,
        )
        return True

    cleaned_attributes: dict[str, Any] = {}
    attribute_summary = _MISSING

    for raw_key, raw_value in raw_attributes.items():
        key = str(raw_key)
        clean_value = _coerce_neo4j_property_value(raw_value)

        if key == "summary":
            attribute_summary = clean_value
            changed = True
            continue

        if key in _RESERVED_ATTRIBUTE_KEYS:
            changed = True
            logger.debug(
                "Dropped reserved Graphiti node attribute before Neo4j write: node=%s, key=%s",
                getattr(node, "name", ""),
                key,
            )
            continue

        if clean_value is _MISSING:
            changed = True
            logger.debug(
                "Dropped unsupported Graphiti node attribute before Neo4j write: node=%s, key=%s",
                getattr(node, "name", ""),
                key,
            )
            continue

        cleaned_attributes[key] = clean_value
        if key != raw_key or not _values_equal(clean_value, raw_value):
            changed = True

    if attribute_summary is not _MISSING and not getattr(node, "summary", ""):
        setattr(node, "summary", _coerce_summary(attribute_summary))
        changed = True

    if not _values_equal(cleaned_attributes, raw_attributes):
        setattr(node, "attributes", cleaned_attributes)
        changed = True

    return changed


def install_graphiti_neo4j_property_sanitizer() -> None:
    """Patch Graphiti's bulk writer so entity attributes are sanitized first."""
    import graphiti_core.graphiti as graphiti_module
    import graphiti_core.utils.bulk_utils as bulk_utils

    current = graphiti_module.add_nodes_and_edges_bulk
    if getattr(current, _PATCH_MARKER, False):
        return

    original = current

    async def sanitized_add_nodes_and_edges_bulk(
        driver,
        episodic_nodes,
        episodic_edges,
        entity_nodes,
        entity_edges,
        embedder,
    ):
        changed_count = sanitize_graphiti_entity_nodes_for_neo4j(entity_nodes)
        if changed_count:
            logger.debug(
                "Sanitized Graphiti entity node attributes before Neo4j bulk write: count=%s",
                changed_count,
            )
        return await original(
            driver,
            episodic_nodes,
            episodic_edges,
            entity_nodes,
            entity_edges,
            embedder,
        )

    setattr(sanitized_add_nodes_and_edges_bulk, _PATCH_MARKER, True)
    setattr(sanitized_add_nodes_and_edges_bulk, "_goalfish_original", original)

    graphiti_module.add_nodes_and_edges_bulk = sanitized_add_nodes_and_edges_bulk
    if bulk_utils.add_nodes_and_edges_bulk is original:
        bulk_utils.add_nodes_and_edges_bulk = sanitized_add_nodes_and_edges_bulk


def _coerce_summary(value: Any) -> str:
    clean_value = _coerce_neo4j_property_value(value)
    if clean_value is _MISSING:
        return ""
    if isinstance(clean_value, str):
        return clean_value
    if isinstance(clean_value, list):
        return _json_dumps(clean_value)
    return str(clean_value)


def _coerce_neo4j_property_value(value: Any) -> Any:
    if value is None:
        return _MISSING

    if isinstance(value, (str, bool, int, float)):
        return value

    if isinstance(value, (datetime, date, time)):
        return value.isoformat()

    if isinstance(value, Mapping):
        if "value" in value:
            return _coerce_neo4j_property_value(value.get("value"))
        if _is_schema_like_mapping(value):
            return _MISSING
        return _json_dumps(value)

    if isinstance(value, (list, tuple, set)):
        clean_items = []
        iterable = sorted(value, key=str) if isinstance(value, set) else value
        for item in iterable:
            clean_item = _coerce_neo4j_property_value(item)
            if clean_item is _MISSING:
                continue
            if isinstance(clean_item, list):
                clean_item = _json_dumps(clean_item)
            clean_items.append(clean_item)
        return _normalize_neo4j_list(clean_items)

    return str(value)


def _is_schema_like_mapping(value: Mapping[str, Any]) -> bool:
    keys = {str(key) for key in value.keys()}
    if "properties" in keys or "required" in keys or "anyOf" in keys:
        return True
    return {"description", "title", "type"}.issubset(keys)


def _normalize_neo4j_list(items: list[Any]) -> list[Any]:
    if len(items) <= 1:
        return items

    buckets = {_list_item_bucket(item) for item in items}
    if len(buckets) <= 1:
        return items
    return [str(item) for item in items]


def _list_item_bucket(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    return type(value).__name__


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except TypeError:
        return str(value)


def _values_equal(left: Any, right: Any) -> bool:
    try:
        return left == right
    except Exception:
        return False

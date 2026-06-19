"""
Graphiti ontology 转换工具。

这里专门为 Graphiti 的 Pydantic entity_types 参数生成类型。
"""

from __future__ import annotations

import re
from typing import Any, Dict

from pydantic import BaseModel, Field, create_model


GRAPHITI_RESERVED_FIELDS = {
    "uuid",
    "name",
    "group_id",
    "labels",
    "summary",
    "created_at",
    "attributes",
    "name_embedding",
}


def to_pascal_case(name: str) -> str:
    parts = re.split(r"[^a-zA-Z0-9]+", name or "")
    words: list[str] = []
    for part in parts:
        words.extend(re.sub(r"([a-z])([A-Z])", r"\1_\2", part).split("_"))
    result = "".join(word.capitalize() for word in words if word)
    return result or "Unknown"


def edge_name_to_class_name(name: str) -> str:
    return to_pascal_case(name.lower())


def safe_graphiti_attr_name(attr_name: str) -> str:
    normalized = (attr_name or "attribute").strip() or "attribute"
    normalized = re.sub(r"[^\w]+", "_", normalized, flags=re.UNICODE)
    normalized = re.sub(r"_{2,}", "_", normalized).strip("_").lower()
    if not normalized:
        normalized = "attribute"
    if normalized[0].isdigit():
        normalized = f"field_{normalized}"
    if normalized in GRAPHITI_RESERVED_FIELDS:
        normalized = f"entity_{normalized}"
    return normalized


def build_graphiti_entity_types(ontology: Dict[str, Any]) -> dict[str, type[BaseModel]]:
    entity_types: dict[str, type[BaseModel]] = {}

    for entity_def in ontology.get("entity_types", []) or []:
        raw_name = entity_def.get("name", "Entity")
        type_name = to_pascal_case(raw_name)
        field_definitions: dict[str, Any] = {}

        for attr_def in entity_def.get("attributes", []) or []:
            raw_attr_name = attr_def.get("name", "attribute")
            attr_name = safe_graphiti_attr_name(raw_attr_name)
            description = attr_def.get("description") or attr_name
            field_definitions[attr_name] = (
                str | None,
                Field(default=None, description=description),
            )

        if not field_definitions:
            field_definitions["description"] = (
                str | None,
                Field(default=None, description=entity_def.get("description") or type_name),
            )

        entity_types[type_name] = create_model(
            type_name,
            __base__=BaseModel,
            **field_definitions,
        )

    return entity_types


def build_graphiti_edge_type_map(ontology: Dict[str, Any]) -> dict[tuple[str, str], list[str]]:
    edge_type_map: dict[tuple[str, str], list[str]] = {}

    for edge_def in ontology.get("edge_types", []) or []:
        edge_class_name = edge_name_to_class_name(edge_def.get("name", "Relationship"))
        for source_target in edge_def.get("source_targets", []) or []:
            source = to_pascal_case(source_target.get("source", "Entity"))
            target = to_pascal_case(source_target.get("target", "Entity"))
            edge_type_map.setdefault((source, target), []).append(edge_class_name)

    return edge_type_map

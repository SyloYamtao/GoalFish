"""
Provider-neutral structured-output helpers for Graphiti LLM calls.
"""

from __future__ import annotations

import json
import re
import ast
from typing import Any

JSON_SCHEMA_PROMPT_MARKERS = (
    "Respond with a JSON object in the following format:",
)
_JSON_SCHEMA_METADATA_KEYS = {
    "$defs",
    "$schema",
    "definitions",
    "description",
    "default",
    "examples",
    "title",
}
_STRUCTURED_FIELD_ALIASES = {
    "id": ("entity_id", "entityId", "idx", "index"),
    "name": ("entity_name", "entityName", "entity", "label"),
    "duplicate_idx": ("duplicate_id", "duplicate_index", "duplicateIdx"),
    "relation_type": ("relation", "relationship", "relationship_type", "predicate", "edge_type"),
    "source_entity_name": (
        "source",
        "source_entity",
        "source_name",
        "sourceEntityName",
        "subject",
        "subject_entity_name",
    ),
    "target_entity_name": (
        "target",
        "target_entity",
        "target_name",
        "targetEntityName",
        "object",
        "object_entity_name",
    ),
    "fact": ("fact_text", "factText", "statement", "description", "text"),
    "valid_at": ("validAt", "valid_from", "start_time", "start_date"),
    "invalid_at": ("invalidAt", "valid_until", "end_time", "end_date"),
}


def to_plain_data(value: Any) -> Any:
    if _is_omitted(value):
        return None
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): to_plain_data(v) for k, v in value.items() if not _is_omitted(v)}
    if isinstance(value, (list, tuple, set)):
        return [to_plain_data(item) for item in value if not _is_omitted(item)]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return to_plain_data(model_dump(exclude_none=True))
    return value


def extract_prompt_json_schema(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(messages):
        content = message.get("content")
        if not isinstance(content, str):
            continue

        schema = _extract_prompt_json_schema_from_text(content)
        if schema is not None:
            return schema
    return None


def rewrite_prompt_json_schema_messages(
    messages: list[dict[str, Any]],
    schema: dict[str, Any],
) -> None:
    replacement = _build_result_json_instruction(schema)
    for message in reversed(messages):
        content = message.get("content")
        if not isinstance(content, str):
            continue

        rewritten = _replace_prompt_json_schema_block(content, replacement)
        if rewritten != content:
            message["content"] = rewritten
            return


def normalize_structured_output_schema(schema: dict[str, Any]) -> dict[str, Any]:
    plain_schema = to_plain_data(schema)
    if not isinstance(plain_schema, dict):
        return schema

    definitions: dict[str, Any] = {}
    for key in ("$defs", "definitions"):
        raw_definitions = plain_schema.get(key)
        if isinstance(raw_definitions, dict):
            definitions.update(raw_definitions)

    normalized = _normalize_schema_node(plain_schema, definitions, set())
    return normalized if isinstance(normalized, dict) else plain_schema


def normalize_ollama_format_schema(schema: dict[str, Any]) -> dict[str, Any]:
    return normalize_structured_output_schema(schema)


def normalize_response_content(content: str) -> str:
    return _strip_json_markdown_fence(_strip_think_tags(content))


def repair_structured_response_content(
    content: str,
    *,
    request_messages: list[dict[str, Any]] | None,
    response_schema: dict[str, Any] | str | None,
) -> str:
    if not isinstance(response_schema, dict):
        return content

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return _compact_json(_minimal_response_for_schema(response_schema))

    if not isinstance(parsed, dict):
        return content

    if _looks_like_json_schema(parsed):
        return _compact_json(_minimal_response_for_schema(response_schema))

    if _has_empty_entities_block(request_messages):
        if _schema_has_top_level_key(response_schema, "entity_resolutions"):
            return _compact_json({"entity_resolutions": []})
        if _schema_has_top_level_key(response_schema, "edges"):
            return _compact_json({"edges": []})

    parsed, edge_duplicate_changed = _normalize_edge_duplicate_ids_for_prompt(
        parsed,
        request_messages,
        response_schema,
    )
    normalized, changed = _normalize_response_to_schema(parsed, response_schema)
    normalized, id_filter_changed = _filter_entity_resolutions_for_prompt(
        normalized,
        request_messages,
        response_schema,
    )
    if changed or id_filter_changed or edge_duplicate_changed:
        return _compact_json(normalized)

    return content


def _replace_prompt_json_schema_block(text: str, replacement: str) -> str:
    lower_text = text.lower()
    marker_offsets = [
        lower_text.rfind(marker.lower())
        for marker in JSON_SCHEMA_PROMPT_MARKERS
        if lower_text.rfind(marker.lower()) >= 0
    ]
    if not marker_offsets:
        return text

    marker_offset = max(marker_offsets)
    return f"{text[:marker_offset].rstrip()}\n\n{replacement}"


def _build_result_json_instruction(schema: dict[str, Any]) -> str:
    fields = _top_level_field_lines(schema)
    if fields:
        field_text = " with these fields:\n" + "\n".join(fields)
    else:
        keys = _top_level_schema_keys(schema)
        field_text = f" containing top-level key(s): {', '.join(keys)}" if keys else ""
    return (
        f"Respond with only the result JSON object{field_text}. "
        "Use null for unknown nullable fields and [] for empty arrays. "
        "Do not return the JSON Schema, markdown fences, or explanatory text."
    )


def _top_level_field_lines(schema: dict[str, Any]) -> list[str]:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return []

    lines: list[str] = []
    for key in _top_level_schema_keys(schema):
        property_schema = properties.get(key)
        if not isinstance(property_schema, dict):
            lines.append(f"- {key}")
            continue
        detail = _schema_description(property_schema) or _schema_type_hint(property_schema)
        lines.append(f"- {key}: {detail}" if detail else f"- {key}")
    return lines


def _schema_description(schema: dict[str, Any]) -> str:
    description = schema.get("description")
    return str(description).strip() if description else ""


def _schema_type_hint(schema: dict[str, Any]) -> str:
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        schema_type = " or ".join(str(item) for item in schema_type)
    if isinstance(schema_type, str):
        return schema_type
    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        types = [
            str(item.get("type"))
            for item in any_of
            if isinstance(item, dict) and item.get("type")
        ]
        return " or ".join(types)
    return ""


def _top_level_schema_keys(schema: dict[str, Any]) -> list[str]:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return []

    required = schema.get("required")
    keys: list[str] = []
    if isinstance(required, list):
        keys.extend(str(key) for key in required if str(key) in properties)
    keys.extend(str(key) for key in properties if str(key) not in keys)
    return keys


def _extract_prompt_json_schema_from_text(text: str) -> dict[str, Any] | None:
    lower_text = text.lower()
    schema_starts = []
    for marker in JSON_SCHEMA_PROMPT_MARKERS:
        marker_offset = lower_text.rfind(marker.lower())
        if marker_offset >= 0:
            schema_starts.append(marker_offset + len(marker))

    for schema_start in sorted(schema_starts, reverse=True):
        schema = _extract_first_json_schema(text[schema_start:])
        if schema is not None:
            return schema
    return None


def _extract_first_json_schema(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            parsed, _ = decoder.raw_decode(text[match.start():])
        except json.JSONDecodeError:
            continue

        if _looks_like_json_schema(parsed):
            return parsed
    return None


def _looks_like_json_schema(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("type") == "object"
        and isinstance(value.get("properties"), dict)
    )


def _normalize_schema_node(
    value: Any,
    definitions: dict[str, Any],
    seen_refs: set[str],
) -> Any:
    if isinstance(value, list):
        return [_normalize_schema_node(item, definitions, seen_refs) for item in value]
    if not isinstance(value, dict):
        return value

    ref = value.get("$ref")
    if isinstance(ref, str):
        resolved = _resolve_local_schema_ref(ref, definitions)
        if resolved is not None and ref not in seen_refs:
            return _normalize_schema_node(resolved, definitions, {*seen_refs, ref})

    normalized: dict[str, Any] = {}
    for key, item in value.items():
        if key in _JSON_SCHEMA_METADATA_KEYS or key == "$ref":
            continue
        if key == "properties" and isinstance(item, dict):
            normalized[key] = {
                str(property_name): _normalize_schema_node(property_schema, definitions, seen_refs)
                for property_name, property_schema in item.items()
            }
        else:
            normalized[key] = _normalize_schema_node(item, definitions, seen_refs)

    if normalized.get("type") == "object" and isinstance(normalized.get("properties"), dict):
        normalized.setdefault("additionalProperties", False)

    return normalized


def _resolve_local_schema_ref(ref: str, definitions: dict[str, Any]) -> Any | None:
    if not ref.startswith("#/"):
        return None

    parts = [_decode_json_pointer_part(part) for part in ref[2:].split("/")]
    if not parts or parts[0] not in {"$defs", "definitions"}:
        return None

    current: Any = definitions
    for part in parts[1:]:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _decode_json_pointer_part(part: str) -> str:
    return part.replace("~1", "/").replace("~0", "~")


def _strip_think_tags(content: str) -> str:
    return re.sub(r"<think>[\s\S]*?</think>", "", content).strip()


def _strip_json_markdown_fence(content: str) -> str:
    match = re.match(r"^\s*```(?:json)?\s*(?P<body>[\s\S]*?)\s*```\s*$", content, re.IGNORECASE)
    if not match:
        return content.strip()
    return match.group("body").strip()


def _minimal_response_for_schema(schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return {}

    keys = _top_level_schema_keys(schema)
    return {
        key: _minimal_json_value(properties.get(key))
        for key in keys
        if key in properties
    }


def _minimal_json_value(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return None

    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        schema_type = next((item for item in schema_type if item != "null"), None)

    if schema_type == "array":
        return []
    if schema_type == "object":
        return {}
    if schema_type == "string":
        return ""
    if schema_type in {"integer", "number"}:
        return 0
    if schema_type == "boolean":
        return False
    return None


def _normalize_response_to_schema(value: Any, schema: Any) -> tuple[Any, bool]:
    if not isinstance(schema, dict):
        return value, False

    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        schema_type = next((item for item in schema_type if item != "null"), None)

    if schema_type == "object" and isinstance(value, dict):
        return _normalize_object_to_schema(value, schema)

    if schema_type == "array" and isinstance(value, list):
        item_schema = schema.get("items")
        normalized_items = []
        changed = False
        for item in value:
            normalized_item, item_changed = _normalize_response_to_schema(item, item_schema)
            if _schema_required_keys_present(normalized_item, item_schema):
                normalized_items.append(normalized_item)
            else:
                changed = True
            changed = changed or item_changed
        return normalized_items, changed

    normalized_scalar, scalar_changed = _normalize_scalar_to_schema_type(value, schema_type)
    if scalar_changed:
        return normalized_scalar, True

    return value, False


def _normalize_scalar_to_schema_type(value: Any, schema_type: Any) -> tuple[Any, bool]:
    if schema_type == "integer":
        coerced = _coerce_integer(value)
        if coerced is not None and coerced != value:
            return coerced, True
    if schema_type == "number":
        coerced = _coerce_number(value)
        if coerced is not None and coerced != value:
            return coerced, True
    if schema_type == "boolean" and isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "false"}:
            return normalized == "true", True
    return value, False


def _coerce_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
        return int(value.strip())
    return None


def _coerce_number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if re.fullmatch(r"[+-]?\d+", normalized):
        return int(normalized)
    if re.fullmatch(r"[+-]?(?:\d+\.\d*|\d*\.\d+)(?:[eE][+-]?\d+)?", normalized):
        return float(normalized)
    return None


def _normalize_object_to_schema(
    value: dict[str, Any],
    schema: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return value, False

    normalized: dict[str, Any] = {}
    changed = False
    for property_name, property_schema in properties.items():
        property_name = str(property_name)
        if property_name in value:
            raw_value = value[property_name]
            source_key = property_name
        else:
            alias = _find_present_alias(value, property_name)
            if alias is None:
                continue
            raw_value = value[alias]
            source_key = alias
            changed = True

        normalized_value, value_changed = _normalize_response_to_schema(raw_value, property_schema)
        property_value = _normalize_scalar_for_property(property_name, normalized_value)
        normalized[property_name] = property_value
        changed = changed or value_changed or source_key != property_name or property_value != normalized_value

    if schema.get("additionalProperties") is False:
        changed = changed or any(key not in properties for key in value)
        return normalized, changed

    extras = {key: item for key, item in value.items() if key not in normalized}
    return {**normalized, **extras}, changed


def _find_present_alias(value: dict[str, Any], property_name: str) -> str | None:
    aliases = _STRUCTURED_FIELD_ALIASES.get(property_name, ())
    for alias in aliases:
        if alias in value:
            return alias

    lower_to_key = {str(key).lower(): key for key in value}
    for alias in aliases:
        key = lower_to_key.get(str(alias).lower())
        if key is not None:
            return key
    return None


def _normalize_scalar_for_property(property_name: str, value: Any) -> Any:
    if property_name == "duplicate_fact_id":
        return _as_int(value) if _as_int(value) is not None else -1
    if property_name == "contradicted_facts" and isinstance(value, list):
        return [item_id for item in value if (item_id := _as_int(item)) is not None]
    if property_name == "relation_type" and isinstance(value, str):
        normalized = re.sub(r"[^0-9A-Za-z]+", "_", value).strip("_").upper()
        return normalized or value
    return value


def _normalize_edge_duplicate_ids_for_prompt(
    value: dict[str, Any],
    messages: list[dict[str, Any]] | None,
    schema: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    if not (
        _schema_has_top_level_key(schema, "duplicate_fact_id")
        and _schema_has_top_level_key(schema, "contradicted_facts")
    ):
        return value, False
    if "duplicate_fact_id" not in value and "contradicted_facts" not in value:
        return value, False

    related_fact_id_to_index = _extract_fact_id_index_from_messages(messages, "EXISTING FACTS")
    invalidation_ids = _extract_fact_ids_from_messages(messages, "FACT INVALIDATION CANDIDATES")
    updated = dict(value)
    changed = False

    if "duplicate_fact_id" in updated:
        raw_duplicate_id = updated["duplicate_fact_id"]
        duplicate_index = None
        if related_fact_id_to_index:
            duplicate_index = related_fact_id_to_index.get(str(raw_duplicate_id))
        if duplicate_index is None:
            duplicate_index = _as_int(raw_duplicate_id)
        if duplicate_index is None:
            duplicate_index = -1
        if duplicate_index != raw_duplicate_id:
            updated["duplicate_fact_id"] = duplicate_index
            changed = True

    if "contradicted_facts" in updated and isinstance(updated["contradicted_facts"], list):
        invalidation_id_to_index = _extract_fact_id_index_from_messages(
            messages,
            "FACT INVALIDATION CANDIDATES",
        )
        normalized_contradictions: list[int] = []
        for item in updated["contradicted_facts"]:
            item_id = None
            if invalidation_id_to_index:
                item_id = invalidation_id_to_index.get(str(item))
            if item_id is None:
                item_id = _as_int(item)
            if item_id is None:
                continue
            if invalidation_ids is not None and item_id not in invalidation_ids:
                continue
            normalized_contradictions.append(item_id)
        if normalized_contradictions != updated["contradicted_facts"]:
            updated["contradicted_facts"] = normalized_contradictions
            changed = True

    return updated, changed


def _schema_required_keys_present(value: Any, schema: Any) -> bool:
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return True
    if not isinstance(value, dict):
        return False

    required = schema.get("required")
    if not isinstance(required, list):
        return True
    return all(str(key) in value for key in required)


def _filter_entity_resolutions_for_prompt(
    value: Any,
    messages: list[dict[str, Any]] | None,
    schema: dict[str, Any],
) -> tuple[Any, bool]:
    if not _schema_has_top_level_key(schema, "entity_resolutions"):
        return value, False
    if not isinstance(value, dict):
        return value, False

    allowed_ids = _extract_entity_ids_from_messages(messages)
    if allowed_ids is None:
        return value, False

    resolutions = value.get("entity_resolutions")
    if not isinstance(resolutions, list):
        return value, False

    filtered: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    changed = False
    for resolution in resolutions:
        if not isinstance(resolution, dict):
            changed = True
            continue

        resolution_id = _as_int(resolution.get("id"))
        if resolution_id is None or resolution_id not in allowed_ids or resolution_id in seen_ids:
            changed = True
            continue

        normalized_resolution = dict(resolution)
        if normalized_resolution.get("id") != resolution_id:
            normalized_resolution["id"] = resolution_id
            changed = True

        filtered.append(normalized_resolution)
        seen_ids.add(resolution_id)

    if not changed and len(filtered) == len(resolutions):
        return value, False

    updated = dict(value)
    updated["entity_resolutions"] = filtered
    return updated, True


def _extract_entity_ids_from_messages(messages: list[dict[str, Any]] | None) -> set[int] | None:
    if not messages:
        return None

    for message in reversed(messages):
        content = message.get("content")
        if not isinstance(content, str):
            continue

        for body in _iter_entities_block_bodies(content):
            stripped = body.strip()
            if re.match(r"^\[\s*\](?:\s*#.*)?$", stripped, re.DOTALL):
                return set()

            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                continue

            if not isinstance(parsed, list):
                continue

            ids: set[int] = set()
            for entity in parsed:
                if not isinstance(entity, dict):
                    continue
                entity_id = _as_int(entity.get("id"))
                if entity_id is not None:
                    ids.add(entity_id)
            return ids
    return None


def _extract_fact_id_index_from_messages(
    messages: list[dict[str, Any]] | None,
    tag_name: str,
) -> dict[str, int] | None:
    facts = _extract_fact_list_from_messages(messages, tag_name)
    if facts is None:
        return None

    id_to_index: dict[str, int] = {}
    for index, fact in enumerate(facts):
        if not isinstance(fact, dict) or "id" not in fact:
            continue
        fact_id = fact.get("id")
        if fact_id is not None:
            id_to_index[str(fact_id)] = index
    return id_to_index


def _extract_fact_ids_from_messages(
    messages: list[dict[str, Any]] | None,
    tag_name: str,
) -> set[int] | None:
    facts = _extract_fact_list_from_messages(messages, tag_name)
    if facts is None:
        return None
    return set(range(len(facts)))


def _extract_fact_list_from_messages(
    messages: list[dict[str, Any]] | None,
    tag_name: str,
) -> list[Any] | None:
    if not messages:
        return None

    for message in reversed(messages):
        content = message.get("content")
        if not isinstance(content, str):
            continue

        for body in _iter_tag_block_bodies(content, tag_name):
            parsed = _parse_list_literal(body.strip())
            if parsed is not None:
                return parsed
    return None


def _parse_list_literal(value: str) -> list[Any] | None:
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return None
    return parsed if isinstance(parsed, list) else None


def _has_empty_entities_block(messages: list[dict[str, Any]] | None) -> bool:
    if not messages:
        return False

    for message in reversed(messages):
        content = message.get("content")
        if not isinstance(content, str):
            continue

        for body in _iter_entities_block_bodies(content):
            body = body.strip()
            if re.match(r"^\[\s*\](?:\s*#.*)?$", body, re.DOTALL):
                return True
    return False


def _iter_entities_block_bodies(content: str):
    for match in re.finditer(r"<ENTITIES>(?P<body>[\s\S]*?)</ENTITIES>", content, re.IGNORECASE):
        yield match.group("body")


def _iter_tag_block_bodies(content: str, tag_name: str):
    escaped_tag = re.escape(tag_name)
    pattern = rf"<{escaped_tag}>(?P<body>[\s\S]*?)</{escaped_tag}>"
    for match in re.finditer(pattern, content, re.IGNORECASE):
        yield match.group("body")


def _schema_has_top_level_key(schema: dict[str, Any], key: str) -> bool:
    properties = schema.get("properties")
    return isinstance(properties, dict) and key in properties


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_omitted(value: Any) -> bool:
    if value is None:
        return False
    return value.__class__.__name__ in {"NotGiven", "Omit"}

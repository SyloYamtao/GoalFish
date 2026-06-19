import json

from app.utils.llm_logging import (
    _build_llm_audit_payload,
    _format_completion_request,
    _format_completion_response,
    _prepare_openai_compatible_structured_request,
    _repair_openai_compatible_structured_response,
    _sanitize_for_logging,
)


def test_sanitize_redacts_secret_fields():
    payload = {
        "api_key": "placeholder-key",
        "Authorization": "Token placeholder",
        "messages": [{"role": "user", "content": "hello"}],
        "extra_headers": {"X-API-Key": "placeholder"},
    }

    sanitized = _sanitize_for_logging(payload)

    assert sanitized["api_key"] == "<redacted>"
    assert sanitized["Authorization"] == "<redacted>"
    assert sanitized["extra_headers"]["X-API-Key"] == "<redacted>"
    assert sanitized["messages"][0]["content"] == "hello"


def test_format_completion_request_keeps_prompt_details():
    details = _format_completion_request(
        {
            "model": "test-model",
            "messages": [{"role": "user", "content": "full prompt"}],
            "temperature": 0.3,
        }
    )

    serialized = json.dumps(details, ensure_ascii=False)
    assert "test-model" in serialized
    assert "full prompt" in serialized
    assert "temperature" in serialized


def test_format_completion_response_extracts_choices_and_usage():
    class Message:
        content = '{"ok": true}'
        reasoning_content = "hidden reasoning"
        tool_calls = None

    class Choice:
        index = 0
        finish_reason = "stop"
        message = Message()

    class Usage:
        prompt_tokens = 3
        completion_tokens = 5
        total_tokens = 8

    class Response:
        id = "chatcmpl-test"
        model = "test-model"
        created = 123
        choices = [Choice()]
        usage = Usage()

    details = _format_completion_response(Response())

    assert details["id"] == "chatcmpl-test"
    assert details["choices"][0]["message"]["content"] == '{"ok": true}'
    assert details["choices"][0]["message"]["reasoning_content"] == "hidden reasoning"
    assert details["usage"]["total_tokens"] == 8


def test_build_llm_audit_payload_extracts_request_response_and_usage():
    request_details = {
        "model": "test-model",
        "base_url": "https://api.example.com/v1",
        "messages": [{"role": "user", "content": "完整 prompt"}],
        "temperature": 0,
        "max_tokens": 128,
    }
    response_details = {
        "choices": [
            {
                "message": {
                    "content": "{\"ok\": true}",
                }
            }
        ],
        "usage": {
            "prompt_tokens": 3,
            "completion_tokens": 5,
            "total_tokens": 8,
        },
    }

    payload = _build_llm_audit_payload(
        request_id="req_1",
        request_details=request_details,
        response_details=response_details,
        elapsed_ms=42.3,
    )

    assert payload["request_id"] == "req_1"
    assert payload["model"] == "test-model"
    assert payload["messages"][0]["content"] == "完整 prompt"
    assert payload["request_params"] == {"temperature": 0, "max_tokens": 128}
    assert payload["response_text"] == "{\"ok\": true}"
    assert payload["prompt_tokens"] == 3
    assert payload["completion_tokens"] == 5
    assert payload["total_tokens"] == 8
    assert payload["latency_ms"] == 42
    assert payload["status"] == "succeeded"


def test_prepare_openai_compatible_structured_request_rewrites_graphiti_schema_prompt():
    schema = {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Summary containing the important information about the entity.",
            },
            "队伍名称": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "国家队官方名称",
            },
        },
        "required": ["summary", "队伍名称"],
    }
    kwargs = {
        "model": "MiniMax-M3",
        "messages": [
            {
                "role": "user",
                "content": (
                    "Given the entity, update attributes.\n\n"
                    "Respond with a JSON object in the following format:\n\n"
                    f"{json.dumps(schema, ensure_ascii=False)}"
                ),
            }
        ],
        "response_format": {"type": "json_object"},
    }

    response_schema = _prepare_openai_compatible_structured_request(kwargs)

    assert response_schema == {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "队伍名称": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
            },
        },
        "required": ["summary", "队伍名称"],
        "additionalProperties": False,
    }
    content = kwargs["messages"][0]["content"]
    assert '"properties"' not in content
    assert '"required"' not in content
    assert '"description"' not in content
    assert "summary" in content
    assert "队伍名称" in content
    assert "国家队官方名称" in content
    assert "Do not return the JSON Schema" in content


def test_repair_openai_compatible_structured_response_handles_minimax_schema_echo():
    schema = {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Summary containing the important information about the entity.",
            },
            "队伍名称": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "国家队官方名称",
            },
            "所属足协": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "description": "国家足球协会",
            },
        },
        "required": ["summary", "队伍名称", "所属足协"],
    }

    class Message:
        content = json.dumps(schema, ensure_ascii=False) + "}"

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    repaired = _repair_openai_compatible_structured_response(
        Response(),
        request_messages=[{"role": "user", "content": "prompt"}],
        response_schema=schema,
    )

    assert repaired.choices[0].message.content == (
        '{"summary":"","队伍名称":null,"所属足协":null}'
    )


def test_openai_compatible_structured_request_normalizes_ref_schema_for_alias_repair():
    schema = {
        "$defs": {
            "ExtractedEntity": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "entity_type_id": {"type": "integer"},
                },
                "required": ["name", "entity_type_id"],
            }
        },
        "type": "object",
        "properties": {
            "extracted_entities": {
                "type": "array",
                "items": {"$ref": "#/$defs/ExtractedEntity"},
            }
        },
        "required": ["extracted_entities"],
    }
    kwargs = {
        "messages": [
            {
                "role": "user",
                "content": (
                    "Extract entities.\n\n"
                    "Respond with a JSON object in the following format:\n\n"
                    f"{json.dumps(schema, ensure_ascii=False)}"
                ),
            }
        ],
        "response_format": {"type": "json_object"},
    }

    response_schema = _prepare_openai_compatible_structured_request(kwargs)

    class Message:
        content = (
            '{"extracted_entities":['
            '{"entity_name":"墨西哥国家男子足球队","entity_type_id":3}'
            ']}'
        )

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    repaired = _repair_openai_compatible_structured_response(
        Response(),
        request_messages=kwargs["messages"],
        response_schema=response_schema,
    )

    assert repaired.choices[0].message.content == (
        '{"extracted_entities":[{"name":"墨西哥国家男子足球队","entity_type_id":3}]}'
    )


def test_structured_response_repair_coerces_integer_strings():
    schema = {
        "type": "object",
        "properties": {
            "duplicate_fact_id": {"type": "integer"},
            "contradicted_facts": {
                "type": "array",
                "items": {"type": "integer"},
            },
        },
        "required": ["duplicate_fact_id", "contradicted_facts"],
    }

    class Message:
        content = '{"duplicate_fact_id":"-1","contradicted_facts":["0","2"]}'

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    repaired = _repair_openai_compatible_structured_response(
        Response(),
        request_messages=[{"role": "user", "content": "prompt"}],
        response_schema=schema,
    )

    assert repaired.choices[0].message.content == (
        '{"duplicate_fact_id":-1,"contradicted_facts":[0,2]}'
    )


def test_structured_response_repair_defaults_non_integer_duplicate_fact_id():
    schema = {
        "type": "object",
        "properties": {
            "duplicate_fact_id": {"type": "integer"},
            "contradicted_facts": {
                "type": "array",
                "items": {"type": "integer"},
            },
        },
        "required": ["duplicate_fact_id", "contradicted_facts"],
    }

    class Message:
        content = (
            '{"duplicate_fact_id":"2ad3079b-f8b1-4811-b4cb-84b8b3b7e5b4",'
            '"contradicted_facts":["not-an-index",1]}'
        )

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    repaired = _repair_openai_compatible_structured_response(
        Response(),
        request_messages=[{"role": "user", "content": "prompt"}],
        response_schema=schema,
    )

    assert repaired.choices[0].message.content == (
        '{"duplicate_fact_id":-1,"contradicted_facts":[1]}'
    )


def test_structured_response_repair_maps_graphiti_fact_uuid_to_index():
    schema = {
        "type": "object",
        "properties": {
            "duplicate_fact_id": {"type": "integer"},
            "contradicted_facts": {
                "type": "array",
                "items": {"type": "integer"},
            },
        },
        "required": ["duplicate_fact_id", "contradicted_facts"],
    }
    prompt = """
        <EXISTING FACTS>
        [{'id': 'edge-a', 'fact': 'A'}, {'id': 'edge-b', 'fact': 'B'}]
        </EXISTING FACTS>
        <FACT INVALIDATION CANDIDATES>
        [{'id': 7, 'fact': 'Old A'}, {'id': 9, 'fact': 'Old B'}]
        </FACT INVALIDATION CANDIDATES>
    """

    class Message:
        content = '{"duplicate_fact_id":"edge-b","contradicted_facts":[9]}'

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    repaired = _repair_openai_compatible_structured_response(
        Response(),
        request_messages=[{"role": "user", "content": prompt}],
        response_schema=schema,
    )

    assert repaired.choices[0].message.content == (
        '{"duplicate_fact_id":1,"contradicted_facts":[1]}'
    )

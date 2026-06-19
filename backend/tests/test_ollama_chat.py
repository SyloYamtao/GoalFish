import json

import pytest
from openai import OpenAI

from app.config import Config
from app.utils import llm_client as llm_client_module
from app.utils import llm_logging
from app.utils import ollama_chat as ollama_chat_module
from app.utils.llm_client import LLMClient
from app.utils.ollama_chat import (
    create_ollama_chat_completion,
    is_ollama_native_chat_base_url,
    normalize_ollama_chat_url,
)


def test_detects_ollama_native_chat_base_url():
    assert is_ollama_native_chat_base_url("http://localhost:11434/api/chat")
    assert is_ollama_native_chat_base_url("http://127.0.0.1:11434/api/chat")
    assert is_ollama_native_chat_base_url("http://localhost:11434")
    assert not is_ollama_native_chat_base_url("http://localhost:11434/v1")
    assert not is_ollama_native_chat_base_url("https://api.deepseek.com/v1")


def test_normalize_ollama_chat_url_preserves_native_endpoint():
    assert (
        normalize_ollama_chat_url("http://localhost:11434/api/chat")
        == "http://localhost:11434/api/chat"
    )
    assert normalize_ollama_chat_url("http://localhost:11434") == "http://localhost:11434/api/chat"
    assert normalize_ollama_chat_url("http://localhost:11434/api") == "http://localhost:11434/api/chat"


def test_create_ollama_chat_completion_posts_native_payload(monkeypatch):
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "model": "qwen3.5:2b-mlx",
                    "created_at": "2026-06-04T10:00:00Z",
                    "message": {"role": "assistant", "content": '{"ok": true}'},
                    "done_reason": "stop",
                    "prompt_eval_count": 11,
                    "eval_count": 7,
                }
            ).encode("utf-8")

    def local_open(request, timeout):
        calls.append(
            (
                request.full_url,
                json.loads(request.data.decode("utf-8")),
                timeout,
            )
        )
        return FakeResponse()

    def proxy_urlopen(request, timeout):
        raise AssertionError("loopback Ollama chat requests must not use urllib proxy opener")

    monkeypatch.setattr(ollama_chat_module._LOCAL_OPENER, "open", local_open)
    monkeypatch.setattr(ollama_chat_module.urllib.request, "urlopen", proxy_urlopen)

    response = create_ollama_chat_completion(
        "http://localhost:11434/api/chat",
        {
            "model": "qwen3.5:2b-mlx",
            "messages": [{"role": "user", "content": "Hello!"}],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_tokens": 128,
        },
    )

    assert response.model == "qwen3.5:2b-mlx"
    assert response.choices[0].message.content == '{"ok": true}'
    assert response.choices[0].finish_reason == "stop"
    assert response.usage.prompt_tokens == 11
    assert response.usage.completion_tokens == 7
    assert response.usage.total_tokens == 18
    assert calls == [
        (
            "http://localhost:11434/api/chat",
            {
                "model": "qwen3.5:2b-mlx",
                "messages": [{"role": "user", "content": "Hello!"}],
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": 0.2,
                    "num_predict": 128,
                },
            },
            600,
        )
    ]


def test_ollama_native_json_schema_response_format_posts_schema():
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "scores": {"type": "array", "items": {"type": "number"}},
        },
        "required": ["name", "scores"],
    }

    payload = ollama_chat_module.build_ollama_chat_payload(
        {
            "model": "qwen3.5:2b-mlx",
            "messages": [{"role": "user", "content": "Return structured data"}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "ScorePayload",
                    "schema": schema,
                },
            },
        }
    )

    assert payload["format"] == {
        **schema,
        "additionalProperties": False,
    }
    assert "response_format" not in payload


def test_ollama_native_json_object_extracts_graphiti_prompt_schema():
    graphiti_schema = {
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
    prompt = (
        "Given the above text, extract entities.\n\n"
        "Respond with a JSON object in the following format:\n\n"
        f"{json.dumps(graphiti_schema, ensure_ascii=False)}"
    )
    kwargs = {
        "model": "qwen3.5:2b-mlx",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "extra_body": {"think": False},
    }

    payload = ollama_chat_module.build_ollama_chat_payload(kwargs)

    assert payload["format"] == {
        "type": "object",
        "properties": {
            "extracted_entities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "entity_type_id": {"type": "integer"},
                    },
                    "required": ["name", "entity_type_id"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["extracted_entities"],
        "additionalProperties": False,
    }
    assert payload["think"] is False
    assert "extra_body" not in payload
    assert kwargs["response_format"] == {"type": "json_object"}
    assert "format" not in kwargs


def test_ollama_native_json_object_removes_graphiti_schema_from_prompt():
    graphiti_schema = {
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
    prompt = (
        "Given the above text, extract entities.\n\n"
        "Respond with a JSON object in the following format:\n\n"
        f"{json.dumps(graphiti_schema, ensure_ascii=False)}"
    )

    payload = ollama_chat_module.build_ollama_chat_payload(
        {
            "model": "qwen3.5:2b-mlx",
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
    )

    assert "$defs" not in payload["messages"][0]["content"]
    assert '"properties"' not in payload["messages"][0]["content"]
    assert "extracted_entities" in payload["messages"][0]["content"]
    assert "Do not return the JSON Schema" in payload["messages"][0]["content"]


def test_ollama_native_schema_echo_response_fails_closed_to_empty_payload(monkeypatch):
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
    prompt = (
        "Given the above text, extract entities.\n\n"
        "Respond with a JSON object in the following format:\n\n"
        f"{json.dumps(schema, ensure_ascii=False)}"
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "model": "qwen3.5:2b-mlx",
                    "message": {"role": "assistant", "content": json.dumps(schema)},
                    "done_reason": "stop",
                }
            ).encode("utf-8")

    monkeypatch.setattr(
        ollama_chat_module._LOCAL_OPENER,
        "open",
        lambda request, timeout: FakeResponse(),
    )

    response = create_ollama_chat_completion(
        "http://localhost:11434/api/chat",
        {
            "model": "qwen3.5:2b-mlx",
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        },
    )

    assert response.choices[0].message.content == '{"extracted_entities":[]}'


def test_ollama_native_empty_entities_dedupe_response_discards_hallucinated_ids(monkeypatch):
    schema = {
        "$defs": {
            "NodeDuplicate": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "duplicate_idx": {"type": "integer"},
                    "name": {"type": "string"},
                },
                "required": ["id", "duplicate_idx", "name"],
            }
        },
        "type": "object",
        "properties": {
            "entity_resolutions": {
                "type": "array",
                "items": {"$ref": "#/$defs/NodeDuplicate"},
            }
        },
        "required": ["entity_resolutions"],
    }
    prompt = (
        "<ENTITIES>\n[]\n</ENTITIES>\n\n"
        "For each of the above ENTITIES, determine if the entity is a duplicate.\n\n"
        "Respond with a JSON object in the following format:\n\n"
        f"{json.dumps(schema, ensure_ascii=False)}"
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "model": "qwen3.5:2b-mlx",
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(
                            {
                                "entity_resolutions": [
                                    {"id": 1, "name": "Hugo Broos", "duplicate_idx": -1}
                                ]
                            }
                        ),
                    },
                    "done_reason": "stop",
                }
            ).encode("utf-8")

    monkeypatch.setattr(
        ollama_chat_module._LOCAL_OPENER,
        "open",
        lambda request, timeout: FakeResponse(),
    )

    response = create_ollama_chat_completion(
        "http://localhost:11434/api/chat",
        {
            "model": "qwen3.5:2b-mlx",
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        },
    )

    assert response.choices[0].message.content == '{"entity_resolutions":[]}'


def test_ollama_native_malformed_structured_json_fails_closed(monkeypatch):
    schema = {
        "$defs": {
            "NodeDuplicate": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "duplicate_idx": {"type": "integer"},
                    "name": {"type": "string"},
                },
                "required": ["id", "duplicate_idx", "name"],
            }
        },
        "type": "object",
        "properties": {
            "entity_resolutions": {
                "type": "array",
                "items": {"$ref": "#/$defs/NodeDuplicate"},
            }
        },
        "required": ["entity_resolutions"],
    }
    prompt = (
        "<ENTITIES>\n[{\"id\": 0, \"name\": \"墨西哥\"}]\n</ENTITIES>\n\n"
        "Respond with a JSON object in the following format:\n\n"
        f"{json.dumps(schema, ensure_ascii=False)}"
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "model": "qwen3.5:2b-mlx",
                    "message": {
                        "role": "assistant",
                        "content": (
                            '{"entity_resolutions":[{"id":0,"name":"墨西哥",'
                            '"duplicate_idx":-1}'
                        ),
                    },
                    "done_reason": "stop",
                }
            ).encode("utf-8")

    monkeypatch.setattr(
        ollama_chat_module._LOCAL_OPENER,
        "open",
        lambda request, timeout: FakeResponse(),
    )

    response = create_ollama_chat_completion(
        "http://localhost:11434/api/chat",
        {
            "model": "qwen3.5:2b-mlx",
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        },
    )

    assert response.choices[0].message.content == '{"entity_resolutions":[]}'


def test_ollama_native_dedupe_response_discards_out_of_range_entity_ids(monkeypatch):
    schema = {
        "$defs": {
            "NodeDuplicate": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "duplicate_idx": {"type": "integer"},
                    "name": {"type": "string"},
                },
                "required": ["id", "duplicate_idx", "name"],
            }
        },
        "type": "object",
        "properties": {
            "entity_resolutions": {
                "type": "array",
                "items": {"$ref": "#/$defs/NodeDuplicate"},
            }
        },
        "required": ["entity_resolutions"],
    }
    prompt = (
        "<ENTITIES>\n"
        "[{\"id\": 0, \"name\": \"墨西哥\"}, {\"id\": 1, \"name\": \"南非\"}]\n"
        "</ENTITIES>\n\n"
        "Respond with a JSON object in the following format:\n\n"
        f"{json.dumps(schema, ensure_ascii=False)}"
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "model": "qwen3.5:2b-mlx",
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(
                            {
                                "entity_resolutions": [
                                    {"id": 0, "name": "墨西哥", "duplicate_idx": -1},
                                    {"id": 2, "name": "Javier Aguirre", "duplicate_idx": -1},
                                    {"id": 10, "name": "Hugo Broos", "duplicate_idx": -1},
                                ]
                            },
                            ensure_ascii=False,
                        ),
                    },
                    "done_reason": "stop",
                }
            ).encode("utf-8")

    monkeypatch.setattr(
        ollama_chat_module._LOCAL_OPENER,
        "open",
        lambda request, timeout: FakeResponse(),
    )

    response = create_ollama_chat_completion(
        "http://localhost:11434/api/chat",
        {
            "model": "qwen3.5:2b-mlx",
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        },
    )

    assert response.choices[0].message.content == (
        '{"entity_resolutions":[{"id":0,"duplicate_idx":-1,"name":"墨西哥"}]}'
    )


def test_ollama_native_extracted_entities_normalizes_entity_name_alias(monkeypatch):
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
    prompt = (
        "Given the above text, extract entities.\n\n"
        "Respond with a JSON object in the following format:\n\n"
        f"{json.dumps(schema, ensure_ascii=False)}"
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "model": "qwen3.5:2b-mlx",
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(
                            {
                                "extracted_entities": [
                                    {"entity_name": "墨西哥", "entity_type_id": 1}
                                ]
                            },
                            ensure_ascii=False,
                        ),
                    },
                    "done_reason": "stop",
                }
            ).encode("utf-8")

    monkeypatch.setattr(
        ollama_chat_module._LOCAL_OPENER,
        "open",
        lambda request, timeout: FakeResponse(),
    )

    response = create_ollama_chat_completion(
        "http://localhost:11434/api/chat",
        {
            "model": "qwen3.5:2b-mlx",
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        },
    )

    assert response.choices[0].message.content == (
        '{"extracted_entities":[{"name":"墨西哥","entity_type_id":1}]}'
    )


def test_ollama_native_extracted_edges_normalizes_common_field_aliases(monkeypatch):
    schema = {
        "$defs": {
            "Edge": {
                "type": "object",
                "properties": {
                    "relation_type": {"type": "string"},
                    "source_entity_name": {"type": "string"},
                    "target_entity_name": {"type": "string"},
                    "fact": {"type": "string"},
                },
                "required": [
                    "relation_type",
                    "source_entity_name",
                    "target_entity_name",
                    "fact",
                ],
            }
        },
        "type": "object",
        "properties": {
            "edges": {
                "type": "array",
                "items": {"$ref": "#/$defs/Edge"},
            }
        },
        "required": ["edges"],
    }
    prompt = (
        "Extract all factual relationships.\n\n"
        "Respond with a JSON object in the following format:\n\n"
        f"{json.dumps(schema, ensure_ascii=False)}"
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "model": "qwen3.5:2b-mlx",
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(
                            {
                                "edges": [
                                    {
                                        "relation": "HOSTS",
                                        "source": "墨西哥",
                                        "target": "2026 FIFA World Cup",
                                        "fact_text": "墨西哥是2026世界杯东道主。",
                                    }
                                ]
                            },
                            ensure_ascii=False,
                        ),
                    },
                    "done_reason": "stop",
                }
            ).encode("utf-8")

    monkeypatch.setattr(
        ollama_chat_module._LOCAL_OPENER,
        "open",
        lambda request, timeout: FakeResponse(),
    )

    response = create_ollama_chat_completion(
        "http://localhost:11434/api/chat",
        {
            "model": "qwen3.5:2b-mlx",
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        },
    )

    assert response.choices[0].message.content == (
        '{"edges":[{"relation_type":"HOSTS","source_entity_name":"墨西哥",'
        '"target_entity_name":"2026 FIFA World Cup","fact":"墨西哥是2026世界杯东道主。"}]}'
    )


def test_ollama_native_response_strips_json_markdown_fence():
    response = ollama_chat_module.build_chat_completion_response(
        {
            "model": "qwen3.5:2b-mlx",
            "message": {
                "role": "assistant",
                "content": "```json\n{\"extracted_entities\": []}\n```",
            },
            "done_reason": "stop",
        },
        request_model="qwen3.5:2b-mlx",
    )

    assert response.choices[0].message.content == '{"extracted_entities": []}'


def test_ollama_native_tool_messages_convert_openai_shape():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "get_temperature",
                "description": "Get the current temperature for a city",
                "parameters": {
                    "type": "object",
                    "required": ["city"],
                    "properties": {
                        "city": {"type": "string", "description": "The name of the city"}
                    },
                },
            },
        }
    ]
    kwargs = {
        "model": "qwen3.5:2b-mlx",
        "messages": [
            {"role": "user", "content": "What is the temperature in New York?"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_temperature",
                        "type": "function",
                        "function": {
                            "name": "get_temperature",
                            "arguments": "{\"city\": \"New York\"}",
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_temperature",
                "content": "22°C",
            },
        ],
        "tools": tools,
    }

    payload = ollama_chat_module.build_ollama_chat_payload(kwargs)

    assert payload["tools"] == tools
    assert payload["messages"][1]["tool_calls"] == [
        {
            "type": "function",
            "function": {
                "index": 0,
                "name": "get_temperature",
                "arguments": {"city": "New York"},
            },
        }
    ]
    assert payload["messages"][2] == {
        "role": "tool",
        "content": "22°C",
        "tool_name": "get_temperature",
    }
    assert kwargs["messages"][1]["tool_calls"][0]["function"]["arguments"] == "{\"city\": \"New York\"}"


def test_ollama_native_tool_response_converts_to_openai_shape():
    response = ollama_chat_module.build_chat_completion_response(
        {
            "model": "qwen3.5:2b-mlx",
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {
                            "name": "get_temperature",
                            "arguments": {"city": "New York"},
                        },
                    }
                ],
            },
            "done_reason": "stop",
        },
        request_model="qwen3.5:2b-mlx",
    )

    tool_call = response.choices[0].message.tool_calls[0]
    assert tool_call.id == "call_0"
    assert tool_call.type == "function"
    assert tool_call.function.name == "get_temperature"
    assert json.loads(tool_call.function.arguments) == {"city": "New York"}


def test_openai_compatible_ollama_url_does_not_get_native_think_default(monkeypatch):
    kwargs = {"model": "qwen3.5:2b-mlx"}

    monkeypatch.setenv("LLM_DISABLE_THINKING", "auto")
    llm_logging._apply_provider_defaults(kwargs, "http://localhost:11434/v1")

    assert "extra_body" not in kwargs


def test_explicit_openai_chat_protocol_overrides_ollama_like_url(monkeypatch):
    kwargs = {"model": "qwen3.5:2b-mlx"}

    monkeypatch.setenv("LLM_CHAT_PROTOCOL", "openai")
    monkeypatch.setenv("LLM_DISABLE_THINKING", "auto")

    assert llm_logging._chat_protocol_for_base_url("http://localhost:11434/api/chat") == "openai"
    llm_logging._apply_provider_defaults(kwargs, "http://localhost:11434/api/chat")

    assert "extra_body" not in kwargs


def test_graphiti_chat_protocol_can_override_global_protocol(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://api.minimaxi.com/v1")
    monkeypatch.setenv("LLM_CHAT_PROTOCOL", "openai")
    monkeypatch.setenv("GRAPHITI_LLM_BASE_URL", "http://localhost:11434/api/chat")
    monkeypatch.setenv("GRAPHITI_LLM_CHAT_PROTOCOL", "ollama")

    assert llm_logging._chat_protocol_for_base_url("https://api.minimaxi.com/v1") == "openai"
    assert llm_logging._chat_protocol_for_base_url("http://localhost:11434/api/chat/") == "ollama"


def test_llm_logging_minimax_m3_disables_thinking_by_default(monkeypatch):
    kwargs = {"model": "MiniMax-M3"}

    monkeypatch.setenv("LLM_DISABLE_THINKING", "auto")
    llm_logging._apply_provider_defaults(kwargs, "https://api.minimaxi.com/v1/")

    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


def test_llm_logging_disabled_setting_disables_thinking_for_openai_compatible(monkeypatch):
    kwargs = {"model": "glm-5.2"}

    monkeypatch.setenv("LLM_DISABLE_THINKING", "disabled")
    llm_logging._apply_provider_defaults(kwargs, "https://ark.cn-beijing.volces.com/api/coding/v3/")

    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


def test_llm_logging_disabled_setting_disables_thinking_when_env_unset(monkeypatch):
    kwargs = {"model": "provider-reasoning-model"}

    monkeypatch.delenv("LLM_DISABLE_THINKING", raising=False)
    llm_logging._apply_provider_defaults(kwargs, "https://provider.example/v1/")

    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


def test_llm_logging_minimax_m2_does_not_disable_thinking(monkeypatch):
    kwargs = {"model": "MiniMax-M2.7"}

    monkeypatch.setenv("LLM_DISABLE_THINKING", "auto")
    llm_logging._apply_provider_defaults(kwargs, "https://api.minimaxi.com/v1/")

    assert "extra_body" not in kwargs


def test_llm_logging_routes_openai_sdk_calls_to_ollama_native(monkeypatch):
    calls = []

    def fake_create_ollama_chat_completion(base_url, kwargs):
        calls.append((base_url, kwargs))
        return ollama_chat_module.build_chat_completion_response(
            {
                "model": kwargs["model"],
                "message": {"role": "assistant", "content": "local answer"},
                "done_reason": "stop",
            },
            request_model=kwargs["model"],
        )

    monkeypatch.setattr(
        llm_logging,
        "create_ollama_chat_completion",
        fake_create_ollama_chat_completion,
    )
    monkeypatch.setattr(llm_logging, "_record_llm_audit", lambda payload: None)
    monkeypatch.setenv("LLM_CHAT_PROTOCOL", "ollama")
    llm_logging.install_llm_completion_logging()

    client = OpenAI(api_key="ollama", base_url="http://localhost:11434/api/chat")
    response = client.chat.completions.create(
        model="qwen3.5:2b-mlx",
        messages=[{"role": "user", "content": "Hello!"}],
    )

    assert response.choices[0].message.content == "local answer"
    assert calls[0][0].rstrip("/") == "http://localhost:11434/api/chat"
    assert calls[0][1]["model"] == "qwen3.5:2b-mlx"


def test_llm_client_uses_ollama_native_without_api_key(monkeypatch):
    calls = []

    def fake_create_ollama_chat_completion(base_url, kwargs):
        calls.append((base_url, kwargs))
        return ollama_chat_module.build_chat_completion_response(
            {
                "model": kwargs["model"],
                "message": {"role": "assistant", "content": "client answer"},
                "done_reason": "stop",
            },
            request_model=kwargs["model"],
        )

    monkeypatch.setattr(
        llm_client_module,
        "create_logged_ollama_chat_completion",
        fake_create_ollama_chat_completion,
    )

    client = LLMClient(
        api_key="",
        base_url="http://localhost:11434/api/chat",
        model="qwen3.5:2b-mlx",
    )

    assert client.chat([{"role": "user", "content": "Hello!"}]) == "client answer"
    assert calls[0][0] == "http://localhost:11434/api/chat"
    assert calls[0][1]["model"] == "qwen3.5:2b-mlx"


def test_llm_client_respects_explicit_openai_protocol_for_ollama_like_url():
    client = LLMClient(
        api_key="placeholder-key",
        base_url="http://localhost:11434/api/chat",
        model="openai-compatible-model",
        chat_protocol="openai",
    )

    assert client._use_ollama_native is False


def test_llm_client_rejects_unimplemented_anthropic_protocol():
    with pytest.raises(NotImplementedError, match="anthropic"):
        LLMClient(
            api_key="anthropic-key",
            base_url="https://api.anthropic.com",
            model="claude-3-5-sonnet",
            chat_protocol="anthropic",
        )


def test_llm_client_ollama_native_direct_calls_are_logged_and_audited(monkeypatch):
    request_logs = []
    response_logs = []
    audits = []

    def fake_create_ollama_chat_completion(base_url, kwargs):
        return ollama_chat_module.build_chat_completion_response(
            {
                "model": kwargs["model"],
                "message": {"role": "assistant", "content": "logged answer"},
                "done_reason": "stop",
                "prompt_eval_count": 5,
                "eval_count": 3,
            },
            request_model=kwargs["model"],
        )

    monkeypatch.setenv("LLM_LOG_COMPLETIONS", "true")
    monkeypatch.setattr(
        llm_logging,
        "create_ollama_chat_completion",
        fake_create_ollama_chat_completion,
    )
    monkeypatch.setattr(
        llm_logging,
        "_log_completion_request",
        lambda request_id, details: request_logs.append((request_id, details)),
    )
    monkeypatch.setattr(
        llm_logging,
        "_log_completion_response",
        lambda request_id, details, elapsed_ms: response_logs.append(
            (request_id, details, elapsed_ms)
        ),
    )
    monkeypatch.setattr(llm_logging, "_record_llm_audit", lambda payload: audits.append(payload))

    client = LLMClient(
        api_key="",
        base_url="http://localhost:11434/api/chat",
        model="qwen3.5:2b-mlx",
    )

    assert client.chat([{"role": "user", "content": "Hello!"}]) == "logged answer"
    assert request_logs
    assert response_logs
    assert audits
    assert request_logs[0][1]["base_url"] == "http://localhost:11434/api/chat"
    assert request_logs[0][1]["messages"] == [{"role": "user", "content": "Hello!"}]
    assert response_logs[0][1]["choices"][0]["message"]["content"] == "logged answer"
    assert audits[0]["base_url"] == "http://localhost:11434/api/chat"
    assert audits[0]["model"] == "qwen3.5:2b-mlx"
    assert audits[0]["response_text"] == "logged answer"
    assert audits[0]["prompt_tokens"] == 5
    assert audits[0]["completion_tokens"] == 3
    assert audits[0]["total_tokens"] == 8


def test_llm_client_ollama_native_qwen3_disables_thinking_by_default(monkeypatch):
    calls = []

    def fake_create_ollama_chat_completion(base_url, kwargs):
        calls.append((base_url, kwargs))
        return ollama_chat_module.build_chat_completion_response(
            {
                "model": kwargs["model"],
                "message": {"role": "assistant", "content": '{"ok": true}'},
                "done_reason": "stop",
            },
            request_model=kwargs["model"],
        )

    monkeypatch.setenv("LLM_LOG_COMPLETIONS", "true")
    monkeypatch.setenv("LLM_DISABLE_THINKING", "auto")
    monkeypatch.setattr(
        llm_logging,
        "create_ollama_chat_completion",
        fake_create_ollama_chat_completion,
    )
    monkeypatch.setattr(llm_logging, "_record_llm_audit", lambda payload: None)

    client = LLMClient(
        api_key="",
        base_url="http://localhost:11434/api/chat",
        model="qwen3.5:2b-mlx",
    )

    assert client.chat([{"role": "user", "content": "Return JSON"}]) == '{"ok": true}'
    assert calls[0][1]["extra_body"] == {"think": False}


def test_llm_client_ollama_native_respects_disable_thinking_false(monkeypatch):
    calls = []

    def fake_create_ollama_chat_completion(base_url, kwargs):
        calls.append((base_url, kwargs))
        return ollama_chat_module.build_chat_completion_response(
            {
                "model": kwargs["model"],
                "message": {"role": "assistant", "content": "plain answer"},
                "done_reason": "stop",
            },
            request_model=kwargs["model"],
        )

    monkeypatch.setenv("LLM_LOG_COMPLETIONS", "true")
    monkeypatch.setenv("LLM_DISABLE_THINKING", "false")
    monkeypatch.setattr(
        llm_logging,
        "create_ollama_chat_completion",
        fake_create_ollama_chat_completion,
    )
    monkeypatch.setattr(llm_logging, "_record_llm_audit", lambda payload: None)

    client = LLMClient(
        api_key="",
        base_url="http://localhost:11434/api/chat",
        model="qwen3.5:2b-mlx",
    )

    assert client.chat([{"role": "user", "content": "Hello!"}]) == "plain answer"
    assert "extra_body" not in calls[0][1]


def test_llm_client_ollama_native_direct_errors_are_logged_and_audited(monkeypatch):
    error_logs = []
    audits = []

    def fake_create_ollama_chat_completion(base_url, kwargs):
        raise RuntimeError("native ollama failed")

    monkeypatch.setenv("LLM_LOG_COMPLETIONS", "true")
    monkeypatch.setattr(
        llm_logging,
        "create_ollama_chat_completion",
        fake_create_ollama_chat_completion,
    )
    monkeypatch.setattr(llm_logging, "_log_completion_request", lambda request_id, details: None)
    monkeypatch.setattr(
        llm_logging,
        "_log_completion_error",
        lambda request_id, error, elapsed_ms: error_logs.append((request_id, error, elapsed_ms)),
    )
    monkeypatch.setattr(llm_logging, "_record_llm_audit", lambda payload: audits.append(payload))

    client = LLMClient(
        api_key="",
        base_url="http://localhost:11434/api/chat",
        model="qwen3.5:2b-mlx",
    )

    with pytest.raises(RuntimeError, match="native ollama failed"):
        client.chat([{"role": "user", "content": "Hello!"}])

    assert error_logs
    assert audits
    assert audits[0]["status"] == "failed"
    assert audits[0]["error_message"] == "native ollama failed"
    assert audits[0]["messages"] == [{"role": "user", "content": "Hello!"}]


def test_ollama_llm_config_does_not_require_api_key(monkeypatch):
    monkeypatch.setattr(Config, "LLM_API_KEY", "")
    monkeypatch.setattr(Config, "LLM_CHAT_PROTOCOL", "ollama")
    monkeypatch.setattr(Config, "LLM_BASE_URL", "http://localhost:11434/api/chat")
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "qwen3.5:2b-mlx")
    monkeypatch.setattr(Config, "GRAPH_BACKEND", "graphiti")
    monkeypatch.setattr(Config, "GRAPHITI_NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setattr(Config, "GRAPHITI_NEO4J_USER", "neo4j")
    monkeypatch.setattr(Config, "GRAPHITI_NEO4J_PASSWORD", "password")
    monkeypatch.setattr(Config, "GRAPHITI_LLM_CHAT_PROTOCOL", "ollama")
    monkeypatch.setattr(Config, "GRAPHITI_LLM_BASE_URL", "http://localhost:11434/api/chat")
    monkeypatch.setattr(Config, "GRAPHITI_LLM_API_KEY", "")
    monkeypatch.setattr(Config, "GRAPHITI_EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setattr(Config, "GRAPHITI_OLLAMA_EMBED_URL", "http://127.0.0.1:11434/api/embed")
    monkeypatch.setattr(Config, "GRAPHITI_EMBEDDING_MODEL", "qwen3-embedding")
    monkeypatch.setattr(Config, "GRAPHITI_EMBEDDING_DIM", 1024)

    errors = Config.validate()

    assert not any("LLM_API_KEY" in error for error in errors)

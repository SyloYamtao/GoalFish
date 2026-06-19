from app.config import Config, _normalize_ollama_localhost_url
from app.services.graph_diagnostics import (
    creating_graph_message,
    format_graph_exception,
    graph_build_context,
    waiting_graph_process_message,
)
from app.services.graph_backend_factory import get_backend_name
from app.services.graphiti_client import create_graphiti_embedder
from app.services.graphiti_ollama_embedder import OllamaEmbedder
from app.services.graphiti_ontology import build_graphiti_entity_types


def test_graphiti_ollama_embedding_config_does_not_require_api_key(monkeypatch):
    monkeypatch.setattr(Config, "LLM_API_KEY", "llm-key")
    monkeypatch.setattr(Config, "GRAPH_BACKEND", "graphiti")
    monkeypatch.setattr(Config, "GRAPHITI_NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setattr(Config, "GRAPHITI_NEO4J_USER", "neo4j")
    monkeypatch.setattr(Config, "GRAPHITI_NEO4J_PASSWORD", "password")
    monkeypatch.setattr(Config, "GRAPHITI_LLM_API_KEY", "llm-key")
    monkeypatch.setattr(Config, "GRAPHITI_EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setattr(Config, "GRAPHITI_EMBEDDING_API_KEY", "")
    monkeypatch.setattr(Config, "GRAPHITI_OLLAMA_EMBED_URL", "http://localhost:11434/api/embed")
    monkeypatch.setattr(Config, "GRAPHITI_EMBEDDING_MODEL", "qwen3-embedding")

    assert Config.validate() == []


def test_graphiti_rejects_unknown_embedding_provider(monkeypatch):
    monkeypatch.setattr(Config, "LLM_API_KEY", "llm-key")
    monkeypatch.setattr(Config, "GRAPH_BACKEND", "graphiti")
    monkeypatch.setattr(Config, "GRAPHITI_NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setattr(Config, "GRAPHITI_NEO4J_USER", "neo4j")
    monkeypatch.setattr(Config, "GRAPHITI_NEO4J_PASSWORD", "password")
    monkeypatch.setattr(Config, "GRAPHITI_LLM_API_KEY", "llm-key")
    monkeypatch.setattr(Config, "GRAPHITI_EMBEDDING_PROVIDER", "invalid")
    monkeypatch.setattr(Config, "GRAPHITI_EMBEDDING_MODEL", "qwen3-embedding")

    errors = Config.validate()

    assert any("GRAPHITI_EMBEDDING_PROVIDER" in error for error in errors)


def test_config_rejects_invalid_chat_protocol(monkeypatch):
    monkeypatch.setattr(Config, "LLM_CHAT_PROTOCOL", "invalid")
    monkeypatch.setattr(Config, "GRAPHITI_LLM_CHAT_PROTOCOL", "openai")
    monkeypatch.setattr(Config, "LLM_API_KEY", "llm-key")
    monkeypatch.setattr(Config, "GRAPH_BACKEND", "graphiti")
    monkeypatch.setattr(Config, "GRAPHITI_NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setattr(Config, "GRAPHITI_NEO4J_USER", "neo4j")
    monkeypatch.setattr(Config, "GRAPHITI_NEO4J_PASSWORD", "password")
    monkeypatch.setattr(Config, "GRAPHITI_LLM_API_KEY", "llm-key")
    monkeypatch.setattr(Config, "GRAPHITI_EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setattr(Config, "GRAPHITI_OLLAMA_EMBED_URL", "http://127.0.0.1:11434/api/embed")
    monkeypatch.setattr(Config, "GRAPHITI_EMBEDDING_MODEL", "qwen3-embedding")
    monkeypatch.setattr(Config, "GRAPHITI_EMBEDDING_DIM", 1024)

    errors = Config.validate()

    assert any("LLM_CHAT_PROTOCOL" in error for error in errors)


def test_config_rejects_unimplemented_anthropic_chat_protocol(monkeypatch):
    monkeypatch.setattr(Config, "LLM_CHAT_PROTOCOL", "anthropic")
    monkeypatch.setattr(Config, "GRAPHITI_LLM_CHAT_PROTOCOL", "openai")
    monkeypatch.setattr(Config, "LLM_API_KEY", "llm-key")
    monkeypatch.setattr(Config, "GRAPH_BACKEND", "graphiti")
    monkeypatch.setattr(Config, "GRAPHITI_NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setattr(Config, "GRAPHITI_NEO4J_USER", "neo4j")
    monkeypatch.setattr(Config, "GRAPHITI_NEO4J_PASSWORD", "password")
    monkeypatch.setattr(Config, "GRAPHITI_LLM_API_KEY", "llm-key")
    monkeypatch.setattr(Config, "GRAPHITI_EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setattr(Config, "GRAPHITI_OLLAMA_EMBED_URL", "http://127.0.0.1:11434/api/embed")
    monkeypatch.setattr(Config, "GRAPHITI_EMBEDDING_MODEL", "qwen3-embedding")
    monkeypatch.setattr(Config, "GRAPHITI_EMBEDDING_DIM", 1024)

    errors = Config.validate()

    assert any("anthropic" in error for error in errors)


def test_graphiti_ollama_url_normalizes_localhost_to_ipv4_loopback():
    assert (
        _normalize_ollama_localhost_url("http://localhost:11434/api/embed")
        == "http://127.0.0.1:11434/api/embed"
    )
    assert (
        _normalize_ollama_localhost_url("http://127.0.0.1:11434/api/embed")
        == "http://127.0.0.1:11434/api/embed"
    )


def test_graphiti_rejects_invalid_ollama_tuning_values(monkeypatch):
    monkeypatch.setattr(Config, "LLM_API_KEY", "llm-key")
    monkeypatch.setattr(Config, "GRAPH_BACKEND", "graphiti")
    monkeypatch.setattr(Config, "GRAPHITI_NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setattr(Config, "GRAPHITI_NEO4J_USER", "neo4j")
    monkeypatch.setattr(Config, "GRAPHITI_NEO4J_PASSWORD", "password")
    monkeypatch.setattr(Config, "GRAPHITI_LLM_API_KEY", "llm-key")
    monkeypatch.setattr(Config, "GRAPHITI_EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setattr(Config, "GRAPHITI_OLLAMA_EMBED_URL", "http://localhost:11434/api/embed")
    monkeypatch.setattr(Config, "GRAPHITI_EMBEDDING_MODEL", "qwen3-embedding")
    monkeypatch.setattr(Config, "GRAPHITI_EMBEDDING_DIM", 1024)
    monkeypatch.setattr(Config, "GRAPHITI_OLLAMA_MAX_CONCURRENCY", 0)
    monkeypatch.setattr(Config, "GRAPHITI_OLLAMA_MAX_RETRIES", 0)
    monkeypatch.setattr(Config, "GRAPHITI_OLLAMA_RETRY_DELAY", -1)

    errors = Config.validate()

    assert any("GRAPHITI_OLLAMA_MAX_CONCURRENCY" in error for error in errors)
    assert any("GRAPHITI_OLLAMA_MAX_RETRIES" in error for error in errors)
    assert any("GRAPHITI_OLLAMA_RETRY_DELAY" in error for error in errors)


def test_create_graphiti_embedder_uses_ollama_provider(monkeypatch):
    monkeypatch.setattr(Config, "GRAPHITI_EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setattr(Config, "GRAPHITI_OLLAMA_EMBED_URL", "http://127.0.0.1:11434/api/embed")
    monkeypatch.setattr(Config, "GRAPHITI_EMBEDDING_MODEL", "qwen3-embedding")
    monkeypatch.setattr(Config, "GRAPHITI_EMBEDDING_DIM", 1024)
    monkeypatch.setattr(Config, "GRAPHITI_OLLAMA_MAX_CONCURRENCY", 1)
    monkeypatch.setattr(Config, "GRAPHITI_OLLAMA_MAX_RETRIES", 3)
    monkeypatch.setattr(Config, "GRAPHITI_OLLAMA_RETRY_DELAY", 0.5)

    embedder = create_graphiti_embedder()

    assert isinstance(embedder, OllamaEmbedder)
    assert embedder.config.embed_url == "http://127.0.0.1:11434/api/embed"
    assert embedder.config.embedding_model == "qwen3-embedding"
    assert embedder.config.max_concurrency == 1
    assert embedder.config.max_retries == 3
    assert embedder.config.retry_delay == 0.5


def test_graph_progress_messages_use_selected_backend(monkeypatch):
    monkeypatch.setattr(Config, "GRAPH_BACKEND", "graphiti")
    assert creating_graph_message() == "创建Graphiti图谱..."
    assert "Graphiti" in waiting_graph_process_message()


def test_graphiti_build_context_uses_graphiti_llm_config(monkeypatch):
    monkeypatch.setattr(Config, "GRAPH_BACKEND", "graphiti")
    monkeypatch.setattr(Config, "LLM_BASE_URL", "http://localhost:11434/api/chat")
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "qwen3.5:2b-mlx")
    monkeypatch.setattr(Config, "GRAPHITI_LLM_BASE_URL", "https://graphiti-llm.example/v1")
    monkeypatch.setattr(Config, "GRAPHITI_LLM_CHAT_PROTOCOL", "openai")
    monkeypatch.setattr(Config, "GRAPHITI_LLM_MODEL", "graphiti-model")
    monkeypatch.setattr(Config, "GRAPHITI_NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setattr(Config, "GRAPHITI_NEO4J_USER", "neo4j")
    monkeypatch.setattr(Config, "GRAPHITI_NEO4J_PASSWORD", "password")
    monkeypatch.setattr(Config, "GRAPHITI_EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setattr(Config, "GRAPHITI_EMBEDDING_MODEL", "qwen3-embedding")
    monkeypatch.setattr(Config, "GRAPHITI_EMBEDDING_DIM", 1024)
    monkeypatch.setattr(Config, "GRAPHITI_OLLAMA_EMBED_URL", "http://127.0.0.1:11434/api/embed")

    context = graph_build_context(project_id="proj_test", graph_id="graph_test")

    assert context["llm_base_url"] == "https://graphiti-llm.example/v1"
    assert context["llm_chat_protocol"] == "openai"
    assert context["llm_model"] == "graphiti-model"


def test_format_graph_exception_explains_neo4j_auth_error(monkeypatch):
    from neo4j.exceptions import AuthError

    monkeypatch.setattr(Config, "GRAPHITI_NEO4J_URI", "bolt://localhost:7687")
    monkeypatch.setattr(Config, "GRAPHITI_NEO4J_USER", "neo4j")

    try:
        raise AuthError("bad auth")
    except Exception as exc:
        diagnostics = format_graph_exception(exc)

    assert "Neo4j认证失败" in diagnostics.summary
    assert "GRAPHITI_NEO4J_PASSWORD" in diagnostics.detail
    assert "neo4j_data" in diagnostics.detail


def test_get_backend_name_defaults_to_supported_value(monkeypatch):
    monkeypatch.setattr(Config, "GRAPH_BACKEND", "graphiti")
    assert get_backend_name() == "graphiti"


def test_get_backend_name_rejects_invalid_value(monkeypatch):
    monkeypatch.setattr(Config, "GRAPH_BACKEND", "invalid")

    try:
        get_backend_name()
    except ValueError as exc:
        assert "GRAPH_BACKEND" in str(exc)
    else:
        raise AssertionError("invalid backend should raise")


def test_graphiti_entity_type_conversion_sanitizes_reserved_fields():
    ontology = {
        "entity_types": [
            {
                "name": "Player",
                "description": "A tournament player.",
                "attributes": [
                    {"name": "name", "description": "Reserved field"},
                    {"name": "role", "description": "Role"},
                ],
            }
        ]
    }

    entity_types = build_graphiti_entity_types(ontology)

    assert "Player" in entity_types
    fields = entity_types["Player"].model_fields
    assert "entity_name" in fields
    assert "role" in fields
    assert "name" not in fields


def test_graphiti_entity_type_conversion_preserves_chinese_attribute_names():
    ontology = {
        "entity_types": [
            {
                "name": "Organization",
                "description": "A tournament organization.",
                "attributes": [
                    {"name": "组织名称", "description": "组织名称"},
                    {"name": "影响力 分级", "description": "影响力分级"},
                ],
            }
        ]
    }

    entity_types = build_graphiti_entity_types(ontology)

    fields = entity_types["Organization"].model_fields
    assert "组织名称" in fields
    assert "影响力_分级" in fields

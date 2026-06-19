"""
配置管理
统一从项目根目录的 .env 文件加载配置
"""

import os
from urllib.parse import urlparse, urlunparse

from dotenv import load_dotenv

from .llm_protocol import (
    chat_protocol_requires_api_key,
    llm_api_key_or_dummy,
    normalize_chat_protocol,
    unsupported_chat_protocol_error,
)

# 加载项目根目录的 .env 文件
# 路径: GoalFish/.env (相对于 backend/app/config.py)
project_root_env = os.path.join(os.path.dirname(__file__), '../../.env')

if os.path.exists(project_root_env):
    load_dotenv(project_root_env, override=True)
else:
    # 如果根目录没有 .env，尝试加载环境变量（用于生产环境）
    load_dotenv(override=True)


def _infer_graphiti_embedding_provider() -> str:
    provider = os.environ.get('GRAPHITI_EMBEDDING_PROVIDER')
    if provider:
        return provider.lower()

    legacy_base_url = os.environ.get('GRAPHITI_EMBEDDING_BASE_URL', '')
    ollama_url = os.environ.get('GRAPHITI_OLLAMA_EMBED_URL', '')
    if ollama_url or legacy_base_url.rstrip('/').endswith('/api/embed'):
        return 'ollama'
    return 'openai'


def _get_graphiti_ollama_embed_url() -> str:
    embed_url = (
        os.environ.get('GRAPHITI_OLLAMA_EMBED_URL')
        or os.environ.get('GRAPHITI_EMBEDDING_BASE_URL')
        or 'http://127.0.0.1:11434/api/embed'
    )
    return _normalize_ollama_localhost_url(embed_url)


def _normalize_ollama_localhost_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname != 'localhost':
        return url

    netloc = '127.0.0.1'
    if parsed.port:
        netloc = f'{netloc}:{parsed.port}'
    if parsed.username:
        userinfo = parsed.username
        if parsed.password:
            userinfo = f'{userinfo}:{parsed.password}'
        netloc = f'{userinfo}@{netloc}'

    return urlunparse(parsed._replace(netloc=netloc))


def _get_graphiti_embedding_model(provider: str) -> str:
    return (
        os.environ.get('GRAPHITI_EMBEDDING_MODEL')
        or ('qwen3-embedding' if provider == 'ollama' else 'text-embedding-3-small')
    )


_RAW_LLM_API_KEY = os.environ.get('LLM_API_KEY')


class Config:
    """Flask配置类"""
    
    # Flask配置
    SECRET_KEY = os.environ.get('SECRET_KEY', 'goalfish-secret-key')
    DEBUG = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    
    # JSON配置 - 禁用ASCII转义，让中文直接显示（而不是 \uXXXX 格式）
    JSON_AS_ASCII = False
    
    # LLM配置
    # LLM_CHAT_PROTOCOL:
    # - auto: 根据 URL 兼容旧配置推断
    # - openai: OpenAI-compatible /v1/chat/completions
    # - ollama: Ollama native /api/chat
    # - anthropic: 预留，当前未实现原生 /v1/messages 适配器
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.openai.com/v1')
    LLM_CHAT_PROTOCOL = normalize_chat_protocol(os.environ.get('LLM_CHAT_PROTOCOL', 'auto'))
    LLM_API_KEY = llm_api_key_or_dummy(_RAW_LLM_API_KEY, LLM_BASE_URL, LLM_CHAT_PROTOCOL)
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'gpt-4o-mini')
    LLM_DISABLE_THINKING = os.environ.get('LLM_DISABLE_THINKING', 'disabled').lower()

    # Football Step4/Step5 prediction report LLM. Empty values reuse global LLM_*.
    PREDICTION_REPORT_LLM_BASE_URL = os.environ.get('PREDICTION_REPORT_LLM_BASE_URL') or LLM_BASE_URL
    PREDICTION_REPORT_LLM_CHAT_PROTOCOL = normalize_chat_protocol(
        os.environ.get('PREDICTION_REPORT_LLM_CHAT_PROTOCOL') or LLM_CHAT_PROTOCOL
    )
    PREDICTION_REPORT_LLM_API_KEY = llm_api_key_or_dummy(
        os.environ.get('PREDICTION_REPORT_LLM_API_KEY') or _RAW_LLM_API_KEY,
        PREDICTION_REPORT_LLM_BASE_URL,
        PREDICTION_REPORT_LLM_CHAT_PROTOCOL,
    )
    PREDICTION_REPORT_LLM_MODEL_NAME = os.environ.get('PREDICTION_REPORT_LLM_MODEL_NAME') or LLM_MODEL_NAME
    
    # 任务事件化与持久化配置
    DATABASE_URL = os.environ.get('DATABASE_URL')
    SQLALCHEMY_ECHO = os.environ.get('SQLALCHEMY_ECHO', 'False').lower() == 'true'
    TASK_WORKFLOW_AUTO_CREATE_TABLES = (
        os.environ.get('TASK_WORKFLOW_AUTO_CREATE_TABLES', 'true').lower()
        in {'1', 'true', 'yes', 'on'}
    )
    TASK_WORKFLOW_FAIL_OPEN = (
        os.environ.get('TASK_WORKFLOW_FAIL_OPEN', 'true').lower()
        in {'1', 'true', 'yes', 'on'}
    )

    REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL') or REDIS_URL
    CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND') or REDIS_URL
    CELERY_TASK_DEFAULT_QUEUE = os.environ.get('CELERY_TASK_DEFAULT_QUEUE', 'goalfish')
    WORKFLOW_EVENT_MAX_RETRIES = int(os.environ.get('WORKFLOW_EVENT_MAX_RETRIES', '2'))
    WORKFLOW_EVENT_RETRY_BACKOFF_SECONDS = int(os.environ.get('WORKFLOW_EVENT_RETRY_BACKOFF_SECONDS', '30'))
    PREDICTION_ASYNC_STALE_SECONDS = int(os.environ.get('PREDICTION_ASYNC_STALE_SECONDS', '1800'))
    GRAPH_BUILD_EXECUTOR = os.environ.get('GRAPH_BUILD_EXECUTOR', 'celery').lower()

    # 图谱后端配置：公开版只支持本地 Graphiti
    GRAPH_BACKEND = os.environ.get('GRAPH_BACKEND', 'graphiti').lower()

    # Graphiti 配置
    GRAPHITI_NEO4J_URI = os.environ.get('GRAPHITI_NEO4J_URI', os.environ.get('NEO4J_URI', 'bolt://localhost:7687'))
    GRAPHITI_NEO4J_USER = os.environ.get('GRAPHITI_NEO4J_USER', os.environ.get('NEO4J_USER', 'neo4j'))
    GRAPHITI_NEO4J_PASSWORD = os.environ.get('GRAPHITI_NEO4J_PASSWORD', os.environ.get('NEO4J_PASSWORD'))
    GRAPHITI_LLM_BASE_URL = os.environ.get('GRAPHITI_LLM_BASE_URL') or LLM_BASE_URL
    GRAPHITI_LLM_CHAT_PROTOCOL = normalize_chat_protocol(
        os.environ.get('GRAPHITI_LLM_CHAT_PROTOCOL') or LLM_CHAT_PROTOCOL
    )
    GRAPHITI_LLM_API_KEY = llm_api_key_or_dummy(
        os.environ.get('GRAPHITI_LLM_API_KEY') or _RAW_LLM_API_KEY,
        GRAPHITI_LLM_BASE_URL,
        GRAPHITI_LLM_CHAT_PROTOCOL,
    )
    GRAPHITI_LLM_MODEL = os.environ.get('GRAPHITI_LLM_MODEL') or LLM_MODEL_NAME
    GRAPHITI_EMBEDDING_PROVIDER = _infer_graphiti_embedding_provider()
    GRAPHITI_EMBEDDING_API_KEY = os.environ.get('GRAPHITI_EMBEDDING_API_KEY') or _RAW_LLM_API_KEY
    GRAPHITI_EMBEDDING_BASE_URL = os.environ.get('GRAPHITI_EMBEDDING_BASE_URL') or LLM_BASE_URL
    GRAPHITI_OLLAMA_EMBED_URL = _get_graphiti_ollama_embed_url()
    GRAPHITI_EMBEDDING_MODEL = _get_graphiti_embedding_model(GRAPHITI_EMBEDDING_PROVIDER)
    GRAPHITI_EMBEDDING_DIM = int(os.environ.get('GRAPHITI_EMBEDDING_DIM', '1024'))
    GRAPHITI_OLLAMA_MAX_CONCURRENCY = int(os.environ.get('GRAPHITI_OLLAMA_MAX_CONCURRENCY', '1'))
    GRAPHITI_OLLAMA_MAX_RETRIES = int(os.environ.get('GRAPHITI_OLLAMA_MAX_RETRIES', '3'))
    GRAPHITI_OLLAMA_RETRY_DELAY = float(os.environ.get('GRAPHITI_OLLAMA_RETRY_DELAY', '0.5'))
    GRAPHITI_DELETE_NON_ONTOLOGY_EDGES = (
        os.environ.get('GRAPHITI_DELETE_NON_ONTOLOGY_EDGES', 'false').lower()
        in {'1', 'true', 'yes', 'on'}
    )
    
    # 文件上传配置
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../uploads')
    ALLOWED_EXTENSIONS = {'pdf', 'md', 'txt', 'markdown'}
    
    # 文本处理配置
    DEFAULT_CHUNK_SIZE = 500  # 默认切块大小
    DEFAULT_CHUNK_OVERLAP = 50  # 默认重叠大小
    
    # Report Agent配置
    REPORT_AGENT_MAX_TOOL_CALLS = int(os.environ.get('REPORT_AGENT_MAX_TOOL_CALLS', '5'))
    REPORT_AGENT_MAX_REFLECTION_ROUNDS = int(os.environ.get('REPORT_AGENT_MAX_REFLECTION_ROUNDS', '2'))
    REPORT_AGENT_TEMPERATURE = float(os.environ.get('REPORT_AGENT_TEMPERATURE', '0.5'))
    
    @classmethod
    def validate(cls) -> list[str]:
        """验证必要配置"""
        errors: list[str] = []
        protocol_error = unsupported_chat_protocol_error(cls.LLM_CHAT_PROTOCOL, 'LLM_CHAT_PROTOCOL')
        if protocol_error:
            errors.append(protocol_error)
        graphiti_protocol_error = unsupported_chat_protocol_error(
            cls.GRAPHITI_LLM_CHAT_PROTOCOL,
            'GRAPHITI_LLM_CHAT_PROTOCOL',
        )
        if graphiti_protocol_error:
            errors.append(graphiti_protocol_error)
        prediction_report_protocol_error = unsupported_chat_protocol_error(
            cls.PREDICTION_REPORT_LLM_CHAT_PROTOCOL,
            'PREDICTION_REPORT_LLM_CHAT_PROTOCOL',
        )
        if prediction_report_protocol_error:
            errors.append(prediction_report_protocol_error)

        if (
            not cls.LLM_API_KEY
            and chat_protocol_requires_api_key(cls.LLM_CHAT_PROTOCOL, cls.LLM_BASE_URL)
        ):
            errors.append("LLM_API_KEY 未配置")
        if (
            not cls.PREDICTION_REPORT_LLM_API_KEY
            and chat_protocol_requires_api_key(
                cls.PREDICTION_REPORT_LLM_CHAT_PROTOCOL,
                cls.PREDICTION_REPORT_LLM_BASE_URL,
            )
        ):
            errors.append("PREDICTION_REPORT_LLM_API_KEY 或 LLM_API_KEY 未配置")
        if cls.GRAPH_BACKEND != 'graphiti':
            errors.append("GRAPH_BACKEND 必须是 graphiti")
        if not cls.DATABASE_URL:
            errors.append("DATABASE_URL 未配置")
        if not cls.CELERY_BROKER_URL:
            errors.append("CELERY_BROKER_URL 或 REDIS_URL 未配置")
        if not cls.CELERY_RESULT_BACKEND:
            errors.append("CELERY_RESULT_BACKEND 或 REDIS_URL 未配置")
        if cls.GRAPH_BUILD_EXECUTOR not in {'thread', 'celery'}:
            errors.append("GRAPH_BUILD_EXECUTOR 必须是 thread 或 celery")
        if cls.WORKFLOW_EVENT_MAX_RETRIES < 0:
            errors.append("WORKFLOW_EVENT_MAX_RETRIES 不能小于 0")
        if cls.WORKFLOW_EVENT_RETRY_BACKOFF_SECONDS < 0:
            errors.append("WORKFLOW_EVENT_RETRY_BACKOFF_SECONDS 不能小于 0")
        if cls.PREDICTION_ASYNC_STALE_SECONDS < 0:
            errors.append("PREDICTION_ASYNC_STALE_SECONDS 不能小于 0")
        if cls.GRAPH_BACKEND == 'graphiti':
            if not cls.GRAPHITI_NEO4J_URI:
                errors.append("GRAPHITI_NEO4J_URI 未配置")
            if not cls.GRAPHITI_NEO4J_USER:
                errors.append("GRAPHITI_NEO4J_USER 未配置")
            if not cls.GRAPHITI_NEO4J_PASSWORD:
                errors.append("GRAPHITI_NEO4J_PASSWORD 未配置")
            if (
                not cls.GRAPHITI_LLM_API_KEY
                and chat_protocol_requires_api_key(
                    cls.GRAPHITI_LLM_CHAT_PROTOCOL,
                    cls.GRAPHITI_LLM_BASE_URL,
                )
            ):
                errors.append("GRAPHITI_LLM_API_KEY 或 LLM_API_KEY 未配置")
            if cls.GRAPHITI_EMBEDDING_PROVIDER not in {'openai', 'ollama'}:
                errors.append("GRAPHITI_EMBEDDING_PROVIDER 必须是 openai 或 ollama")
            if cls.GRAPHITI_EMBEDDING_PROVIDER == 'openai':
                if not cls.GRAPHITI_EMBEDDING_API_KEY:
                    errors.append("GRAPHITI_EMBEDDING_API_KEY 或 LLM_API_KEY 未配置")
                if not cls.GRAPHITI_EMBEDDING_BASE_URL:
                    errors.append("GRAPHITI_EMBEDDING_BASE_URL 或 LLM_BASE_URL 未配置")
            if cls.GRAPHITI_EMBEDDING_PROVIDER == 'ollama' and not cls.GRAPHITI_OLLAMA_EMBED_URL:
                errors.append("GRAPHITI_OLLAMA_EMBED_URL 未配置")
            if not cls.GRAPHITI_EMBEDDING_MODEL:
                errors.append("GRAPHITI_EMBEDDING_MODEL 未配置")
            if cls.GRAPHITI_EMBEDDING_DIM <= 0:
                errors.append("GRAPHITI_EMBEDDING_DIM 必须大于 0")
            if cls.GRAPHITI_EMBEDDING_PROVIDER == 'ollama':
                if cls.GRAPHITI_OLLAMA_MAX_CONCURRENCY <= 0:
                    errors.append("GRAPHITI_OLLAMA_MAX_CONCURRENCY 必须大于 0")
                if cls.GRAPHITI_OLLAMA_MAX_RETRIES <= 0:
                    errors.append("GRAPHITI_OLLAMA_MAX_RETRIES 必须大于 0")
                if cls.GRAPHITI_OLLAMA_RETRY_DELAY < 0:
                    errors.append("GRAPHITI_OLLAMA_RETRY_DELAY 不能小于 0")
        return errors

"""
Celery application entrypoint.
"""

from celery import Celery

from .config import Config
from .utils import llm_logging


llm_logging.install_llm_completion_logging()

celery_app = Celery(
    "goalfish",
    broker=Config.CELERY_BROKER_URL,
    backend=Config.CELERY_RESULT_BACKEND,
    include=["app.tasks.workflow_tasks"],
)

celery_app.conf.update(
    task_default_queue=Config.CELERY_TASK_DEFAULT_QUEUE,
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=True,
    # Celery 默认会把 stdout/stderr 捕获成 WARNING 级别日志。
    # 项目自己的 logger 已经按 logback 风格格式化输出，关闭重定向可以避免
    # “外层 WARNING + 内层 DEBUG/INFO”的双重日志格式。
    worker_redirect_stdouts=False,
)

"""
Fail-open wrappers for dual-writing workflow state during incremental migration.
"""

from collections.abc import Callable
from typing import TypeVar

from ..config import Config
from ..utils.logger import get_logger
from .task_workflow import TaskWorkflowService


T = TypeVar("T")
logger = get_logger("goalfish.task_workflow")


def try_workflow(operation: str, callback: Callable[[TaskWorkflowService], T]) -> T | None:
    try:
        return callback(TaskWorkflowService())
    except Exception as exc:
        if Config.TASK_WORKFLOW_FAIL_OPEN:
            logger.warning("任务事件持久化失败，旧流程继续执行: operation=%s, error=%s", operation, exc)
            return None
        raise

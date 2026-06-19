"""
Context helpers for attaching LLM interactions to workflow events.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class LLMAuditContext:
    task_id: str | None = None
    attempt_id: str | None = None
    event_id: str | None = None
    operation: str | None = None


_current_llm_context: ContextVar[LLMAuditContext] = ContextVar(
    "goalfish_llm_audit_context",
    default=LLMAuditContext(),
)


def get_current_llm_context() -> LLMAuditContext:
    return _current_llm_context.get()


@contextmanager
def llm_audit_context(
    *,
    task_id: str | None = None,
    attempt_id: str | None = None,
    event_id: str | None = None,
    operation: str | None = None,
) -> Iterator[LLMAuditContext]:
    parent = get_current_llm_context()
    context = LLMAuditContext(
        task_id=task_id if task_id is not None else parent.task_id,
        attempt_id=attempt_id if attempt_id is not None else parent.attempt_id,
        event_id=event_id if event_id is not None else parent.event_id,
        operation=operation if operation is not None else parent.operation,
    )
    token = _current_llm_context.set(context)
    try:
        yield context
    finally:
        _current_llm_context.reset(token)

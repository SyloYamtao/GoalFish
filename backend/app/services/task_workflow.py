"""
Persistent task workflow service.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import func, select

from ..config import Config
from ..db.models import (
    CeleryJobRecord,
    GraphBindingRecord,
    LLMInteractionRecord,
    PredictionTaskRecord,
    TaskArtifactRecord,
    TaskAttemptRecord,
    TaskEventRecord,
    utc_now,
)
from ..db.session import get_session, init_db


class WorkflowStateError(ValueError):
    pass


class TaskStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AttemptStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EventStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    REUSED = "reused"
    CANCELLED = "cancelled"


class GraphBindingStatus(str, Enum):
    CREATING = "creating"
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"
    DELETED = "deleted"


class CeleryJobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


DEFAULT_EVENT_SEQUENCE: tuple[tuple[int, str], ...] = (
    (10, "upload_files"),
    (20, "extract_match_material"),
    (30, "generate_football_ontology"),
    (40, "build_match_graph"),
    (50, "extract_team_context"),
    (60, "build_prediction_config"),
    (70, "compute_team_strength"),
    (80, "generate_scenario_matrix"),
    (90, "compute_scoreline_distribution"),
    (100, "generate_match_events"),
    (110, "generate_analyst_notes"),
    (120, "generate_report"),
    (130, "prepare_prediction_qa"),
)

ALLOWED_EVENT_TRANSITIONS: dict[EventStatus, set[EventStatus]] = {
    EventStatus.PENDING: {
        EventStatus.RUNNING,
        EventStatus.SKIPPED,
        EventStatus.REUSED,
        EventStatus.CANCELLED,
    },
    EventStatus.RUNNING: {
        EventStatus.RUNNING,
        EventStatus.SUCCEEDED,
        EventStatus.FAILED,
        EventStatus.CANCELLED,
    },
    EventStatus.FAILED: {EventStatus.RUNNING},
    EventStatus.SUCCEEDED: set(),
    EventStatus.SKIPPED: set(),
    EventStatus.REUSED: set(),
    EventStatus.CANCELLED: set(),
}


def _enum_value(value: str | Enum) -> str:
    return value.value if isinstance(value, Enum) else str(value)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def event_sequence_for(event_type: str) -> int:
    for sequence, candidate in DEFAULT_EVENT_SEQUENCE:
        if candidate == event_type:
            return sequence
    raise ValueError(f"未知事件类型: {event_type}")


def _task_to_dict(task: PredictionTaskRecord, active_attempt: TaskAttemptRecord | None = None) -> dict[str, Any]:
    return {
        "id": task.id,
        "project_id": task.project_id,
        "name": task.name,
        "status": task.status,
        "active_attempt_id": task.active_attempt_id,
        "active_attempt": _attempt_to_dict(active_attempt) if active_attempt else None,
        "created_at": _as_iso(task.created_at),
        "updated_at": _as_iso(task.updated_at),
        "completed_at": _as_iso(task.completed_at),
        "metadata": task.task_metadata or {},
    }


def _attempt_to_dict(attempt: TaskAttemptRecord) -> dict[str, Any]:
    return {
        "id": attempt.id,
        "task_id": attempt.task_id,
        "attempt_no": attempt.attempt_no,
        "status": attempt.status,
        "source_attempt_id": attempt.source_attempt_id,
        "rerun_from_event_type": attempt.rerun_from_event_type,
        "created_at": _as_iso(attempt.created_at),
        "started_at": _as_iso(attempt.started_at),
        "finished_at": _as_iso(attempt.finished_at),
        "config": attempt.config or {},
        "metadata": attempt.attempt_metadata or {},
    }


def _event_to_dict(event: TaskEventRecord) -> dict[str, Any]:
    return {
        "id": event.id,
        "task_id": event.task_id,
        "attempt_id": event.attempt_id,
        "event_type": event.event_type,
        "sequence": event.sequence,
        "status": event.status,
        "progress": event.progress,
        "started_at": _as_iso(event.started_at),
        "finished_at": _as_iso(event.finished_at),
        "input_artifact_ids": event.input_artifact_ids or [],
        "output_artifact_ids": event.output_artifact_ids or [],
        "reused_from_event_id": event.reused_from_event_id,
        "error_code": event.error_code,
        "error_message": event.error_message,
        "error_traceback": event.error_traceback,
        "metadata": event.event_metadata or {},
    }


def _artifact_to_dict(artifact: TaskArtifactRecord) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "task_id": artifact.task_id,
        "attempt_id": artifact.attempt_id,
        "event_id": artifact.event_id,
        "artifact_type": artifact.artifact_type,
        "storage_kind": artifact.storage_kind,
        "name": artifact.name,
        "mime_type": artifact.mime_type,
        "content_text": artifact.content_text,
        "content_json": artifact.content_json,
        "file_path": artifact.file_path,
        "checksum": artifact.checksum,
        "size_bytes": artifact.size_bytes,
        "created_at": _as_iso(artifact.created_at),
        "metadata": artifact.artifact_metadata or {},
    }


def _artifact_to_summary(artifact: TaskArtifactRecord) -> dict[str, Any]:
    return {
        "id": artifact.id,
        "task_id": artifact.task_id,
        "attempt_id": artifact.attempt_id,
        "event_id": artifact.event_id,
        "artifact_type": artifact.artifact_type,
        "storage_kind": artifact.storage_kind,
        "name": artifact.name,
        "mime_type": artifact.mime_type,
        "file_path": artifact.file_path,
        "checksum": artifact.checksum,
        "size_bytes": artifact.size_bytes,
        "created_at": _as_iso(artifact.created_at),
        "metadata": artifact.artifact_metadata or {},
        "has_content_text": artifact.content_text is not None,
        "has_content_json": artifact.content_json is not None,
    }


def _graph_binding_to_dict(binding: GraphBindingRecord) -> dict[str, Any]:
    return {
        "id": binding.id,
        "task_id": binding.task_id,
        "attempt_id": binding.attempt_id,
        "project_id": binding.project_id,
        "graph_backend": binding.graph_backend,
        "graph_id": binding.graph_id,
        "group_id": binding.group_id,
        "neo4j_uri": binding.neo4j_uri,
        "status": binding.status,
        "node_count": binding.node_count,
        "edge_count": binding.edge_count,
        "created_at": _as_iso(binding.created_at),
        "updated_at": _as_iso(binding.updated_at),
        "metadata": binding.binding_metadata or {},
    }


def _llm_interaction_to_dict(record: LLMInteractionRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "task_id": record.task_id,
        "attempt_id": record.attempt_id,
        "event_id": record.event_id,
        "request_id": record.request_id,
        "provider": record.provider,
        "base_url": record.base_url,
        "model": record.model,
        "operation": record.operation,
        "messages": record.messages,
        "request_params": record.request_params,
        "response": record.response,
        "response_text": record.response_text,
        "status": record.status,
        "error_message": record.error_message,
        "error_traceback": record.error_traceback,
        "prompt_tokens": record.prompt_tokens,
        "completion_tokens": record.completion_tokens,
        "total_tokens": record.total_tokens,
        "latency_ms": record.latency_ms,
        "created_at": _as_iso(record.created_at),
        "finished_at": _as_iso(record.finished_at),
        "metadata": record.interaction_metadata or {},
    }


def _celery_job_to_dict(record: CeleryJobRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "task_id": record.task_id,
        "attempt_id": record.attempt_id,
        "event_id": record.event_id,
        "celery_task_id": record.celery_task_id,
        "queue_name": record.queue_name,
        "status": record.status,
        "created_at": _as_iso(record.created_at),
        "started_at": _as_iso(record.started_at),
        "finished_at": _as_iso(record.finished_at),
        "last_error": record.last_error,
        "metadata": record.job_metadata or {},
    }


@dataclass
class TaskWorkflowService:
    auto_init: bool = True

    def __post_init__(self) -> None:
        if self.auto_init and Config.TASK_WORKFLOW_AUTO_CREATE_TABLES:
            init_db()

    def create_task(
        self,
        *,
        project_id: str | None,
        name: str,
        metadata: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with get_session() as session:
            task = PredictionTaskRecord(
                project_id=project_id,
                name=name,
                status=TaskStatus.CREATED.value,
                task_metadata=metadata or {},
            )
            session.add(task)
            session.flush()

            attempt = TaskAttemptRecord(
                task_id=task.id,
                attempt_no=1,
                status=AttemptStatus.CREATED.value,
                config=config or {},
            )
            session.add(attempt)
            session.flush()

            task.active_attempt_id = attempt.id
            self._create_default_events(session, task.id, attempt.id)
            session.flush()
            return _task_to_dict(task, attempt)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with get_session() as session:
            task = session.get(PredictionTaskRecord, task_id)
            if task is None:
                return None
            active_attempt = session.get(TaskAttemptRecord, task.active_attempt_id) if task.active_attempt_id else None
            return _task_to_dict(task, active_attempt)

    def get_task_by_project_id(self, project_id: str) -> dict[str, Any] | None:
        with get_session() as session:
            task = session.execute(
                select(PredictionTaskRecord)
                .where(PredictionTaskRecord.project_id == project_id)
                .order_by(PredictionTaskRecord.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if task is None:
                return None
            active_attempt = session.get(TaskAttemptRecord, task.active_attempt_id) if task.active_attempt_id else None
            return _task_to_dict(task, active_attempt)

    def get_task_snapshot(self, task_id: str) -> dict[str, Any] | None:
        with get_session() as session:
            task = session.get(PredictionTaskRecord, task_id)
            if task is None:
                return None
            return self._build_snapshot(session, task)

    def get_task_snapshot_by_project_id(self, project_id: str) -> dict[str, Any] | None:
        with get_session() as session:
            task = session.execute(
                select(PredictionTaskRecord)
                .where(PredictionTaskRecord.project_id == project_id)
                .order_by(PredictionTaskRecord.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            if task is None:
                return None
            return self._build_snapshot(session, task)

    def get_or_create_task_for_project(
        self,
        *,
        project_id: str,
        name: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = self.get_task_by_project_id(project_id)
        if existing:
            return existing
        return self.create_task(project_id=project_id, name=name, metadata=metadata)

    def list_attempts(self, task_id: str) -> list[dict[str, Any]]:
        with get_session() as session:
            attempts = session.execute(
                select(TaskAttemptRecord)
                .where(TaskAttemptRecord.task_id == task_id)
                .order_by(TaskAttemptRecord.attempt_no.asc())
            ).scalars().all()
            return [_attempt_to_dict(attempt) for attempt in attempts]

    def list_events(self, task_id: str, attempt_id: str | None = None) -> list[dict[str, Any]]:
        with get_session() as session:
            if attempt_id is None:
                task = session.get(PredictionTaskRecord, task_id)
                if task is None or not task.active_attempt_id:
                    return []
                attempt_id = task.active_attempt_id
            events = session.execute(
                select(TaskEventRecord)
                .where(TaskEventRecord.task_id == task_id, TaskEventRecord.attempt_id == attempt_id)
                .order_by(TaskEventRecord.sequence.asc())
            ).scalars().all()
            return [_event_to_dict(event) for event in events]

    def get_event(self, task_id: str, attempt_id: str, event_type: str) -> dict[str, Any] | None:
        with get_session() as session:
            event = self._get_event_record(session, task_id, attempt_id, event_type)
            return _event_to_dict(event) if event else None

    def get_resume_event(
        self,
        task_id: str,
        *,
        attempt_id: str | None = None,
        from_event_type: str | None = None,
    ) -> dict[str, Any]:
        with get_session() as session:
            task = session.get(PredictionTaskRecord, task_id)
            if task is None:
                raise KeyError(f"任务不存在: {task_id}")
            resolved_attempt_id = attempt_id or task.active_attempt_id
            if not resolved_attempt_id:
                raise WorkflowStateError("任务没有 active attempt")

            if from_event_type:
                event = self._require_event_record(session, task_id, resolved_attempt_id, from_event_type)
            else:
                events = self._list_event_records(session, task_id, resolved_attempt_id)
                event = self._pick_resume_event(events)

            if event is None:
                raise WorkflowStateError("当前 attempt 没有可恢复事件")
            if event.status in {
                EventStatus.SUCCEEDED.value,
                EventStatus.SKIPPED.value,
                EventStatus.REUSED.value,
                EventStatus.CANCELLED.value,
            }:
                raise WorkflowStateError(f"事件已结束，不能 resume: {event.event_type}")
            return _event_to_dict(event)

    def start_event(
        self,
        task_id: str,
        attempt_id: str,
        event_type: str,
        *,
        progress: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with get_session() as session:
            event = self._require_event_record(session, task_id, attempt_id, event_type)
            self._transition_event_record(
                event,
                EventStatus.RUNNING,
                progress=progress,
                metadata=metadata,
            )
            task = session.get(PredictionTaskRecord, task_id)
            attempt = session.get(TaskAttemptRecord, attempt_id)
            if task:
                task.status = TaskStatus.RUNNING.value
            if attempt:
                attempt.status = AttemptStatus.RUNNING.value
                attempt.started_at = attempt.started_at or _now()
            return _event_to_dict(event)

    def transition_event(
        self,
        event_id: str,
        status: EventStatus | str,
        *,
        progress: int | None = None,
        metadata: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        error_traceback: str | None = None,
    ) -> dict[str, Any]:
        with get_session() as session:
            event = session.get(TaskEventRecord, event_id)
            if event is None:
                raise KeyError(f"事件不存在: {event_id}")
            self._transition_event_record(
                event,
                status,
                progress=progress,
                metadata=metadata,
                error_code=error_code,
                error_message=error_message,
                error_traceback=error_traceback,
            )
            return _event_to_dict(event)

    def succeed_event(
        self,
        event_id: str,
        *,
        progress: int = 100,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.transition_event(event_id, EventStatus.SUCCEEDED, progress=progress, metadata=metadata)

    def fail_event(
        self,
        event_id: str,
        *,
        error_message: str,
        error_code: str | None = None,
        error_traceback: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with get_session() as session:
            event = session.get(TaskEventRecord, event_id)
            if event is None:
                raise KeyError(f"事件不存在: {event_id}")
            self._transition_event_record(
                event,
                EventStatus.FAILED,
                error_code=error_code,
                error_message=error_message,
                error_traceback=error_traceback,
                metadata=metadata,
            )
            task = session.get(PredictionTaskRecord, event.task_id)
            attempt = session.get(TaskAttemptRecord, event.attempt_id)
            if task:
                task.status = TaskStatus.FAILED.value
            if attempt:
                attempt.status = AttemptStatus.FAILED.value
                attempt.finished_at = _now()
            return _event_to_dict(event)

    def complete_task_if_all_events_finished(self, task_id: str, attempt_id: str) -> dict[str, Any] | None:
        """Mark task/attempt completed once every event in an attempt has finished."""
        terminal_statuses = {
            EventStatus.SUCCEEDED.value,
            EventStatus.SKIPPED.value,
            EventStatus.REUSED.value,
            EventStatus.CANCELLED.value,
        }
        with get_session() as session:
            events = self._list_event_records(session, task_id, attempt_id)
            if not events or any(event.status not in terminal_statuses for event in events):
                return None

            task = session.get(PredictionTaskRecord, task_id)
            attempt = session.get(TaskAttemptRecord, attempt_id)
            if task:
                task.status = TaskStatus.COMPLETED.value
                task.completed_at = _now()
            if attempt:
                attempt.status = AttemptStatus.COMPLETED.value
                attempt.finished_at = _now()
            return _task_to_dict(task, attempt) if task else None

    def create_rerun_attempt(
        self,
        task_id: str,
        *,
        from_event_type: str,
        config_overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from_sequence = event_sequence_for(from_event_type)
        with get_session() as session:
            task = session.get(PredictionTaskRecord, task_id)
            if task is None:
                raise KeyError(f"任务不存在: {task_id}")
            source_attempt_id = task.active_attempt_id
            source_events = {
                event.event_type: event
                for event in session.execute(
                    select(TaskEventRecord).where(TaskEventRecord.attempt_id == source_attempt_id)
                ).scalars().all()
            }
            max_attempt_no = session.execute(
                select(func.max(TaskAttemptRecord.attempt_no)).where(TaskAttemptRecord.task_id == task_id)
            ).scalar_one() or 0
            source_attempt = session.get(TaskAttemptRecord, source_attempt_id) if source_attempt_id else None
            new_config = dict(source_attempt.config if source_attempt else {})
            if config_overrides:
                new_config.update(config_overrides)

            attempt = TaskAttemptRecord(
                task_id=task_id,
                attempt_no=max_attempt_no + 1,
                status=AttemptStatus.CREATED.value,
                source_attempt_id=source_attempt_id,
                rerun_from_event_type=from_event_type,
                config=new_config,
            )
            session.add(attempt)
            session.flush()
            task.active_attempt_id = attempt.id
            task.status = TaskStatus.CREATED.value

            for sequence, event_type in DEFAULT_EVENT_SEQUENCE:
                source_event = source_events.get(event_type)
                status = EventStatus.REUSED.value if sequence < from_sequence and source_event else EventStatus.PENDING.value
                event = TaskEventRecord(
                    task_id=task_id,
                    attempt_id=attempt.id,
                    event_type=event_type,
                    sequence=sequence,
                    status=status,
                    progress=100 if status == EventStatus.REUSED.value else 0,
                    reused_from_event_id=source_event.id if status == EventStatus.REUSED.value else None,
                    finished_at=_now() if status == EventStatus.REUSED.value else None,
                    event_metadata={
                        "reused_from_attempt_id": source_attempt_id,
                    } if status == EventStatus.REUSED.value else {},
                )
                session.add(event)
            session.flush()
            return _task_to_dict(task, attempt)

    def mark_running_events_interrupted(
        self,
        *,
        task_id: str,
        attempt_id: str | None = None,
        message: str = "任务执行被中断，请从该节点继续",
    ) -> list[dict[str, Any]]:
        with get_session() as session:
            query = select(TaskEventRecord).where(
                TaskEventRecord.task_id == task_id,
                TaskEventRecord.status == EventStatus.RUNNING.value,
            )
            if attempt_id:
                query = query.where(TaskEventRecord.attempt_id == attempt_id)
            events = session.execute(query).scalars().all()
            updated: list[dict[str, Any]] = []
            for event in events:
                self._transition_event_record(
                    event,
                    EventStatus.FAILED,
                    error_code="interrupted",
                    error_message=message,
                )
                updated.append(_event_to_dict(event))
            if updated:
                task = session.get(PredictionTaskRecord, task_id)
                attempt = session.get(TaskAttemptRecord, attempt_id) if attempt_id else None
                if task:
                    task.status = TaskStatus.FAILED.value
                if attempt:
                    attempt.status = AttemptStatus.FAILED.value
                    attempt.finished_at = _now()
            return updated

    def create_artifact(
        self,
        *,
        task_id: str,
        attempt_id: str,
        event_id: str | None,
        artifact_type: str,
        storage_kind: str = "postgres_json",
        name: str | None = None,
        mime_type: str | None = None,
        content_text: str | None = None,
        content_json: Any | None = None,
        file_path: str | None = None,
        checksum: str | None = None,
        size_bytes: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with get_session() as session:
            artifact = TaskArtifactRecord(
                task_id=task_id,
                attempt_id=attempt_id,
                event_id=event_id,
                artifact_type=artifact_type,
                storage_kind=storage_kind,
                name=name,
                mime_type=mime_type,
                content_text=content_text,
                content_json=content_json,
                file_path=file_path,
                checksum=checksum,
                size_bytes=size_bytes,
                artifact_metadata=metadata or {},
            )
            session.add(artifact)
            session.flush()
            if event_id:
                event = session.get(TaskEventRecord, event_id)
                if event:
                    output_ids = list(event.output_artifact_ids or [])
                    output_ids.append(artifact.id)
                    event.output_artifact_ids = output_ids
            return _artifact_to_dict(artifact)

    def list_artifacts(
        self,
        task_id: str,
        *,
        attempt_id: str | None = None,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        with get_session() as session:
            query = select(TaskArtifactRecord).where(TaskArtifactRecord.task_id == task_id)
            if attempt_id:
                query = query.where(TaskArtifactRecord.attempt_id == attempt_id)
            if event_type:
                event_ids = select(TaskEventRecord.id).where(
                    TaskEventRecord.task_id == task_id,
                    TaskEventRecord.event_type == event_type,
                )
                if attempt_id:
                    event_ids = event_ids.where(TaskEventRecord.attempt_id == attempt_id)
                query = query.where(TaskArtifactRecord.event_id.in_(event_ids))
            artifacts = session.execute(query.order_by(TaskArtifactRecord.created_at.asc())).scalars().all()
            return [_artifact_to_dict(artifact) for artifact in artifacts]

    def create_graph_binding(
        self,
        *,
        task_id: str,
        attempt_id: str,
        project_id: str | None,
        graph_backend: str,
        graph_id: str,
        group_id: str,
        neo4j_uri: str | None = None,
        status: GraphBindingStatus | str = GraphBindingStatus.CREATING,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with get_session() as session:
            binding = GraphBindingRecord(
                task_id=task_id,
                attempt_id=attempt_id,
                project_id=project_id,
                graph_backend=graph_backend,
                graph_id=graph_id,
                group_id=group_id,
                neo4j_uri=neo4j_uri,
                status=_enum_value(status),
                binding_metadata=metadata or {},
            )
            session.add(binding)
            session.flush()
            return _graph_binding_to_dict(binding)

    def update_graph_binding(
        self,
        binding_id: str,
        *,
        status: GraphBindingStatus | str | None = None,
        node_count: int | None = None,
        edge_count: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with get_session() as session:
            binding = session.get(GraphBindingRecord, binding_id)
            if binding is None:
                raise KeyError(f"图谱绑定不存在: {binding_id}")
            if status is not None:
                binding.status = _enum_value(status)
            if node_count is not None:
                binding.node_count = node_count
            if edge_count is not None:
                binding.edge_count = edge_count
            if metadata:
                merged = dict(binding.binding_metadata or {})
                merged.update(metadata)
                binding.binding_metadata = merged
            binding.updated_at = _now()
            return _graph_binding_to_dict(binding)

    def get_active_graph_binding(self, task_id: str) -> dict[str, Any] | None:
        with get_session() as session:
            task = session.get(PredictionTaskRecord, task_id)
            if task is None or not task.active_attempt_id:
                return None
            binding = session.execute(
                select(GraphBindingRecord)
                .where(GraphBindingRecord.attempt_id == task.active_attempt_id)
                .order_by(GraphBindingRecord.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()
            return _graph_binding_to_dict(binding) if binding else None

    def record_llm_interaction(
        self,
        *,
        request_id: str,
        provider: str | None,
        base_url: str | None,
        model: str | None,
        operation: str | None,
        messages: Any | None,
        request_params: Any | None,
        response: Any | None,
        response_text: str | None,
        status: str,
        task_id: str | None = None,
        attempt_id: str | None = None,
        event_id: str | None = None,
        error_message: str | None = None,
        error_traceback: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
        latency_ms: int | float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from .llm_audit import get_current_llm_context

        context = get_current_llm_context()
        with get_session() as session:
            record = LLMInteractionRecord(
                task_id=task_id if task_id is not None else context.task_id,
                attempt_id=attempt_id if attempt_id is not None else context.attempt_id,
                event_id=event_id if event_id is not None else context.event_id,
                request_id=request_id,
                provider=provider,
                base_url=base_url,
                model=model,
                operation=operation if operation is not None else context.operation,
                messages=messages,
                request_params=request_params,
                response=response,
                response_text=response_text,
                status=status,
                error_message=error_message,
                error_traceback=error_traceback,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=int(latency_ms) if latency_ms is not None else None,
                finished_at=utc_now(),
                interaction_metadata=metadata or {},
            )
            session.add(record)
            session.flush()
            return _llm_interaction_to_dict(record)

    def list_llm_interactions(
        self,
        task_id: str,
        *,
        attempt_id: str | None = None,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        with get_session() as session:
            query = select(LLMInteractionRecord).where(LLMInteractionRecord.task_id == task_id)
            if attempt_id:
                query = query.where(LLMInteractionRecord.attempt_id == attempt_id)
            if event_type:
                event_ids = select(TaskEventRecord.id).where(
                    TaskEventRecord.task_id == task_id,
                    TaskEventRecord.event_type == event_type,
                )
                if attempt_id:
                    event_ids = event_ids.where(TaskEventRecord.attempt_id == attempt_id)
                query = query.where(LLMInteractionRecord.event_id.in_(event_ids))
            records = session.execute(query.order_by(LLMInteractionRecord.created_at.asc())).scalars().all()
            return [_llm_interaction_to_dict(record) for record in records]

    def create_celery_job(
        self,
        *,
        celery_task_id: str,
        task_id: str | None = None,
        attempt_id: str | None = None,
        event_id: str | None = None,
        queue_name: str | None = None,
        status: CeleryJobStatus | str = CeleryJobStatus.QUEUED,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with get_session() as session:
            record = CeleryJobRecord(
                task_id=task_id,
                attempt_id=attempt_id,
                event_id=event_id,
                celery_task_id=celery_task_id,
                queue_name=queue_name,
                status=_enum_value(status),
                job_metadata=metadata or {},
            )
            session.add(record)
            session.flush()
            return _celery_job_to_dict(record)

    def get_celery_job(self, celery_task_id: str) -> dict[str, Any] | None:
        with get_session() as session:
            record = self._get_celery_job_record(session, celery_task_id)
            return _celery_job_to_dict(record) if record else None

    def start_celery_job(
        self,
        celery_task_id: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.update_celery_job(
            celery_task_id,
            status=CeleryJobStatus.RUNNING,
            started=True,
            metadata=metadata,
        )

    def finish_celery_job(
        self,
        celery_task_id: str,
        *,
        status: CeleryJobStatus | str,
        last_error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.update_celery_job(
            celery_task_id,
            status=status,
            finished=True,
            last_error=last_error,
            metadata=metadata,
        )

    def update_celery_job(
        self,
        celery_task_id: str,
        *,
        status: CeleryJobStatus | str | None = None,
        started: bool = False,
        finished: bool = False,
        last_error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with get_session() as session:
            record = self._get_celery_job_record(session, celery_task_id)
            if record is None:
                raise KeyError(f"Celery job 不存在: {celery_task_id}")
            if status is not None:
                record.status = _enum_value(status)
            if started:
                record.started_at = record.started_at or _now()
            if finished:
                record.finished_at = _now()
            if last_error is not None:
                record.last_error = last_error
            if metadata:
                merged = dict(record.job_metadata or {})
                merged.update(metadata)
                record.job_metadata = merged
            return _celery_job_to_dict(record)

    def list_celery_jobs(
        self,
        task_id: str,
        *,
        attempt_id: str | None = None,
        event_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with get_session() as session:
            query = select(CeleryJobRecord).where(CeleryJobRecord.task_id == task_id)
            if attempt_id:
                query = query.where(CeleryJobRecord.attempt_id == attempt_id)
            if event_id:
                query = query.where(CeleryJobRecord.event_id == event_id)
            records = session.execute(query.order_by(CeleryJobRecord.created_at.asc())).scalars().all()
            return [_celery_job_to_dict(record) for record in records]

    def find_celery_job_by_legacy_task_id(self, legacy_task_id: str) -> dict[str, Any] | None:
        with get_session() as session:
            records = session.execute(
                select(CeleryJobRecord).order_by(CeleryJobRecord.created_at.desc())
            ).scalars().all()
            for record in records:
                payload = (record.job_metadata or {}).get("payload")
                if isinstance(payload, dict) and payload.get("legacy_task_id") == legacy_task_id:
                    return _celery_job_to_dict(record)
            return None

    def _create_default_events(self, session, task_id: str, attempt_id: str) -> None:
        for sequence, event_type in DEFAULT_EVENT_SEQUENCE:
            session.add(
                TaskEventRecord(
                    task_id=task_id,
                    attempt_id=attempt_id,
                    event_type=event_type,
                    sequence=sequence,
                    status=EventStatus.PENDING.value,
                    progress=0,
                )
            )

    def _build_snapshot(self, session, task: PredictionTaskRecord) -> dict[str, Any]:
        active_attempt = session.get(TaskAttemptRecord, task.active_attempt_id) if task.active_attempt_id else None
        attempt_id = active_attempt.id if active_attempt else None
        events = self._list_event_records(session, task.id, attempt_id) if attempt_id else []
        artifact_query = select(TaskArtifactRecord).where(TaskArtifactRecord.task_id == task.id)
        if attempt_id:
            artifact_query = artifact_query.where(TaskArtifactRecord.attempt_id == attempt_id)
        artifacts = session.execute(artifact_query.order_by(TaskArtifactRecord.created_at.asc())).scalars().all()

        binding = None
        if attempt_id:
            binding = session.execute(
                select(GraphBindingRecord)
                .where(GraphBindingRecord.attempt_id == attempt_id)
                .order_by(GraphBindingRecord.created_at.desc())
                .limit(1)
            ).scalar_one_or_none()

        event_dicts = [_event_to_dict(event) for event in events]
        current_event = self._pick_current_event(events)
        resume_event = self._pick_resume_event(events)
        last_successful_event = self._pick_last_successful_event(events)
        next_pending_event = self._pick_next_pending_event(events)
        return {
            "task": _task_to_dict(task, active_attempt),
            "active_attempt": _attempt_to_dict(active_attempt) if active_attempt else None,
            "events": event_dicts,
            "artifacts": [_artifact_to_summary(artifact) for artifact in artifacts],
            "active_graph_binding": _graph_binding_to_dict(binding) if binding else None,
            "current_event": _event_to_dict(current_event) if current_event else None,
            "last_successful_event": _event_to_dict(last_successful_event) if last_successful_event else None,
            "next_pending_event": _event_to_dict(next_pending_event) if next_pending_event else None,
            "can_resume": resume_event is not None,
            "resume_from_event_type": resume_event.event_type if resume_event else None,
            "rerun_points": [
                {
                    "event_type": event.event_type,
                    "sequence": event.sequence,
                    "status": event.status,
                    "progress": event.progress,
                }
                for event in events
            ],
        }

    def _list_event_records(
        self,
        session,
        task_id: str,
        attempt_id: str | None,
    ) -> list[TaskEventRecord]:
        if attempt_id is None:
            return []
        return session.execute(
            select(TaskEventRecord)
            .where(TaskEventRecord.task_id == task_id, TaskEventRecord.attempt_id == attempt_id)
            .order_by(TaskEventRecord.sequence.asc())
        ).scalars().all()

    def _pick_current_event(self, events: list[TaskEventRecord]) -> TaskEventRecord | None:
        for status in (
            EventStatus.RUNNING.value,
            EventStatus.FAILED.value,
            EventStatus.PENDING.value,
        ):
            for event in events:
                if event.status == status:
                    return event
        return events[-1] if events else None

    def _pick_resume_event(self, events: list[TaskEventRecord]) -> TaskEventRecord | None:
        for status in (
            EventStatus.FAILED.value,
            EventStatus.RUNNING.value,
            EventStatus.PENDING.value,
        ):
            for event in events:
                if event.status == status:
                    return event
        return None

    def _pick_last_successful_event(self, events: list[TaskEventRecord]) -> TaskEventRecord | None:
        for event in reversed(events):
            if event.status in {
                EventStatus.SUCCEEDED.value,
                EventStatus.REUSED.value,
                EventStatus.SKIPPED.value,
            }:
                return event
        return None

    def _pick_next_pending_event(self, events: list[TaskEventRecord]) -> TaskEventRecord | None:
        for event in events:
            if event.status == EventStatus.PENDING.value:
                return event
        return None

    def _require_event_record(self, session, task_id: str, attempt_id: str, event_type: str) -> TaskEventRecord:
        event = self._get_event_record(session, task_id, attempt_id, event_type)
        if event is None:
            raise KeyError(f"事件不存在: task={task_id}, attempt={attempt_id}, event_type={event_type}")
        return event

    def _get_event_record(self, session, task_id: str, attempt_id: str, event_type: str) -> TaskEventRecord | None:
        return session.execute(
            select(TaskEventRecord).where(
                TaskEventRecord.task_id == task_id,
                TaskEventRecord.attempt_id == attempt_id,
                TaskEventRecord.event_type == event_type,
            )
        ).scalar_one_or_none()

    def _get_celery_job_record(self, session, celery_task_id: str) -> CeleryJobRecord | None:
        return session.execute(
            select(CeleryJobRecord).where(CeleryJobRecord.celery_task_id == celery_task_id)
        ).scalar_one_or_none()

    def _transition_event_record(
        self,
        event: TaskEventRecord,
        status: EventStatus | str,
        *,
        progress: int | None = None,
        metadata: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        error_traceback: str | None = None,
    ) -> None:
        target = EventStatus(_enum_value(status))
        current = EventStatus(event.status)
        if target not in ALLOWED_EVENT_TRANSITIONS[current]:
            raise WorkflowStateError(f"非法事件状态转换: {current.value} -> {target.value}")

        event.status = target.value
        if progress is not None:
            event.progress = max(0, min(100, int(progress)))
        if target == EventStatus.RUNNING:
            event.started_at = event.started_at or _now()
        if target in {
            EventStatus.SUCCEEDED,
            EventStatus.FAILED,
            EventStatus.SKIPPED,
            EventStatus.REUSED,
            EventStatus.CANCELLED,
        }:
            event.finished_at = _now()
        if metadata:
            merged = dict(event.event_metadata or {})
            merged.update(metadata)
            event.event_metadata = merged
        event.error_code = error_code
        event.error_message = error_message
        event.error_traceback = error_traceback

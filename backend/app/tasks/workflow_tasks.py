"""
Celery tasks for persistent workflow event execution.
"""

from __future__ import annotations

import traceback
import uuid
from typing import Any

from ..celery_app import celery_app
from ..config import Config
from ..services.graph_build_workflow import GraphBuildWorkflowRunner
from ..services.task_workflow import CeleryJobStatus, TaskWorkflowService
from ..utils.logger import get_logger


logger = get_logger("goalfish.tasks.workflow")


class UnsupportedWorkflowEventError(ValueError):
    """Raised for workflow event names that this worker cannot handle."""


def enqueue_workflow_event(
    *,
    event_type: str,
    payload: dict[str, Any],
    task_id: str | None,
    attempt_id: str | None,
    event_id: str | None = None,
) -> dict[str, Any]:
    celery_task_id = str(uuid.uuid4())
    service = TaskWorkflowService()
    job = service.create_celery_job(
        task_id=task_id,
        attempt_id=attempt_id,
        event_id=event_id,
        celery_task_id=celery_task_id,
        queue_name=Config.CELERY_TASK_DEFAULT_QUEUE,
        metadata={"event_type": event_type, "payload": payload},
    )
    try:
        execute_workflow_event.apply_async(
            kwargs={"event_type": event_type, "payload": payload},
            task_id=celery_task_id,
            queue=Config.CELERY_TASK_DEFAULT_QUEUE,
        )
    except Exception as exc:
        service.finish_celery_job(
            celery_task_id,
            status=CeleryJobStatus.FAILED,
            last_error=str(exc),
            metadata={"enqueue_traceback": traceback.format_exc()},
        )
        raise
    return job


@celery_app.task(
    bind=True,
    name="goalfish.workflow.execute_event",
    autoretry_for=(Exception,),
    dont_autoretry_for=(UnsupportedWorkflowEventError,),
    retry_backoff=Config.WORKFLOW_EVENT_RETRY_BACKOFF_SECONDS or True,
    retry_jitter=True,
    max_retries=Config.WORKFLOW_EVENT_MAX_RETRIES,
)
def execute_workflow_event(self, *, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    service = TaskWorkflowService()
    celery_task_id = self.request.id
    service.start_celery_job(
        celery_task_id,
        metadata={"event_type": event_type, "retry": self.request.retries},
    )
    try:
        if event_type == "build_match_graph":
            result = GraphBuildWorkflowRunner().run(payload)
        elif event_type == "run_prediction_from_config":
            from ..services.football_prediction import PredictionPersistenceService

            prediction_run_id = payload.get("prediction_run_id")
            prediction_config_id = payload.get("prediction_config_id")
            if not prediction_run_id or not prediction_config_id:
                raise ValueError("prediction_run_id and prediction_config_id are required")
            prediction_service = PredictionPersistenceService()
            try:
                result = prediction_service.run_pending_prediction_from_config(
                    prediction_run_id=str(prediction_run_id),
                    prediction_config_id=str(prediction_config_id),
                    force_rerun=bool(payload.get("force_rerun", False)),
                    rerun_from_event_type=payload.get("rerun_from_event_type"),
                )
            except Exception as exc:
                prediction_service.mark_prediction_failed(str(prediction_run_id), str(exc))
                raise
        elif event_type in {
            "extract_team_context",
            "build_prediction_config",
            "generate_coach_agents",
            "discuss_scenario_space_design",
            "discuss_resume_replay_policy",
            "initialize_scientific_model",
            "compute_team_strength",
            "generate_scenario_matrix",
            "compute_scoreline_distribution",
            "generate_match_events",
            "generate_nine_scenario_match_events",
            "coach_review_match_events",
            "generate_analyst_notes",
            "generate_report",
            "prepare_prediction_qa",
        }:
            from ..services.football_prediction_workflow import FootballPredictionWorkflowRunner

            result = FootballPredictionWorkflowRunner().run(event_type, payload)
        else:
            raise UnsupportedWorkflowEventError(f"暂不支持的 workflow event: {event_type}")

        service.finish_celery_job(
            celery_task_id,
            status=CeleryJobStatus.SUCCEEDED,
            metadata={"event_type": event_type, "result": result},
        )
        return result
    except Exception as exc:
        will_retry = (
            self.request.retries < Config.WORKFLOW_EVENT_MAX_RETRIES
            and not isinstance(exc, UnsupportedWorkflowEventError)
        )
        metadata = {
            "event_type": event_type,
            "retry": self.request.retries,
            "traceback": traceback.format_exc(),
        }
        if will_retry:
            service.update_celery_job(
                celery_task_id,
                status=CeleryJobStatus.RETRYING,
                last_error=str(exc),
                metadata=metadata,
            )
        else:
            service.finish_celery_job(
                celery_task_id,
                status=CeleryJobStatus.FAILED,
                last_error=str(exc),
                metadata=metadata,
            )
        logger.exception("Workflow event 执行失败: event_type=%s, celery_task_id=%s", event_type, celery_task_id)
        raise


@celery_app.task(name="goalfish.workflow.noop_event")
def noop_event(task_id: str, attempt_id: str, event_type: str) -> dict[str, Any]:
    service = TaskWorkflowService()
    event = service.get_event(task_id, attempt_id, event_type)
    return {
        "task_id": task_id,
        "attempt_id": attempt_id,
        "event_type": event_type,
        "event": event,
    }

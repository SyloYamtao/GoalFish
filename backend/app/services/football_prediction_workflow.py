"""Persistent workflow runner for football prediction events."""

from __future__ import annotations

from typing import Any

from ..models.project import ProjectManager
from ..utils.logger import get_logger
from .football_prediction import PredictionPersistenceService, PredictionReportAssembler
from .prediction_config import DEFAULT_PLAYER_DATASET_ID, PredictionConfigService
from .task_workflow import EventStatus, TaskWorkflowService


logger = get_logger("goalfish.football_prediction_workflow")


PREDICTION_EVENTS = {
    "extract_team_context",
    "build_prediction_config",
    "generate_coach_agents",
    "discuss_scenario_space_design",
    "discuss_resume_replay_policy",
    "initialize_scientific_model",
    "compute_team_strength",
    "generate_scenario_matrix",
    "compute_scoreline_distribution",
    "generate_nine_scenario_match_events",
    "generate_match_events",
    "coach_review_match_events",
    "generate_analyst_notes",
    "generate_report",
    "prepare_prediction_qa",
}


class FootballPredictionWorkflowRunner:
    """Execute football-only prediction workflow events.

    The first implementation keeps model execution deterministic and
    idempotent. If a prediction run already exists in the payload or task
    artifacts, downstream events reuse it instead of creating duplicate runs.
    """

    def run(self, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if event_type not in PREDICTION_EVENTS:
            raise ValueError(f"暂不支持的 football prediction workflow event: {event_type}")

        service = TaskWorkflowService()
        task_id = payload.get("workflow_task_id") or payload.get("task_id")
        attempt_id = payload.get("workflow_attempt_id") or payload.get("attempt_id")
        event = self._start_event(service, task_id, attempt_id, event_type, payload)

        try:
            if event_type in {
                "extract_team_context",
                "build_prediction_config",
                "generate_coach_agents",
                "discuss_scenario_space_design",
                "discuss_resume_replay_policy",
                "initialize_scientific_model",
                "compute_team_strength",
                "generate_scenario_matrix",
            }:
                result = self._ensure_prediction_config(payload, service, task_id, attempt_id, event)
            elif event_type in {
                "compute_scoreline_distribution",
                "generate_match_events",
                "generate_nine_scenario_match_events",
                "coach_review_match_events",
                "generate_analyst_notes",
            }:
                result = self._ensure_prediction_run(payload, service, task_id, attempt_id, event)
            elif event_type == "generate_report":
                result = self._ensure_report(payload, service, task_id, attempt_id, event)
            else:
                result = self._prepare_prediction_qa(payload, service, task_id, attempt_id, event)

            if event:
                service.succeed_event(
                    event["id"],
                    progress=100,
                    metadata={"result": result},
                )
                service.complete_task_if_all_events_finished(task_id, attempt_id)
            return result
        except Exception as exc:
            logger.exception("Football prediction workflow event failed: %s", event_type)
            if event:
                service.fail_event(event["id"], error_message=str(exc))
            raise

    def _start_event(
        self,
        service: TaskWorkflowService,
        task_id: str | None,
        attempt_id: str | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not task_id or not attempt_id:
            return None
        event = service.get_event(task_id, attempt_id, event_type)
        if not event:
            return None
        if event["status"] == "running":
            return event
        if event["status"] in {"pending", "failed"}:
            return service.start_event(
                task_id,
                attempt_id,
                event_type,
                progress=10,
                metadata={"payload_keys": sorted(payload.keys())},
            )
        return event

    def _ensure_prediction_config(
        self,
        payload: dict[str, Any],
        service: TaskWorkflowService,
        task_id: str | None,
        attempt_id: str | None,
        event: dict[str, Any] | None,
    ) -> dict[str, Any]:
        existing_config_id = self._resolve_prediction_config_id(payload, service, task_id, attempt_id)
        config_service = PredictionConfigService()
        if existing_config_id:
            status = config_service.get_status(existing_config_id)
        else:
            project_id = payload.get("project_id")
            if not project_id:
                raise ValueError("project_id is required for football prediction config workflow")

            project = ProjectManager.get_project(project_id)
            status = config_service.prepare(
                project_id=project_id,
                graph_id=payload.get("graph_id") or getattr(project, "graph_id", None),
                prediction_requirement=(
                    payload.get("prediction_requirement")
                    or payload.get("simulation_requirement")
                    or getattr(project, "simulation_requirement", "")
                    or ""
                ),
                home_team=payload.get("home_team"),
                away_team=payload.get("away_team"),
                competition=payload.get("competition"),
                kickoff_time=payload.get("kickoff_time"),
                graph_entities=payload.get("graph_entities") if isinstance(payload.get("graph_entities"), list) else [],
                llm_budget=payload.get("llm_budget") if isinstance(payload.get("llm_budget"), dict) else None,
                player_dataset_id=payload.get("player_dataset_id") or DEFAULT_PLAYER_DATASET_ID,
            )

        self._record_artifact(
            service,
            task_id,
            attempt_id,
            event,
            artifact_type="prediction_config",
            content_json=status,
        )
        return status

    def _ensure_prediction_run(
        self,
        payload: dict[str, Any],
        service: TaskWorkflowService,
        task_id: str | None,
        attempt_id: str | None,
        event: dict[str, Any] | None,
    ) -> dict[str, Any]:
        existing_run_id = self._resolve_prediction_run_id(payload, service, task_id, attempt_id)
        if existing_run_id:
            status = PredictionPersistenceService().get_status(existing_run_id)
        else:
            prediction_config_id = self._resolve_prediction_config_id(payload, service, task_id, attempt_id)
            if not prediction_config_id:
                config_status = self._ensure_prediction_config(payload, service, task_id, attempt_id, event)
                prediction_config_id = config_status["prediction_config_id"]
            status = PredictionPersistenceService().create_completed_prediction_from_config(
                prediction_config_id=prediction_config_id,
                force_rerun=bool(payload.get("force_rerun", False)),
                rerun_from_event_type=payload.get("rerun_from_event_type"),
            )

        self._record_artifact(
            service,
            task_id,
            attempt_id,
            event,
            artifact_type="prediction_run",
            content_json=status,
        )
        return status

    def _resolve_prediction_config_id(
        self,
        payload: dict[str, Any],
        service: TaskWorkflowService,
        task_id: str | None,
        attempt_id: str | None,
    ) -> str | None:
        if payload.get("prediction_config_id"):
            return str(payload["prediction_config_id"])
        if not task_id:
            return None
        artifacts = service.list_artifacts(task_id, attempt_id=attempt_id)
        for artifact in reversed(artifacts):
            content = artifact.get("content_json")
            if isinstance(content, dict) and content.get("prediction_config_id"):
                return str(content["prediction_config_id"])
        return None

    def _ensure_report(
        self,
        payload: dict[str, Any],
        service: TaskWorkflowService,
        task_id: str | None,
        attempt_id: str | None,
        event: dict[str, Any] | None,
    ) -> dict[str, Any]:
        prediction_run_id = self._resolve_prediction_run_id(payload, service, task_id, attempt_id)
        if not prediction_run_id:
            status = self._ensure_prediction_run(payload, service, task_id, attempt_id, event)
            prediction_run_id = status["prediction_run_id"]

        result = PredictionReportAssembler().create_report(
            prediction_run_id,
            force_regenerate=bool(payload.get("force_regenerate", False)),
        )
        self._record_artifact(
            service,
            task_id,
            attempt_id,
            event,
            artifact_type="prediction_report",
            content_json=result,
        )
        return result

    def _prepare_prediction_qa(
        self,
        payload: dict[str, Any],
        service: TaskWorkflowService,
        task_id: str | None,
        attempt_id: str | None,
        event: dict[str, Any] | None,
    ) -> dict[str, Any]:
        prediction_run_id = self._resolve_prediction_run_id(payload, service, task_id, attempt_id)
        if not prediction_run_id:
            report = self._ensure_report(payload, service, task_id, attempt_id, event)
            prediction_run_id = report["prediction_run_id"]

        result = {
            "prediction_run_id": prediction_run_id,
            "qa_ready": True,
            "source": "football_prediction_workflow_v1",
        }
        self._record_artifact(
            service,
            task_id,
            attempt_id,
            event,
            artifact_type="prediction_qa",
            content_json=result,
        )
        return result

    def _resolve_prediction_run_id(
        self,
        payload: dict[str, Any],
        service: TaskWorkflowService,
        task_id: str | None,
        attempt_id: str | None,
    ) -> str | None:
        if payload.get("prediction_run_id"):
            return str(payload["prediction_run_id"])
        if not task_id:
            return None
        artifacts = service.list_artifacts(task_id, attempt_id=attempt_id)
        for artifact in reversed(artifacts):
            content = artifact.get("content_json")
            if isinstance(content, dict) and content.get("prediction_run_id"):
                return str(content["prediction_run_id"])
        return None

    def _record_artifact(
        self,
        service: TaskWorkflowService,
        task_id: str | None,
        attempt_id: str | None,
        event: dict[str, Any] | None,
        *,
        artifact_type: str,
        content_json: dict[str, Any],
    ) -> None:
        if not task_id or not attempt_id:
            return
        service.create_artifact(
            task_id=task_id,
            attempt_id=attempt_id,
            event_id=event["id"] if event else None,
            artifact_type=artifact_type,
            content_json=content_json,
            metadata={"source": "football_prediction_workflow_v1"},
        )

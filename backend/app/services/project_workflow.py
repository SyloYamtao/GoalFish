"""Project workflow lineage and active artifact management."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

from ..db.models import (
    PredictionConfigRecord,
    PredictionReportRecord,
    PredictionReportSectionRecord,
    PredictionRunRecord,
    ProjectRecord,
    ReportConversationRecord,
    utc_now,
)
from ..db.session import get_session


ARTIFACT_ACTIVE = "active"
ARTIFACT_SUPERSEDED = "superseded"
ARTIFACT_ARCHIVED = "archived"
ARTIFACT_FAILED = "failed"

WORKFLOW_METADATA_KEY = "workflow"
ACTIVE_ARTIFACT_KEYS = (
    "graph_id",
    "prediction_config_id",
    "prediction_run_id",
    "report_id",
)
RUNNING_STATUSES = {"created", "pending", "preparing", "queued", "running", "generating", "regenerating"}
INVALIDATED_STEPS = {
    1: [1, 2, 3, 4, 5],
    2: [2, 3, 4, 5],
    3: [3, 4, 5],
    4: [4, 5],
    5: [5],
}


class WorkflowConflictError(RuntimeError):
    """Raised when a project has running jobs and cannot be regenerated."""


class ProjectWorkflowService:
    """Single source of truth for Step1-Step5 active workflow pointers.

    The current schema already has JSON metadata on all key artifacts. This
    service stores active pointers in ``projects.project_metadata.workflow`` and
    stamps artifacts with ``artifact_status`` and ``workflow_revision``.
    """

    def get_state(self, project_id: str) -> dict[str, Any]:
        with get_session() as session:
            project = session.get(ProjectRecord, project_id)
            if not project:
                raise KeyError(f"project not found: {project_id}")
            state = self._ensure_workflow_state(session, project)
            state = self._repair_workflow_state(session, project, state)
            return self._state_payload(project, state)

    def regenerate_step(
        self,
        project_id: str,
        step: int,
        *,
        reason: str = "user_requested",
        preserve_history: bool = True,
    ) -> dict[str, Any]:
        if step not in INVALIDATED_STEPS:
            raise ValueError("step must be between 1 and 5")

        del preserve_history
        with get_session() as session:
            project = session.get(ProjectRecord, project_id)
            if not project:
                raise KeyError(f"project not found: {project_id}")
            state = self._ensure_workflow_state(session, project)
            running = self._running_artifacts(session, project_id)
            if running:
                raise WorkflowConflictError("当前项目有生成任务正在运行，请等待任务完成或取消后再重新生成")

            now = utc_now()
            current_revision = int(state.get("workflow_revision") or 1)
            next_revision = current_revision + 1
            active = self._normalize_active_artifacts(state.get("active_artifacts"))
            invalidated_steps = INVALIDATED_STEPS[step]

            if step <= 2 and active.get("prediction_config_id"):
                self._mark_config_superseded(
                    session,
                    active["prediction_config_id"],
                    revision=next_revision,
                    step=step,
                    reason=reason,
                    now=now,
                )
                active["prediction_config_id"] = None
            if step <= 3 and active.get("prediction_run_id"):
                self._mark_run_superseded(
                    session,
                    active["prediction_run_id"],
                    revision=next_revision,
                    step=step,
                    reason=reason,
                    now=now,
                )
                active["prediction_run_id"] = None
            if step <= 4 and active.get("report_id"):
                self._mark_report_superseded(
                    session,
                    active["report_id"],
                    revision=next_revision,
                    step=step,
                    reason=reason,
                    now=now,
                )
                active["report_id"] = None
            if step <= 5:
                self._mark_conversations_superseded(
                    session,
                    report_id=None if step <= 4 else active.get("report_id"),
                    project_id=project_id,
                    revision=next_revision,
                    step=step,
                    reason=reason,
                    now=now,
                )

            if step == 1:
                active = self._blank_active_artifacts()

            new_state = {
                "workflow_revision": next_revision,
                "current_step": step,
                "active_artifacts": active,
                "last_regenerated_step": step,
                "last_regenerated_at": now.isoformat(),
                "last_regenerated_reason": reason,
                "invalidations": [
                    *list(state.get("invalidations") or [])[-24:],
                    {
                        "step": step,
                        "invalidated_steps": invalidated_steps,
                        "reason": reason,
                        "created_at": now.isoformat(),
                        "previous_revision": current_revision,
                        "workflow_revision": next_revision,
                    },
                ],
            }
            self._write_workflow_state(project, new_state)
            project.status = self._status_for_step(step)
            return {
                "success": True,
                "project_id": project_id,
                "regenerated_from_step": step,
                "invalidated_steps": invalidated_steps,
                **self._state_payload(project, new_state),
            }

    def register_graph(self, project_id: str, graph_id: str | None) -> dict[str, Any]:
        with get_session() as session:
            project = session.get(ProjectRecord, project_id)
            if not project:
                raise KeyError(f"project not found: {project_id}")
            state = self._ensure_workflow_state(session, project)
            active = self._normalize_active_artifacts(state.get("active_artifacts"))
            active["graph_id"] = graph_id
            state = {
                **state,
                "current_step": max(int(state.get("current_step") or 1), 2),
                "active_artifacts": active,
            }
            self._write_workflow_state(project, state)
            return self._state_payload(project, state)

    def register_config(self, project_id: str, prediction_config_id: str) -> dict[str, Any]:
        with get_session() as session:
            project = session.get(ProjectRecord, project_id)
            config = session.get(PredictionConfigRecord, prediction_config_id)
            if not project or not config:
                raise KeyError("project or prediction config not found")
            state = self._ensure_workflow_state(session, project)
            active = self._normalize_active_artifacts(state.get("active_artifacts"))
            same_config = active.get("prediction_config_id") == prediction_config_id
            active.update(
                {
                    "graph_id": config.graph_id or active.get("graph_id") or project.graph_id,
                    "prediction_config_id": prediction_config_id,
                    "prediction_run_id": active.get("prediction_run_id") if same_config else None,
                    "report_id": active.get("report_id") if same_config else None,
                }
            )
            state = {
                **state,
                "current_step": max(int(state.get("current_step") or 1), self._current_step_from_active(active), 3),
                "active_artifacts": active,
            }
            self._stamp_config(config, state, active=True)
            self._write_workflow_state(project, state)
            return self._state_payload(project, state)

    def register_run(self, project_id: str, prediction_run_id: str) -> dict[str, Any]:
        with get_session() as session:
            project = session.get(ProjectRecord, project_id)
            run = session.get(PredictionRunRecord, prediction_run_id)
            if not project or not run:
                raise KeyError("project or prediction run not found")
            state = self._ensure_workflow_state(session, project)
            active = self._normalize_active_artifacts(state.get("active_artifacts"))
            expected_config_id = active.get("prediction_config_id")
            if expected_config_id and run.prediction_config_id != expected_config_id:
                self._stamp_run(run, state, active=False, reason="upstream_config_changed")
                return self._state_payload(project, state)
            active.update(
                {
                    "graph_id": run.graph_id or active.get("graph_id") or project.graph_id,
                    "prediction_config_id": run.prediction_config_id or active.get("prediction_config_id"),
                    "prediction_run_id": prediction_run_id,
                    "report_id": None,
                }
            )
            state = {
                **state,
                "current_step": max(int(state.get("current_step") or 1), 4),
                "active_artifacts": active,
            }
            self._stamp_run(run, state, active=True)
            self._write_workflow_state(project, state)
            return self._state_payload(project, state)

    def register_report(self, project_id: str, report_id: str) -> dict[str, Any]:
        with get_session() as session:
            project = session.get(ProjectRecord, project_id)
            report = session.get(PredictionReportRecord, report_id)
            if not project or not report:
                raise KeyError("project or prediction report not found")
            state = self._ensure_workflow_state(session, project)
            active = self._normalize_active_artifacts(state.get("active_artifacts"))
            if active.get("prediction_run_id") and report.simulation_id != active.get("prediction_run_id"):
                self._stamp_report(report, state, active=False, reason="upstream_run_changed")
                return self._state_payload(project, state)
            active.update(
                {
                    "graph_id": report.graph_id or active.get("graph_id") or project.graph_id,
                    "prediction_run_id": report.simulation_id or active.get("prediction_run_id"),
                    "report_id": report_id,
                }
            )
            metadata = report.report_metadata or {}
            if metadata.get("prediction_config_id"):
                active["prediction_config_id"] = metadata.get("prediction_config_id")
            state = {
                **state,
                "current_step": max(int(state.get("current_step") or 1), 5),
                "active_artifacts": active,
            }
            self._stamp_report(report, state, active=True)
            self._write_workflow_state(project, state)
            return self._state_payload(project, state)

    def get_active_config_id(self, project_id: str) -> str | None:
        return (self.get_state(project_id).get("active_artifacts") or {}).get("prediction_config_id")

    def get_active_run_id(self, project_id: str) -> str:
        run_id = (self.get_state(project_id).get("active_artifacts") or {}).get("prediction_run_id")
        if not run_id:
            raise ValueError("Step3 场景推演不存在，请先完成 Step3")
        return run_id

    def get_active_report_id(self, project_id: str) -> str | None:
        return (self.get_state(project_id).get("active_artifacts") or {}).get("report_id")

    def require_active_config(self, project_id: str, prediction_config_id: str) -> None:
        state = self.get_state(project_id)
        active_id = (state.get("active_artifacts") or {}).get("prediction_config_id")
        if active_id != prediction_config_id:
            raise ValueError("Step2 配置已失效，请重新生成 Step2")

    def require_active_run(self, prediction_run_id: str) -> PredictionRunRecord:
        with get_session() as session:
            run = session.get(PredictionRunRecord, prediction_run_id)
            if not run:
                raise KeyError(f"prediction run not found: {prediction_run_id}")
            project = session.get(ProjectRecord, run.project_id)
            if not project:
                raise KeyError(f"project not found: {run.project_id}")
            state = self._ensure_workflow_state(session, project)
            active = self._normalize_active_artifacts(state.get("active_artifacts"))
            if active.get("prediction_run_id") != prediction_run_id:
                raise ValueError("Step3 场景推演已失效，请重新生成 Step3")
            metadata = run.run_metadata or {}
            if metadata.get("artifact_status") not in {None, ARTIFACT_ACTIVE}:
                raise ValueError("Step3 场景推演已失效，请重新生成 Step3")
            if run.prediction_config_id and active.get("prediction_config_id") != run.prediction_config_id:
                raise ValueError("Step2 配置已失效，请重新生成 Step2")
            session.expunge(run)
            return run

    def require_active_report(self, report_id: str) -> PredictionReportRecord:
        with get_session() as session:
            report = session.get(PredictionReportRecord, report_id)
            if not report:
                raise KeyError(f"report not found: {report_id}")
            run = session.get(PredictionRunRecord, report.simulation_id)
            if not run:
                raise ValueError("Step3 场景推演不存在，请先完成 Step3")
            project = session.get(ProjectRecord, run.project_id)
            if not project:
                raise KeyError(f"project not found: {run.project_id}")
            state = self._ensure_workflow_state(session, project)
            active = self._normalize_active_artifacts(state.get("active_artifacts"))
            if active.get("report_id") != report_id:
                raise ValueError("Step4 报告已失效，请重新生成 Step4")
            metadata = report.report_metadata or {}
            if metadata.get("artifact_status") not in {None, ARTIFACT_ACTIVE}:
                raise ValueError("Step4 报告已失效，请重新生成 Step4")
            session.expunge(report)
            return report

    def report_lineage_info(self, report_id: str) -> dict[str, Any]:
        with get_session() as session:
            report = session.get(PredictionReportRecord, report_id)
            if not report:
                raise KeyError(f"report not found: {report_id}")
            run = session.get(PredictionRunRecord, report.simulation_id)
            project = session.get(ProjectRecord, run.project_id) if run else None
            state = self._ensure_workflow_state(session, project) if project else {}
            active = self._normalize_active_artifacts(state.get("active_artifacts"))
            metadata = report.report_metadata or {}
            stored_status = metadata.get("artifact_status") or ARTIFACT_ACTIVE
            is_active = (
                active.get("report_id") == report_id
                and stored_status in {None, ARTIFACT_ACTIVE}
            )
            effective_status = stored_status if is_active else (
                ARTIFACT_SUPERSEDED if stored_status == ARTIFACT_ACTIVE else stored_status
            )
            return {
                "project_id": project.project_id if project else None,
                "prediction_run_id": report.simulation_id,
                "active_report_id": active.get("report_id"),
                "active_prediction_run_id": active.get("prediction_run_id"),
                "is_active_report": is_active,
                "artifact_status": effective_status,
                "stored_artifact_status": stored_status,
                "workflow_revision": metadata.get("workflow_revision"),
                "current_workflow_revision": state.get("workflow_revision"),
            }

    def mark_conversation_active(self, conversation_id: str, *, report_id: str) -> None:
        with get_session() as session:
            conversation = session.get(ReportConversationRecord, conversation_id)
            report = session.get(PredictionReportRecord, report_id)
            if not conversation or not report:
                return
            run = session.get(PredictionRunRecord, report.simulation_id)
            project = session.get(ProjectRecord, run.project_id) if run else None
            state = self._ensure_workflow_state(session, project) if project else {}
            metadata = dict(conversation.conversation_metadata or {})
            metadata.update(
                {
                    "artifact_status": ARTIFACT_ACTIVE,
                    "workflow_revision": state.get("workflow_revision"),
                    "report_id": report_id,
                    "prediction_run_id": report.simulation_id,
                    "updated_at": utc_now().isoformat(),
                }
            )
            conversation.conversation_metadata = metadata

    def _ensure_workflow_state(self, session: Any, project: ProjectRecord) -> dict[str, Any]:
        metadata = dict(project.project_metadata or {})
        state = metadata.get(WORKFLOW_METADATA_KEY)
        if isinstance(state, dict) and isinstance(state.get("active_artifacts"), dict):
            return {
                "workflow_revision": int(state.get("workflow_revision") or metadata.get("workflow_revision") or 1),
                "current_step": int(state.get("current_step") or metadata.get("current_step") or 1),
                "active_artifacts": self._normalize_active_artifacts(state.get("active_artifacts")),
                "invalidations": list(state.get("invalidations") or []),
                **{
                    key: value
                    for key, value in state.items()
                    if key not in {"workflow_revision", "current_step", "active_artifacts", "invalidations"}
                },
            }

        state = self._legacy_state(session, project, metadata)
        self._write_workflow_state(project, state)
        self._stamp_legacy_active_artifacts(session, project, state)
        session.flush()
        return state

    def _repair_workflow_state(self, session: Any, project: ProjectRecord, state: dict[str, Any]) -> dict[str, Any]:
        """Keep active Step2/Step3 pointers on one valid artifact chain.

        Older flows and failed retries can leave ``active_artifacts`` pointing at
        a failed or stale Step2 config while a valid Step3 run still exists. The
        UI treats this JSON as the source of truth, so repair it before exposing
        workflow state.
        """

        active = self._normalize_active_artifacts(state.get("active_artifacts"))
        original = dict(active)
        config = session.get(PredictionConfigRecord, active["prediction_config_id"]) if active.get("prediction_config_id") else None
        run = session.get(PredictionRunRecord, active["prediction_run_id"]) if active.get("prediction_run_id") else None

        if run and self._is_run_usable(project, run):
            run_config = session.get(PredictionConfigRecord, run.prediction_config_id) if run.prediction_config_id else None
            if self._is_config_usable(project, run_config):
                if active.get("prediction_config_id") != run_config.prediction_config_id:
                    active["prediction_config_id"] = run_config.prediction_config_id
                if active.get("graph_id") != (run.graph_id or run_config.graph_id or active.get("graph_id") or project.graph_id):
                    active["graph_id"] = run.graph_id or run_config.graph_id or active.get("graph_id") or project.graph_id
                config = run_config
            else:
                active["prediction_run_id"] = None
                active["report_id"] = None
                run = None
        elif active.get("prediction_run_id"):
            active["prediction_run_id"] = None
            active["report_id"] = None
            run = None

        if not self._is_config_usable(project, config):
            replacement = None
            if run and run.prediction_config_id:
                candidate = session.get(PredictionConfigRecord, run.prediction_config_id)
                if self._is_config_usable(project, candidate):
                    replacement = candidate
            if not replacement:
                replacement = self._latest_usable_config(session, project, active.get("graph_id"))
            active["prediction_config_id"] = replacement.prediction_config_id if replacement else None
            if replacement:
                active["graph_id"] = replacement.graph_id or active.get("graph_id") or project.graph_id
                config = replacement
            else:
                config = None

        if not active.get("prediction_run_id") and config:
            recovered_run = self._latest_usable_run(session, project, config.prediction_config_id)
            if recovered_run:
                active["prediction_run_id"] = recovered_run.prediction_run_id
                active["graph_id"] = recovered_run.graph_id or active.get("graph_id") or config.graph_id or project.graph_id

        if active != original or int(state.get("current_step") or 1) != self._current_step_from_active(active):
            repaired = {
                **state,
                "current_step": self._current_step_from_active(active),
                "active_artifacts": active,
            }
            self._write_workflow_state(project, repaired)
            session.flush()
            return repaired
        return state

    def _is_config_usable(self, project: ProjectRecord, config: PredictionConfigRecord | None) -> bool:
        if not config or config.project_id != project.project_id or config.status != "ready":
            return False
        metadata = config.config_metadata or {}
        if metadata.get("artifact_status") not in {None, ARTIFACT_ACTIVE}:
            return False
        return self._config_matches_project_identity(project, config)

    def _is_run_usable(self, project: ProjectRecord, run: PredictionRunRecord | None) -> bool:
        if not run or run.project_id != project.project_id or not run.prediction_config_id:
            return False
        if run.status in {"failed", "cancelled", "canceled"}:
            return False
        metadata = run.run_metadata or {}
        return metadata.get("artifact_status") in {None, ARTIFACT_ACTIVE, "pending"}

    def _latest_usable_config(
        self,
        session: Any,
        project: ProjectRecord,
        graph_id: str | None,
    ) -> PredictionConfigRecord | None:
        query = session.query(PredictionConfigRecord).filter_by(project_id=project.project_id, status="ready")
        if graph_id:
            query = query.filter_by(graph_id=graph_id)
        rows = query.order_by(
            PredictionConfigRecord.completed_at.desc().nullslast(),
            PredictionConfigRecord.created_at.desc(),
        ).limit(10).all()
        for row in rows:
            if self._is_config_usable(project, row):
                return row
        return None

    def _latest_usable_run(
        self,
        session: Any,
        project: ProjectRecord,
        prediction_config_id: str,
    ) -> PredictionRunRecord | None:
        rows = (
            session.query(PredictionRunRecord)
            .filter_by(project_id=project.project_id, prediction_config_id=prediction_config_id)
            .order_by(PredictionRunRecord.completed_at.desc().nullslast(), PredictionRunRecord.created_at.desc())
            .limit(10)
            .all()
        )
        for row in rows:
            if self._is_run_usable(project, row):
                return row
        return None

    def _config_matches_project_identity(self, project: ProjectRecord, config: PredictionConfigRecord) -> bool:
        expected = self._project_identity_pair(project)
        actual = self._config_identity_pair(config)
        return not expected or not actual or expected == actual

    def _project_identity_pair(self, project: ProjectRecord) -> tuple[str, str] | None:
        metadata = project.project_metadata or {}
        preview = metadata.get("step2_preview") if isinstance(metadata.get("step2_preview"), dict) else {}
        home = str(preview.get("home_iso3") or "").strip().upper()
        away = str(preview.get("away_iso3") or "").strip().upper()
        return (home, away) if home and away else None

    def _config_identity_pair(self, config: PredictionConfigRecord) -> tuple[str, str] | None:
        snapshot = config.model_input_snapshot or {}
        squads = snapshot.get("squads") if isinstance(snapshot.get("squads"), dict) else {}
        home_squad = squads.get("home") if isinstance(squads.get("home"), dict) else {}
        away_squad = squads.get("away") if isinstance(squads.get("away"), dict) else {}
        home = str(snapshot.get("home_iso3") or home_squad.get("team_iso3") or "").strip().upper()
        away = str(snapshot.get("away_iso3") or away_squad.get("team_iso3") or "").strip().upper()
        return (home, away) if home and away else None

    def _legacy_state(self, session: Any, project: ProjectRecord, metadata: dict[str, Any]) -> dict[str, Any]:
        active = self._normalize_active_artifacts(metadata.get("active_artifacts"))
        active["graph_id"] = active.get("graph_id") or project.graph_id
        revision = int(metadata.get("workflow_revision") or 1)

        config = None
        if active.get("prediction_config_id"):
            config = session.get(PredictionConfigRecord, active["prediction_config_id"])
        if not config:
            config = (
                session.query(PredictionConfigRecord)
                .filter_by(project_id=project.project_id, status="ready")
                .order_by(PredictionConfigRecord.completed_at.desc().nullslast(), PredictionConfigRecord.created_at.desc())
                .first()
            )
        if config:
            active["prediction_config_id"] = config.prediction_config_id
            active["graph_id"] = active.get("graph_id") or config.graph_id

        run = None
        if active.get("prediction_run_id"):
            run = session.get(PredictionRunRecord, active["prediction_run_id"])
        if not run:
            query = session.query(PredictionRunRecord).filter_by(project_id=project.project_id, status="completed")
            if active.get("prediction_config_id"):
                query = query.filter_by(prediction_config_id=active["prediction_config_id"])
            run = query.order_by(PredictionRunRecord.completed_at.desc().nullslast(), PredictionRunRecord.created_at.desc()).first()
        if run:
            active["prediction_run_id"] = run.prediction_run_id
            active["prediction_config_id"] = active.get("prediction_config_id") or run.prediction_config_id
            active["graph_id"] = active.get("graph_id") or run.graph_id

        report = None
        if active.get("report_id"):
            report = session.get(PredictionReportRecord, active["report_id"])
        if not report and active.get("prediction_run_id"):
            report = (
                session.query(PredictionReportRecord)
                .filter_by(simulation_id=active["prediction_run_id"], status="completed")
                .order_by(PredictionReportRecord.completed_at.desc().nullslast(), PredictionReportRecord.created_at.desc())
                .first()
            )
        if report:
            active["report_id"] = report.report_id

        current_step = self._current_step_from_active(active)
        return {
            "workflow_revision": revision,
            "current_step": int(metadata.get("current_step") or current_step),
            "active_artifacts": active,
            "invalidations": list(metadata.get("invalidations") or []),
        }

    def _stamp_legacy_active_artifacts(self, session: Any, project: ProjectRecord, state: dict[str, Any]) -> None:
        active = self._normalize_active_artifacts(state.get("active_artifacts"))
        if active.get("prediction_config_id"):
            config = session.get(PredictionConfigRecord, active["prediction_config_id"])
            if config:
                self._stamp_config(config, state, active=True)
        if active.get("prediction_run_id"):
            run = session.get(PredictionRunRecord, active["prediction_run_id"])
            if run:
                self._stamp_run(run, state, active=True)
        if active.get("report_id"):
            report = session.get(PredictionReportRecord, active["report_id"])
            if report:
                self._stamp_report(report, state, active=True)

    def _write_workflow_state(self, project: ProjectRecord, state: dict[str, Any]) -> None:
        metadata = dict(project.project_metadata or {})
        state = {
            **state,
            "active_artifacts": self._normalize_active_artifacts(state.get("active_artifacts")),
        }
        metadata[WORKFLOW_METADATA_KEY] = state
        metadata["workflow_revision"] = state.get("workflow_revision")
        metadata["current_step"] = state.get("current_step")
        metadata["active_artifacts"] = state.get("active_artifacts")
        project.project_metadata = metadata
        project.graph_id = state["active_artifacts"].get("graph_id")
        project.updated_at = utc_now()

    def _state_payload(self, project: ProjectRecord, state: dict[str, Any]) -> dict[str, Any]:
        active = self._normalize_active_artifacts(state.get("active_artifacts"))
        return {
            "project_id": project.project_id,
            "workflow_revision": int(state.get("workflow_revision") or 1),
            "current_step": int(state.get("current_step") or self._current_step_from_active(active)),
            "active_artifacts": active,
            "steps": self._step_statuses(active),
        }

    def _step_statuses(self, active: dict[str, Any]) -> list[dict[str, Any]]:
        current = self._current_step_from_active(active)
        return [
            {"step": 1, "status": "completed" if active.get("graph_id") else "current" if current == 1 else "pending"},
            {"step": 2, "status": "completed" if active.get("prediction_config_id") else "current" if current == 2 else "pending"},
            {"step": 3, "status": "completed" if active.get("prediction_run_id") else "current" if current == 3 else "pending"},
            {"step": 4, "status": "completed" if active.get("report_id") else "current" if current == 4 else "pending"},
            {"step": 5, "status": "current" if current == 5 and active.get("report_id") else "pending"},
        ]

    def _running_artifacts(self, session: Any, project_id: str) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        configs = (
            session.query(PredictionConfigRecord)
            .filter(PredictionConfigRecord.project_id == project_id, PredictionConfigRecord.status.in_(RUNNING_STATUSES))
            .all()
        )
        rows.extend({"type": "prediction_config", "id": row.prediction_config_id, "status": row.status} for row in configs)
        runs = (
            session.query(PredictionRunRecord)
            .filter(PredictionRunRecord.project_id == project_id, PredictionRunRecord.status.in_(RUNNING_STATUSES))
            .all()
        )
        rows.extend({"type": "prediction_run", "id": row.prediction_run_id, "status": row.status} for row in runs)
        return rows

    def _mark_config_superseded(self, session: Any, config_id: str, *, revision: int, step: int, reason: str, now: datetime) -> None:
        config = session.get(PredictionConfigRecord, config_id)
        if not config:
            return
        metadata = dict(config.config_metadata or {})
        metadata.update(self._superseded_metadata(revision=revision, step=step, reason=reason, now=now))
        config.config_metadata = metadata

    def _mark_run_superseded(self, session: Any, run_id: str, *, revision: int, step: int, reason: str, now: datetime) -> None:
        run = session.get(PredictionRunRecord, run_id)
        if not run:
            return
        metadata = dict(run.run_metadata or {})
        metadata.update(self._superseded_metadata(revision=revision, step=step, reason=reason, now=now))
        run.run_metadata = metadata

    def _mark_report_superseded(self, session: Any, report_id: str, *, revision: int, step: int, reason: str, now: datetime) -> None:
        report = session.get(PredictionReportRecord, report_id)
        if report:
            metadata = dict(report.report_metadata or {})
            metadata.update(self._superseded_metadata(revision=revision, step=step, reason=reason, now=now))
            report.report_metadata = metadata
        sections = session.query(PredictionReportSectionRecord).filter_by(report_id=report_id).all()
        for section in sections:
            metadata = dict(section.section_metadata or {})
            metadata.update(self._superseded_metadata(revision=revision, step=step, reason=reason, now=now))
            section.section_metadata = metadata
        self._mark_conversations_superseded(
            session,
            report_id=report_id,
            project_id=None,
            revision=revision,
            step=step,
            reason=reason,
            now=now,
        )

    def _mark_conversations_superseded(
        self,
        session: Any,
        *,
        report_id: str | None,
        project_id: str | None,
        revision: int,
        step: int,
        reason: str,
        now: datetime,
    ) -> None:
        query = session.query(ReportConversationRecord)
        if report_id:
            query = query.filter_by(report_id=report_id)
        elif project_id:
            run_ids = select(PredictionRunRecord.prediction_run_id).where(PredictionRunRecord.project_id == project_id)
            report_ids = select(PredictionReportRecord.report_id).where(PredictionReportRecord.simulation_id.in_(run_ids))
            query = query.filter(ReportConversationRecord.report_id.in_(report_ids))
        else:
            return
        for conversation in query.all():
            metadata = dict(conversation.conversation_metadata or {})
            metadata.update(self._superseded_metadata(revision=revision, step=step, reason=reason, now=now))
            conversation.conversation_metadata = metadata

    def _stamp_config(self, config: PredictionConfigRecord, state: dict[str, Any], *, active: bool, reason: str | None = None) -> None:
        metadata = dict(config.config_metadata or {})
        metadata.update(
            {
                "artifact_status": ARTIFACT_ACTIVE if active else ARTIFACT_SUPERSEDED,
                "workflow_revision": state.get("workflow_revision"),
                "lineage_updated_at": utc_now().isoformat(),
            }
        )
        if reason:
            metadata["lineage_reason"] = reason
        config.config_metadata = metadata

    def _stamp_run(self, run: PredictionRunRecord, state: dict[str, Any], *, active: bool, reason: str | None = None) -> None:
        metadata = dict(run.run_metadata or {})
        metadata.update(
            {
                "artifact_status": ARTIFACT_ACTIVE if active else ARTIFACT_SUPERSEDED,
                "workflow_revision": state.get("workflow_revision"),
                "lineage_updated_at": utc_now().isoformat(),
            }
        )
        if reason:
            metadata["lineage_reason"] = reason
        run.run_metadata = metadata

    def _stamp_report(self, report: PredictionReportRecord, state: dict[str, Any], *, active: bool, reason: str | None = None) -> None:
        metadata = dict(report.report_metadata or {})
        metadata.update(
            {
                "artifact_status": ARTIFACT_ACTIVE if active else ARTIFACT_SUPERSEDED,
                "workflow_revision": state.get("workflow_revision"),
                "lineage_updated_at": utc_now().isoformat(),
            }
        )
        if reason:
            metadata["lineage_reason"] = reason
        report.report_metadata = metadata
        for section in report.sections or []:
            section_metadata = dict(section.section_metadata or {})
            section_metadata.update(
                {
                    "artifact_status": ARTIFACT_ACTIVE if active else ARTIFACT_SUPERSEDED,
                    "workflow_revision": state.get("workflow_revision"),
                }
            )
            section.section_metadata = section_metadata

    def _superseded_metadata(self, *, revision: int, step: int, reason: str, now: datetime) -> dict[str, Any]:
        return {
            "artifact_status": ARTIFACT_SUPERSEDED,
            "superseded_at": now.isoformat(),
            "superseded_by_step": step,
            "superseded_reason": reason,
            "workflow_revision": revision,
        }

    def _normalize_active_artifacts(self, value: Any) -> dict[str, Any]:
        source = value if isinstance(value, dict) else {}
        return {key: source.get(key) for key in ACTIVE_ARTIFACT_KEYS}

    def _blank_active_artifacts(self) -> dict[str, Any]:
        return {key: None for key in ACTIVE_ARTIFACT_KEYS}

    def _current_step_from_active(self, active: dict[str, Any]) -> int:
        if active.get("report_id"):
            return 5
        if active.get("prediction_run_id"):
            return 4
        if active.get("prediction_config_id"):
            return 3
        if active.get("graph_id"):
            return 2
        return 1

    def _status_for_step(self, step: int) -> str:
        return {
            1: "created",
            2: "graph_completed",
            3: "prediction_config_ready",
            4: "prediction_completed",
            5: "report_completed",
        }.get(step, "created")

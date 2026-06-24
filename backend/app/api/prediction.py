"""Football prediction APIs."""

from __future__ import annotations

import traceback
from datetime import datetime, timezone

from flask import jsonify, request

from . import prediction_bp
from ..config import Config
from ..db.models import (
    PredictionConfigRecord,
    PredictionPlayerDatasetRecord,
    PredictionReportRecord,
    PredictionResultRecord,
    PredictionRunRecord,
    ProjectRecord,
)
from ..db.session import get_session
from ..services.football_prediction import PredictionPersistenceService, PredictionReportAssembler
from ..services.prediction_config import DEFAULT_PLAYER_DATASET_ID, DatasetNotFoundError, PredictionConfigService
from ..services.project_workflow import ProjectWorkflowService
from ..services.task_workflow import CeleryJobStatus, TaskWorkflowService
from ..tasks.workflow_tasks import enqueue_workflow_event
from ..celery_app import celery_app
from ..utils.logger import get_logger


logger = get_logger("goalfish.api.prediction")


_CELERY_BACKEND_STATUS = {
    "PENDING": CeleryJobStatus.QUEUED.value,
    "RECEIVED": CeleryJobStatus.QUEUED.value,
    "STARTED": CeleryJobStatus.RUNNING.value,
    "RETRY": CeleryJobStatus.RETRYING.value,
    "SUCCESS": CeleryJobStatus.SUCCEEDED.value,
    "FAILURE": CeleryJobStatus.FAILED.value,
    "REVOKED": CeleryJobStatus.CANCELLED.value,
}


def _json_error(message: str, status_code: int = 500):
    return jsonify({"success": False, "error": message, "traceback": traceback.format_exc()}), status_code


def _json_code_error(message: str, code: str, status_code: int, details: dict | None = None):
    payload = {"success": False, "error": message, "code": code}
    if details is not None:
        payload["details"] = details
    return jsonify(payload), status_code


def _ensure_active_prediction_run(prediction_run_id: str) -> None:
    ProjectWorkflowService().require_active_run(prediction_run_id)


def _isoformat(value):
    return value.isoformat() if value else None


def _celery_async_result(celery_task_id: str):
    return celery_app.AsyncResult(celery_task_id)


def _sync_celery_backend_status(
    *,
    celery_task_id: str,
    job: dict,
    task_service: TaskWorkflowService,
) -> dict:
    try:
        async_result = _celery_async_result(celery_task_id)
    except Exception as exc:  # noqa: BLE001 - status endpoint must not fail on broker issues.
        logger.warning("读取 Celery backend 状态失败: celery_task_id=%s, error=%s", celery_task_id, exc)
        return job

    backend_state = str(getattr(async_result, "state", "") or getattr(async_result, "status", "") or "").upper()
    mapped_status = _CELERY_BACKEND_STATUS.get(backend_state)
    if not mapped_status:
        return job

    last_error = job.get("last_error")
    if mapped_status in {CeleryJobStatus.RETRYING.value, CeleryJobStatus.FAILED.value}:
        result = getattr(async_result, "result", None)
        if result is not None:
            last_error = str(result)

    metadata = {
        "celery_backend_state": backend_state,
        "celery_backend_ready": bool(async_result.ready()) if hasattr(async_result, "ready") else None,
    }

    return task_service.update_celery_job(
        celery_task_id,
        status=mapped_status,
        finished=mapped_status in {
            CeleryJobStatus.SUCCEEDED.value,
            CeleryJobStatus.FAILED.value,
            CeleryJobStatus.CANCELLED.value,
        },
        last_error=last_error,
        metadata=metadata,
    )


def _parse_iso_datetime(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _job_runtime_seconds(job: dict) -> float | None:
    started_at = _parse_iso_datetime(job.get("started_at"))
    if started_at is None:
        created_at = _parse_iso_datetime(job.get("created_at"))
        started_at = created_at
    if started_at is None:
        return None
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - started_at).total_seconds())


def _stale_async_error(job: dict, status: dict) -> str | None:
    if status.get("status") not in {"queued", "running"}:
        return None
    job_status = job.get("status")
    if job_status not in {CeleryJobStatus.RUNNING.value, CeleryJobStatus.RETRYING.value}:
        return None
    runtime_seconds = _job_runtime_seconds(job)
    stale_seconds = int(getattr(Config, "PREDICTION_ASYNC_STALE_SECONDS", 1800) or 0)
    if runtime_seconds is None or stale_seconds <= 0 or runtime_seconds < stale_seconds:
        return None
    state = str(job_status).lower()
    return f"后台任务长时间停留在 {state} 状态，已按失联任务处理"


def _prediction_history_item(
    run: PredictionRunRecord,
    project: ProjectRecord | None,
    report: PredictionReportRecord | None,
    result: PredictionResultRecord | None,
) -> dict:
    run_metadata = run.run_metadata or {}
    project_requirement = project.simulation_requirement if project else None
    prediction_requirement = run_metadata.get("simulation_requirement") or project_requirement or ""
    scoreline_summary = (result.scoreline_summary if result else {}) or {}
    final_score_hypothesis = (result.final_score_hypothesis if result else {}) or {}

    return {
        "prediction_run_id": run.prediction_run_id,
        "prediction_config_id": run.prediction_config_id,
        "project_id": run.project_id,
        "graph_id": run.graph_id,
        "report_id": report.report_id if report else None,
        "simulation_requirement": prediction_requirement,
        "prediction_requirement": prediction_requirement,
        "simulation_domain": "football_match",
        "files": project.files if project else [],
        "project_name": project.name if project else None,
        "project_status": project.status if project else None,
        "created_at": _isoformat(run.created_at),
        "updated_at": _isoformat(run.updated_at),
        "completed_at": _isoformat(run.completed_at),
        "status": run.status,
        "current_phase": run.current_phase,
        "progress_percent": run.progress_percent,
        "can_resume": run.status in {"failed", "interrupted"},
        "resume_from_event_type": run.current_phase if run.status in {"failed", "interrupted"} else None,
        "match_name": run.match_name,
        "home_team": run.home_team,
        "away_team": run.away_team,
        "competition": run.competition,
        "kickoff_time": run.kickoff_time,
        "most_likely_score": (
            scoreline_summary.get("most_likely_score")
            or final_score_hypothesis.get("score")
        ),
        "win_draw_loss_probability": scoreline_summary.get("win_draw_loss_probability") or {},
        "confidence": result.confidence if result else None,
        "error": run.error,
    }


@prediction_bp.route("/history", methods=["GET"])
def get_prediction_history():
    """List replayable football prediction runs for the home history panel."""
    try:
        limit = request.args.get("limit", 20, type=int)
        limit = max(1, min(limit or 20, 100))
        with get_session() as session:
            runs = (
                session.query(PredictionRunRecord)
                .order_by(PredictionRunRecord.created_at.desc())
                .limit(limit)
                .all()
            )
            items = []
            for run in runs:
                project = session.get(ProjectRecord, run.project_id) if run.project_id else None
                report = (
                    session.query(PredictionReportRecord)
                    .filter_by(simulation_id=run.prediction_run_id)
                    .order_by(PredictionReportRecord.created_at.desc())
                    .first()
                )
                result = (
                    session.query(PredictionResultRecord)
                    .filter_by(prediction_run_id=run.prediction_run_id)
                    .one_or_none()
                )
                items.append(_prediction_history_item(run, project, report, result))

        return jsonify({"success": True, "data": items, "count": len(items)})
    except Exception as exc:
        logger.exception("查询足球预测历史失败")
        return _json_error(str(exc))


@prediction_bp.route("/datasets", methods=["GET"])
def list_prediction_datasets():
    try:
        rows = PredictionConfigService().list_datasets()
        return jsonify({"success": True, "data": {"datasets": rows}, "count": len(rows)})
    except Exception as exc:
        logger.exception("查询球员数据集失败")
        return _json_error(str(exc))


@prediction_bp.route("/<project_id>/configs/latest", methods=["GET"])
def get_latest_prediction_config(project_id: str):
    """Read the latest reusable Step2 config without triggering preparation."""
    try:
        graph_id = request.args.get("graph_id")
        data = PredictionConfigService().get_latest_ready_config(project_id=project_id, graph_id=graph_id)
        return jsonify({"success": True, "data": data})
    except Exception as exc:
        logger.exception("查询最新预测配置失败: project_id=%s", project_id)
        return _json_error(str(exc))


@prediction_bp.route("/<project_id>/run", methods=["POST"])
def run_prediction(project_id: str):
    """Run Step3 from a ready Step2 prediction_config."""
    try:
        data = request.get_json(silent=True) or {}
        prediction_config_id = data.get("prediction_config_id")
        if not prediction_config_id:
            return jsonify({"success": False, "error": "prediction_config_id is required"}), 400

        with get_session() as session:
            config = session.get(PredictionConfigRecord, prediction_config_id)
            if not config:
                return jsonify({"success": False, "error": f"prediction config not found: {prediction_config_id}"}), 404
            if config.project_id != project_id:
                return jsonify({"success": False, "error": "prediction_config_id does not belong to project_id"}), 400
            if config.status != "ready":
                return jsonify({"success": False, "error": f"prediction config is not ready: {config.status}"}), 409
        try:
            ProjectWorkflowService().require_active_config(project_id, prediction_config_id)
        except ValueError as exc:
            return _json_code_error(str(exc), "inactive_prediction_config", 409)

        service = PredictionPersistenceService()
        force_rerun = bool(data.get("force_rerun", False))
        rerun_from_event_type = data.get("rerun_from_event_type")
        if bool(data.get("async", False)):
            status = service.create_pending_prediction_from_config(
                prediction_config_id=prediction_config_id,
                force_rerun=force_rerun,
                rerun_from_event_type=rerun_from_event_type,
            )
            job = enqueue_workflow_event(
                event_type="run_prediction_from_config",
                payload={
                    "prediction_run_id": status["prediction_run_id"],
                    "prediction_config_id": prediction_config_id,
                    "project_id": project_id,
                    "force_rerun": force_rerun,
                    "rerun_from_event_type": rerun_from_event_type,
                },
                task_id=None,
                attempt_id=None,
                event_id=None,
            )
            with get_session() as session:
                run = session.get(PredictionRunRecord, status["prediction_run_id"])
                if run:
                    metadata = dict(run.run_metadata or {})
                    metadata.update({
                        "executor": "celery",
                        "celery_job_id": job["id"],
                        "celery_task_id": job["celery_task_id"],
                    })
                    run.run_metadata = metadata
            status = {
                **status,
                "executor": "celery",
                "celery_job_id": job["id"],
                "celery_task_id": job["celery_task_id"],
            }
        else:
            status = service.create_completed_prediction_from_config(
                prediction_config_id=prediction_config_id,
                force_rerun=force_rerun,
                rerun_from_event_type=rerun_from_event_type,
            )
        return jsonify({"success": True, "data": status})
    except Exception as exc:
        logger.exception("运行足球预测失败: project_id=%s", project_id)
        return _json_error(str(exc))


@prediction_bp.route("/<project_id>/prepare", methods=["POST"])
def prepare_prediction_config(project_id: str):
    """Prepare Step2 prediction_config artifacts."""
    try:
        data = request.get_json(silent=True) or {}
        explicit_dataset_id = data.get("player_dataset_id")
        if explicit_dataset_id:
            with get_session() as session:
                if session.get(PredictionPlayerDatasetRecord, explicit_dataset_id) is None:
                    available = [
                        row.dataset_id
                        for row in session.query(PredictionPlayerDatasetRecord)
                        .order_by(PredictionPlayerDatasetRecord.created_at.desc())
                        .all()
                    ]
                    return _json_code_error(
                        f"Player dataset '{explicit_dataset_id}' not found",
                        "dataset_not_found",
                        404,
                        {"available_datasets": available},
                    )
        result = PredictionConfigService().prepare(
            project_id=project_id,
            graph_id=data.get("graph_id"),
            prediction_requirement=data.get("prediction_requirement") or data.get("simulation_requirement") or data.get("requirement") or "",
            force_regenerate=bool(data.get("force_regenerate", False)),
            home_team=data.get("home_team"),
            away_team=data.get("away_team"),
            competition=data.get("competition"),
            kickoff_time=data.get("kickoff_time"),
            graph_entities=data.get("graph_entities") if isinstance(data.get("graph_entities"), list) else [],
            llm_budget=data.get("llm_budget") if isinstance(data.get("llm_budget"), dict) else None,
            player_dataset_id=data.get("player_dataset_id") or DEFAULT_PLAYER_DATASET_ID,
        )
        return jsonify({"success": True, "data": result})
    except ValueError as exc:
        code = "budget_overcap" if "hard_cap_calls" in str(exc) or "budget" in str(exc).lower() else "bad_request"
        return _json_code_error(str(exc), code, 400)
    except Exception as exc:
        logger.exception("准备足球预测配置失败: project_id=%s", project_id)
        return _json_error(str(exc))


@prediction_bp.route("/configs/<prediction_config_id>", methods=["GET"])
def get_prediction_config(prediction_config_id: str):
    try:
        data = PredictionConfigService().get_config(prediction_config_id)
        return jsonify({"success": True, "data": data})
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except Exception as exc:
        logger.exception("查询预测配置失败: prediction_config_id=%s", prediction_config_id)
        return _json_error(str(exc))


@prediction_bp.route("/configs/<prediction_config_id>/status", methods=["GET"])
def get_prediction_config_status(prediction_config_id: str):
    try:
        data = PredictionConfigService().get_status(prediction_config_id)
        return jsonify({"success": True, "data": data})
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except Exception as exc:
        logger.exception("查询预测配置状态失败: prediction_config_id=%s", prediction_config_id)
        return _json_error(str(exc))


@prediction_bp.route("/configs/<prediction_config_id>/dataset", methods=["PATCH"])
def switch_prediction_config_dataset(prediction_config_id: str):
    try:
        data = request.get_json(silent=True) or {}
        player_dataset_id = data.get("player_dataset_id")
        if not player_dataset_id:
            return _json_code_error("player_dataset_id is required", "bad_request", 400)
        result = PredictionConfigService().switch_dataset(prediction_config_id, player_dataset_id)
        return jsonify({"success": True, "data": result})
    except DatasetNotFoundError as exc:
        return _json_code_error(
            str(exc).strip("'"),
            "dataset_not_found",
            404,
            {"available_datasets": exc.available_datasets},
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except Exception as exc:
        logger.exception("切换预测配置数据集失败: prediction_config_id=%s", prediction_config_id)
        return _json_error(str(exc))


@prediction_bp.route("/configs/<prediction_config_id>/progress", methods=["GET"])
def get_prediction_config_progress(prediction_config_id: str):
    try:
        data = PredictionConfigService().get_progress(prediction_config_id)
        return jsonify({"success": True, "data": data})
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except Exception as exc:
        logger.exception("查询预测配置进度失败: prediction_config_id=%s", prediction_config_id)
        return _json_error(str(exc))


@prediction_bp.route("/configs/<prediction_config_id>/roster", methods=["GET"])
def get_prediction_config_roster(prediction_config_id: str):
    try:
        data = PredictionConfigService().get_roster(prediction_config_id)
        return jsonify({"success": True, "data": data})
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except Exception as exc:
        logger.exception("查询配置名册失败: prediction_config_id=%s", prediction_config_id)
        return _json_error(str(exc))


@prediction_bp.route("/configs/<prediction_config_id>/coach-agents", methods=["GET"])
def get_prediction_config_coach_agents(prediction_config_id: str):
    try:
        rows = PredictionConfigService().list_coach_agents(prediction_config_id)
        return jsonify({"success": True, "data": {"coach_agents": rows}, "count": len(rows)})
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except Exception as exc:
        logger.exception("查询教练评审团失败: prediction_config_id=%s", prediction_config_id)
        return _json_error(str(exc))


@prediction_bp.route("/configs/<prediction_config_id>/coach-discussions", methods=["GET"])
def get_prediction_config_coach_discussions(prediction_config_id: str):
    try:
        rows = PredictionConfigService().list_coach_discussions(prediction_config_id)
        return jsonify({"success": True, "data": {"coach_discussions": rows}, "count": len(rows)})
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except Exception as exc:
        logger.exception("查询教练讨论失败: prediction_config_id=%s", prediction_config_id)
        return _json_error(str(exc))


@prediction_bp.route("/configs/<prediction_config_id>/scenario-design", methods=["GET"])
def get_prediction_config_scenario_design(prediction_config_id: str):
    try:
        service = PredictionConfigService()
        config = service.get_config(prediction_config_id)
        rows = service.list_scenario_cases(prediction_config_id)
        return jsonify({
            "success": True,
            "data": {
                "scenario_design_summary": config["scenario_design_summary"],
                "scenario_cases": rows,
            },
            "count": len(rows),
        })
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except Exception as exc:
        logger.exception("查询场景设计失败: prediction_config_id=%s", prediction_config_id)
        return _json_error(str(exc))


@prediction_bp.route("/configs/<prediction_config_id>/resume-policy", methods=["GET"])
def get_prediction_config_resume_policy(prediction_config_id: str):
    try:
        service = PredictionConfigService()
        config = service.get_config(prediction_config_id)
        rows = service.list_resume_nodes(prediction_config_id)
        return jsonify({
            "success": True,
            "data": {
                "resume_policy_summary": config["resume_policy_summary"],
                "resume_nodes": rows,
            },
            "count": len(rows),
        })
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except Exception as exc:
        logger.exception("查询恢复策略失败: prediction_config_id=%s", prediction_config_id)
        return _json_error(str(exc))


@prediction_bp.route("/configs/<prediction_config_id>/team-strengths", methods=["GET"])
def get_prediction_config_team_strengths(prediction_config_id: str):
    try:
        rows = PredictionConfigService().list_team_strengths(prediction_config_id)
        return jsonify({"success": True, "data": {"team_strengths": rows}, "count": len(rows)})
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except Exception as exc:
        logger.exception("查询配置球队强度失败: prediction_config_id=%s", prediction_config_id)
        return _json_error(str(exc))


@prediction_bp.route("/<prediction_run_id>/resume", methods=["POST"])
def resume_prediction(prediction_run_id: str):
    """Return current persisted status.

    The first implementation writes deterministic artifacts synchronously. The
    endpoint exists so the frontend can use the new football-only resume
    contract while workflow-level resume is implemented behind it.
    """
    try:
        status = PredictionPersistenceService().get_status(prediction_run_id)
        return jsonify({"success": True, "data": status})
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except Exception as exc:
        logger.exception("恢复足球预测失败: prediction_run_id=%s", prediction_run_id)
        return _json_error(str(exc))


@prediction_bp.route("/<prediction_run_id>/replay", methods=["POST"])
def replay_prediction(prediction_run_id: str):
    """Replay a completed Step3 run with its original seed and config snapshot."""
    try:
        result = PredictionPersistenceService().replay_prediction(prediction_run_id)
        return jsonify({"success": True, "data": result})
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return _json_code_error(str(exc), "replay_drift_blocked", 409)
    except Exception as exc:
        logger.exception("复现足球预测失败: prediction_run_id=%s", prediction_run_id)
        return _json_error(str(exc))


@prediction_bp.route("/<prediction_run_id>/report", methods=["POST"])
def create_prediction_report(prediction_run_id: str):
    """Create a replayable Step4 report from persisted football artifacts."""
    try:
        data = request.get_json(silent=True) or {}
        result = PredictionReportAssembler().create_report(
            prediction_run_id,
            force_regenerate=bool(data.get("force_regenerate", False)),
        )
        return jsonify({"success": True, "data": result})
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return _json_code_error(str(exc), "inactive_prediction_run", 409)
    except Exception as exc:
        logger.exception("生成足球预测报告失败: prediction_run_id=%s", prediction_run_id)
        return _json_error(str(exc))


@prediction_bp.route("/<prediction_run_id>/status", methods=["GET"])
def get_prediction_status(prediction_run_id: str):
    try:
        is_active_run = True
        try:
            _ensure_active_prediction_run(prediction_run_id)
        except ValueError:
            is_active_run = False
        prediction_service = PredictionPersistenceService()
        status = prediction_service.get_status(prediction_run_id)
        status["is_active_run"] = is_active_run
        celery_task_id = (status.get("metadata") or {}).get("celery_task_id")
        if celery_task_id:
            task_service = TaskWorkflowService()
            job = task_service.get_celery_job(celery_task_id)
            if job:
                job_retry = (job.get("metadata") or {}).get("retry")
                has_terminal_recorded_error = (
                    job.get("last_error")
                    and isinstance(job_retry, int)
                    and job_retry >= Config.WORKFLOW_EVENT_MAX_RETRIES
                )
                if not has_terminal_recorded_error:
                    job = _sync_celery_backend_status(
                        celery_task_id=celery_task_id,
                        job=job,
                        task_service=task_service,
                    )
                status["celery_job"] = job
                stale_error = _stale_async_error(job, status)
                if stale_error:
                    job = task_service.finish_celery_job(
                        celery_task_id,
                        status=CeleryJobStatus.FAILED,
                        last_error=stale_error,
                        metadata={"stale": True},
                    )
                    status = prediction_service.sync_async_failure_from_celery_job(
                        prediction_run_id,
                        job,
                    )
                    status["is_active_run"] = is_active_run
                    status["celery_job"] = job
                    return jsonify({"success": True, "data": status})

                job_status = job.get("status")
                job_error = job.get("last_error")
                job_retry = (job.get("metadata") or {}).get("retry")
                is_terminal_failure = job_status == CeleryJobStatus.FAILED.value or (
                    job_status in {CeleryJobStatus.RUNNING.value, CeleryJobStatus.RETRYING.value}
                    and job_error
                    and isinstance(job_retry, int)
                    and job_retry >= Config.WORKFLOW_EVENT_MAX_RETRIES
                )
                if status["status"] in {"queued", "running"} and is_terminal_failure:
                    status = prediction_service.sync_async_failure_from_celery_job(prediction_run_id, job)
                    status["is_active_run"] = is_active_run
                    status["celery_job"] = job
        return jsonify({"success": True, "data": status})
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return _json_code_error(str(exc), "inactive_prediction_run", 409)
    except Exception as exc:
        logger.exception("查询足球预测状态失败: prediction_run_id=%s", prediction_run_id)
        return _json_error(str(exc))


@prediction_bp.route("/<prediction_run_id>/scenario-cases", methods=["GET"])
def get_scenario_cases(prediction_run_id: str):
    try:
        _ensure_active_prediction_run(prediction_run_id)
        rows = PredictionPersistenceService().list_scenario_cases(prediction_run_id)
        return jsonify({"success": True, "data": {"scenario_cases": rows}, "count": len(rows)})
    except ValueError as exc:
        return _json_code_error(str(exc), "inactive_prediction_run", 409)
    except Exception as exc:
        logger.exception("查询场景矩阵失败: prediction_run_id=%s", prediction_run_id)
        return _json_error(str(exc))


@prediction_bp.route("/<prediction_run_id>/roster", methods=["GET"])
def get_prediction_run_roster(prediction_run_id: str):
    try:
        _ensure_active_prediction_run(prediction_run_id)
        data = PredictionPersistenceService().get_roster(prediction_run_id)
        return jsonify({"success": True, "data": data})
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return _json_code_error(str(exc), "inactive_prediction_run", 409)
    except Exception as exc:
        logger.exception("查询运行名册失败: prediction_run_id=%s", prediction_run_id)
        return _json_error(str(exc))


@prediction_bp.route("/<prediction_run_id>/budget-usage", methods=["GET"])
def get_prediction_budget_usage(prediction_run_id: str):
    try:
        _ensure_active_prediction_run(prediction_run_id)
        data = PredictionPersistenceService().get_budget_usage(prediction_run_id)
        return jsonify({"success": True, "data": data})
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return _json_code_error(str(exc), "inactive_prediction_run", 409)
    except Exception as exc:
        logger.exception("查询运行 LLM 预算失败: prediction_run_id=%s", prediction_run_id)
        return _json_error(str(exc))


@prediction_bp.route("/<prediction_run_id>/team-strengths", methods=["GET"])
def get_team_strengths(prediction_run_id: str):
    try:
        _ensure_active_prediction_run(prediction_run_id)
        rows = PredictionPersistenceService().list_team_strengths(prediction_run_id)
        return jsonify({"success": True, "data": {"team_strengths": rows}, "count": len(rows)})
    except ValueError as exc:
        return _json_code_error(str(exc), "inactive_prediction_run", 409)
    except Exception as exc:
        logger.exception("查询球队强度失败: prediction_run_id=%s", prediction_run_id)
        return _json_error(str(exc))


@prediction_bp.route("/<prediction_run_id>/scorelines", methods=["GET"])
def get_scorelines(prediction_run_id: str):
    try:
        _ensure_active_prediction_run(prediction_run_id)
        rows = PredictionPersistenceService().list_scorelines(prediction_run_id)
        return jsonify({"success": True, "data": {"scorelines": rows}, "count": len(rows)})
    except ValueError as exc:
        return _json_code_error(str(exc), "inactive_prediction_run", 409)
    except Exception as exc:
        logger.exception("查询比分分布失败: prediction_run_id=%s", prediction_run_id)
        return _json_error(str(exc))


@prediction_bp.route("/<prediction_run_id>/scenario-spaces", methods=["GET"])
def get_scenario_spaces(prediction_run_id: str):
    try:
        _ensure_active_prediction_run(prediction_run_id)
        rows = PredictionPersistenceService().list_scenario_spaces(prediction_run_id)
        return jsonify({"success": True, "data": {"scenario_spaces": rows}, "count": len(rows)})
    except ValueError as exc:
        return _json_code_error(str(exc), "inactive_prediction_run", 409)
    except Exception as exc:
        logger.exception("查询场景空间失败: prediction_run_id=%s", prediction_run_id)
        return _json_error(str(exc))


@prediction_bp.route("/<prediction_run_id>/match-events", methods=["GET"])
def get_match_events(prediction_run_id: str):
    try:
        _ensure_active_prediction_run(prediction_run_id)
        rows = PredictionPersistenceService().list_match_events(prediction_run_id)
        return jsonify({"success": True, "data": {"match_events": rows}, "count": len(rows)})
    except ValueError as exc:
        return _json_code_error(str(exc), "inactive_prediction_run", 409)
    except Exception as exc:
        logger.exception("查询比赛事件失败: prediction_run_id=%s", prediction_run_id)
        return _json_error(str(exc))


@prediction_bp.route("/<prediction_run_id>/analyst-notes", methods=["GET"])
def get_analyst_notes(prediction_run_id: str):
    try:
        _ensure_active_prediction_run(prediction_run_id)
        rows = PredictionPersistenceService().list_analyst_notes(prediction_run_id)
        return jsonify({"success": True, "data": {"analyst_notes": rows}, "count": len(rows)})
    except ValueError as exc:
        return _json_code_error(str(exc), "inactive_prediction_run", 409)
    except Exception as exc:
        logger.exception("查询模型研判失败: prediction_run_id=%s", prediction_run_id)
        return _json_error(str(exc))


@prediction_bp.route("/<prediction_run_id>/result", methods=["GET"])
def get_prediction_result(prediction_run_id: str):
    try:
        _ensure_active_prediction_run(prediction_run_id)
        result = PredictionPersistenceService().get_result(prediction_run_id)
        if result is None:
            return jsonify({"success": False, "error": f"预测结果不存在: {prediction_run_id}"}), 404
        return jsonify({"success": True, "data": result})
    except ValueError as exc:
        return _json_code_error(str(exc), "inactive_prediction_run", 409)
    except Exception as exc:
        logger.exception("查询预测结果失败: prediction_run_id=%s", prediction_run_id)
        return _json_error(str(exc))

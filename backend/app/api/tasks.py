"""
Persistent prediction task APIs.
"""

import traceback

from flask import jsonify, request

from . import tasks_bp
from ..services.task_workflow import WorkflowStateError
from ..services.task_workflow import TaskWorkflowService
from ..tasks.workflow_tasks import enqueue_workflow_event
from ..utils.logger import get_logger


logger = get_logger("goalfish.api.tasks")


def _json_error(message: str, status_code: int = 500):
    return jsonify({"success": False, "error": message, "traceback": traceback.format_exc()}), status_code


@tasks_bp.route("", methods=["POST"])
def create_prediction_task():
    try:
        data = request.get_json() or {}
        project_id = data.get("project_id")
        name = data.get("name") or data.get("project_name") or "Unnamed Prediction Task"
        metadata = data.get("metadata") or {}
        config = data.get("config") or {}

        task = TaskWorkflowService().create_task(
            project_id=project_id,
            name=name,
            metadata=metadata,
            config=config,
        )
        return jsonify({"success": True, "data": task})
    except Exception as exc:
        logger.exception("创建 prediction task 失败")
        return _json_error(str(exc))


@tasks_bp.route("/<task_id>", methods=["GET"])
def get_prediction_task(task_id: str):
    try:
        task = TaskWorkflowService().get_task(task_id)
        if task is None:
            return jsonify({"success": False, "error": f"任务不存在: {task_id}"}), 404
        return jsonify({"success": True, "data": task})
    except Exception as exc:
        logger.exception("查询 prediction task 失败: %s", task_id)
        return _json_error(str(exc))


@tasks_bp.route("/by-project/<project_id>", methods=["GET"])
def get_prediction_task_by_project(project_id: str):
    try:
        task = TaskWorkflowService().get_task_by_project_id(project_id)
        if task is None:
            return jsonify({"success": False, "error": f"项目未绑定任务: {project_id}"}), 404
        return jsonify({"success": True, "data": task})
    except Exception as exc:
        logger.exception("按 project 查询 prediction task 失败: %s", project_id)
        return _json_error(str(exc))


@tasks_bp.route("/<task_id>/snapshot", methods=["GET"])
def get_prediction_task_snapshot(task_id: str):
    try:
        snapshot = TaskWorkflowService().get_task_snapshot(task_id)
        if snapshot is None:
            return jsonify({"success": False, "error": f"任务不存在: {task_id}"}), 404
        return jsonify({"success": True, "data": snapshot})
    except Exception as exc:
        logger.exception("查询 task snapshot 失败: %s", task_id)
        return _json_error(str(exc))


@tasks_bp.route("/by-project/<project_id>/snapshot", methods=["GET"])
def get_prediction_task_snapshot_by_project(project_id: str):
    try:
        snapshot = TaskWorkflowService().get_task_snapshot_by_project_id(project_id)
        if snapshot is None:
            return jsonify({"success": False, "error": f"项目未绑定任务: {project_id}"}), 404
        return jsonify({"success": True, "data": snapshot})
    except Exception as exc:
        logger.exception("按 project 查询 task snapshot 失败: %s", project_id)
        return _json_error(str(exc))


@tasks_bp.route("/<task_id>/attempts", methods=["GET"])
def list_prediction_task_attempts(task_id: str):
    try:
        attempts = TaskWorkflowService().list_attempts(task_id)
        return jsonify({"success": True, "data": attempts, "count": len(attempts)})
    except Exception as exc:
        logger.exception("查询 task attempts 失败: %s", task_id)
        return _json_error(str(exc))


@tasks_bp.route("/<task_id>/attempts/<attempt_id>/events", methods=["GET"])
def list_prediction_task_events(task_id: str, attempt_id: str):
    try:
        events = TaskWorkflowService().list_events(task_id, attempt_id)
        return jsonify({"success": True, "data": events, "count": len(events)})
    except Exception as exc:
        logger.exception("查询 task events 失败: %s", task_id)
        return _json_error(str(exc))


@tasks_bp.route("/<task_id>/artifacts", methods=["GET"])
def list_prediction_task_artifacts(task_id: str):
    try:
        artifacts = TaskWorkflowService().list_artifacts(
            task_id,
            attempt_id=request.args.get("attempt_id"),
            event_type=request.args.get("event_type"),
        )
        return jsonify({"success": True, "data": artifacts, "count": len(artifacts)})
    except Exception as exc:
        logger.exception("查询 task artifacts 失败: %s", task_id)
        return _json_error(str(exc))


@tasks_bp.route("/<task_id>/llm-interactions", methods=["GET"])
def list_prediction_task_llm_interactions(task_id: str):
    try:
        interactions = TaskWorkflowService().list_llm_interactions(
            task_id,
            attempt_id=request.args.get("attempt_id"),
            event_type=request.args.get("event_type"),
        )
        return jsonify({"success": True, "data": interactions, "count": len(interactions)})
    except Exception as exc:
        logger.exception("查询 LLM interactions 失败: %s", task_id)
        return _json_error(str(exc))


@tasks_bp.route("/<task_id>/celery-jobs", methods=["GET"])
def list_prediction_task_celery_jobs(task_id: str):
    try:
        jobs = TaskWorkflowService().list_celery_jobs(
            task_id,
            attempt_id=request.args.get("attempt_id"),
            event_id=request.args.get("event_id"),
        )
        return jsonify({"success": True, "data": jobs, "count": len(jobs)})
    except Exception as exc:
        logger.exception("查询 Celery jobs 失败: %s", task_id)
        return _json_error(str(exc))


def _payload_from_latest_job(
    service: TaskWorkflowService,
    task_id: str,
    attempt_id: str,
    event_id: str,
) -> dict:
    jobs = service.list_celery_jobs(task_id, attempt_id=attempt_id, event_id=event_id)
    for job in reversed(jobs):
        payload = (job.get("metadata") or {}).get("payload")
        if isinstance(payload, dict):
            return dict(payload)
    return {}


@tasks_bp.route("/<task_id>/resume", methods=["POST"])
def resume_prediction_task(task_id: str):
    try:
        data = request.get_json() or {}
        service = TaskWorkflowService()
        event = service.get_resume_event(
            task_id,
            attempt_id=data.get("attempt_id"),
            from_event_type=data.get("from_event_type"),
        )
        if event["status"] == "running":
            service.mark_running_events_interrupted(
                task_id=task_id,
                attempt_id=event["attempt_id"],
                message="恢复任务前将旧 running 事件标记为中断",
            )
            event = service.get_resume_event(
                task_id,
                attempt_id=event["attempt_id"],
                from_event_type=event["event_type"],
            )
        payload = data.get("payload")
        if not isinstance(payload, dict):
            payload = _payload_from_latest_job(
                service,
                task_id,
                event["attempt_id"],
                event["id"],
            )
        payload.update(
            {
                "workflow_task_id": task_id,
                "workflow_attempt_id": event["attempt_id"],
            }
        )
        job = enqueue_workflow_event(
            event_type=event["event_type"],
            payload=payload,
            task_id=task_id,
            attempt_id=event["attempt_id"],
            event_id=event["id"],
        )
        return jsonify(
            {
                "success": True,
                "data": {
                    "event": event,
                    "job": job,
                    "snapshot": service.get_task_snapshot(task_id),
                },
            }
        )
    except (KeyError, WorkflowStateError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.exception("恢复 task attempt 失败: %s", task_id)
        return _json_error(str(exc))


@tasks_bp.route("/<task_id>/rerun", methods=["POST"])
def rerun_prediction_task(task_id: str):
    try:
        data = request.get_json() or {}
        from_event_type = data.get("from_event_type")
        if not from_event_type:
            return jsonify({"success": False, "error": "from_event_type 必填"}), 400
        task = TaskWorkflowService().create_rerun_attempt(
            task_id,
            from_event_type=from_event_type,
            config_overrides=data.get("config_overrides") or {},
        )
        return jsonify({"success": True, "data": task})
    except Exception as exc:
        logger.exception("创建 rerun attempt 失败: %s", task_id)
        return _json_error(str(exc))

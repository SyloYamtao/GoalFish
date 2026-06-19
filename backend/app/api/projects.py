"""Project workflow lineage APIs."""

from __future__ import annotations

import traceback

from flask import jsonify, request

from . import projects_bp
from ..services.project_workflow import ProjectWorkflowService, WorkflowConflictError
from ..utils.logger import get_logger


logger = get_logger("goalfish.api.projects")


@projects_bp.route("/<project_id>/workflow", methods=["GET"])
def get_project_workflow(project_id: str):
    try:
        state = ProjectWorkflowService().get_state(project_id)
        return jsonify({"success": True, "data": state})
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except Exception as exc:
        logger.exception("查询项目工作流失败: project_id=%s", project_id)
        return jsonify({"success": False, "error": str(exc), "traceback": traceback.format_exc()}), 500


@projects_bp.route("/<project_id>/steps/<int:step>/regenerate", methods=["POST"])
def regenerate_project_step(project_id: str, step: int):
    try:
        data = request.get_json(silent=True) or {}
        state = ProjectWorkflowService().regenerate_step(
            project_id,
            step,
            reason=data.get("reason") or "user_requested",
            preserve_history=bool(data.get("preserve_history", True)),
        )
        return jsonify(state)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc), "code": "bad_request"}), 400
    except WorkflowConflictError as exc:
        return jsonify({"success": False, "error": str(exc), "code": "workflow_running"}), 409
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc), "code": "not_found"}), 404
    except Exception as exc:
        logger.exception("重新生成项目步骤失败: project_id=%s step=%s", project_id, step)
        return jsonify({"success": False, "error": str(exc), "traceback": traceback.format_exc()}), 500

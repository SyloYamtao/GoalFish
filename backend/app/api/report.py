"""
Report API路由
提供模拟报告生成、获取、对话等接口
"""

import traceback
from flask import request, jsonify, Response

from . import report_bp
from ..services.football_prediction import PredictionReportAssembler
from ..services.project_workflow import ProjectWorkflowService
from ..services.report_agent import ReportManager, ReportStatus
from ..services.simulation_domains import FOOTBALL_MATCH
from ..models.task import TaskManager
from ..db.models import (
    PredictionResultRecord,
    PredictionRunRecord,
)
from ..db.session import get_session
from ..utils.logger import get_logger
from ..utils.locale import t

logger = get_logger('goalfish.api.report')


def _build_football_prediction_chat_response(report, message: str, chat_history: list[dict] | None = None) -> dict:
    """Answer Step5 questions from persisted football prediction artifacts."""
    return PredictionReportAssembler().answer_question(
        report_id=report.report_id,
        prediction_run_id=report.simulation_id,
        message=message,
        chat_history=chat_history or [],
    )


def _prediction_run_exists(prediction_run_id: str | None) -> bool:
    if not prediction_run_id:
        return False
    with get_session() as session:
        return session.get(PredictionRunRecord, prediction_run_id) is not None


def _ensure_score_phrase(content: str, result: dict, prediction_run_id: str | None = None) -> str:
    if "最可能比分" in (content or ""):
        return content
    most_likely = None
    try:
        evidence = (
            ((result.get("metadata") or {}).get("evidence_package") or {})
            if isinstance(result.get("metadata"), dict)
            else {}
        )
        most_likely = (
            ((evidence.get("step3") or {}).get("scoreline_summary") or {}).get("most_likely_score")
            or ((evidence.get("step3") or {}).get("top_scores") or [{}])[0].get("score")
        )
    except Exception:
        most_likely = None
    most_likely = most_likely or _most_likely_score_for_run(prediction_run_id)
    prefix = f"根据报告，**最可能比分** 是 **{most_likely or '资料未明确'}**。"
    return f"{prefix}\n\n{content or ''}".strip()


def _most_likely_score_for_run(prediction_run_id: str | None) -> str | None:
    if not prediction_run_id:
        return None
    with get_session() as session:
        row = session.query(PredictionResultRecord).filter_by(prediction_run_id=prediction_run_id).one_or_none()
        if not row:
            return None
        return (
            ((row.scoreline_summary or {}).get("most_likely_score"))
            or ((row.final_score_hypothesis or {}).get("score"))
        )


def _report_payload_with_lineage(report) -> dict:
    payload = report.to_dict()
    try:
        lineage = ProjectWorkflowService().report_lineage_info(report.report_id)
    except Exception:
        lineage = {}
    if lineage:
        payload.update(
            {
                "project_id": lineage.get("project_id"),
                "active_report_id": lineage.get("active_report_id"),
                "active_prediction_run_id": lineage.get("active_prediction_run_id"),
                "is_active_report": lineage.get("is_active_report"),
                "artifact_status": lineage.get("artifact_status"),
                "stored_artifact_status": lineage.get("stored_artifact_status"),
                "workflow_revision": lineage.get("workflow_revision"),
                "current_workflow_revision": lineage.get("current_workflow_revision"),
            }
        )
        metadata = dict(payload.get("report_metadata") or {})
        metadata.setdefault("project_id", lineage.get("project_id"))
        metadata["artifact_status"] = lineage.get("artifact_status")
        metadata["stored_artifact_status"] = lineage.get("stored_artifact_status")
        metadata.setdefault("workflow_revision", lineage.get("workflow_revision"))
        metadata["is_active_report"] = lineage.get("is_active_report")
        metadata["active_report_id"] = lineage.get("active_report_id")
        metadata["active_prediction_run_id"] = lineage.get("active_prediction_run_id")
        payload["report_metadata"] = metadata
    return payload


# ============== 报告生成接口 ==============

@report_bp.route('/generate', methods=['POST'])
def generate_report():
    """
    生成模拟分析报告（异步任务）
    
    这是一个耗时操作，接口会立即返回task_id，
    使用 GET /api/report/generate/status 查询进度
    
    请求（JSON）：
        {
            "simulation_id": "sim_xxxx",    // 必填，模拟ID
            "force_regenerate": false        // 可选，强制重新生成
        }
    
    返回：
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "task_id": "task_xxxx",
                "status": "generating",
                "message": "报告生成任务已启动"
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id') or data.get('prediction_run_id')
        prediction_config_id = data.get('prediction_config_id')
        project_id = data.get('project_id')
        if not simulation_id and not project_id:
            return jsonify({
                "success": False,
                "error": "simulation_id / prediction_run_id or project_id is required"
            }), 400

        force_regenerate = data.get('force_regenerate', False)

        if project_id:
            result = PredictionReportAssembler().create_report_for_project(
                project_id,
                force_regenerate=bool(force_regenerate),
                prediction_run_id=simulation_id,
                prediction_config_id=prediction_config_id,
            )
            return jsonify({
                "success": True,
                "data": {
                    **result,
                    "simulation_id": result["prediction_run_id"],
                    "project_id": project_id,
                    "message": "足球预测报告已生成",
                }
            })

        if simulation_id and _prediction_run_exists(simulation_id):
            result = PredictionReportAssembler().create_report(
                simulation_id,
                force_regenerate=bool(force_regenerate),
            )
            return jsonify({
                "success": True,
                "data": {
                    **result,
                    "simulation_id": simulation_id,
                    "message": "足球预测报告已生成",
                }
            })

        return jsonify({
            "success": False,
            "error": "当前版本只支持足球预测报告，请传入有效的 prediction_run_id 或 project_id",
        }), 404

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e),
        }), 400
    except Exception as e:
        logger.error(f"启动报告生成任务失败: {str(e)}")
        status_code = 409 if "已失效" in str(e) or "请先完成 Step3" in str(e) or "请重新生成" in str(e) else 500
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), status_code


@report_bp.route('/generate/status', methods=['POST'])
def get_generate_status():
    """
    查询报告生成任务进度
    
    请求（JSON）：
        {
            "task_id": "task_xxxx",         // 可选，generate返回的task_id
            "simulation_id": "sim_xxxx"     // 可选，模拟ID
        }
    
    返回：
        {
            "success": true,
            "data": {
                "task_id": "task_xxxx",
                "status": "processing|completed|failed",
                "progress": 45,
                "message": "..."
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        task_id = data.get('task_id')
        simulation_id = data.get('simulation_id')
        
        # 如果提供了simulation_id，先检查是否已有完成的报告
        if simulation_id:
            existing_report = ReportManager.get_report_by_simulation(simulation_id)
            if existing_report and existing_report.status == ReportStatus.COMPLETED:
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "report_id": existing_report.report_id,
                        "status": "completed",
                        "progress": 100,
                        "message": t('api.reportGenerated'),
                        "already_completed": True
                    }
                })
        
        if not task_id:
            return jsonify({
                "success": False,
                "error": t('api.requireTaskOrSimId')
            }), 400
        
        task_manager = TaskManager()
        task = task_manager.get_task(task_id)
        
        if not task:
            return jsonify({
                "success": False,
                "error": t('api.taskNotFound', id=task_id)
            }), 404
        
        return jsonify({
            "success": True,
            "data": task.to_dict()
        })
        
    except Exception as e:
        logger.error(f"查询任务状态失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============== 报告获取接口 ==============

@report_bp.route('/<report_id>', methods=['GET'])
def get_report(report_id: str):
    """
    获取报告详情
    
    返回：
        {
            "success": true,
            "data": {
                "report_id": "report_xxxx",
                "simulation_id": "sim_xxxx",
                "status": "completed",
                "outline": {...},
                "markdown_content": "...",
                "created_at": "...",
                "completed_at": "..."
            }
        }
    """
    try:
        report = ReportManager.get_report(report_id)
        
        if not report:
            return jsonify({
                "success": False,
                "error": t('api.reportNotFound', id=report_id)
            }), 404
        return jsonify({
            "success": True,
            "data": _report_payload_with_lineage(report)
        })
        
    except Exception as e:
        logger.error(f"获取报告失败: {str(e)}")
        status_code = 409 if "已失效" in str(e) or "请重新生成" in str(e) else 500
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), status_code


@report_bp.route('/<report_id>/conversations', methods=['GET'])
def list_report_conversations(report_id: str):
    """列出报告相关对话。"""
    try:
        report = ReportManager.get_report(report_id)
        if not report:
            return jsonify({
                "success": False,
                "error": t('api.reportNotFound', id=report_id)
            }), 404
        ProjectWorkflowService().require_active_report(report_id)

        conversations = ReportManager.list_conversations(
            report_id,
            target_type=request.args.get("target_type"),
            target_agent_id=request.args.get("target_agent_id"),
        )
        return jsonify({
            "success": True,
            "data": {
                "conversations": conversations,
                "count": len(conversations),
            }
        })
    except Exception as e:
        logger.error(f"获取报告对话失败: {str(e)}")
        status_code = 409 if "已失效" in str(e) or "请重新生成" in str(e) else 500
        return jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}), status_code


@report_bp.route('/<report_id>/conversations', methods=['POST'])
def create_report_conversation(report_id: str):
    """获取或创建报告对话。"""
    try:
        data = request.get_json() or {}
        report = ReportManager.get_report(report_id)
        if not report:
            return jsonify({
                "success": False,
                "error": t('api.reportNotFound', id=report_id)
            }), 404
        ProjectWorkflowService().require_active_report(report_id)

        conversation = ReportManager.get_or_create_conversation(
            report_id=report_id,
            simulation_id=data.get("simulation_id") or report.simulation_id,
            target_type=data.get("target_type") or "report_agent",
            target_agent_id=data.get("target_agent_id"),
            title=data.get("title"),
            metadata=data.get("metadata") or {},
        )
        ProjectWorkflowService().mark_conversation_active(conversation["id"], report_id=report_id)
        return jsonify({"success": True, "data": conversation})
    except Exception as e:
        logger.error(f"创建报告对话失败: {str(e)}")
        status_code = 409 if "已失效" in str(e) or "请重新生成" in str(e) else 500
        return jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}), status_code


@report_bp.route('/<report_id>/conversations/<conversation_id>/messages', methods=['GET'])
def get_report_conversation_messages(report_id: str, conversation_id: str):
    """读取报告对话消息。"""
    try:
        conversation = ReportManager.get_conversation(conversation_id)
        if not conversation or conversation.get("report_id") != report_id:
            return jsonify({
                "success": False,
                "error": "对话不存在或不属于当前报告"
            }), 404
        ProjectWorkflowService().require_active_report(report_id)

        limit = request.args.get("limit", type=int)
        messages = ReportManager.list_conversation_messages(conversation_id, limit=limit)
        return jsonify({
            "success": True,
            "data": {
                "conversation": conversation,
                "messages": messages,
                "count": len(messages),
            }
        })
    except Exception as e:
        logger.error(f"获取报告对话消息失败: {str(e)}")
        status_code = 409 if "已失效" in str(e) or "请重新生成" in str(e) else 500
        return jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}), status_code


@report_bp.route('/<report_id>/conversations/<conversation_id>/messages', methods=['POST'])
def send_report_conversation_message(report_id: str, conversation_id: str):
    """发送消息给 Report Agent，并持久化 user/assistant 对话。"""
    try:
        data = request.get_json() or {}
        message = (data.get("message") or "").strip()
        if not message:
            return jsonify({
                "success": False,
                "error": t('api.requireMessage')
            }), 400

        report = ReportManager.get_report(report_id)
        if not report:
            return jsonify({
                "success": False,
                "error": t('api.reportNotFound', id=report_id)
            }), 404
        ProjectWorkflowService().require_active_report(report_id)

        conversation = ReportManager.get_conversation(conversation_id)
        if not conversation or conversation.get("report_id") != report_id:
            return jsonify({
                "success": False,
                "error": "对话不存在或不属于当前报告"
            }), 404

        if conversation.get("target_type") != "report_agent":
            return jsonify({
                "success": False,
                "error": "当前接口仅支持 Report Agent 对话"
            }), 400

        existing_messages = ReportManager.list_conversation_messages(conversation_id, limit=20)
        user_message = ReportManager.append_conversation_message(
            conversation_id=conversation_id,
            role="user",
            content=message,
        )

        if report.simulation_domain == FOOTBALL_MATCH and _prediction_run_exists(report.simulation_id):
            result = _build_football_prediction_chat_response(report, message, existing_messages)
        else:
            return jsonify({
                "success": False,
                "error": "当前版本只支持足球预测报告对话",
            }), 400

        assistant_content = _ensure_score_phrase(
            result.get("response") or result.get("answer") or "",
            result,
            report.simulation_id,
        )
        assistant_message = ReportManager.append_conversation_message(
            conversation_id=conversation_id,
            role="assistant",
            content=assistant_content,
            tool_calls=result.get("tool_calls") or [],
            sources=result.get("sources") or [],
            metadata={"raw_result": result},
        )

        return jsonify({
            "success": True,
            "data": {
                "conversation": ReportManager.get_conversation(conversation_id),
                "user_message": user_message,
                "assistant_message": assistant_message,
                "response": assistant_content,
                "tool_calls": result.get("tool_calls") or [],
                "sources": result.get("sources") or [],
            }
        })
    except Exception as e:
        logger.error(f"报告对话失败: {str(e)}")
        status_code = 409 if "已失效" in str(e) or "请重新生成" in str(e) else 500
        return jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}), status_code


@report_bp.route('/by-simulation/<simulation_id>', methods=['GET'])
def get_report_by_simulation(simulation_id: str):
    """
    根据模拟ID获取报告
    
    返回：
        {
            "success": true,
            "data": {
                "report_id": "report_xxxx",
                ...
            }
        }
    """
    try:
        report = ReportManager.get_report_by_simulation(simulation_id)
        
        if not report:
            return jsonify({
                "success": False,
                "error": t('api.noReportForSim', id=simulation_id),
                "has_report": False
            }), 404
        ProjectWorkflowService().require_active_report(report.report_id)
        
        return jsonify({
            "success": True,
            "data": report.to_dict(),
            "has_report": True
        })
        
    except Exception as e:
        logger.error(f"获取报告失败: {str(e)}")
        status_code = 409 if "已失效" in str(e) or "请重新生成" in str(e) else 500
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), status_code


@report_bp.route('/list', methods=['GET'])
def list_reports():
    """
    列出所有报告
    
    Query参数：
        simulation_id: 按模拟ID过滤（可选）
        limit: 返回数量限制（默认50）
    
    返回：
        {
            "success": true,
            "data": [...],
            "count": 10
        }
    """
    try:
        simulation_id = request.args.get('simulation_id')
        limit = request.args.get('limit', 50, type=int)
        
        reports = ReportManager.list_reports(
            simulation_id=simulation_id,
            limit=limit
        )
        
        return jsonify({
            "success": True,
            "data": [r.to_dict() for r in reports],
            "count": len(reports)
        })
        
    except Exception as e:
        logger.error(f"列出报告失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>/download', methods=['GET'])
def download_report(report_id: str):
    """
    下载报告（Markdown格式）
    
    返回Markdown文件
    """
    try:
        report = ReportManager.get_report(report_id)
        
        if not report:
            return jsonify({
                "success": False,
                "error": t('api.reportNotFound', id=report_id)
            }), 404
        ProjectWorkflowService().require_active_report(report_id)
        
        return Response(
            report.markdown_content or "",
            mimetype="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={report_id}.md"},
        )
        
    except Exception as e:
        logger.error(f"下载报告失败: {str(e)}")
        status_code = 409 if "已失效" in str(e) or "请重新生成" in str(e) else 500
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), status_code


@report_bp.route('/<report_id>', methods=['DELETE'])
def delete_report(report_id: str):
    """删除报告"""
    try:
        success = ReportManager.delete_report(report_id)
        
        if not success:
            return jsonify({
                "success": False,
                "error": t('api.reportNotFound', id=report_id)
            }), 404
        
        return jsonify({
            "success": True,
            "message": t('api.reportDeleted', id=report_id)
        })
        
    except Exception as e:
        logger.error(f"删除报告失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 预测报告助理对话接口 ==============

@report_bp.route('/chat', methods=['POST'])
def chat_with_report_agent():
    """
    与预测报告助理对话

    football-only 主路径优先读取 prediction_* 持久化产物回答。
    
    请求（JSON）：
        {
            "simulation_id": "sim_xxxx",        // 必填，模拟ID
            "message": "请解释这场比赛最可能的比分与关键风险",    // 必填，用户消息
            "chat_history": [                   // 可选，对话历史
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": "..."}
            ]
        }
    
    返回：
        {
            "success": true,
            "data": {
                "response": "预测助理回复...",
                "tool_calls": [调用的工具列表],
                "sources": [信息来源]
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        message = data.get('message')
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": t('api.requireSimulationId')
            }), 400

        if not message:
            return jsonify({
                "success": False,
                "error": t('api.requireMessage')
            }), 400

        report = ReportManager.get_report_by_simulation(simulation_id)
        if report and report.simulation_domain == FOOTBALL_MATCH and _prediction_run_exists(report.simulation_id):
            ProjectWorkflowService().require_active_report(report.report_id)
            result = _build_football_prediction_chat_response(report, message, data.get('chat_history') or [])
            result = {**result, "response": _ensure_score_phrase(result.get("response") or "", result, simulation_id)}
            return jsonify({
                "success": True,
                "data": result
            })

        return jsonify({
            "success": False,
            "error": "当前版本只支持足球预测报告对话",
        }), 404
        
    except Exception as e:
        logger.error(f"对话失败: {str(e)}")
        status_code = 409 if "已失效" in str(e) or "请重新生成" in str(e) else 500
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), status_code


# ============== 报告进度与分章节接口 ==============

@report_bp.route('/<report_id>/progress', methods=['GET'])
def get_report_progress(report_id: str):
    """
    获取报告生成进度（实时）
    
    返回：
        {
            "success": true,
            "data": {
                "status": "generating",
                "progress": 45,
                "message": "正在生成章节: 关键发现",
                "current_section": "关键发现",
                "completed_sections": ["执行摘要", "模拟背景"],
                "updated_at": "2025-12-09T..."
            }
        }
    """
    try:
        ProjectWorkflowService().require_active_report(report_id)
        progress = ReportManager.get_progress(report_id)
        
        if not progress:
            return jsonify({
                "success": False,
                "error": t('api.reportProgressNotAvail', id=report_id)
            }), 404
        
        return jsonify({
            "success": True,
            "data": progress
        })
        
    except Exception as e:
        logger.error(f"获取报告进度失败: {str(e)}")
        status_code = 409 if "已失效" in str(e) or "请重新生成" in str(e) else 500
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), status_code


@report_bp.route('/<report_id>/sections', methods=['GET'])
def get_report_sections(report_id: str):
    """
    获取已生成的章节列表（分章节输出）
    
    前端可以轮询此接口获取已生成的章节内容，无需等待整个报告完成
    
    返回：
        {
            "success": true,
            "data": {
                "report_id": "report_xxxx",
                "sections": [
                    {
                        "filename": "section_01.md",
                        "section_index": 1,
                        "content": "## 执行摘要\\n\\n..."
                    },
                    ...
                ],
                "total_sections": 3,
                "is_complete": false
            }
        }
    """
    try:
        sections = ReportManager.get_generated_sections(report_id)
        
        # 获取报告状态
        report = ReportManager.get_report(report_id)
        is_complete = report is not None and report.status == ReportStatus.COMPLETED
        
        return jsonify({
            "success": True,
            "data": {
                "report_id": report_id,
                "sections": sections,
                "total_sections": len(sections),
                "is_complete": is_complete
            }
        })
        
    except Exception as e:
        logger.error(f"获取章节列表失败: {str(e)}")
        status_code = 409 if "已失效" in str(e) or "请重新生成" in str(e) else 500
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), status_code


@report_bp.route('/<report_id>/section/<int:section_index>', methods=['GET'])
def get_single_section(report_id: str, section_index: int):
    """
    获取单个章节内容
    
    返回：
        {
            "success": true,
            "data": {
                "filename": "section_01.md",
                "content": "## 执行摘要\\n\\n..."
            }
        }
    """
    try:
        section = next(
            (
                item for item in ReportManager.get_generated_sections(report_id)
                if item["section_index"] == section_index
            ),
            None,
        )
        if not section:
            return jsonify({
                "success": False,
                "error": t('api.sectionNotFound', index=f"{section_index:02d}")
            }), 404
        content = section["content"]
        
        return jsonify({
            "success": True,
            "data": {
                "filename": f"section_{section_index:02d}.md",
                "section_index": section_index,
                "content": content
            }
        })
        
    except Exception as e:
        logger.error(f"获取章节内容失败: {str(e)}")
        status_code = 409 if "已失效" in str(e) or "请重新生成" in str(e) else 500
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), status_code


# ============== 报告状态检查接口 ==============

@report_bp.route('/check/<simulation_id>', methods=['GET'])
def check_report_status(simulation_id: str):
    """
    检查模拟是否有报告，以及报告状态
    
    用于前端判断是否解锁Interview功能
    
    返回：
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "has_report": true,
                "report_status": "completed",
                "report_id": "report_xxxx",
                "interview_unlocked": true
            }
        }
    """
    try:
        report = ReportManager.get_report_by_simulation(simulation_id)
        if report:
            try:
                ProjectWorkflowService().require_active_report(report.report_id)
            except Exception:
                report = None
        
        has_report = report is not None
        report_status = report.status.value if report else None
        report_id = report.report_id if report else None
        
        # 只有报告完成后才解锁interview
        interview_unlocked = has_report and report.status == ReportStatus.COMPLETED
        
        return jsonify({
            "success": True,
            "data": {
                "simulation_id": simulation_id,
                "has_report": has_report,
                "report_status": report_status,
                "report_id": report_id,
                "interview_unlocked": interview_unlocked
            }
        })
        
    except Exception as e:
        logger.error(f"检查报告状态失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Agent 日志接口 ==============

@report_bp.route('/<report_id>/agent-log', methods=['GET'])
def get_agent_log(report_id: str):
    """
    获取 Report Agent 的详细执行日志
    
    实时获取报告生成过程中的每一步动作，包括：
    - 报告开始、规划开始/完成
    - 每个章节的开始、工具调用、LLM响应、完成
    - 报告完成或失败
    
    Query参数：
        from_line: 从第几行开始读取（可选，默认0，用于增量获取）
    
    返回：
        {
            "success": true,
            "data": {
                "logs": [
                    {
                        "timestamp": "2025-12-13T...",
                        "elapsed_seconds": 12.5,
                        "report_id": "report_xxxx",
                        "action": "tool_call",
                        "stage": "generating",
                        "section_title": "执行摘要",
                        "section_index": 1,
                        "details": {
                            "tool_name": "insight_forge",
                            "parameters": {...},
                            ...
                        }
                    },
                    ...
                ],
                "total_lines": 25,
                "from_line": 0,
                "has_more": false
            }
        }
    """
    try:
        from_line = request.args.get('from_line', 0, type=int)
        
        log_data = ReportManager.get_agent_log(report_id, from_line=from_line)
        
        return jsonify({
            "success": True,
            "data": log_data
        })
        
    except Exception as e:
        logger.error(f"获取Agent日志失败: {str(e)}")
        status_code = 409 if "已失效" in str(e) or "请重新生成" in str(e) else 500
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), status_code


@report_bp.route('/<report_id>/agent-log/stream', methods=['GET'])
def stream_agent_log(report_id: str):
    """
    获取完整的 Agent 日志（一次性获取全部）
    
    返回：
        {
            "success": true,
            "data": {
                "logs": [...],
                "count": 25
            }
        }
    """
    try:
        logs = ReportManager.get_agent_log_stream(report_id)
        
        return jsonify({
            "success": True,
            "data": {
                "logs": logs,
                "count": len(logs)
            }
        })
        
    except Exception as e:
        logger.error(f"获取Agent日志失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 控制台日志接口 ==============

@report_bp.route('/<report_id>/console-log', methods=['GET'])
def get_console_log(report_id: str):
    """
    获取 Report Agent 的控制台输出日志
    
    实时获取报告生成过程中的控制台输出（INFO、WARNING等），
    这与 agent-log 接口返回的结构化 JSON 日志不同，
    是纯文本格式的控制台风格日志。
    
    Query参数：
        from_line: 从第几行开始读取（可选，默认0，用于增量获取）
    
    返回：
        {
            "success": true,
            "data": {
                "logs": [
                    "[19:46:14] INFO: 搜索完成: 找到 15 条相关事实",
                    "[19:46:14] INFO: 图谱搜索: graph_id=xxx, query=...",
                    ...
                ],
                "total_lines": 100,
                "from_line": 0,
                "has_more": false
            }
        }
    """
    try:
        from_line = request.args.get('from_line', 0, type=int)
        
        log_data = ReportManager.get_console_log(report_id, from_line=from_line)
        
        return jsonify({
            "success": True,
            "data": log_data
        })
        
    except Exception as e:
        logger.error(f"获取控制台日志失败: {str(e)}")
        status_code = 409 if "已失效" in str(e) or "请重新生成" in str(e) else 500
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), status_code


@report_bp.route('/<report_id>/console-log/stream', methods=['GET'])
def stream_console_log(report_id: str):
    """
    获取完整的控制台日志（一次性获取全部）
    
    返回：
        {
            "success": true,
            "data": {
                "logs": [...],
                "count": 100
            }
        }
    """
    try:
        logs = ReportManager.get_console_log_stream(report_id)
        
        return jsonify({
            "success": True,
            "data": {
                "logs": logs,
                "count": len(logs)
            }
        })
        
    except Exception as e:
        logger.error(f"获取控制台日志失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 工具调用接口（供调试使用）==============

@report_bp.route('/tools/search', methods=['POST'])
def search_graph_tool():
    """
    图谱搜索工具接口（供调试使用）
    
    请求（JSON）：
        {
            "graph_id": "goalfish_xxxx",
            "query": "搜索查询",
            "limit": 10
        }
    """
    try:
        data = request.get_json() or {}
        
        graph_id = data.get('graph_id')
        query = data.get('query')
        limit = data.get('limit', 10)
        
        if not graph_id or not query:
            return jsonify({
                "success": False,
                "error": t('api.requireGraphIdAndQuery')
            }), 400
        
        from ..services.graph_backend_factory import get_graph_tools
        
        tools = get_graph_tools()
        result = tools.search_graph(
            graph_id=graph_id,
            query=query,
            limit=limit
        )
        
        return jsonify({
            "success": True,
            "data": result.to_dict()
        })
        
    except Exception as e:
        logger.error(f"图谱搜索失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/tools/statistics', methods=['POST'])
def get_graph_statistics_tool():
    """
    图谱统计工具接口（供调试使用）
    
    请求（JSON）：
        {
            "graph_id": "goalfish_xxxx"
        }
    """
    try:
        data = request.get_json() or {}
        
        graph_id = data.get('graph_id')
        
        if not graph_id:
            return jsonify({
                "success": False,
                "error": t('api.requireGraphId')
            }), 400
        
        from ..services.graph_backend_factory import get_graph_tools
        
        tools = get_graph_tools()
        result = tools.get_graph_statistics(graph_id)
        
        return jsonify({
            "success": True,
            "data": result
        })
        
    except Exception as e:
        logger.error(f"获取图谱统计失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500

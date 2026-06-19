"""
图谱相关API路由
采用项目上下文机制，服务端持久化状态
"""

import os
import traceback
import threading
from flask import request, jsonify

from . import graph_bp
from ..config import Config
from ..services.ontology_generator import OntologyGenerator
from ..services.simulation_domains import normalize_simulation_domain
from ..services.graph_backend_factory import get_graph_builder
from ..services.graph_diagnostics import (
    creating_graph_message,
    format_graph_exception,
    graph_backend_label,
    graph_build_context,
    waiting_graph_process_message,
)
from ..services.text_processor import TextProcessor
from ..services.llm_audit import llm_audit_context
from ..services.project_workflow import ProjectWorkflowService
from ..services.step2_preview import build_step2_preview_best_effort
from ..services.task_workflow import GraphBindingStatus, TaskWorkflowService
from ..services.task_workflow_safe import try_workflow
from ..tasks.workflow_tasks import enqueue_workflow_event
from ..utils.file_parser import FileParser
from ..utils.logger import get_logger
from ..utils.locale import t, get_locale, set_locale
from ..models.task import TaskManager, TaskStatus
from ..models.project import ProjectManager, ProjectStatus

# 获取日志器
logger = get_logger('goalfish.api')


def allowed_file(filename: str) -> bool:
    """检查文件扩展名是否允许"""
    if not filename or '.' not in filename:
        return False
    ext = os.path.splitext(filename)[1].lower().lstrip('.')
    return ext in Config.ALLOWED_EXTENSIONS


# ============== 项目管理接口 ==============

@graph_bp.route('/project/<project_id>', methods=['GET'])
def get_project(project_id: str):
    """
    获取项目详情
    """
    project = ProjectManager.get_project(project_id)
    
    if not project:
        return jsonify({
            "success": False,
            "error": t('api.projectNotFound', id=project_id)
        }), 404

    return jsonify({
        "success": True,
        "data": project.to_dict()
    })


@graph_bp.route('/project/list', methods=['GET'])
def list_projects():
    """
    列出所有项目
    """
    limit = request.args.get('limit', 50, type=int)
    projects = ProjectManager.list_projects(limit=limit)
    
    return jsonify({
        "success": True,
        "data": [p.to_dict() for p in projects],
        "count": len(projects)
    })


@graph_bp.route('/project/<project_id>', methods=['DELETE'])
def delete_project(project_id: str):
    """
    删除项目
    """
    success = ProjectManager.delete_project(project_id)
    
    if not success:
        return jsonify({
            "success": False,
            "error": t('api.projectDeleteFailed', id=project_id)
        }), 404

    return jsonify({
        "success": True,
        "message": t('api.projectDeleted', id=project_id)
    })


@graph_bp.route('/project/<project_id>/reset', methods=['POST'])
def reset_project(project_id: str):
    """
    重置项目状态（用于重新构建图谱）
    """
    project = ProjectManager.get_project(project_id)
    
    if not project:
        return jsonify({
            "success": False,
            "error": t('api.projectNotFound', id=project_id)
        }), 404

    # 重置到本体已生成状态
    if project.ontology:
        project.status = ProjectStatus.ONTOLOGY_GENERATED
    else:
        project.status = ProjectStatus.CREATED
    
    project.graph_id = None
    project.graph_build_task_id = None
    project.error = None
    ProjectManager.save_project(project)
    
    return jsonify({
        "success": True,
        "message": t('api.projectReset', id=project_id),
        "data": project.to_dict()
    })


# ============== 接口1：上传文件并生成本体 ==============

@graph_bp.route('/ontology/generate', methods=['POST'])
def generate_ontology():
    """
    接口1：上传文件，分析生成本体定义

    这条接口是“用户上传资料后的第一步业务入口”。前端提交一个
    multipart/form-data 请求，后端在一次 HTTP 请求里完成以下事情：
    1. 读取并校验表单参数，例如模拟需求、项目名称、模拟领域。
    2. 创建 Project，并把后续流程需要的项目状态持久化到本地。
    3. 保存上传文件，解析文件文本，并把原文保存到项目目录。
    4. 调用 OntologyGenerator，让 LLM 根据文本生成本体结构。
    5. 保存本体结果，同时写入 workflow 事件，供前端进度条/历史任务查询。
    
    请求方式：multipart/form-data
    
    参数：
        files: 上传的文件（PDF/MD/TXT），可多个
        simulation_requirement: 模拟需求描述（必填）
        project_name: 项目名称（可选）
        additional_context: 额外说明（可选）
        
    返回：
        {
            "success": true,
            "data": {
                "project_id": "proj_xxxx",
                "ontology": {
                    "entity_types": [...],
                    "edge_types": [...],
                    "analysis_summary": "..."
                },
                "files": [...],
                "total_text_length": 12345
            }
        }
    """
    # 下面三个变量先赋值为 None，是为了让 except 异常处理块也能安全访问它们。
    # 如果代码在创建 workflow 任务前就报错，这些变量仍然存在，不会引发新的变量未定义错误。
    workflow_task_id = None
    workflow_attempt_id = None
    workflow_current_event_id = None
    try:
        logger.info("=== 开始生成本体定义 ===")
        
        # request.form 表示 multipart/form-data 里的普通文本字段。
        # get('字段名', 默认值) 的意思是：字段存在就取字段值，不存在就使用默认值。
        simulation_requirement = request.form.get('simulation_requirement', '')
        project_name = request.form.get('project_name', 'Unnamed Project')
        additional_context = request.form.get('additional_context', '')
        try:
            # 产品主路径固定为 football_match，字段保留是为了兼容现有 projects schema。
            # normalize_simulation_domain 会把空值转成默认领域，并拒绝不支持的值。
            # 这里必须在创建项目之前校验，避免无效请求留下脏项目数据。
            simulation_domain = normalize_simulation_domain(request.form.get('simulation_domain', ''))
        except ValueError as e:
            return jsonify({
                "success": False,
                "error": str(e)
            }), 400
        
        logger.debug(f"项目名称: {project_name}")
        logger.debug(f"模拟需求: {simulation_requirement[:100]}...")
        
        # 模拟需求是 LLM 设计本体的重要依据。例如“预测某场足球比赛比分”
        # 会让模型提取球队、球员、比赛、阵型等实体类型。
        if not simulation_requirement:
            return jsonify({
                "success": False,
                "error": t('api.requireSimulationRequirement')
            }), 400
        
        # request.files 保存 multipart/form-data 里的文件字段。
        # getlist('files') 用于一次上传多个文件；即使只有一个文件，也会返回列表。
        uploaded_files = request.files.getlist('files')
        if not uploaded_files or all(not f.filename for f in uploaded_files):
            return jsonify({
                "success": False,
                "error": t('api.requireFileUpload')
            }), 400
        
        # 创建项目对象后，后续所有中间产物都会挂在 project_id 下面。
        # 这样接口返回后，前端可以继续用 project_id 构建图谱、准备模拟、生成报告。
        project = ProjectManager.create_project(name=project_name)
        project.simulation_requirement = simulation_requirement
        project.simulation_domain = simulation_domain
        logger.info(f"创建项目: {project.project_id}")

        # workflow 是一套“任务进度和产物记录”机制。
        # try_workflow 会捕获 workflow 子系统自身的异常，避免进度记录失败影响主业务。
        # lambda service: ... 是一个延迟执行的小函数；try_workflow 内部拿到 service 后再调用它。
        workflow_snapshot = try_workflow(
            "ontology.create_task",
            lambda service: service.create_task(
                project_id=project.project_id,
                name=project.name,
                metadata={
                    "simulation_requirement": simulation_requirement,
                    "simulation_domain": simulation_domain,
                    "additional_context": additional_context,
                    "source": "api.graph.ontology.generate",
                },
            ),
        )
        if workflow_snapshot:
            workflow_task_id = workflow_snapshot["id"]
            workflow_attempt_id = workflow_snapshot["active_attempt"]["id"]
        
        # document_texts 是传给 LLM 的“纯文本列表”，一个文件对应一个字符串。
        # all_text 是保存到项目目录的完整拼接文本，后续构建图谱还会复用它。
        document_texts = []
        all_text = ""
        
        for file in uploaded_files:
            # allowed_file 只检查扩展名是否在允许范围内；不符合要求的文件会被跳过。
            if file and file.filename and allowed_file(file.filename):
                # 保存原始文件到项目目录，file_info 是普通字典，里面有 path、size、original_filename 等信息。
                file_info = ProjectManager.save_file_to_project(
                    project.project_id, 
                    file, 
                    file.filename
                )
                project.files.append({
                    "filename": file_info["original_filename"],
                    "size": file_info["size"]
                })

                try:
                    # FileParser 根据文件类型读取内容；TextProcessor 做基础清洗，减少噪声再交给 LLM。
                    text = FileParser.extract_text(file_info["path"])
                    text = TextProcessor.preprocess_text(text)
                    document_texts.append(text)
                    all_text += f"\n\n=== {file_info['original_filename']} ===\n{text}"
                finally:
                    if file_info.get("temporary") and file_info.get("path"):
                        try:
                            os.remove(file_info["path"])
                        except OSError as cleanup_error:
                            logger.warning("临时上传文件删除失败: %s", cleanup_error)
        
        # 如果所有文件都被跳过或解析失败，这个项目没有可用资料。
        # 这里删除刚创建的项目，避免前端看到一个无法继续处理的空项目。
        if not document_texts:
            ProjectManager.delete_project(project.project_id)
            return jsonify({
                "success": False,
                "error": t('api.noDocProcessed')
            }), 400
        
        # 保存提取文本的长度和正文文件。本体生成只用 document_texts，
        # 图谱构建阶段会通过 ProjectManager 再读取这里保存的文本。
        project.total_text_length = len(all_text)
        ProjectManager.save_extracted_text(project.project_id, all_text)
        ProjectManager.save_project(project)
        logger.info(f"文本提取完成，共 {len(all_text)} 字符")

        if workflow_task_id and workflow_attempt_id:
            # 上传文件和提取文本在这个接口中是同步完成的，所以事件创建后立即标记为成功。
            upload_event = try_workflow(
                "ontology.upload_files.succeed",
                lambda service: service.start_event(
                    workflow_task_id,
                    workflow_attempt_id,
                    "upload_files",
                    progress=100,
                    metadata={"file_count": len(project.files)},
                ),
            )
            if upload_event:
                workflow_current_event_id = upload_event["id"]
                try_workflow(
                    "ontology.upload_files.artifact",
                    lambda service: service.create_artifact(
                        task_id=workflow_task_id,
                        attempt_id=workflow_attempt_id,
                        event_id=upload_event["id"],
                        artifact_type="uploaded_files",
                        content_json=project.files,
                        metadata={"project_id": project.project_id},
                    ),
                )
                try_workflow(
                    "ontology.upload_files.finish",
                    lambda service: service.succeed_event(upload_event["id"], progress=100),
                )
                workflow_current_event_id = None

            extract_event = try_workflow(
                "ontology.extract_text.succeed",
                lambda service: service.start_event(
                    workflow_task_id,
                    workflow_attempt_id,
                    "extract_match_material",
                    progress=100,
                    metadata={"text_chars": len(all_text)},
                ),
            )
            if extract_event:
                workflow_current_event_id = extract_event["id"]
                try_workflow(
                    "ontology.extract_text.artifact",
                    lambda service: service.create_artifact(
                        task_id=workflow_task_id,
                        attempt_id=workflow_attempt_id,
                        event_id=extract_event["id"],
                        artifact_type="extracted_text",
                        storage_kind="postgres_text",
                        content_text=all_text,
                        size_bytes=len(all_text.encode("utf-8")),
                        metadata={"text_chars": len(all_text)},
                    ),
                )
                try_workflow(
                    "ontology.extract_text.finish",
                    lambda service: service.succeed_event(extract_event["id"], progress=100),
                )
                workflow_current_event_id = None
        
        # 生成本体是这个接口最核心的一步：把文档文本、模拟需求和领域类型交给 LLM。
        logger.info("调用 LLM 生成本体定义...")
        generator = OntologyGenerator()
        ontology_event = None
        if workflow_task_id and workflow_attempt_id:
            ontology_event = try_workflow(
                "ontology.generate_ontology.start",
                lambda service: service.start_event(
                    workflow_task_id,
                    workflow_attempt_id,
                    "generate_football_ontology",
                    progress=10,
                    metadata={"document_count": len(document_texts)},
                ),
            )
            if ontology_event:
                workflow_current_event_id = ontology_event["id"]

        # llm_audit_context 是一个上下文管理器。Python 的 with 会在进入代码块时登记上下文，
        # 在离开代码块时自动清理。这里用它把 LLM 调用和 workflow event 关联起来，方便审计日志定位。
        with llm_audit_context(
            task_id=workflow_task_id,
            attempt_id=workflow_attempt_id,
            event_id=ontology_event["id"] if ontology_event else None,
            operation="generate_football_ontology",
        ):
            ontology = generator.generate(
                document_texts=document_texts,
                simulation_requirement=simulation_requirement,
                additional_context=additional_context if additional_context else None,
                simulation_domain=simulation_domain
            )
        
        # generator.generate 返回的是完整结果；项目里只保存后续图谱构建真正需要的本体结构
        # 和用于展示/报告的 analysis_summary。
        entity_count = len(ontology.get("entity_types", []))
        edge_count = len(ontology.get("edge_types", []))
        logger.info(f"本体生成完成: {entity_count} 个实体类型, {edge_count} 个关系类型")
        
        project.ontology = {
            "entity_types": ontology.get("entity_types", []),
            "edge_types": ontology.get("edge_types", [])
        }
        project.analysis_summary = ontology.get("analysis_summary", "")
        project.status = ProjectStatus.ONTOLOGY_GENERATED
        ProjectManager.save_project(project)
        if workflow_task_id and workflow_attempt_id and ontology_event:
            # 把本体结果作为 workflow artifact 保存，历史任务页可以直接读取这份产物。
            try_workflow(
                "ontology.generate_ontology.artifact",
                lambda service: service.create_artifact(
                    task_id=workflow_task_id,
                    attempt_id=workflow_attempt_id,
                    event_id=ontology_event["id"],
                    artifact_type="ontology",
                    content_json={
                        "ontology": project.ontology,
                        "analysis_summary": project.analysis_summary,
                    },
                    metadata={
                        "entity_count": entity_count,
                        "edge_count": edge_count,
                    },
                ),
            )
            try_workflow(
                "ontology.generate_ontology.finish",
                lambda service: service.succeed_event(
                    ontology_event["id"],
                    progress=100,
                    metadata={"entity_count": entity_count, "edge_count": edge_count},
                ),
            )
            workflow_current_event_id = None
        logger.info(f"=== 本体生成完成 === 项目ID: {project.project_id}")
        
        # Flask 的 jsonify 会把 Python 字典转换成 JSON 响应。
        # 前端拿到 project_id 后，会进入下一步 /api/graph/build 构建知识图谱。
        return jsonify({
            "success": True,
            "data": {
                "project_id": project.project_id,
                "project_name": project.name,
                "ontology": project.ontology,
                "analysis_summary": project.analysis_summary,
                "files": project.files,
                "total_text_length": project.total_text_length,
                "workflow_task_id": workflow_task_id,
                "workflow_attempt_id": workflow_attempt_id,
                "simulation_domain": project.simulation_domain,
            }
        })
        
    except Exception as e:
        # 捕获所有未预期异常，记录完整 traceback，方便排查是文件解析、LLM、保存项目还是 workflow 出错。
        logger.exception(
            "本体生成失败: project_id=%s, workflow_task_id=%s, workflow_attempt_id=%s",
            getattr(project, "project_id", None) if "project" in locals() else None,
            workflow_task_id,
            workflow_attempt_id,
        )
        if workflow_current_event_id:
            # 如果异常发生时有正在执行的 workflow event，就把这个事件标记为失败。
            # 前端查询进度时就能看到准确失败步骤，而不是一直停留在“处理中”。
            try_workflow(
                "ontology.fail_current_event",
                lambda service: service.fail_event(
                    workflow_current_event_id,
                    error_message=str(e),
                    error_traceback=traceback.format_exc(),
                ),
            )
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 接口2：构建图谱 ==============

@graph_bp.route('/build', methods=['POST'])
def build_graph():
    """
    接口2：根据project_id构建图谱
    
    请求（JSON）：
        {
            "project_id": "proj_xxxx",  // 必填，来自接口1
            "graph_name": "图谱名称",    // 可选
            "chunk_size": 500,          // 可选，默认500
            "chunk_overlap": 50         // 可选，默认50
        }
        
    返回：
        {
            "success": true,
            "data": {
                "project_id": "proj_xxxx",
                "task_id": "task_xxxx",
                "message": "图谱构建任务已启动"
            }
        }
    """
    try:
        logger.info("=== 开始构建图谱 ===")
        
        # 检查配置
        errors = Config.validate()
        if errors:
            logger.error(f"配置错误: {errors}")
            return jsonify({
                "success": False,
                "error": t('api.configError', details="; ".join(errors))
            }), 500
        
        # 解析请求
        data = request.get_json() or {}
        project_id = data.get('project_id')
        logger.debug(f"请求参数: project_id={project_id}")
        
        if not project_id:
            return jsonify({
                "success": False,
                "error": t('api.requireProjectId')
            }), 400
        
        # 获取项目
        project = ProjectManager.get_project(project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": t('api.projectNotFound', id=project_id)
            }), 404

        # 检查项目状态
        force = data.get('force', False)  # 强制重新构建
        
        if project.status == ProjectStatus.CREATED:
            return jsonify({
                "success": False,
                "error": t('api.ontologyNotGenerated')
            }), 400
        
        if project.status == ProjectStatus.GRAPH_BUILDING and not force:
            return jsonify({
                "success": False,
                "error": t('api.graphBuilding'),
                "task_id": project.graph_build_task_id
            }), 400
        
        # 如果强制重建，重置状态
        if force and project.status in [ProjectStatus.GRAPH_BUILDING, ProjectStatus.FAILED, ProjectStatus.GRAPH_COMPLETED]:
            project.status = ProjectStatus.ONTOLOGY_GENERATED
            project.graph_id = None
            project.graph_build_task_id = None
            project.error = None
        
        # 获取配置
        graph_name = data.get('graph_name', project.name or 'GoalFish Graph')
        chunk_size = data.get('chunk_size', project.chunk_size or Config.DEFAULT_CHUNK_SIZE)
        chunk_overlap = data.get('chunk_overlap', project.chunk_overlap or Config.DEFAULT_CHUNK_OVERLAP)
        
        # 更新项目配置
        project.chunk_size = chunk_size
        project.chunk_overlap = chunk_overlap
        
        # 获取提取的文本
        text = ProjectManager.get_extracted_text(project_id)
        if not text:
            return jsonify({
                "success": False,
                "error": t('api.textNotFound')
            }), 400
        
        # 获取本体
        ontology = project.ontology
        if not ontology:
            return jsonify({
                "success": False,
                "error": t('api.ontologyNotFound')
            }), 400
        
        # 创建异步任务
        task_manager = TaskManager()
        task_id = task_manager.create_task(f"构建图谱: {graph_name}")
        logger.info(f"创建图谱构建任务: task_id={task_id}, project_id={project_id}")

        def ensure_graph_workflow(service):
            existing = service.get_task_by_project_id(project_id)
            if existing and (force or project.status == ProjectStatus.GRAPH_COMPLETED):
                return service.create_rerun_attempt(existing["id"], from_event_type="build_match_graph")
            if existing:
                return existing
            return service.create_task(
                project_id=project_id,
                name=project.name,
                metadata={"source": "api.graph.build", "legacy_graph_task_id": task_id},
            )

        workflow_snapshot = try_workflow("graph.ensure_workflow", ensure_graph_workflow)
        workflow_task_id = workflow_snapshot["id"] if workflow_snapshot else None
        workflow_attempt_id = (
            workflow_snapshot["active_attempt"]["id"]
            if workflow_snapshot and workflow_snapshot.get("active_attempt")
            else None
        )
        
        # 更新项目状态
        project.status = ProjectStatus.GRAPH_BUILDING
        project.graph_build_task_id = task_id
        ProjectManager.save_project(project)
        
        # Capture locale before spawning background thread
        current_locale = get_locale()
        build_payload = {
            "project_id": project_id,
            "legacy_task_id": task_id,
            "workflow_task_id": workflow_task_id,
            "workflow_attempt_id": workflow_attempt_id,
            "graph_name": graph_name,
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "locale": current_locale,
        }

        if Config.GRAPH_BUILD_EXECUTOR == "celery":
            workflow_build_event = None
            if workflow_task_id and workflow_attempt_id:
                workflow_build_event = try_workflow(
                    "graph.build_graph.get_for_celery_job",
                    lambda service: service.get_event(workflow_task_id, workflow_attempt_id, "build_match_graph"),
                )
            celery_job = enqueue_workflow_event(
                event_type="build_match_graph",
                payload=build_payload,
                task_id=workflow_task_id,
                attempt_id=workflow_attempt_id,
                event_id=workflow_build_event.get("id") if workflow_build_event else None,
            )
            task_manager.update_task(
                task_id,
                status=TaskStatus.PROCESSING,
                message="图谱构建已进入 Celery 队列，请查看任务事件时间线",
                progress=0,
                progress_detail={
                    "executor": "celery",
                    "celery_job_id": celery_job["id"],
                    "celery_task_id": celery_job["celery_task_id"],
                    "workflow_task_id": workflow_task_id,
                    "workflow_attempt_id": workflow_attempt_id,
                },
            )
            return jsonify({
                "success": True,
                "data": {
                    "project_id": project_id,
                    "task_id": task_id,
                    "workflow_task_id": workflow_task_id,
                    "workflow_attempt_id": workflow_attempt_id,
                    "executor": "celery",
                    "celery_job_id": celery_job["id"],
                    "celery_task_id": celery_job["celery_task_id"],
                    "message": t('api.graphBuildStarted', taskId=task_id),
                }
            })

        # 启动后台任务
        def build_task():
            set_locale(current_locale)
            build_logger = get_logger('goalfish.build')
            graph_id = None
            build_event_id = None
            graph_binding_id = None
            try:
                build_logger.info(f"[{task_id}] 开始构建图谱: backend={Config.GRAPH_BACKEND}, label={graph_backend_label()}")
                build_logger.info(f"[{task_id}] 构建上下文: {graph_build_context(project_id=project_id)}")
                task_manager.update_task(
                    task_id, 
                    status=TaskStatus.PROCESSING,
                    message=t('progress.initGraphService')
                )

                # 创建当前后端的图谱构建服务
                builder = get_graph_builder()

                # 分块
                task_manager.update_task(
                    task_id,
                    message=t('progress.textChunking'),
                    progress=5
                )
                chunk_event = None
                if workflow_task_id and workflow_attempt_id:
                    existing_chunk_event = try_workflow(
                        "graph.chunk_text.get",
                        lambda service: service.get_event(workflow_task_id, workflow_attempt_id, "extract_match_material"),
                    )
                    if existing_chunk_event and existing_chunk_event["status"] == "pending":
                        chunk_event = try_workflow(
                            "graph.chunk_text.start",
                            lambda service: service.start_event(
                                workflow_task_id,
                                workflow_attempt_id,
                                "extract_match_material",
                                progress=10,
                                metadata={"chunk_size": chunk_size, "chunk_overlap": chunk_overlap},
                            ),
                        )
                chunks = TextProcessor.split_text(
                    text, 
                    chunk_size=chunk_size, 
                    overlap=chunk_overlap
                )
                total_chunks = len(chunks)
                build_logger.info(
                    f"[{task_id}] 文本分块完成: project_id={project_id}, chunk_size={chunk_size}, "
                    f"chunk_overlap={chunk_overlap}, total_chunks={total_chunks}, text_chars={len(text)}"
                )
                if workflow_task_id and workflow_attempt_id and chunk_event:
                    try_workflow(
                        "graph.chunk_text.artifact",
                        lambda service: service.create_artifact(
                            task_id=workflow_task_id,
                            attempt_id=workflow_attempt_id,
                            event_id=chunk_event["id"],
                            artifact_type="chunks",
                            content_json={"chunks": chunks},
                            metadata={
                                "chunk_count": total_chunks,
                                "chunk_size": chunk_size,
                                "chunk_overlap": chunk_overlap,
                            },
                        ),
                    )
                    try_workflow(
                        "graph.chunk_text.finish",
                        lambda service: service.succeed_event(
                            chunk_event["id"],
                            progress=100,
                            metadata={"chunk_count": total_chunks},
                        ),
                    )

                # 创建图谱
                task_manager.update_task(
                    task_id,
                    message=creating_graph_message(),
                    progress=10
                )
                build_event = None
                if workflow_task_id and workflow_attempt_id:
                    existing_build_event = try_workflow(
                        "graph.build_graph.get",
                        lambda service: service.get_event(workflow_task_id, workflow_attempt_id, "build_match_graph"),
                    )
                    if existing_build_event and existing_build_event["status"] in {"pending", "failed"}:
                        build_event = try_workflow(
                            "graph.build_graph.start",
                            lambda service: service.start_event(
                                workflow_task_id,
                                workflow_attempt_id,
                                "build_match_graph",
                                progress=5,
                                metadata={"graph_backend": Config.GRAPH_BACKEND},
                            ),
                        )
                    elif existing_build_event:
                        build_event = existing_build_event
                    if build_event:
                        build_event_id = build_event["id"]
                graph_id = builder.create_graph(name=graph_name)
                build_logger.info(f"[{task_id}] 图谱标识已创建: graph_id={graph_id}, graph_name={graph_name}")
                project.graph_id = graph_id
                project.status = ProjectStatus.GRAPH_BUILDING
                ProjectManager.save_project(project)
                if workflow_task_id and workflow_attempt_id and build_event_id:
                    graph_binding = try_workflow(
                        "graph.binding.create",
                        lambda service: service.create_graph_binding(
                            task_id=workflow_task_id,
                            attempt_id=workflow_attempt_id,
                            project_id=project_id,
                            graph_backend=Config.GRAPH_BACKEND,
                            graph_id=graph_id,
                            group_id=graph_id,
                            neo4j_uri=Config.GRAPHITI_NEO4J_URI if Config.GRAPH_BACKEND == "graphiti" else None,
                            status=GraphBindingStatus.BUILDING,
                            metadata={"legacy_graph_task_id": task_id},
                        ),
                    )
                    graph_binding_id = graph_binding["id"] if graph_binding else None

                with llm_audit_context(
                    task_id=workflow_task_id,
                    attempt_id=workflow_attempt_id,
                    event_id=build_event_id,
                    operation="build_match_graph",
                ):
                    # 设置本体
                    task_manager.update_task(
                        task_id,
                        message=t('progress.settingOntology'),
                        progress=15
                    )
                    build_logger.info(
                        f"[{task_id}] 设置本体: entity_types={len(ontology.get('entity_types', []))}, "
                        f"edge_types={len(ontology.get('edge_types', []))}, graph_id={graph_id}"
                    )
                    builder.set_ontology(graph_id, ontology)
                
                    # 添加文本（progress_callback 签名是 (msg, progress_ratio)）
                    def add_progress_callback(msg, progress_ratio):
                        progress = 15 + int(progress_ratio * 40)  # 15% - 55%
                        build_logger.debug(
                            f"[{task_id}] 文本写入进度: progress={progress}, ratio={progress_ratio:.3f}, message={msg}"
                        )
                        task_manager.update_task(
                            task_id,
                            message=msg,
                            progress=progress
                        )
                        if build_event_id:
                            try_workflow(
                                "graph.build_graph.progress.add_text",
                                lambda service: service.transition_event(
                                    build_event_id,
                                    "running",
                                    progress=progress,
                                    metadata={"message": msg},
                                ),
                            )

                    task_manager.update_task(
                        task_id,
                        message=t('progress.addingChunks', count=total_chunks),
                        progress=15
                    )

                    episode_uuids = builder.add_text_batches(
                        graph_id,
                        chunks,
                        batch_size=3,
                        progress_callback=add_progress_callback
                    )
                    build_logger.info(f"[{task_id}] 文本写入完成: graph_id={graph_id}, episodes={len(episode_uuids)}")

                    # 等待当前图谱后端处理完成
                    task_manager.update_task(
                        task_id,
                        message=waiting_graph_process_message(),
                        progress=55
                    )

                    def wait_progress_callback(msg, progress_ratio):
                        progress = 55 + int(progress_ratio * 35)  # 55% - 90%
                        build_logger.debug(
                            f"[{task_id}] 后端处理进度: progress={progress}, ratio={progress_ratio:.3f}, message={msg}"
                        )
                        task_manager.update_task(
                            task_id,
                            message=msg,
                            progress=progress
                        )
                        if build_event_id:
                            try_workflow(
                                "graph.build_graph.progress.wait",
                                lambda service: service.transition_event(
                                    build_event_id,
                                    "running",
                                    progress=progress,
                                    metadata={"message": msg},
                                ),
                            )

                    builder._wait_for_episodes(episode_uuids, wait_progress_callback)

                # 获取图谱数据
                task_manager.update_task(
                    task_id,
                    message=t('progress.fetchingGraphData'),
                    progress=95
                )
                graph_data = builder.get_graph_data(graph_id)
                build_logger.info(f"[{task_id}] 图谱数据读取完成: graph_id={graph_id}")
                
                # 更新项目状态
                project.graph_id = graph_id
                project.status = ProjectStatus.GRAPH_COMPLETED
                ProjectManager.save_project(project)
                ProjectWorkflowService().register_graph(project_id, graph_id)
                build_step2_preview_best_effort(project_id, graph_id, logger=build_logger)
                
                node_count = graph_data.get("node_count", 0)
                edge_count = graph_data.get("edge_count", 0)
                build_logger.info(f"[{task_id}] 图谱构建完成: graph_id={graph_id}, 节点={node_count}, 边={edge_count}")
                if graph_binding_id:
                    try_workflow(
                        "graph.binding.ready",
                        lambda service: service.update_graph_binding(
                            graph_binding_id,
                            status=GraphBindingStatus.READY,
                            node_count=node_count,
                            edge_count=edge_count,
                        ),
                    )
                if build_event_id:
                    try_workflow(
                        "graph.build_graph.artifact",
                        lambda service: service.create_artifact(
                            task_id=workflow_task_id,
                            attempt_id=workflow_attempt_id,
                            event_id=build_event_id,
                            artifact_type="graph_binding",
                            storage_kind="neo4j",
                            content_json={
                                "graph_id": graph_id,
                                "node_count": node_count,
                                "edge_count": edge_count,
                            },
                            metadata={"graph_backend": Config.GRAPH_BACKEND},
                        ),
                    )
                    try_workflow(
                        "graph.build_graph.finish",
                        lambda service: service.succeed_event(
                            build_event_id,
                            progress=100,
                            metadata={
                                "graph_id": graph_id,
                                "node_count": node_count,
                                "edge_count": edge_count,
                                "chunk_count": total_chunks,
                            },
                        ),
                    )
                
                # 完成
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.COMPLETED,
                    message=t('progress.graphBuildComplete'),
                    progress=100,
                    result={
                        "project_id": project_id,
                        "graph_id": graph_id,
                        "node_count": node_count,
                        "edge_count": edge_count,
                        "chunk_count": total_chunks
                    }
                )
                
            except Exception as e:
                diagnostics = format_graph_exception(e)
                # 更新项目状态为失败
                build_logger.exception(f"[{task_id}] 图谱构建失败: {diagnostics.detail}")
                build_logger.error(
                    f"[{task_id}] 失败上下文: {graph_build_context(project_id=project_id, graph_id=graph_id)}"
                )
                
                project.status = ProjectStatus.FAILED
                project.graph_id = None
                project.error = diagnostics.detail
                ProjectManager.save_project(project)
                if graph_binding_id:
                    try_workflow(
                        "graph.binding.failed",
                        lambda service: service.update_graph_binding(
                            graph_binding_id,
                            status=GraphBindingStatus.FAILED,
                            metadata={"error": diagnostics.detail},
                        ),
                    )
                if build_event_id:
                    try_workflow(
                        "graph.build_graph.fail",
                        lambda service: service.fail_event(
                            build_event_id,
                            error_message=diagnostics.detail,
                            error_traceback=diagnostics.traceback_text,
                            metadata={"context": graph_build_context(project_id=project_id, graph_id=graph_id)},
                        ),
                    )
                
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.FAILED,
                    message=t('progress.buildFailed', error=diagnostics.summary),
                    error=diagnostics.detail,
                    progress_detail={
                        "summary": diagnostics.summary,
                        "detail": diagnostics.detail,
                        "traceback": diagnostics.traceback_text,
                        "context": graph_build_context(project_id=project_id, graph_id=graph_id),
                    }
                )
        
        # 启动后台线程
        thread = threading.Thread(target=build_task, daemon=True)
        thread.start()
        
        return jsonify({
            "success": True,
            "data": {
                "project_id": project_id,
                "task_id": task_id,
                "workflow_task_id": workflow_task_id,
                "workflow_attempt_id": workflow_attempt_id,
                "message": t('api.graphBuildStarted', taskId=task_id)
            }
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 任务查询接口 ==============


def _apply_workflow_status_to_legacy_task_data(
    task_data: dict,
    *,
    service: TaskWorkflowService | None = None,
) -> dict:
    """Backfill legacy in-memory graph task status from persisted workflow state."""
    data = dict(task_data)
    progress_detail = dict(data.get("progress_detail") or {})
    workflow_task_id = progress_detail.get("workflow_task_id")
    workflow_attempt_id = progress_detail.get("workflow_attempt_id")
    if not workflow_task_id or not workflow_attempt_id:
        return data

    service = service or TaskWorkflowService()
    try:
        build_event = service.get_event(workflow_task_id, workflow_attempt_id, "build_match_graph")
    except Exception as exc:
        logger.debug("旧图谱 task workflow 状态回填失败: %s", exc)
        return data

    if not build_event:
        return data

    latest_job = None
    try:
        jobs = service.list_celery_jobs(
            workflow_task_id,
            attempt_id=workflow_attempt_id,
            event_id=build_event.get("id"),
        )
        latest_job = jobs[-1] if jobs else None
    except Exception as exc:
        logger.debug("旧图谱 task celery 状态回填失败: %s", exc)

    event_status = build_event.get("status")
    event_metadata = build_event.get("metadata") or {}
    progress_detail.update(
        {
            "workflow_event_id": build_event.get("id"),
            "workflow_event_status": event_status,
            "workflow_event_progress": build_event.get("progress"),
        }
    )
    if latest_job:
        progress_detail.update(
            {
                "celery_job_id": latest_job.get("id"),
                "celery_task_id": latest_job.get("celery_task_id") or progress_detail.get("celery_task_id"),
                "celery_job_status": latest_job.get("status"),
                "celery_job_error": latest_job.get("last_error"),
            }
        )

    if event_status == "succeeded":
        data["status"] = TaskStatus.COMPLETED.value
        data["progress"] = 100
        data["message"] = t("progress.graphBuildComplete")
        result = {
            key: event_metadata.get(key)
            for key in ("project_id", "graph_id", "node_count", "edge_count", "chunk_count")
            if event_metadata.get(key) is not None
        }
        if result:
            data["result"] = result
    elif event_status == "failed" or (latest_job and latest_job.get("status") == "failed"):
        error_message = (
            build_event.get("error_message")
            or (latest_job or {}).get("last_error")
            or data.get("error")
            or "图谱构建失败"
        )
        data["status"] = TaskStatus.FAILED.value
        data["progress"] = build_event.get("progress") or data.get("progress") or 0
        data["message"] = t("progress.buildFailed", error=error_message)
        data["error"] = error_message
    elif event_status in {"running", "pending"} or (
        latest_job and latest_job.get("status") in {"queued", "running", "retrying"}
    ):
        data["status"] = TaskStatus.PROCESSING.value
        data["progress"] = build_event.get("progress") or data.get("progress") or 0
        data["message"] = event_metadata.get("message") or data.get("message") or "图谱构建中..."

    data["progress_detail"] = progress_detail
    return data


def _legacy_task_data_from_workflow(
    legacy_task_id: str,
    *,
    service: TaskWorkflowService | None = None,
) -> dict | None:
    service = service or TaskWorkflowService()
    try:
        job = service.find_celery_job_by_legacy_task_id(legacy_task_id)
    except Exception as exc:
        logger.debug("按 legacy task 查询 workflow job 失败: %s", exc)
        return None
    if not job:
        return None

    payload = ((job.get("metadata") or {}).get("payload") or {})
    workflow_task_id = job.get("task_id") or payload.get("workflow_task_id")
    workflow_attempt_id = job.get("attempt_id") or payload.get("workflow_attempt_id")
    if not workflow_task_id or not workflow_attempt_id:
        return None

    data = {
        "task_id": legacy_task_id,
        "task_type": "构建图谱",
        "status": TaskStatus.PROCESSING.value,
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at") or job.get("finished_at") or job.get("started_at") or job.get("created_at"),
        "progress": 0,
        "message": "图谱构建已进入 Celery 队列，请查看任务事件时间线",
        "progress_detail": {
            "executor": "celery",
            "celery_job_id": job.get("id"),
            "celery_task_id": job.get("celery_task_id"),
            "workflow_task_id": workflow_task_id,
            "workflow_attempt_id": workflow_attempt_id,
            "project_id": payload.get("project_id"),
        },
        "result": None,
        "error": None,
        "metadata": {"recovered_from_workflow": True},
    }
    return _apply_workflow_status_to_legacy_task_data(data, service=service)


@graph_bp.route('/task/<task_id>', methods=['GET'])
def get_task(task_id: str):
    """
    查询任务状态
    """
    task = TaskManager().get_task(task_id)
    
    if not task:
        recovered = _legacy_task_data_from_workflow(task_id)
        if recovered:
            return jsonify({
                "success": True,
                "data": recovered
            })
        return jsonify({
            "success": False,
            "error": t('api.taskNotFound', id=task_id)
        }), 404
    
    data = _apply_workflow_status_to_legacy_task_data(task.to_dict())
    return jsonify({
        "success": True,
        "data": data
    })


@graph_bp.route('/tasks', methods=['GET'])
def list_tasks():
    """
    列出所有任务
    """
    tasks = TaskManager().list_tasks()
    
    return jsonify({
        "success": True,
        "data": [t.to_dict() for t in tasks],
        "count": len(tasks)
    })


# ============== 图谱数据接口 ==============

@graph_bp.route('/data/<graph_id>', methods=['GET'])
def get_graph_data(graph_id: str):
    """
    获取图谱数据（节点和边）
    """
    try:
        errors = Config.validate()
        if errors:
            return jsonify({
                "success": False,
                "error": t('api.configError', details="; ".join(errors))
            }), 500
        
        builder = get_graph_builder()
        graph_data = builder.get_graph_data(graph_id)
        
        return jsonify({
            "success": True,
            "data": graph_data
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@graph_bp.route('/delete/<graph_id>', methods=['DELETE'])
def delete_graph(graph_id: str):
    """删除 Graphiti 图谱。"""
    try:
        errors = Config.validate()
        if errors:
            return jsonify({
                "success": False,
                "error": t('api.configError', details="; ".join(errors))
            }), 500
        
        builder = get_graph_builder()
        builder.delete_graph(graph_id)
        
        return jsonify({
            "success": True,
            "message": t('api.graphDeleted', id=graph_id)
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500

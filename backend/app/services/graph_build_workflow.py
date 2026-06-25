"""
Graph build workflow runner shared by background threads and Celery tasks.
"""

from __future__ import annotations

from typing import Any

from ..config import Config
from ..models.project import ProjectManager, ProjectStatus
from ..models.task import TaskManager, TaskStatus as LegacyTaskStatus
from ..utils.locale import set_locale, t
from ..utils.logger import get_logger
from .graph_backend_factory import get_graph_builder
from .graph_diagnostics import (
    creating_graph_message,
    format_graph_exception,
    graph_backend_label,
    graph_build_context,
    waiting_graph_process_message,
)
from .llm_audit import llm_audit_context
from .project_workflow import ProjectWorkflowService
from .step2_preview import build_step2_preview_best_effort
from .task_workflow import GraphBindingStatus
from .task_workflow_safe import try_workflow
from .text_processor import TextProcessor


class GraphBuildWorkflowRunner:
    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        project_id = payload["project_id"]
        legacy_task_id = payload["legacy_task_id"]
        workflow_task_id = payload.get("workflow_task_id")
        workflow_attempt_id = payload.get("workflow_attempt_id")
        graph_name = payload.get("graph_name") or "GoalFish Graph"
        chunk_size = int(payload.get("chunk_size") or Config.DEFAULT_CHUNK_SIZE)
        chunk_overlap = int(payload.get("chunk_overlap") or Config.DEFAULT_CHUNK_OVERLAP)
        locale = payload.get("locale")
        set_locale(locale or "en")

        build_logger = get_logger("goalfish.build")
        task_manager = TaskManager()
        graph_id = None
        build_event_id = None
        graph_binding_id = None
        project = None

        try:
            project = ProjectManager.get_project(project_id)
            if not project:
                raise KeyError(f"项目不存在: {project_id}")

            text = ProjectManager.get_extracted_text(project_id)
            if not text:
                raise ValueError("项目提取文本不存在")

            ontology = project.ontology
            if not ontology:
                raise ValueError("项目本体不存在")

            build_logger.info(
                f"[{legacy_task_id}] 开始构建图谱: backend={Config.GRAPH_BACKEND}, "
                f"label={graph_backend_label()}"
            )
            build_logger.info(f"[{legacy_task_id}] 构建上下文: {graph_build_context(project_id=project_id)}")
            task_manager.update_task(
                legacy_task_id,
                status=LegacyTaskStatus.PROCESSING,
                message=t("progress.initGraphService"),
            )

            builder = get_graph_builder()

            task_manager.update_task(
                legacy_task_id,
                message=t("progress.textChunking"),
                progress=5,
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

            chunks = TextProcessor.split_text(text, chunk_size=chunk_size, overlap=chunk_overlap)
            total_chunks = len(chunks)
            build_logger.info(
                f"[{legacy_task_id}] 文本分块完成: project_id={project_id}, chunk_size={chunk_size}, "
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

            task_manager.update_task(
                legacy_task_id,
                message=creating_graph_message(),
                progress=10,
            )
            build_event = None
            if workflow_task_id and workflow_attempt_id:
                existing_build_event = try_workflow(
                    "graph.build_graph.get",
                    lambda service: service.get_event(workflow_task_id, workflow_attempt_id, "build_match_graph"),
                )
                if existing_build_event and existing_build_event["status"] in {"pending", "failed"}:
                    retry_start_progress = max(int(existing_build_event.get("progress") or 0), 5)
                    build_event = try_workflow(
                        "graph.build_graph.start",
                        lambda service: service.start_event(
                            workflow_task_id,
                            workflow_attempt_id,
                            "build_match_graph",
                            progress=retry_start_progress,
                            metadata={"graph_backend": Config.GRAPH_BACKEND},
                        ),
                    )
                elif existing_build_event:
                    build_event = existing_build_event
                if build_event:
                    build_event_id = build_event["id"]

            existing_graph_binding = None
            if workflow_task_id and workflow_attempt_id:
                existing_graph_binding = try_workflow(
                    "graph.binding.get_active",
                    lambda service: service.get_active_graph_binding(workflow_task_id),
                )

            if existing_graph_binding and existing_graph_binding.get("graph_id"):
                graph_id = existing_graph_binding["graph_id"]
                graph_binding_id = existing_graph_binding.get("id")
                build_logger.info(
                    f"[{legacy_task_id}] 复用已有图谱标识: graph_id={graph_id}, "
                    f"binding_id={graph_binding_id}"
                )
                if graph_binding_id:
                    try_workflow(
                        "graph.binding.reuse_building",
                        lambda service: service.update_graph_binding(
                            graph_binding_id,
                            status=GraphBindingStatus.BUILDING,
                            metadata={"legacy_graph_task_id": legacy_task_id},
                        ),
                    )
            else:
                graph_id = builder.create_graph(name=graph_name)
                build_logger.info(f"[{legacy_task_id}] 图谱标识已创建: graph_id={graph_id}, graph_name={graph_name}")
            project.graph_id = graph_id
            project.status = ProjectStatus.GRAPH_BUILDING
            ProjectManager.save_project(project)

            if workflow_task_id and workflow_attempt_id and build_event_id and not graph_binding_id:
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
                        metadata={"legacy_graph_task_id": legacy_task_id},
                    ),
                )
                graph_binding_id = graph_binding["id"] if graph_binding else None

            with llm_audit_context(
                task_id=workflow_task_id,
                attempt_id=workflow_attempt_id,
                event_id=build_event_id,
                operation="build_match_graph",
            ):
                task_manager.update_task(
                    legacy_task_id,
                    message=t("progress.settingOntology"),
                    progress=15,
                )
                build_logger.info(
                    f"[{legacy_task_id}] 设置本体: entity_types={len(ontology.get('entity_types', []))}, "
                    f"edge_types={len(ontology.get('edge_types', []))}, graph_id={graph_id}"
                )
                builder.set_ontology(graph_id, ontology)

                def add_progress_callback(msg, progress_ratio):
                    progress = 15 + int(progress_ratio * 40)
                    build_logger.debug(
                        f"[{legacy_task_id}] 文本写入进度: progress={progress}, "
                        f"ratio={progress_ratio:.3f}, message={msg}"
                    )
                    task_manager.update_task(legacy_task_id, message=msg, progress=progress)
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
                    legacy_task_id,
                    message=t("progress.addingChunks", count=total_chunks),
                    progress=15,
                )
                episode_uuids = builder.add_text_batches(
                    graph_id,
                    chunks,
                    batch_size=3,
                    progress_callback=add_progress_callback,
                )
                build_logger.info(f"[{legacy_task_id}] 文本写入完成: graph_id={graph_id}, episodes={len(episode_uuids)}")

                task_manager.update_task(
                    legacy_task_id,
                    message=waiting_graph_process_message(),
                    progress=55,
                )

                def wait_progress_callback(msg, progress_ratio):
                    progress = 55 + int(progress_ratio * 35)
                    build_logger.debug(
                        f"[{legacy_task_id}] 后端处理进度: progress={progress}, "
                        f"ratio={progress_ratio:.3f}, message={msg}"
                    )
                    task_manager.update_task(legacy_task_id, message=msg, progress=progress)
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

            task_manager.update_task(
                legacy_task_id,
                message=t("progress.fetchingGraphData"),
                progress=95,
            )
            graph_data = builder.get_graph_data(graph_id)
            node_count = graph_data.get("node_count", 0)
            edge_count = graph_data.get("edge_count", 0)
            build_logger.info(f"[{legacy_task_id}] 图谱构建完成: graph_id={graph_id}, 节点={node_count}, 边={edge_count}")

            project.graph_id = graph_id
            project.status = ProjectStatus.GRAPH_COMPLETED
            ProjectManager.save_project(project)
            ProjectWorkflowService().register_graph(project_id, graph_id)
            build_step2_preview_best_effort(project_id, graph_id, logger=build_logger)

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

            result = {
                "project_id": project_id,
                "graph_id": graph_id,
                "node_count": node_count,
                "edge_count": edge_count,
                "chunk_count": total_chunks,
            }
            task_manager.update_task(
                legacy_task_id,
                status=LegacyTaskStatus.COMPLETED,
                message=t("progress.graphBuildComplete"),
                progress=100,
                result=result,
            )
            return result

        except Exception as exc:
            diagnostics = format_graph_exception(exc)
            build_logger.exception(f"[{legacy_task_id}] 图谱构建失败: {diagnostics.detail}")
            build_logger.error(
                f"[{legacy_task_id}] 失败上下文: {graph_build_context(project_id=project_id, graph_id=graph_id)}"
            )

            if project is not None:
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
                legacy_task_id,
                status=LegacyTaskStatus.FAILED,
                message=t("progress.buildFailed", error=diagnostics.summary),
                error=diagnostics.detail,
                progress_detail={
                    "summary": diagnostics.summary,
                    "detail": diagnostics.detail,
                    "traceback": diagnostics.traceback_text,
                    "context": graph_build_context(project_id=project_id, graph_id=graph_id),
                },
            )
            raise

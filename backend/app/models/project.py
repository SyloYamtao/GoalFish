"""
项目上下文管理
用于在服务端持久化项目状态，避免前端在接口间传递大量数据
"""

import uuid
import os
import tempfile
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from enum import Enum
from dataclasses import dataclass, field
from ..config import Config
from ..db.models import ProjectRecord, utc_now
from ..db.session import get_session, init_db
from ..services.simulation_domains import FOOTBALL_MATCH, normalize_simulation_domain


class ProjectStatus(str, Enum):
    """项目状态"""
    CREATED = "created"              # 刚创建，文件已上传
    ONTOLOGY_GENERATED = "ontology_generated"  # 本体已生成
    GRAPH_BUILDING = "graph_building"    # 图谱构建中
    GRAPH_COMPLETED = "graph_completed"  # 图谱构建完成
    PREDICTION_CONFIG_READY = "prediction_config_ready"  # Step2 配置完成
    PREDICTION_COMPLETED = "prediction_completed"  # Step3 预测完成
    REPORT_COMPLETED = "report_completed"  # Step4 报告完成
    FAILED = "failed"                # 失败


@dataclass
class Project:
    """项目数据模型"""
    project_id: str
    name: str
    status: ProjectStatus | str
    created_at: str
    updated_at: str
    
    # 文件信息
    files: List[Dict[str, str]] = field(default_factory=list)  # [{filename, path, size}]
    total_text_length: int = 0
    
    # 本体信息（接口1生成后填充）
    ontology: Optional[Dict[str, Any]] = None
    analysis_summary: Optional[str] = None
    
    # 图谱信息（接口2完成后填充）
    graph_id: Optional[str] = None
    graph_build_task_id: Optional[str] = None
    
    # 配置
    simulation_requirement: Optional[str] = None
    simulation_domain: str = FOOTBALL_MATCH
    chunk_size: int = 500
    chunk_overlap: int = 50
    
    # 错误信息
    error: Optional[str] = None

    # 扩展元数据
    project_metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "project_id": self.project_id,
            "name": self.name,
            "status": self.status.value if isinstance(self.status, ProjectStatus) else self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "files": self.files,
            "total_text_length": self.total_text_length,
            "ontology": self.ontology,
            "analysis_summary": self.analysis_summary,
            "graph_id": self.graph_id,
            "graph_build_task_id": self.graph_build_task_id,
            "simulation_requirement": self.simulation_requirement,
            "simulation_domain": normalize_simulation_domain(self.simulation_domain),
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "error": self.error,
            "project_metadata": self.project_metadata or {},
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Project':
        """从字典创建"""
        status = ProjectManager._coerce_status(data.get('status', 'created'))
        
        return cls(
            project_id=data['project_id'],
            name=data.get('name', 'Unnamed Project'),
            status=status,
            created_at=data.get('created_at', ''),
            updated_at=data.get('updated_at', ''),
            files=data.get('files', []),
            total_text_length=data.get('total_text_length', 0),
            ontology=data.get('ontology'),
            analysis_summary=data.get('analysis_summary'),
            graph_id=data.get('graph_id'),
            graph_build_task_id=data.get('graph_build_task_id'),
            simulation_requirement=data.get('simulation_requirement'),
            simulation_domain=normalize_simulation_domain(data.get('simulation_domain')),
            chunk_size=data.get('chunk_size', 500),
            chunk_overlap=data.get('chunk_overlap', 50),
            error=data.get('error'),
            project_metadata=data.get('project_metadata') or {},
        )


class ProjectManager:
    """项目管理器 - 负责项目在数据库中的持久化存储和检索"""

    @classmethod
    def _ensure_db(cls) -> None:
        if Config.TASK_WORKFLOW_AUTO_CREATE_TABLES:
            init_db()

    @staticmethod
    def _status_value(status: ProjectStatus | str) -> str:
        return status.value if isinstance(status, ProjectStatus) else str(status)

    @staticmethod
    def _coerce_status(status: ProjectStatus | str | None) -> ProjectStatus | str:
        if isinstance(status, ProjectStatus):
            return status
        value = str(status or ProjectStatus.CREATED.value)
        try:
            return ProjectStatus(value)
        except ValueError:
            return value

    @staticmethod
    def _as_iso(value: datetime | None) -> str:
        return value.isoformat() if value else ""

    @staticmethod
    def _parse_datetime(value: str | datetime | None) -> datetime:
        if isinstance(value, datetime):
            return value
        if not value:
            return utc_now()
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

    @classmethod
    def _record_to_project(cls, record: ProjectRecord) -> Project:
        return Project(
            project_id=record.project_id,
            name=record.name,
            status=cls._coerce_status(record.status),
            created_at=cls._as_iso(record.created_at),
            updated_at=cls._as_iso(record.updated_at),
            files=record.files or [],
            total_text_length=record.total_text_length or 0,
            ontology=record.ontology,
            analysis_summary=record.analysis_summary,
            graph_id=record.graph_id,
            graph_build_task_id=record.graph_build_task_id,
            simulation_requirement=record.simulation_requirement,
            simulation_domain=normalize_simulation_domain(record.simulation_domain),
            chunk_size=record.chunk_size or 500,
            chunk_overlap=record.chunk_overlap or 50,
            error=record.error,
            project_metadata=record.project_metadata or {},
        )

    @classmethod
    def _apply_project_to_record(
        cls,
        record: ProjectRecord,
        project: Project,
        *,
        touch_updated_at: bool,
    ) -> None:
        now = utc_now()
        record.name = project.name
        record.status = cls._status_value(project.status)
        record.files = list(project.files or [])
        record.total_text_length = int(project.total_text_length or 0)
        record.ontology = project.ontology
        record.analysis_summary = project.analysis_summary
        record.graph_id = project.graph_id
        record.graph_build_task_id = project.graph_build_task_id
        record.simulation_requirement = project.simulation_requirement
        record.simulation_domain = normalize_simulation_domain(project.simulation_domain)
        record.chunk_size = int(project.chunk_size or 500)
        record.chunk_overlap = int(project.chunk_overlap or 50)
        record.error = project.error
        record.project_metadata = dict(project.project_metadata or {})
        if not record.created_at:
            record.created_at = cls._parse_datetime(project.created_at)
        record.updated_at = now if touch_updated_at else cls._parse_datetime(project.updated_at)
        if touch_updated_at:
            project.updated_at = cls._as_iso(record.updated_at)

    @classmethod
    def create_project(cls, name: str = "Unnamed Project") -> Project:
        """
        创建新项目
        
        Args:
            name: 项目名称
            
        Returns:
            新创建的Project对象
        """
        cls._ensure_db()
        project_id = f"proj_{uuid.uuid4().hex[:12]}"
        now = utc_now()

        with get_session() as session:
            record = ProjectRecord(
                project_id=project_id,
                name=name,
                status=ProjectStatus.CREATED.value,
                created_at=now,
                updated_at=now,
                files=[],
                total_text_length=0,
                simulation_domain=FOOTBALL_MATCH,
                chunk_size=500,
                chunk_overlap=50,
                project_metadata={},
            )
            session.add(record)
            session.flush()
            return cls._record_to_project(record)
    
    @classmethod
    def save_project(cls, project: Project, *, touch_updated_at: bool = True) -> None:
        """保存项目元数据到数据库"""
        cls._ensure_db()
        with get_session() as session:
            record = session.get(ProjectRecord, project.project_id)
            if record is None:
                record = ProjectRecord(
                    project_id=project.project_id,
                    name=project.name,
                    status=cls._status_value(project.status),
                    created_at=cls._parse_datetime(project.created_at),
                    updated_at=cls._parse_datetime(project.updated_at),
                    files=[],
                    total_text_length=0,
                    simulation_domain=FOOTBALL_MATCH,
                    chunk_size=500,
                    chunk_overlap=50,
                    project_metadata={},
                )
                session.add(record)
            cls._apply_project_to_record(record, project, touch_updated_at=touch_updated_at)
    
    @classmethod
    def get_project(cls, project_id: str) -> Optional[Project]:
        """
        获取项目
        
        Args:
            project_id: 项目ID
            
        Returns:
            Project对象，如果不存在返回None
        """
        cls._ensure_db()
        with get_session() as session:
            record = session.get(ProjectRecord, project_id)
            return cls._record_to_project(record) if record else None
    
    @classmethod
    def list_projects(cls, limit: int = 50) -> List[Project]:
        """
        列出所有项目
        
        Args:
            limit: 返回数量限制
            
        Returns:
            项目列表，按创建时间倒序
        """
        cls._ensure_db()
        with get_session() as session:
            records = (
                session.query(ProjectRecord)
                .order_by(ProjectRecord.created_at.desc())
                .limit(limit)
                .all()
            )
            return [cls._record_to_project(record) for record in records]
    
    @classmethod
    def delete_project(cls, project_id: str) -> bool:
        """
        删除项目及其所有文件
        
        Args:
            project_id: 项目ID
            
        Returns:
            是否删除成功
        """
        cls._ensure_db()
        with get_session() as session:
            record = session.get(ProjectRecord, project_id)
            if record is None:
                return False
            session.delete(record)
            return True
    
    @classmethod
    def save_file_to_project(cls, project_id: str, file_storage, original_filename: str) -> Dict[str, Any]:
        """
        保存上传文件到临时文件，用于本次请求内解析文本。

        Project 的长期状态不再保存到项目目录；原始上传文件也不再按项目目录持久化。
        调用方使用返回的 path 完成 FileParser.extract_text 后，应删除这个临时文件。
        
        Args:
            project_id: 项目ID
            file_storage: Flask的FileStorage对象
            original_filename: 原始文件名
            
        Returns:
            文件信息字典 {filename, path, size}
        """
        ext = os.path.splitext(original_filename)[1].lower()
        temp_file = tempfile.NamedTemporaryFile(
            delete=False,
            suffix=ext,
            prefix=f"{project_id}_",
        )
        temp_file.close()
        file_path = temp_file.name
        file_storage.save(file_path)
        file_size = os.path.getsize(file_path)
        return {
            "original_filename": original_filename,
            "saved_filename": os.path.basename(file_path),
            "path": file_path,
            "size": file_size,
            "temporary": True,
        }
    
    @classmethod
    def save_extracted_text(cls, project_id: str, text: str, *, touch_updated_at: bool = True) -> None:
        """保存提取的文本到数据库"""
        cls._ensure_db()
        with get_session() as session:
            record = session.get(ProjectRecord, project_id)
            if record is None:
                raise KeyError(f"项目不存在: {project_id}")
            record.extracted_text = text
            record.total_text_length = len(text)
            if touch_updated_at:
                record.updated_at = utc_now()
    
    @classmethod
    def get_extracted_text(cls, project_id: str) -> Optional[str]:
        """从数据库获取提取的文本"""
        cls._ensure_db()
        with get_session() as session:
            record = session.get(ProjectRecord, project_id)
            return record.extracted_text if record else None
    
    @classmethod
    def get_project_files(cls, project_id: str) -> List[str]:
        """获取项目文件路径。

        新流程不再长期保存原始上传文件，因此通常返回空列表。
        这个方法保留是为了兼容旧调用方。
        """
        project = cls.get_project(project_id)
        if not project:
            return []
        return [
            file_info["path"]
            for file_info in project.files
            if isinstance(file_info, dict) and file_info.get("path")
        ]

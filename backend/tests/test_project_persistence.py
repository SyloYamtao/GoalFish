import os

from app.models.project import ProjectManager, ProjectStatus


def test_project_manager_persists_project_to_database(postgres_db):
    project = ProjectManager.create_project("DB Project")
    project.simulation_requirement = "测试需求"
    project.ontology = {"entity_types": [], "edge_types": []}
    project.analysis_summary = "摘要"
    project.status = ProjectStatus.ONTOLOGY_GENERATED
    project.project_metadata = {"step2_preview": {"status": "preview_ready"}}
    project.files.append({"filename": "report.md", "size": 12})
    project.total_text_length = 4
    ProjectManager.save_project(project)
    ProjectManager.save_extracted_text(project.project_id, "正文内容")

    loaded = ProjectManager.get_project(project.project_id)

    assert loaded is not None
    assert loaded.project_id == project.project_id
    assert loaded.status == ProjectStatus.ONTOLOGY_GENERATED
    assert loaded.files == [{"filename": "report.md", "size": 12}]
    assert loaded.ontology == {"entity_types": [], "edge_types": []}
    assert loaded.analysis_summary == "摘要"
    assert loaded.simulation_requirement == "测试需求"
    assert loaded.project_metadata == {"step2_preview": {"status": "preview_ready"}}
    assert loaded.to_dict()["project_metadata"]["step2_preview"]["status"] == "preview_ready"
    assert ProjectManager.get_extracted_text(project.project_id) == "正文内容"
    assert ProjectManager.list_projects(limit=10)[0].project_id == project.project_id


def test_project_manager_loads_workflow_statuses_after_restart(postgres_db):
    project = ProjectManager.create_project("Workflow Status Project")
    project.status = ProjectStatus.PREDICTION_COMPLETED
    ProjectManager.save_project(project)

    loaded = ProjectManager.get_project(project.project_id)

    assert loaded is not None
    assert loaded.status == ProjectStatus.PREDICTION_COMPLETED
    assert loaded.to_dict()["status"] == "prediction_completed"


def test_project_manager_tolerates_future_status_strings(postgres_db):
    project = ProjectManager.create_project("Future Status Project")
    project.status = "future_workflow_status"
    ProjectManager.save_project(project)

    loaded = ProjectManager.get_project(project.project_id)

    assert loaded is not None
    assert loaded.status == "future_workflow_status"
    assert loaded.to_dict()["status"] == "future_workflow_status"


def test_project_upload_file_uses_temporary_file(postgres_db):

    class FakeUpload:
        def save(self, path):
            with open(path, "wb") as f:
                f.write(b"hello")

    project = ProjectManager.create_project("Temp Upload")

    file_info = ProjectManager.save_file_to_project(project.project_id, FakeUpload(), "hello.txt")

    try:
        assert file_info["temporary"] is True
        assert os.path.exists(file_info["path"])
        assert "uploads/projects" not in file_info["path"]
        assert ProjectManager.get_project_files(project.project_id) == []
    finally:
        if os.path.exists(file_info["path"]):
            os.remove(file_info["path"])

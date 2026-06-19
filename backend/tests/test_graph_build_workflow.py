from types import SimpleNamespace

from app.models.project import Project, ProjectStatus
from app.services import graph_build_workflow as workflow_module
from app.services.graph_build_workflow import GraphBuildWorkflowRunner


def test_graph_build_retry_reuses_existing_graph_binding(monkeypatch):
    project = Project(
        project_id="proj_retry",
        name="Retry Graph",
        status=ProjectStatus.FAILED,
        created_at="2026-06-08T00:00:00",
        updated_at="2026-06-08T00:00:00",
        ontology={"entity_types": [], "edge_types": []},
    )
    saved_projects = []
    binding_updates = []
    start_event_calls = []

    class FakeTaskManager:
        def update_task(self, *args, **kwargs):
            return None

    class FakeBuilder:
        def create_graph(self, name):
            raise AssertionError("retry should reuse the existing graph binding")

        def set_ontology(self, graph_id, ontology):
            assert graph_id == "goalfish_existing"

        def add_text_batches(self, graph_id, chunks, batch_size=3, progress_callback=None):
            assert graph_id == "goalfish_existing"
            if progress_callback:
                progress_callback("chunk done", 1.0)
            return ["episode-1"]

        def _wait_for_episodes(self, episode_uuids, progress_callback):
            progress_callback("ready", 1.0)

        def get_graph_data(self, graph_id):
            assert graph_id == "goalfish_existing"
            return {"node_count": 3, "edge_count": 2}

    class FakeWorkflowService:
        def get_event(self, task_id, attempt_id, event_type):
            if event_type == "extract_match_material":
                return {"id": "chunk-event", "status": "succeeded"}
            if event_type == "build_match_graph":
                return {"id": "build-event", "status": "failed", "progress": 27}
            raise AssertionError(event_type)

        def start_event(self, task_id, attempt_id, event_type, **kwargs):
            start_event_calls.append((event_type, kwargs))
            return {"id": "build-event", "status": "running", "progress": kwargs.get("progress", 0)}

        def get_active_graph_binding(self, task_id):
            assert task_id == "workflow-task"
            return {
                "id": "binding-1",
                "task_id": "workflow-task",
                "attempt_id": "attempt-1",
                "project_id": "proj_retry",
                "graph_backend": "graphiti",
                "graph_id": "goalfish_existing",
                "group_id": "goalfish_existing",
                "status": "failed",
            }

        def create_graph_binding(self, **kwargs):
            raise AssertionError("retry should not create another graph binding")

        def update_graph_binding(self, binding_id, **kwargs):
            binding_updates.append((binding_id, kwargs))
            return {"id": binding_id, **kwargs}

        def transition_event(self, event_id, status, **kwargs):
            return {"id": event_id, "status": status, "progress": kwargs.get("progress")}

        def create_artifact(self, **kwargs):
            return {"id": "artifact-1"}

        def succeed_event(self, event_id, **kwargs):
            return {"id": event_id, "status": "succeeded", "progress": kwargs.get("progress", 100)}

    class FakeProjectWorkflowService:
        def register_graph(self, project_id, graph_id):
            return {"project_id": project_id, "graph_id": graph_id}

    def fake_try_workflow(operation, callback):
        return callback(FakeWorkflowService())

    def fake_save_project(project_to_save):
        saved_projects.append(
            SimpleNamespace(
                status=project_to_save.status,
                graph_id=project_to_save.graph_id,
                error=project_to_save.error,
            )
        )

    monkeypatch.setattr(workflow_module.ProjectManager, "get_project", lambda project_id: project)
    monkeypatch.setattr(workflow_module.ProjectManager, "get_extracted_text", lambda project_id: "hello world")
    monkeypatch.setattr(workflow_module.ProjectManager, "save_project", fake_save_project)
    monkeypatch.setattr(workflow_module, "TaskManager", lambda: FakeTaskManager())
    monkeypatch.setattr(workflow_module, "get_graph_builder", lambda: FakeBuilder())
    monkeypatch.setattr(workflow_module.TextProcessor, "split_text", lambda text, chunk_size, overlap: ["chunk"])
    monkeypatch.setattr(workflow_module, "try_workflow", fake_try_workflow)
    monkeypatch.setattr(workflow_module, "ProjectWorkflowService", FakeProjectWorkflowService)
    monkeypatch.setattr(workflow_module.Config, "GRAPH_BACKEND", "graphiti")

    result = GraphBuildWorkflowRunner().run(
        {
            "project_id": "proj_retry",
            "legacy_task_id": "legacy-task",
            "workflow_task_id": "workflow-task",
            "workflow_attempt_id": "attempt-1",
            "graph_name": "Retry Graph",
            "chunk_size": 500,
            "chunk_overlap": 50,
        }
    )

    assert result["graph_id"] == "goalfish_existing"
    assert any(saved.graph_id == "goalfish_existing" for saved in saved_projects)
    assert start_event_calls[0][0] == "build_match_graph"
    assert start_event_calls[0][1]["progress"] == 27
    assert binding_updates[0][0] == "binding-1"
    assert binding_updates[0][1]["status"] == "building"
    assert binding_updates[-1][1]["status"] == "ready"

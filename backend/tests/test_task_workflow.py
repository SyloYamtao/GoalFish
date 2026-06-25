import pytest
from flask import Flask

from app.api import tasks_bp
from app.services.llm_audit import get_current_llm_context, llm_audit_context
from app.services.task_workflow import (
    EventStatus,
    GraphBindingStatus,
    TaskWorkflowService,
    WorkflowStateError,
)


@pytest.fixture()
def workflow_service(postgres_db):
    return TaskWorkflowService()


def test_create_task_initializes_default_event_timeline(workflow_service):
    snapshot = workflow_service.create_task(project_id="proj_1", name="Prediction")

    assert snapshot["project_id"] == "proj_1"
    assert snapshot["status"] == "created"
    assert snapshot["active_attempt"]["attempt_no"] == 1

    events = workflow_service.list_events(snapshot["id"], snapshot["active_attempt"]["id"])
    assert [event["event_type"] for event in events][:5] == [
        "upload_files",
        "extract_match_material",
        "generate_football_ontology",
        "build_match_graph",
        "extract_team_context",
    ]
    assert all(event["status"] == "pending" for event in events)


def test_event_state_machine_rejects_illegal_transition(workflow_service):
    snapshot = workflow_service.create_task(project_id="proj_2", name="Prediction")
    attempt_id = snapshot["active_attempt"]["id"]

    event = workflow_service.start_event(
        task_id=snapshot["id"],
        attempt_id=attempt_id,
        event_type="generate_football_ontology",
        progress=10,
    )
    assert event["status"] == "running"

    event = workflow_service.succeed_event(event["id"], progress=100)
    assert event["status"] == "succeeded"

    with pytest.raises(WorkflowStateError):
        workflow_service.transition_event(event["id"], EventStatus.RUNNING)


def test_rerun_attempt_reuses_prior_events_before_start_event(workflow_service):
    snapshot = workflow_service.create_task(project_id="proj_3", name="Prediction")
    task_id = snapshot["id"]
    attempt_id = snapshot["active_attempt"]["id"]

    for event_type in ["upload_files", "extract_match_material", "generate_football_ontology", "build_match_graph"]:
        event = workflow_service.start_event(task_id, attempt_id, event_type)
        workflow_service.succeed_event(event["id"], progress=100)

    rerun = workflow_service.create_rerun_attempt(task_id, from_event_type="extract_team_context")
    rerun_events = workflow_service.list_events(task_id, rerun["active_attempt"]["id"])

    reused = [event for event in rerun_events if event["sequence"] < 50]
    assert all(event["status"] == "reused" for event in reused)
    assert all(event["reused_from_event_id"] for event in reused)

    extract_team_event = next(event for event in rerun_events if event["event_type"] == "extract_team_context")
    assert extract_team_event["status"] == "pending"
    assert rerun["active_attempt"]["attempt_no"] == 2
    assert rerun["active_attempt"]["source_attempt_id"] == attempt_id


def test_graph_binding_belongs_to_attempt(workflow_service):
    snapshot = workflow_service.create_task(project_id="proj_4", name="Prediction")
    task_id = snapshot["id"]
    attempt_id = snapshot["active_attempt"]["id"]

    binding = workflow_service.create_graph_binding(
        task_id=task_id,
        attempt_id=attempt_id,
        project_id="proj_4",
        graph_backend="graphiti",
        graph_id="goalfish_test",
        group_id="goalfish_test",
    )
    assert binding["status"] == "creating"
    assert binding["attempt_id"] == attempt_id

    updated = workflow_service.update_graph_binding(
        binding["id"],
        status=GraphBindingStatus.READY,
        node_count=12,
        edge_count=34,
    )
    assert updated["status"] == "ready"
    assert updated["node_count"] == 12
    assert updated["edge_count"] == 34


def test_llm_interaction_records_current_context(workflow_service):
    snapshot = workflow_service.create_task(project_id="proj_5", name="Prediction")
    task_id = snapshot["id"]
    attempt_id = snapshot["active_attempt"]["id"]
    event = workflow_service.start_event(task_id, attempt_id, "generate_football_ontology")

    with llm_audit_context(task_id=task_id, attempt_id=attempt_id, event_id=event["id"], operation="ontology"):
        assert get_current_llm_context().operation == "ontology"
        record = workflow_service.record_llm_interaction(
            request_id="req_1",
            provider="openai-compatible",
            base_url="https://api.example.com/v1",
            model="test-model",
            operation=get_current_llm_context().operation,
            messages=[{"role": "user", "content": "完整 prompt"}],
            request_params={"temperature": 0},
            response={"choices": [{"message": {"content": "{}"}}]},
            response_text="{}",
            status="succeeded",
            prompt_tokens=3,
            completion_tokens=4,
            total_tokens=7,
            latency_ms=42,
        )

    interactions = workflow_service.list_llm_interactions(task_id, attempt_id=attempt_id)

    assert record["task_id"] == task_id
    assert interactions[0]["request_id"] == "req_1"
    assert interactions[0]["messages"][0]["content"] == "完整 prompt"
    assert interactions[0]["total_tokens"] == 7


def test_celery_job_lifecycle_records_status(workflow_service):
    snapshot = workflow_service.create_task(project_id="proj_6", name="Prediction")
    task_id = snapshot["id"]
    attempt_id = snapshot["active_attempt"]["id"]
    event = workflow_service.get_event(task_id, attempt_id, "build_match_graph")

    queued = workflow_service.create_celery_job(
        task_id=task_id,
        attempt_id=attempt_id,
        event_id=event["id"],
        celery_task_id="celery-task-1",
        queue_name="goalfish",
        metadata={"event_type": "build_match_graph"},
    )
    assert queued["status"] == "queued"
    assert queued["celery_task_id"] == "celery-task-1"

    running = workflow_service.start_celery_job("celery-task-1")
    assert running["status"] == "running"
    assert running["started_at"] is not None

    finished = workflow_service.finish_celery_job("celery-task-1", status="succeeded")
    assert finished["status"] == "succeeded"
    assert finished["finished_at"] is not None

    jobs = workflow_service.list_celery_jobs(task_id, attempt_id=attempt_id)
    assert len(jobs) == 1
    assert jobs[0]["event_id"] == event["id"]


def test_task_snapshot_exposes_resume_and_rerun_points(workflow_service):
    snapshot = workflow_service.create_task(project_id="proj_7", name="Prediction")
    task_id = snapshot["id"]
    attempt_id = snapshot["active_attempt"]["id"]

    upload_event = workflow_service.start_event(task_id, attempt_id, "upload_files")
    workflow_service.succeed_event(upload_event["id"], progress=100)
    graph_event = workflow_service.start_event(task_id, attempt_id, "build_match_graph", progress=42)

    workflow_service.create_artifact(
        task_id=task_id,
        attempt_id=attempt_id,
        event_id=graph_event["id"],
        artifact_type="graph_binding",
        content_json={"graph_id": "goalfish_snapshot"},
    )

    current = workflow_service.get_task_snapshot(task_id)

    assert current["current_event"]["event_type"] == "build_match_graph"
    assert current["current_event"]["status"] == "running"
    assert current["resume_from_event_type"] == "build_match_graph"
    assert current["can_resume"] is True
    assert current["last_successful_event"]["event_type"] == "upload_files"
    assert current["artifacts"][0]["has_content_json"] is True
    assert any(point["event_type"] == "generate_scenario_matrix" for point in current["rerun_points"])


def test_resume_api_marks_running_event_interrupted_before_requeue(workflow_service, monkeypatch):
    snapshot = workflow_service.create_task(project_id="proj_resume", name="Prediction")
    task_id = snapshot["id"]
    attempt_id = snapshot["active_attempt"]["id"]
    running_event = workflow_service.start_event(task_id, attempt_id, "build_match_graph", progress=40)
    captured = {}

    def fake_enqueue_workflow_event(*, event_type, payload, task_id, attempt_id, event_id=None):
        captured.update(
            {
                "event_type": event_type,
                "payload": payload,
                "task_id": task_id,
                "attempt_id": attempt_id,
                "event_id": event_id,
            }
        )
        return {"celery_task_id": "celery-resume"}

    monkeypatch.setattr("app.api.tasks.enqueue_workflow_event", fake_enqueue_workflow_event)
    app = Flask(__name__)
    app.register_blueprint(tasks_bp, url_prefix="/api/tasks")

    response = app.test_client().post(
        f"/api/tasks/{task_id}/resume",
        json={"payload": {"project_id": "proj_resume"}},
        headers={"Accept-Language": "zh"},
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    event = workflow_service.get_event(task_id, attempt_id, "build_match_graph")
    assert event["id"] == running_event["id"]
    assert event["status"] == "failed"
    assert event["error_code"] == "interrupted"
    assert data["event"]["status"] == "failed"
    assert captured["event_type"] == "build_match_graph"
    assert captured["event_id"] == running_event["id"]
    assert captured["payload"]["workflow_task_id"] == task_id
    assert captured["payload"]["workflow_attempt_id"] == attempt_id
    assert captured["payload"]["locale"] == "zh"

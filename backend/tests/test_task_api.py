import pytest
from flask import Flask

from app.api import tasks_bp


@pytest.fixture()
def client(postgres_db):
    app = Flask(__name__)
    app.register_blueprint(tasks_bp, url_prefix="/api/tasks")
    return app.test_client()


def test_task_api_create_list_events_and_rerun(client):
    create_response = client.post(
        "/api/tasks",
        json={"project_id": "proj_api", "name": "API Task"},
    )
    assert create_response.status_code == 200
    task = create_response.get_json()["data"]

    events_response = client.get(f"/api/tasks/{task['id']}/attempts/{task['active_attempt']['id']}/events")
    assert events_response.status_code == 200
    events = events_response.get_json()["data"]
    assert events[0]["event_type"] == "upload_files"

    rerun_response = client.post(
        f"/api/tasks/{task['id']}/rerun",
        json={"from_event_type": "build_match_graph"},
    )
    assert rerun_response.status_code == 200
    rerun_task = rerun_response.get_json()["data"]
    assert rerun_task["active_attempt"]["attempt_no"] == 2


def test_task_api_lists_celery_jobs(client):
    create_response = client.post(
        "/api/tasks",
        json={"project_id": "proj_jobs", "name": "API Task"},
    )
    task = create_response.get_json()["data"]
    attempt_id = task["active_attempt"]["id"]

    from app.services.task_workflow import TaskWorkflowService

    event = TaskWorkflowService().get_event(task["id"], attempt_id, "build_match_graph")
    TaskWorkflowService().create_celery_job(
        task_id=task["id"],
        attempt_id=attempt_id,
        event_id=event["id"],
        celery_task_id="celery-api-task",
        queue_name="goalfish",
    )

    response = client.get(f"/api/tasks/{task['id']}/celery-jobs?attempt_id={attempt_id}")
    assert response.status_code == 200
    jobs = response.get_json()["data"]
    assert jobs[0]["celery_task_id"] == "celery-api-task"

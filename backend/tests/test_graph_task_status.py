from app.api.graph import (
    _apply_workflow_status_to_legacy_task_data,
    _legacy_task_data_from_workflow,
)


class FakeWorkflowService:
    def __init__(self, event, jobs=None):
        self.event = event
        self.jobs = jobs or []

    def get_event(self, task_id, attempt_id, event_type):
        assert task_id == "workflow-task"
        assert attempt_id == "attempt"
        assert event_type == "build_match_graph"
        return self.event

    def list_celery_jobs(self, task_id, *, attempt_id=None, event_id=None):
        assert task_id == "workflow-task"
        assert attempt_id == "attempt"
        assert event_id == self.event["id"]
        return self.jobs

    def find_celery_job_by_legacy_task_id(self, legacy_task_id):
        assert legacy_task_id == "legacy-task"
        return {
            "id": "job-record",
            "task_id": "workflow-task",
            "attempt_id": "attempt",
            "event_id": self.event["id"],
            "celery_task_id": "celery-task",
            "status": self.jobs[-1]["status"] if self.jobs else "queued",
            "last_error": self.jobs[-1].get("last_error") if self.jobs else None,
            "created_at": "2026-06-04T11:33:15+00:00",
            "updated_at": "2026-06-04T11:36:15+00:00",
            "metadata": {
                "payload": {
                    "project_id": "project",
                    "legacy_task_id": legacy_task_id,
                    "workflow_task_id": "workflow-task",
                    "workflow_attempt_id": "attempt",
                }
            },
        }


def test_legacy_graph_task_status_uses_failed_workflow_event():
    legacy_data = {
        "task_id": "legacy-task",
        "status": "processing",
        "progress": 0,
        "message": "图谱构建已进入 Celery 队列",
        "error": None,
        "progress_detail": {
            "executor": "celery",
            "workflow_task_id": "workflow-task",
            "workflow_attempt_id": "attempt",
        },
    }
    service = FakeWorkflowService(
        {
            "id": "build-event",
            "status": "failed",
            "progress": 5,
            "error_message": "Rate limit exceeded. Please try again later.",
            "metadata": {},
        },
        jobs=[
            {
                "status": "failed",
                "last_error": "Rate limit exceeded. Please try again later.",
            }
        ],
    )

    result = _apply_workflow_status_to_legacy_task_data(legacy_data, service=service)

    assert result["status"] == "failed"
    assert result["progress"] == 5
    assert result["error"] == "Rate limit exceeded. Please try again later."
    assert result["progress_detail"]["workflow_event_status"] == "failed"
    assert result["progress_detail"]["celery_job_status"] == "failed"


def test_legacy_graph_task_status_uses_succeeded_workflow_event():
    legacy_data = {
        "task_id": "legacy-task",
        "status": "processing",
        "progress": 30,
        "message": "图谱构建中",
        "error": None,
        "progress_detail": {
            "executor": "celery",
            "workflow_task_id": "workflow-task",
            "workflow_attempt_id": "attempt",
        },
    }
    service = FakeWorkflowService(
        {
            "id": "build-event",
            "status": "succeeded",
            "progress": 100,
            "error_message": None,
            "metadata": {
                "graph_id": "graph-1",
                "node_count": 10,
                "edge_count": 7,
            },
        },
        jobs=[{"status": "succeeded", "last_error": None}],
    )

    result = _apply_workflow_status_to_legacy_task_data(legacy_data, service=service)

    assert result["status"] == "completed"
    assert result["progress"] == 100
    assert result["result"] == {
        "graph_id": "graph-1",
        "node_count": 10,
        "edge_count": 7,
    }


def test_legacy_graph_task_can_be_recovered_from_workflow_job():
    service = FakeWorkflowService(
        {
            "id": "build-event",
            "status": "failed",
            "progress": 5,
            "error_message": "Rate limit exceeded. Please try again later.",
            "metadata": {},
        },
        jobs=[
            {
                "status": "failed",
                "last_error": "Rate limit exceeded. Please try again later.",
            }
        ],
    )

    result = _legacy_task_data_from_workflow("legacy-task", service=service)

    assert result["task_id"] == "legacy-task"
    assert result["status"] == "failed"
    assert result["progress_detail"]["workflow_task_id"] == "workflow-task"
    assert result["progress_detail"]["celery_task_id"] == "celery-task"

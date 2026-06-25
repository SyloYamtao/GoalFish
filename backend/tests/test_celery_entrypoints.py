from app.tasks import workflow_tasks
import pytest


def test_workflow_task_dispatches_build_match_graph(monkeypatch):
    captured = {}

    class FakeService:
        def start_celery_job(self, celery_task_id, metadata=None):
            captured["started"] = {"celery_task_id": celery_task_id, "metadata": metadata}

        def finish_celery_job(self, celery_task_id, **kwargs):
            captured["finished"] = {"celery_task_id": celery_task_id, **kwargs}

    class FakeRunner:
        def run(self, payload):
            captured["runner_payload"] = payload
            return {"graph_id": "graph_football"}

    monkeypatch.setattr(workflow_tasks, "TaskWorkflowService", FakeService)
    monkeypatch.setattr(workflow_tasks.GraphBuildWorkflowRunner, "run", FakeRunner().run)

    workflow_tasks.execute_workflow_event.push_request(id="celery-build", retries=0)
    try:
        result = workflow_tasks.execute_workflow_event.run(
            event_type="build_match_graph",
            payload={"project_id": "proj_graph"},
        )
    finally:
        workflow_tasks.execute_workflow_event.pop_request()

    assert result == {"graph_id": "graph_football"}
    assert captured["runner_payload"] == {"project_id": "proj_graph"}
    assert captured["started"]["metadata"]["event_type"] == "build_match_graph"
    assert captured["finished"]["status"] == "succeeded"


def test_workflow_task_dispatches_football_prediction_event(monkeypatch):
    captured = {}

    class FakeService:
        def start_celery_job(self, celery_task_id, metadata=None):
            captured["started"] = {"celery_task_id": celery_task_id, "metadata": metadata}

        def finish_celery_job(self, celery_task_id, **kwargs):
            captured["finished"] = {"celery_task_id": celery_task_id, **kwargs}

    class FakeRunner:
        def run(self, event_type, payload):
            captured["prediction_event_type"] = event_type
            captured["prediction_payload"] = payload
            return {"prediction_run_id": "run_football"}

    monkeypatch.setattr(workflow_tasks, "TaskWorkflowService", FakeService)
    monkeypatch.setattr(
        "app.services.football_prediction_workflow.FootballPredictionWorkflowRunner",
        lambda: FakeRunner(),
    )

    workflow_tasks.execute_workflow_event.push_request(id="celery-prediction", retries=0)
    try:
        result = workflow_tasks.execute_workflow_event.run(
            event_type="generate_match_events",
            payload={"project_id": "proj_prediction"},
        )
    finally:
        workflow_tasks.execute_workflow_event.pop_request()

    assert result == {"prediction_run_id": "run_football"}
    assert captured["prediction_event_type"] == "generate_match_events"
    assert captured["prediction_payload"] == {"project_id": "proj_prediction"}
    assert captured["started"]["metadata"]["event_type"] == "generate_match_events"
    assert captured["finished"]["status"] == "succeeded"


def test_workflow_task_dispatches_async_prediction_run(monkeypatch):
    captured = {}

    class FakeService:
        def start_celery_job(self, celery_task_id, metadata=None):
            captured["started"] = {"celery_task_id": celery_task_id, "metadata": metadata}

        def finish_celery_job(self, celery_task_id, **kwargs):
            captured["finished"] = {"celery_task_id": celery_task_id, **kwargs}

    class FakePredictionService:
        def run_pending_prediction_from_config(self, **kwargs):
            captured["run_kwargs"] = kwargs
            return {"prediction_run_id": kwargs["prediction_run_id"], "status": "completed"}

        def mark_prediction_failed(self, prediction_run_id, error):
            captured["failed"] = {"prediction_run_id": prediction_run_id, "error": error}

    monkeypatch.setattr(workflow_tasks, "TaskWorkflowService", FakeService)
    monkeypatch.setattr(workflow_tasks, "set_locale", lambda locale: captured.setdefault("locale", locale))
    monkeypatch.setattr(
        "app.services.football_prediction.PredictionPersistenceService",
        lambda: FakePredictionService(),
    )

    workflow_tasks.execute_workflow_event.push_request(id="celery-run", retries=0)
    try:
        result = workflow_tasks.execute_workflow_event.run(
            event_type="run_prediction_from_config",
            payload={
                "prediction_run_id": "run_async",
                "prediction_config_id": "cfg_async",
                "force_rerun": True,
                "rerun_from_event_type": "scorelines",
                "locale": "zh",
            },
        )
    finally:
        workflow_tasks.execute_workflow_event.pop_request()

    assert result == {"prediction_run_id": "run_async", "status": "completed"}
    assert captured["run_kwargs"] == {
        "prediction_run_id": "run_async",
        "prediction_config_id": "cfg_async",
        "force_rerun": True,
        "rerun_from_event_type": "scorelines",
    }
    assert captured["locale"] == "zh"
    assert "failed" not in captured
    assert captured["started"]["metadata"]["event_type"] == "run_prediction_from_config"
    assert captured["finished"]["status"] == "succeeded"


def test_workflow_task_unknown_event_fails_without_retrying(monkeypatch):
    captured = {}

    class FakeService:
        def start_celery_job(self, celery_task_id, metadata=None):
            captured["started"] = {"celery_task_id": celery_task_id, "metadata": metadata}

        def update_celery_job(self, celery_task_id, **kwargs):
            captured["updated"] = {"celery_task_id": celery_task_id, **kwargs}

        def finish_celery_job(self, celery_task_id, **kwargs):
            captured["finished"] = {"celery_task_id": celery_task_id, **kwargs}

    monkeypatch.setattr(workflow_tasks, "TaskWorkflowService", FakeService)

    workflow_tasks.execute_workflow_event.push_request(id="celery-unknown", retries=0)
    try:
        with pytest.raises(workflow_tasks.UnsupportedWorkflowEventError):
            workflow_tasks.execute_workflow_event.run(
                event_type="unknown_event",
                payload={"project_id": "proj_unknown"},
            )
    finally:
        workflow_tasks.execute_workflow_event.pop_request()

    assert captured["started"]["metadata"]["event_type"] == "unknown_event"
    assert "updated" not in captured
    assert captured["finished"]["status"] == "failed"
    assert captured["finished"]["last_error"] == "暂不支持的 workflow event: unknown_event"

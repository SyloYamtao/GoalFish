import pytest

from app.db.models import ProjectRecord
from app.db.session import get_session
from app.services.football_prediction_workflow import FootballPredictionWorkflowRunner
from app.services.task_workflow import TaskWorkflowService


@pytest.fixture()
def prediction_workflow_db(postgres_db):
    with get_session() as session:
        session.add(
            ProjectRecord(
                project_id="proj_runner",
                name="Prediction Runner",
                status="graph_completed",
                files=[],
                total_text_length=0,
                simulation_requirement="预测墨西哥 vs 南非的比分和关键事件",
                simulation_domain="football_match",
                graph_id="graph_runner",
                chunk_size=500,
                chunk_overlap=50,
                project_metadata={},
            )
        )


def test_prediction_workflow_report_event_reuses_run_and_persists_report(prediction_workflow_db):
    service = TaskWorkflowService()
    task = service.create_task(project_id="proj_runner", name="Prediction")
    task_id = task["id"]
    attempt_id = task["active_attempt"]["id"]
    runner = FootballPredictionWorkflowRunner()

    run_result = runner.run(
        "generate_match_events",
        {
            "project_id": "proj_runner",
            "workflow_task_id": task_id,
            "workflow_attempt_id": attempt_id,
        },
    )
    report_result = runner.run(
        "generate_report",
        {
            "project_id": "proj_runner",
            "workflow_task_id": task_id,
            "workflow_attempt_id": attempt_id,
        },
    )

    assert report_result["prediction_run_id"] == run_result["prediction_run_id"]
    assert report_result["status"] == "completed"
    assert service.get_event(task_id, attempt_id, "generate_report")["status"] == "succeeded"
    artifacts = service.list_artifacts(task_id, attempt_id=attempt_id, event_type="generate_report")
    assert artifacts[0]["artifact_type"] == "prediction_report"
    assert artifacts[0]["content_json"]["report_id"] == report_result["report_id"]


def test_prediction_workflow_prepare_qa_marks_final_node_ready(prediction_workflow_db):
    service = TaskWorkflowService()
    task = service.create_task(project_id="proj_runner", name="Prediction")
    task_id = task["id"]
    attempt_id = task["active_attempt"]["id"]

    result = FootballPredictionWorkflowRunner().run(
        "prepare_prediction_qa",
        {
            "project_id": "proj_runner",
            "workflow_task_id": task_id,
            "workflow_attempt_id": attempt_id,
        },
    )

    assert result["qa_ready"] is True
    assert service.get_event(task_id, attempt_id, "prepare_prediction_qa")["status"] == "succeeded"
    artifacts = service.list_artifacts(task_id, attempt_id=attempt_id, event_type="prepare_prediction_qa")
    qa_artifact = next(artifact for artifact in artifacts if artifact["artifact_type"] == "prediction_qa")
    assert qa_artifact["content_json"]["prediction_run_id"] == result["prediction_run_id"]

import pytest

from app.db.models import ProjectRecord
from app.db.session import get_session
from app.services.football_prediction_workflow import FootballPredictionWorkflowRunner
from app.services.task_workflow import TaskWorkflowService


@pytest.fixture()
def workflow_db(postgres_db):
    with get_session() as session:
        session.add(
            ProjectRecord(
                project_id="proj_prepare_prediction",
                name="Prepare Prediction",
                status="graph_completed",
                files=[],
                total_text_length=0,
                simulation_requirement="预测阿根廷 vs 法国的比分和关键事件",
                simulation_domain="football_match",
                graph_id="graph_prepare_prediction",
                chunk_size=500,
                chunk_overlap=50,
                project_metadata={},
            )
        )


def test_prediction_workflow_event_persists_config_artifact_for_resume(workflow_db):
    service = TaskWorkflowService()
    task = service.create_task(project_id="proj_prepare_prediction", name="Prediction")
    task_id = task["id"]
    attempt_id = task["active_attempt"]["id"]

    result = FootballPredictionWorkflowRunner().run(
        "compute_team_strength",
        {
            "project_id": "proj_prepare_prediction",
            "workflow_task_id": task_id,
            "workflow_attempt_id": attempt_id,
        },
    )

    event = service.get_event(task_id, attempt_id, "compute_team_strength")
    artifacts = service.list_artifacts(task_id, attempt_id=attempt_id, event_type="compute_team_strength")

    assert result["status"] == "ready"
    assert event["status"] == "succeeded"
    assert artifacts[0]["artifact_type"] == "prediction_config"
    assert artifacts[0]["content_json"]["prediction_config_id"] == result["prediction_config_id"]


def test_prediction_workflow_downstream_event_reuses_existing_prediction_run(workflow_db):
    service = TaskWorkflowService()
    task = service.create_task(project_id="proj_prepare_prediction", name="Prediction")
    task_id = task["id"]
    attempt_id = task["active_attempt"]["id"]

    first = FootballPredictionWorkflowRunner().run(
        "generate_scenario_matrix",
        {
            "project_id": "proj_prepare_prediction",
            "workflow_task_id": task_id,
            "workflow_attempt_id": attempt_id,
        },
    )
    second = FootballPredictionWorkflowRunner().run(
        "generate_match_events",
        {
            "project_id": "proj_prepare_prediction",
            "workflow_task_id": task_id,
            "workflow_attempt_id": attempt_id,
        },
    )

    assert first["prediction_config_id"] == second["prediction_config_id"]
    assert second["prediction_run_id"]
    assert second["status"] == "completed"
    assert service.get_event(task_id, attempt_id, "generate_match_events")["status"] == "succeeded"

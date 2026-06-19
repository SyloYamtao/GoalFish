import pytest
from flask import Flask

from app.api import prediction_bp


@pytest.fixture()
def client(postgres_db):
    app = Flask(__name__)
    app.register_blueprint(prediction_bp, url_prefix="/api/prediction")
    return app.test_client()


def _prepare_and_run(client, project_id, requirement, home_team, away_team):
    prepare_response = client.post(
        f"/api/prediction/{project_id}/prepare",
        json={
            "prediction_requirement": requirement,
            "home_team": home_team,
            "away_team": away_team,
        },
    )
    assert prepare_response.status_code == 200
    config_id = prepare_response.get_json()["data"]["prediction_config_id"]
    run_response = client.post(
        f"/api/prediction/{project_id}/run",
        json={"prediction_config_id": config_id},
    )
    assert run_response.status_code == 200
    return run_response.get_json()["data"]["prediction_run_id"]


def test_prediction_status_summarizes_persisted_artifacts(client):
    run_id = _prepare_and_run(
        client,
        "proj_status",
        "预测巴西 vs 德国的比分、胜平负和关键事件",
        "巴西",
        "德国",
    )

    response = client.get(f"/api/prediction/{run_id}/status")

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["status"] == "completed"
    assert data["can_resume"] is False
    assert data["counts"]["scenario_cases"] == 9
    assert data["counts"]["scenario_spaces"] == 6
    assert data["counts"]["scorelines"] == 9
    assert data["counts"]["match_events"] >= 54


def test_prediction_match_event_detail_is_replayable(client):
    run_id = _prepare_and_run(
        client,
        "proj_events",
        "预测阿根廷 vs 法国的关键事件",
        "阿根廷",
        "法国",
    )

    events_response = client.get(f"/api/prediction/{run_id}/match-events")
    result_response = client.get(f"/api/prediction/{run_id}/result")

    assert events_response.status_code == 200
    events = events_response.get_json()["data"]["match_events"]
    assert events[0]["event_type"] == "KICKOFF"
    assert any(event["event_type"] == "FINAL_SCORE_HYPOTHESIS" for event in events)
    assert all(event["scenario_case_id"] for event in events)
    assert result_response.get_json()["data"]["final_score_hypothesis"]["event_type"] == "FINAL_SCORE_HYPOTHESIS"


def test_prediction_replay_reuses_seed_and_reports_identical_drift(client):
    run_id = _prepare_and_run(
        client,
        "proj_replay",
        "预测巴西 vs 阿根廷的比分、胜平负和关键事件",
        "巴西",
        "阿根廷",
    )

    replay_response = client.post(f"/api/prediction/{run_id}/replay")

    assert replay_response.status_code == 200
    payload = replay_response.get_json()["data"]
    assert payload["original_run_id"] == run_id
    assert payload["replayed_run_id"] != run_id
    assert payload["drift"]["result_diff"] == "identical"

    original_status = client.get(f"/api/prediction/{run_id}/status").get_json()["data"]
    replay_status = client.get(f"/api/prediction/{payload['replayed_run_id']}/status").get_json()["data"]
    assert original_status["metadata"]["simulation_seed"] == replay_status["metadata"]["simulation_seed"]
    assert original_status["metadata"]["n_sims"] == replay_status["metadata"]["n_sims"]

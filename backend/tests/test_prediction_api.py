from datetime import timedelta

from flask import Flask

from app.api import prediction_bp
from app.db.models import (
    CeleryJobRecord,
    ProjectRecord,
    PredictionAnalystNoteRecord,
    PredictionCoachAgentRecord,
    PredictionConfigRecord,
    PredictionConfigResumeNodeRecord,
    PredictionConfigScenarioCaseRecord,
    PredictionMatchEventRecord,
    PredictionPlayerDatasetRecord,
    PredictionPlayerRecord,
    PredictionReportRecord,
    PredictionReportSectionRecord,
    PredictionResultRecord,
    PredictionRunRecord,
    PredictionScenarioCaseRecord,
    PredictionScenarioSpaceRecord,
    PredictionTeamMetadataRecord,
    utc_now,
)
from app.config import Config
from app.db.session import get_session
from app.services.prediction_config import DEFAULT_PLAYER_DATASET_ID


def _create_app():
    app = Flask(__name__)
    app.register_blueprint(prediction_bp, url_prefix="/api/prediction")
    return app


def _prepare_config(
    client,
    project_id="proj_football",
    *,
    graph_id="graph_football",
    requirement="预测阿根廷 vs 法国的比分和关键事件",
    home_team="阿根廷",
    away_team="法国",
    player_dataset_id=None,
    competition=None,
):
    payload = {
        "graph_id": graph_id,
        "prediction_requirement": requirement,
        "home_team": home_team,
        "away_team": away_team,
    }
    if player_dataset_id:
        payload["player_dataset_id"] = player_dataset_id
    if competition is not None:
        payload["competition"] = competition
    response = client.post(
        f"/api/prediction/{project_id}/prepare",
        json=payload,
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    return payload["data"]["prediction_config_id"]


def _run_with_config(
    client,
    project_id="proj_football",
    *,
    config_id=None,
    graph_id="graph_football",
    requirement="预测阿根廷 vs 法国的比分和关键事件",
    home_team="阿根廷",
    away_team="法国",
):
    prediction_config_id = config_id or _prepare_config(
        client,
        project_id,
        graph_id=graph_id,
        requirement=requirement,
        home_team=home_team,
        away_team=away_team,
    )
    response = client.post(
        f"/api/prediction/{project_id}/run",
        json={"prediction_config_id": prediction_config_id},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    return prediction_config_id, payload["data"]["prediction_run_id"]


def _minimal_prediction_result():
    return {
        "home_team": "主队",
        "away_team": "客队",
        "team_strengths": [
            {
                "team_role": "home",
                "team_name": "主队",
                "attack_rating": 60,
                "defense_rating": 60,
                "possession_rating": 60,
                "transition_rating": 60,
                "set_piece_rating": 60,
                "discipline_rating": 60,
                "fitness_rating": 60,
                "goalkeeper_rating": 60,
                "home_away_adjustment": 0,
                "injury_adjustment": 0,
                "form_adjustment": 0,
                "evidence": [],
                "confidence": 60,
                "metadata": {},
            }
        ],
        "scenario_cases": [],
        "scenario_spaces": [],
        "scorelines": [],
        "match_events": [],
        "analyst_notes": [
            {
                "agent_role": "data",
                "scenario_space": "baseline",
                "related_event_id": None,
                "claim": "基准判断",
                "reasoning": "测试保存顺序",
                "evidence": [],
                "confidence": 60,
                "metadata": {},
            }
        ],
        "prediction_result": {
            "baseline_prediction": {},
            "scenario_cases_summary": {},
            "scenario_spaces_summary": {},
            "scoreline_summary": {},
            "match_events_summary": {},
            "analyst_notes_summary": {},
            "final_score_hypothesis": {},
            "uncertainty_factors": [],
            "confidence": 60,
            "metadata": {},
        },
    }


def _seed_player_dataset(dataset_id: str, teams: list[tuple[str, str, str]]) -> None:
    positions = ["GK", "CB", "CB", "FB", "FB", "DM", "CM", "AM", "WG", "WG", "ST"]
    with get_session() as session:
        if session.get(PredictionPlayerDatasetRecord, dataset_id) is None:
            session.add(
                PredictionPlayerDatasetRecord(
                    dataset_id=dataset_id,
                    source_label=f"test_{dataset_id}",
                    scope_label="fifa_world_cup_2026_squads",
                    ratings_schema={"derived_fields": ["overall", "attack", "defense", "pace", "finishing", "passing", "set_piece", "gk"]},
                    teams_count=len(teams),
                    players_count=len(teams) * 22,
                    dataset_metadata={"tournament": "FIFA World Cup 2026", "matches_compatible": True},
                )
            )
        for iso3, team_fifa, team_zh in teams:
            session.add(
                PredictionTeamMetadataRecord(
                    id=f"tm_{dataset_id}_{iso3}",
                    dataset_id=dataset_id,
                    team_fifa=team_fifa,
                    team_iso3=iso3,
                    team_zh=team_zh,
                )
            )
            for index in range(22):
                position = positions[index % len(positions)]
                session.add(
                    PredictionPlayerRecord(
                        id=f"ply_{dataset_id}_{iso3}_{index + 1:02d}",
                        dataset_id=dataset_id,
                        team_name=team_fifa,
                        team_iso3=iso3,
                        player_external_id=f"{iso3}_{index + 1}",
                        full_name=f"{team_zh}球员{index + 1}",
                        full_name_en=f"{team_fifa} Player {index + 1}",
                        full_name_alt=[],
                        position_primary=position,
                        position_secondary=[],
                        age=24 + index % 8,
                        foot="R",
                        height_cm=180,
                        ratings={},
                        derived={
                            "overall": 78 + index % 8,
                            "attack": 74 + index % 15,
                            "defense": 72 + index % 12,
                            "pace": 75 + index % 14,
                            "finishing": 73 + index % 13,
                            "passing": 76 + index % 11,
                            "set_piece": 70 + index % 16,
                            "gk": 86 if position == "GK" else 0,
                        },
                        availability={"status": "available"},
                        expected_role="starter" if index < 11 else "bench",
                        expected_minutes_share=0.95 if index < 11 else 0.20,
                        shirt_number=index + 1,
                        position_class="GK" if position == "GK" else "FW" if position in {"ST", "WG"} else "MF",
                        caps_intl=10,
                        goals_intl=2,
                        club_fifa="Test FC",
                        player_metadata={},
                    )
                )


def test_prediction_save_flushes_run_before_child_artifacts(monkeypatch):
    from app.services import football_prediction

    events = []

    class FakeSession:
        def merge(self, obj):
            events.append(("merge", type(obj).__name__))

        def flush(self):
            events.append(("flush", None))

        def add(self, obj):
            events.append(("add", type(obj).__name__))

    class FakeSessionContext:
        def __enter__(self):
            return FakeSession()

        def __exit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setattr(football_prediction, "get_session", lambda: FakeSessionContext())

    football_prediction.PredictionPersistenceService().save_prediction(
        prediction_run_id="run_order",
        project_id="proj_order",
        graph_id="graph_order",
        simulation_requirement="测试保存顺序",
        competition=None,
        result=_minimal_prediction_result(),
    )

    assert events[0] == ("merge", "PredictionRunRecord")
    assert events[1] == ("flush", None)
    first_child_index = next(
        index for index, event in enumerate(events)
        if event[0] == "add" and event[1] != "PredictionRunRecord"
    )
    assert first_child_index > 1


def test_prediction_prepare_creates_ready_config_and_coach_jury(postgres_db):
    app = _create_app()
    client = app.test_client()

    config_id = _prepare_config(client, "proj_prepare")

    with get_session() as session:
        config = session.get(PredictionConfigRecord, config_id)
        assert config is not None
        assert config.status == "ready"
        assert config.current_phase == "ready"
        assert config.progress_percent == 100
        assert config.fit_status in {"fallback_prior", "insufficient"}
        assert config.data_sufficiency in {"partial", "insufficient"}
        assert config.scenario_design_summary["scenario_cases_count"] == 9
        assert config.resume_policy_summary["version"] == "resume_policy_v2"
        assert session.query(PredictionCoachAgentRecord).filter_by(prediction_config_id=config_id).count() == 100
        assert session.query(PredictionConfigScenarioCaseRecord).filter_by(prediction_config_id=config_id).count() == 9
        assert session.query(PredictionConfigResumeNodeRecord).filter_by(prediction_config_id=config_id).count() >= 8

        cases = session.query(PredictionConfigScenarioCaseRecord).filter_by(prediction_config_id=config_id).all()
        for case in cases:
            assert abs(case.final_weight - case.initial_weight) <= max(1, int(round(case.initial_weight * 0.3)))


def test_prediction_config_endpoints_replay_prepared_config(postgres_db):
    app = _create_app()
    client = app.test_client()
    config_id = _prepare_config(client, "proj_replay_config")

    config_response = client.get(f"/api/prediction/configs/{config_id}")
    status_response = client.get(f"/api/prediction/configs/{config_id}/status")
    agents_response = client.get(f"/api/prediction/configs/{config_id}/coach-agents")
    discussions_response = client.get(f"/api/prediction/configs/{config_id}/coach-discussions")
    scenario_response = client.get(f"/api/prediction/configs/{config_id}/scenario-design")
    resume_response = client.get(f"/api/prediction/configs/{config_id}/resume-policy")

    assert config_response.status_code == 200
    config_payload = config_response.get_json()["data"]
    assert config_payload["prediction_config_id"] == config_id
    assert config_payload["status"] == "ready"
    assert config_payload["scenario_design_summary"]["scenario_cases_count"] == 9
    assert config_payload["resume_policy_summary"]["version"] == "resume_policy_v2"

    assert status_response.status_code == 200
    assert status_response.get_json()["data"]["status"] == "ready"

    assert agents_response.status_code == 200
    assert agents_response.get_json()["count"] == 100

    assert discussions_response.status_code == 200
    discussions = discussions_response.get_json()["data"]["coach_discussions"]
    assert {row["discussion_type"] for row in discussions} >= {"scenario_design", "resume_policy"}

    assert scenario_response.status_code == 200
    assert len(scenario_response.get_json()["data"]["scenario_cases"]) == 9

    assert resume_response.status_code == 200
    assert resume_response.get_json()["data"]["resume_policy_summary"]["last_resumable_event"] == "generate_nine_scenario_match_events"


def test_track6_config_api_contract_exposes_dataset_roster_budget_and_progress(postgres_db):
    app = _create_app()
    client = app.test_client()
    dataset_id = "wc2026_contract_v1"
    _seed_player_dataset(dataset_id, [("ARG", "Argentina", "阿根廷"), ("FRA", "France", "法国")])

    config_id = _prepare_config(
        client,
        "proj_track6_config",
        player_dataset_id=dataset_id,
        competition={
            "tournament": "FIFA World Cup",
            "stage": "semi_final",
            "knockout": True,
            "neutral_venue": True,
            "host_country_iso3": "USA",
        },
    )

    config_payload = client.get(f"/api/prediction/configs/{config_id}").get_json()["data"]
    assert config_payload["competition"]["tournament"] == "FIFA World Cup"
    assert config_payload["competition"]["stage"] == "semi_final"
    assert config_payload["competition"]["knockout"] is True
    assert config_payload["dataset_summary"]["dataset_id"] == dataset_id
    assert config_payload["dataset_summary"]["home"]["team_iso3"] == "ARG"
    assert config_payload["dataset_summary"]["home"]["players_count"] == 22
    assert config_payload["llm_budget"]["profile_key"] == "custom"
    assert "calls_planned" in config_payload["llm_budget"]
    assert isinstance(config_payload["external_sources"], list)
    assert config_payload["config_metadata"]["versions"]["model_version"]

    datasets = client.get("/api/prediction/datasets").get_json()["data"]["datasets"]
    assert any(row["dataset_id"] == dataset_id for row in datasets)

    roster = client.get(f"/api/prediction/configs/{config_id}/roster").get_json()["data"]
    assert roster["dataset_id"] == dataset_id
    assert {team["role"] for team in roster["teams"]} == {"home", "away"}
    assert roster["teams"][0]["players"][0]["position"]

    progress = client.get(f"/api/prediction/configs/{config_id}/progress").get_json()["data"]
    assert progress["current_milestone"] == "ready"
    assert progress["messages"]

    strengths = client.get(f"/api/prediction/configs/{config_id}/team-strengths").get_json()["data"]["team_strengths"]
    assert all("evidence_breakdown" in row for row in strengths)
    assert {row["team_iso3"] for row in strengths} == {"ARG", "FRA"}


def test_prediction_prepare_accepts_config_budget_contract_on_regenerate(postgres_db):
    app = _create_app()
    client = app.test_client()

    config_id = _prepare_config(client, "proj_budget_roundtrip")
    config_payload = client.get(f"/api/prediction/configs/{config_id}").get_json()["data"]

    response = client.post(
        "/api/prediction/proj_budget_roundtrip/prepare",
        json={
            "graph_id": "graph_football",
            "prediction_requirement": "预测阿根廷 vs 法国的比分和关键事件",
            "home_team": "阿根廷",
            "away_team": "法国",
            "force_regenerate": True,
            "llm_budget": config_payload["llm_budget"],
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["prediction_config_id"] != config_id


def test_prediction_budget_usage_merges_run_and_result_ledgers(postgres_db):
    app = _create_app()
    client = app.test_client()
    run_id = "run_budget_merge"

    with get_session() as session:
        session.add(
            PredictionRunRecord(
                prediction_run_id=run_id,
                prediction_config_id=None,
                project_id="proj_budget_merge",
                graph_id=None,
                status="completed",
                current_phase="completed",
                progress_percent=100,
                run_metadata={
                    "ledger_summary": {
                        "total_calls": 1,
                        "cached": 0,
                        "spent": 1,
                        "hard_cap": 12,
                        "by_role": {"narrative_polisher": {"calls": 1, "cached": 0, "tokens": 10, "cost": 0.01}},
                        "failures": [{"role": "narrative_polisher", "reason": "llm_failed"}],
                    }
                },
            )
        )
        session.flush()
        session.add(
            PredictionResultRecord(
                prediction_run_id=run_id,
                baseline_prediction={},
                scenario_cases_summary={},
                scenario_spaces_summary={},
                scoreline_summary={},
                match_events_summary={},
                analyst_notes_summary={},
                final_score_hypothesis={},
                uncertainty_factors=[],
                confidence=60,
                result_metadata={
                    "ledger_summary": {
                        "total_calls": 2,
                        "cached": 1,
                        "spent": 2,
                        "hard_cap": 12,
                        "by_role": {"analyst_notes": {"calls": 2, "cached": 1, "tokens": 20, "cost": 0.02}},
                        "failures": [{"role": "analyst_notes", "reason": "budget_exceeded"}],
                    }
                },
            )
        )

    response = client.get(f"/api/prediction/{run_id}/budget-usage")

    assert response.status_code == 200
    ledger = response.get_json()["data"]["ledger"]
    assert ledger["total_calls"] == 3
    assert ledger["cached"] == 1
    assert ledger["spent"] == 3
    assert ledger["hard_cap"] == 12
    assert set(ledger["by_role"]) == {"narrative_polisher", "analyst_notes"}
    assert len(ledger["failures"]) == 2


def test_prediction_prepare_uses_project_text_for_generic_requirement(postgres_db):
    app = _create_app()
    client = app.test_client()
    dataset_id = "wc2026_can_bih_v1"
    _seed_player_dataset(dataset_id, [("CAN", "Canada", "加拿大"), ("BIH", "Bosnia And Herzegovina", "波黑")])

    with get_session() as session:
        session.add(
            ProjectRecord(
                project_id="proj_generic_match_text",
                name="Generic requirement",
                status="graph_completed",
                files=[{"filename": "2026世界杯加拿大vs波黑赛前信息报告.md"}],
                total_text_length=300,
                extracted_text=(
                    "=== 2026世界杯加拿大vs波黑赛前信息报告.md ===\n"
                    "# 加拿大 vs 波黑 2026 世界杯小组赛赛前信息报告\n"
                    "- 比赛：加拿大 vs 波黑\n"
                ),
                analysis_summary="该图谱面向加拿大对波黑的世界杯小组赛预测。",
                graph_id="graph_generic_match_text",
                simulation_requirement="严谨地预测这场比赛的过程和结果",
                simulation_domain="football_match",
                chunk_size=500,
                chunk_overlap=50,
                project_metadata={},
            )
        )

    response = client.post(
        "/api/prediction/proj_generic_match_text/prepare",
        json={
            "graph_id": "graph_generic_match_text",
            "prediction_requirement": "严谨地预测这场比赛的过程和结果",
            "player_dataset_id": dataset_id,
            "force_regenerate": True,
        },
    )

    assert response.status_code == 200
    config_id = response.get_json()["data"]["prediction_config_id"]
    config_payload = client.get(f"/api/prediction/configs/{config_id}").get_json()["data"]
    roster = client.get(f"/api/prediction/configs/{config_id}/roster").get_json()["data"]

    assert config_payload["home_team"] == "加拿大"
    assert config_payload["away_team"] == "波黑"
    assert config_payload["dataset_summary"]["home"]["team_iso3"] == "CAN"
    assert config_payload["dataset_summary"]["away"]["team_iso3"] == "BIH"
    assert [team["iso3"] for team in roster["teams"]] == ["CAN", "BIH"]
    assert [len(team["players"]) for team in roster["teams"]] == [22, 22]


def test_track6_dataset_switch_and_dataset_not_found_errors(postgres_db):
    app = _create_app()
    client = app.test_client()
    _seed_player_dataset("wc2026_switch_v2", [("ARG", "Argentina", "阿根廷"), ("FRA", "France", "法国")])
    config_id = _prepare_config(client, "proj_track6_switch")

    missing = client.patch(
        f"/api/prediction/configs/{config_id}/dataset",
        json={"player_dataset_id": "wc2030_v1"},
    )
    assert missing.status_code == 404
    assert missing.get_json()["code"] == "dataset_not_found"
    assert "wc2026_switch_v2" in missing.get_json()["details"]["available_datasets"]

    switched = client.patch(
        f"/api/prediction/configs/{config_id}/dataset",
        json={"player_dataset_id": "wc2026_switch_v2"},
    )
    assert switched.status_code == 200
    assert switched.get_json()["data"] == {
        "prediction_config_id": config_id,
        "status": "regenerating",
        "previous_dataset_id": DEFAULT_PLAYER_DATASET_ID,
        "new_dataset_id": "wc2026_switch_v2",
    }

    prepare_missing = client.post(
        "/api/prediction/proj_track6_missing/prepare",
        json={
            "graph_id": "graph_missing",
            "prediction_requirement": "预测阿根廷 vs 法国",
            "player_dataset_id": "wc2030_v1",
        },
    )
    assert prepare_missing.status_code == 404
    assert prepare_missing.get_json()["code"] == "dataset_not_found"


def test_prediction_prepare_is_idempotent_without_force_regenerate(postgres_db):
    app = _create_app()
    client = app.test_client()

    first_id = _prepare_config(client, "proj_idempotent", graph_id="graph_same")
    response = client.post(
        "/api/prediction/proj_idempotent/prepare",
        json={
            "graph_id": "graph_same",
            "prediction_requirement": "预测阿根廷 vs 法国的比分和关键事件",
            "force_regenerate": False,
        },
    )

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["prediction_config_id"] == first_id
    assert payload["already_prepared"] is True


def test_prediction_run_requires_prediction_config_id(postgres_db):
    app = _create_app()

    response = app.test_client().post(
        "/api/prediction/proj_missing_config/run",
        json={"graph_id": "graph_legacy", "simulation_requirement": "预测阿根廷 vs 法国"},
    )

    assert response.status_code == 400
    assert response.get_json()["success"] is False


def test_prediction_run_rejects_non_ready_config(postgres_db):
    app = _create_app()
    client = app.test_client()

    with get_session() as session:
        session.add(
            PredictionConfigRecord(
                prediction_config_id="cfg_not_ready",
                project_id="proj_not_ready",
                graph_id="graph_not_ready",
                match_name="阿根廷 vs 法国",
                home_team="阿根廷",
                away_team="法国",
                status="preparing",
                current_phase="generate_coach_agents",
                progress_percent=35,
                model_name="prior_poisson",
                model_version="v1",
                fit_status="fallback_prior",
                data_sufficiency="partial",
                source_document_ids=[],
                graph_snapshot={},
                model_input_snapshot={},
                scenario_design_summary={},
                resume_policy_summary={},
                coach_jury_summary={},
                config_metadata={},
            )
        )

    response = client.post(
        "/api/prediction/proj_not_ready/run",
        json={"prediction_config_id": "cfg_not_ready"},
    )

    assert response.status_code == 409
    assert response.get_json()["success"] is False


def test_prediction_run_persists_football_prediction_artifacts(postgres_db):
    app = _create_app()
    client = app.test_client()

    config_id, run_id = _run_with_config(client, "proj_football")

    with get_session() as session:
        run = session.get(PredictionRunRecord, run_id)
        assert run is not None
        assert run.prediction_config_id == config_id
        assert run.status == "completed"
        assert session.query(PredictionScenarioCaseRecord).filter_by(prediction_run_id=run_id).count() == 9
        assert session.query(PredictionScenarioSpaceRecord).filter_by(prediction_run_id=run_id).count() == 6
        assert session.query(PredictionMatchEventRecord).filter_by(prediction_run_id=run_id).count() >= 54
        assert session.query(PredictionAnalystNoteRecord).filter_by(prediction_run_id=run_id).count() >= 5


def test_prediction_run_can_start_async_celery_job(monkeypatch, postgres_db):
    app = _create_app()
    client = app.test_client()
    config_id = _prepare_config(client, "proj_async_run")

    captured = {}

    def fake_enqueue_workflow_event(**kwargs):
        captured.update(kwargs)
        return {
            "id": "celery_job_async",
            "celery_task_id": "celery_task_async",
        }

    monkeypatch.setattr("app.api.prediction.enqueue_workflow_event", fake_enqueue_workflow_event)

    response = client.post(
        "/api/prediction/proj_async_run/run",
        json={"prediction_config_id": config_id, "async": True},
    )

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["status"] == "queued"
    assert payload["progress_percent"] == 1
    assert payload["executor"] == "celery"
    assert payload["celery_task_id"] == "celery_task_async"
    assert captured["event_type"] == "run_prediction_from_config"
    assert captured["payload"]["prediction_run_id"] == payload["prediction_run_id"]
    assert captured["payload"]["prediction_config_id"] == config_id

    with get_session() as session:
        run = session.get(PredictionRunRecord, payload["prediction_run_id"])
        assert run.status == "queued"
        assert run.current_phase == "queued"
        assert run.run_metadata["celery_task_id"] == "celery_task_async"


def test_prediction_status_marks_run_failed_when_async_celery_job_failed(postgres_db):
    app = _create_app()
    client = app.test_client()

    with get_session() as session:
        session.add(
            PredictionConfigRecord(
                prediction_config_id="cfg_async_failed",
                project_id="proj_async_failed",
                graph_id="graph_async_failed",
                match_name="阿根廷 vs 阿尔及利亚",
                home_team="阿根廷",
                away_team="阿尔及利亚",
                status="ready",
                current_phase="ready",
                progress_percent=100,
                model_name="prior_poisson",
                model_version="v1",
                fit_status="fallback_prior",
                data_sufficiency="partial",
                source_document_ids=[],
                graph_snapshot={},
                model_input_snapshot={},
                scenario_design_summary={},
                resume_policy_summary={},
                coach_jury_summary={},
                config_metadata={},
            )
        )
        session.add(
            PredictionRunRecord(
                prediction_run_id="run_async_failed",
                prediction_config_id="cfg_async_failed",
                project_id="proj_async_failed",
                graph_id="graph_async_failed",
                match_name="阿根廷 vs 阿尔及利亚",
                home_team="阿根廷",
                away_team="阿尔及利亚",
                status="running",
                current_phase="running_simulation",
                progress_percent=28,
                run_metadata={
                    "async": True,
                    "celery_task_id": "celery_async_failed",
                    "progress_messages": [
                        {
                            "phase": "running_simulation",
                            "message": "执行九场景比赛模拟",
                            "progress_percent": 28,
                            "created_at": "2026-06-17T08:40:56+00:00",
                        }
                    ],
                },
            )
        )
        session.add(
            CeleryJobRecord(
                celery_task_id="celery_async_failed",
                queue_name="goalfish",
                status="running",
                last_error="暂不支持的 workflow event: run_prediction_from_config",
                job_metadata={
                    "event_type": "run_prediction_from_config",
                    "retry": 2,
                },
            )
        )

    response = client.get("/api/prediction/run_async_failed/status")

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["status"] == "failed"
    assert payload["current_phase"] == "failed"
    assert payload["current_event"]["status"] == "failed"
    assert payload["error"] == "暂不支持的 workflow event: run_prediction_from_config"
    assert payload["can_resume"] is True

    with get_session() as session:
        run = session.get(PredictionRunRecord, "run_async_failed")
        assert run.status == "failed"
        assert run.current_phase == "failed"
        assert run.error == "暂不支持的 workflow event: run_prediction_from_config"


def test_prediction_status_persists_celery_retry_state(monkeypatch, postgres_db):
    app = _create_app()
    client = app.test_client()

    with get_session() as session:
        session.add(
            PredictionConfigRecord(
                prediction_config_id="cfg_async_retry",
                project_id="proj_async_retry",
                graph_id="graph_async_retry",
                match_name="伊拉克 vs 挪威",
                home_team="伊拉克",
                away_team="挪威",
                status="ready",
                current_phase="ready",
                progress_percent=100,
                model_name="prior_poisson",
                model_version="v1",
                fit_status="fallback_prior",
                data_sufficiency="partial",
                source_document_ids=[],
                graph_snapshot={},
                model_input_snapshot={},
                scenario_design_summary={},
                resume_policy_summary={},
                coach_jury_summary={},
                config_metadata={},
            )
        )
        session.add(
            PredictionRunRecord(
                prediction_run_id="run_async_retry",
                prediction_config_id="cfg_async_retry",
                project_id="proj_async_retry",
                graph_id="graph_async_retry",
                match_name="伊拉克 vs 挪威",
                home_team="伊拉克",
                away_team="挪威",
                status="running",
                current_phase="running_simulation",
                progress_percent=28,
                run_metadata={"async": True, "celery_task_id": "celery_async_retry"},
            )
        )
        session.add(
            CeleryJobRecord(
                celery_task_id="celery_async_retry",
                queue_name="goalfish",
                status="running",
                job_metadata={"event_type": "run_prediction_from_config", "retry": 0},
            )
        )

    class FakeAsyncResult:
        state = "RETRY"
        result = RuntimeError("provider timeout")

        def ready(self):
            return False

    monkeypatch.setattr("app.api.prediction._celery_async_result", lambda celery_task_id: FakeAsyncResult())

    response = client.get("/api/prediction/run_async_retry/status")

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["status"] == "running"
    assert payload["celery_job"]["status"] == "retrying"
    assert payload["celery_job"]["last_error"] == "provider timeout"

    with get_session() as session:
        job = session.query(CeleryJobRecord).filter_by(celery_task_id="celery_async_retry").one()
        assert job.status == "retrying"
        assert job.last_error == "provider timeout"


def test_prediction_status_marks_stale_retry_run_failed(monkeypatch, postgres_db):
    app = _create_app()
    client = app.test_client()

    monkeypatch.setattr(Config, "PREDICTION_ASYNC_STALE_SECONDS", 1)
    stale_started_at = utc_now() - timedelta(seconds=120)

    with get_session() as session:
        session.add(
            PredictionConfigRecord(
                prediction_config_id="cfg_async_stale",
                project_id="proj_async_stale",
                graph_id="graph_async_stale",
                match_name="伊拉克 vs 挪威",
                home_team="伊拉克",
                away_team="挪威",
                status="ready",
                current_phase="ready",
                progress_percent=100,
                model_name="prior_poisson",
                model_version="v1",
                fit_status="fallback_prior",
                data_sufficiency="partial",
                source_document_ids=[],
                graph_snapshot={},
                model_input_snapshot={},
                scenario_design_summary={},
                resume_policy_summary={},
                coach_jury_summary={},
                config_metadata={},
            )
        )
        session.add(
            PredictionRunRecord(
                prediction_run_id="run_async_stale",
                prediction_config_id="cfg_async_stale",
                project_id="proj_async_stale",
                graph_id="graph_async_stale",
                match_name="伊拉克 vs 挪威",
                home_team="伊拉克",
                away_team="挪威",
                status="running",
                current_phase="running_simulation",
                progress_percent=28,
                run_metadata={"async": True, "celery_task_id": "celery_async_stale"},
            )
        )
        session.add(
            CeleryJobRecord(
                celery_task_id="celery_async_stale",
                queue_name="goalfish",
                status="running",
                started_at=stale_started_at,
                job_metadata={"event_type": "run_prediction_from_config", "retry": 0},
            )
        )

    class FakeAsyncResult:
        state = "RETRY"
        result = RuntimeError("Retry(Retry(...), None, None)")

        def ready(self):
            return False

    monkeypatch.setattr("app.api.prediction._celery_async_result", lambda celery_task_id: FakeAsyncResult())

    response = client.get("/api/prediction/run_async_stale/status")

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["status"] == "failed"
    assert payload["current_phase"] == "failed"
    assert payload["current_event"]["status"] == "failed"
    assert "后台任务长时间停留在 retrying" in payload["error"]
    assert payload["celery_job"]["status"] == "failed"
    assert payload["celery_job"]["last_error"] == payload["error"]

    with get_session() as session:
        run = session.get(PredictionRunRecord, "run_async_stale")
        job = session.query(CeleryJobRecord).filter_by(celery_task_id="celery_async_stale").one()
        assert run.status == "failed"
        assert run.error == payload["error"]
        assert job.status == "failed"
        assert job.last_error == payload["error"]


def test_prediction_status_and_match_events_are_replayable(postgres_db):
    app = _create_app()
    client = app.test_client()

    _, run_id = _run_with_config(
        client,
        "proj_replay",
        requirement="预测墨西哥 vs 南非",
        home_team="墨西哥",
        away_team="南非",
    )

    status_response = client.get(f"/api/prediction/{run_id}/status")
    events_response = client.get(f"/api/prediction/{run_id}/match-events")
    spaces_response = client.get(f"/api/prediction/{run_id}/scenario-spaces")

    assert status_response.status_code == 200
    status = status_response.get_json()["data"]
    assert status["status"] == "completed"
    assert status["counts"]["scenario_cases"] == 9
    assert status["counts"]["scenario_spaces"] == 6
    assert status["counts"]["match_events"] >= 54
    assert status["can_resume"] is False

    events = events_response.get_json()["data"]["match_events"]
    assert events[0]["event_type"] == "KICKOFF"
    assert any(event["event_type"] == "FINAL_SCORE_HYPOTHESIS" for event in events)
    assert all(event["scenario_case_id"] for event in events)

    spaces = spaces_response.get_json()["data"]["scenario_spaces"]
    assert {space["space_key"] for space in spaces} == {
        "baseline",
        "home_upside",
        "away_upside",
        "home_error",
        "away_error",
        "volatility",
    }


def test_track6_step3_contract_exposes_roster_budget_events_and_modal_summary(postgres_db):
    app = _create_app()
    client = app.test_client()
    dataset_id = "wc2026_step3_contract_v1"
    _seed_player_dataset(dataset_id, [("ARG", "Argentina", "阿根廷"), ("FRA", "France", "法国")])
    config_id = _prepare_config(client, "proj_track6_step3", player_dataset_id=dataset_id)

    _, run_id = _run_with_config(client, "proj_track6_step3", config_id=config_id)

    scenarios = client.get(f"/api/prediction/{run_id}/scenario-cases").get_json()["data"]["scenario_cases"]
    assert len(scenarios) == 9
    assert scenarios[0]["n_sims"] == 500
    assert scenarios[0]["modal_trajectory_summary"]["trajectory_id"]
    assert scenarios[0]["modal_trajectory_summary"]["total_events"] >= 1
    assert scenarios[0]["most_likely_score"]

    events = client.get(f"/api/prediction/{run_id}/match-events").get_json()["data"]["match_events"]
    assert events[0]["sample_provenance"]["scenario_key"]
    assert "actor_player" in events[0]
    assert "assist_player" in events[0]
    assert "score_after" in events[0]

    roster = client.get(f"/api/prediction/{run_id}/roster").get_json()["data"]
    assert roster["dataset_id"] == dataset_id
    assert roster["teams"][0]["players"][0]["actor_stats"]["minutes_played_p50"] > 0

    ledger = client.get(f"/api/prediction/{run_id}/budget-usage").get_json()["data"]["ledger"]
    assert {"total_calls", "cached", "hard_cap", "by_role", "failures"} <= set(ledger)


def test_prediction_artifact_endpoints_include_team_strengths_and_scorelines(postgres_db):
    app = _create_app()
    client = app.test_client()

    _, run_id = _run_with_config(
        client,
        "proj_artifacts",
        requirement="预测阿根廷 vs 法国的胜平负、比分、控球和射门质量",
    )

    strengths_response = client.get(f"/api/prediction/{run_id}/team-strengths")
    scorelines_response = client.get(f"/api/prediction/{run_id}/scorelines")

    assert strengths_response.status_code == 200
    strengths_payload = strengths_response.get_json()
    assert strengths_payload["success"] is True
    strengths = strengths_payload["data"]["team_strengths"]
    assert {row["team_role"] for row in strengths} == {"home", "away"}
    assert {row["team_name"] for row in strengths} == {"阿根廷", "法国"}
    assert all("attack_rating" in row and "goalkeeper_rating" in row for row in strengths)

    assert scorelines_response.status_code == 200
    scorelines_payload = scorelines_response.get_json()
    assert scorelines_payload["success"] is True
    scorelines = scorelines_payload["data"]["scorelines"]
    assert len(scorelines) == 9
    assert all(row["scenario_case_id"] for row in scorelines)
    assert {row["scenario_space"] for row in scorelines} >= {
        "baseline",
        "home_upside",
        "away_upside",
        "home_error",
        "away_error",
        "volatility",
    }
    assert all(row["most_likely_score"] for row in scorelines)


def test_prediction_report_can_be_generated_from_persisted_artifacts(postgres_db):
    app = _create_app()
    client = app.test_client()

    config_id, run_id = _run_with_config(
        client,
        "proj_report",
        graph_id="graph_report",
        requirement="预测巴西 vs 德国的胜平负、比分和关键事件",
        home_team="巴西",
        away_team="德国",
    )

    report_response = client.post(f"/api/prediction/{run_id}/report")

    assert report_response.status_code == 200
    payload = report_response.get_json()
    assert payload["success"] is True
    assert payload["data"]["prediction_run_id"] == run_id
    assert payload["data"]["status"] == "completed"
    report_id = payload["data"]["report_id"]

    with get_session() as session:
        report = session.get(PredictionReportRecord, report_id)
        assert report is not None
        assert report.simulation_id == run_id
        assert report.simulation_domain == "football_match"
        assert report.status == "completed"
        assert (report.report_metadata or {})["prediction_run_id"] == run_id
        assert (report.report_metadata or {})["prediction_config_id"] == config_id
        assert (
            session.query(PredictionReportSectionRecord)
            .filter_by(report_id=report_id)
            .count()
            == 6
        )
        first_section = (
            session.query(PredictionReportSectionRecord)
            .filter_by(report_id=report_id, section_index=1)
            .one()
        )
        assert first_section.title == "比赛结论摘要"
        assert "一句话结论" in first_section.content
        assert "怎么读" in first_section.content
        assert "依据来自" in first_section.content
        assert "|" in first_section.content
        assert "比分" in first_section.content

        credibility_section = (
            session.query(PredictionReportSectionRecord)
            .filter_by(report_id=report_id, section_index=6)
            .one()
        )
        assert credibility_section.title == "风险、不确定性与可信度说明"
        assert "预测不是确定结果" in credibility_section.content
        assert "| 风险 |" in credibility_section.content or "| 风险类别 |" in credibility_section.content
        assert "| 角色 | 调用次数 | tokens | 成本 |" not in credibility_section.content

        evidence_package = (report.report_metadata or {})["evidence_package"]
        assert evidence_package["step3"]["scoreline_summary"]["most_likely_score"]
        assert evidence_package["match"]["prediction_run_id"] == run_id
        assert len(evidence_package["step3"]["events"]) >= 1
        assert (report.report_metadata or {})["source"] == "prediction_report_assembler_v2"


def test_prediction_history_lists_replayable_football_runs(postgres_db):
    app = _create_app()
    client = app.test_client()

    with get_session() as session:
        session.add(
            ProjectRecord(
                project_id="proj_history",
                name="世界杯预测项目",
                status="graph_completed",
                files=[{"filename": "match-preview.pdf", "size": 1024}],
                total_text_length=2048,
                simulation_requirement="预测阿根廷 vs 法国的比分和关键事件",
                simulation_domain="football_match",
                chunk_size=500,
                chunk_overlap=50,
                project_metadata={},
            )
        )

    _, run_id = _run_with_config(
        client,
        "proj_history",
        graph_id="graph_history",
        requirement="预测阿根廷 vs 法国的比分和关键事件",
        home_team="阿根廷",
        away_team="法国",
    )
    report_id = client.post(f"/api/prediction/{run_id}/report").get_json()["data"]["report_id"]

    history_response = client.get("/api/prediction/history?limit=5")

    assert history_response.status_code == 200
    payload = history_response.get_json()
    assert payload["success"] is True
    assert payload["count"] == 1
    item = payload["data"][0]
    assert item["prediction_run_id"] == run_id
    assert item["project_id"] == "proj_history"
    assert item["report_id"] == report_id
    assert item["simulation_requirement"] == "预测阿根廷 vs 法国的比分和关键事件"
    assert item["prediction_requirement"] == "预测阿根廷 vs 法国的比分和关键事件"
    assert item["files"] == [{"filename": "match-preview.pdf", "size": 1024}]
    assert item["status"] == "completed"
    assert item["progress_percent"] == 100
    assert item["match_name"] == "阿根廷 vs 法国"
    assert item["home_team"] == "阿根廷"
    assert item["away_team"] == "法国"
    assert item["most_likely_score"]


def test_football_prediction_schema_does_not_recreate_legacy_social_tables(postgres_db):
    from sqlalchemy import inspect
    from app.db.session import get_engine

    table_names = set(inspect(get_engine()).get_table_names())

    assert "prediction_runs" in table_names
    assert "prediction_configs" in table_names
    assert "prediction_coach_agents" in table_names
    assert "prediction_match_events" in table_names
    assert {
        "simulations",
        "simulation_posts",
        "simulation_comments",
        "simulation_actions",
        "simulation_traces",
    }.isdisjoint(table_names)


def test_football_report_conversation_uses_prediction_artifacts(postgres_db):
    from app.api import report_bp

    app = _create_app()
    app.register_blueprint(report_bp, url_prefix="/api/report")
    client = app.test_client()

    config_id, run_id = _run_with_config(
        client,
        "proj_chat",
        graph_id="graph_chat",
        requirement="预测阿根廷 vs 法国的比分和关键事件",
    )
    report_id = client.post(f"/api/prediction/{run_id}/report").get_json()["data"]["report_id"]

    conversation_response = client.post(
        f"/api/report/{report_id}/conversations",
        json={
            "simulation_id": run_id,
            "target_type": "report_agent",
            "title": "Prediction Q&A",
        },
    )
    conversation_id = conversation_response.get_json()["data"]["id"]

    message_response = client.post(
        f"/api/report/{report_id}/conversations/{conversation_id}/messages",
        json={"message": "这场比赛最可能的比分和关键风险是什么？"},
    )

    assert message_response.status_code == 200
    payload = message_response.get_json()
    assert payload["success"] is True
    assert "我基于已保存的足球预测产物回答" not in payload["data"]["response"]
    assert "报告" in payload["data"]["response"]
    assert "最可能比分" in payload["data"]["response"]
    assert "风险" in payload["data"]["response"]
    assert any(source["type"] == "prediction_result" for source in payload["data"]["sources"])
    assert any(source["type"] == "prediction_config" and source["prediction_config_id"] == config_id for source in payload["data"]["sources"])
    assert any(source["type"] == "coach_discussions" for source in payload["data"]["sources"])
    assert any(source["type"] == "match_events" for source in payload["data"]["sources"])
    assert any(source["type"] == "report_sections" for source in payload["data"]["sources"])

    messages_response = client.get(f"/api/report/{report_id}/conversations/{conversation_id}/messages")
    messages = messages_response.get_json()["data"]["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]


def test_legacy_report_chat_endpoint_uses_football_prediction_artifacts(postgres_db):
    from app.api import report_bp

    app = _create_app()
    app.register_blueprint(report_bp, url_prefix="/api/report")
    client = app.test_client()

    _, run_id = _run_with_config(
        client,
        "proj_legacy_chat",
        graph_id="graph_legacy_chat",
        requirement="预测西班牙 vs 葡萄牙的比分和关键事件",
        home_team="西班牙",
        away_team="葡萄牙",
    )
    client.post(f"/api/prediction/{run_id}/report")

    chat_response = client.post(
        "/api/report/chat",
        json={
            "simulation_id": run_id,
            "message": "请解释最可能比分和风险",
            "chat_history": [],
        },
    )

    assert chat_response.status_code == 200
    payload = chat_response.get_json()
    assert payload["success"] is True
    assert "我基于已保存的足球预测产物回答" not in payload["data"]["response"]
    assert "报告" in payload["data"]["response"]
    assert "最可能比分" in payload["data"]["response"]
    assert any(source["type"] == "prediction_result" for source in payload["data"]["sources"])
    assert any(source["type"] == "coach_discussions" for source in payload["data"]["sources"])
    assert any(source["type"] == "report_sections" for source in payload["data"]["sources"])


def test_legacy_report_generate_endpoint_uses_prediction_report_assembler(postgres_db):
    from app.api import report_bp

    app = _create_app()
    app.register_blueprint(report_bp, url_prefix="/api/report")
    client = app.test_client()

    _, run_id = _run_with_config(
        client,
        "proj_legacy_report",
        graph_id="graph_legacy_report",
        requirement="预测荷兰 vs 克罗地亚的比分和关键事件",
        home_team="荷兰",
        away_team="克罗地亚",
    )

    report_response = client.post(
        "/api/report/generate",
        json={"simulation_id": run_id},
    )

    assert report_response.status_code == 200
    payload = report_response.get_json()
    assert payload["success"] is True
    assert payload["data"]["prediction_run_id"] == run_id
    assert payload["data"]["status"] == "completed"


def test_report_generate_endpoint_preserves_explicit_run_and_config_context(postgres_db):
    from app.api import report_bp

    app = _create_app()
    app.register_blueprint(report_bp, url_prefix="/api/report")
    client = app.test_client()

    config_id, run_id = _run_with_config(
        client,
        "proj_report_context",
        graph_id="graph_report_context",
        requirement="预测瑞士 vs 波黑的比分和关键事件",
        home_team="瑞士",
        away_team="波黑",
    )

    report_response = client.post(
        "/api/report/generate",
        json={
            "project_id": "proj_report_context",
            "prediction_run_id": run_id,
            "prediction_config_id": config_id,
        },
    )

    assert report_response.status_code == 200
    payload = report_response.get_json()
    assert payload["success"] is True
    assert payload["data"]["prediction_run_id"] == run_id

    with get_session() as session:
        report = session.get(PredictionReportRecord, payload["data"]["report_id"])
        assert report.report_metadata["prediction_config_id"] == config_id


def test_report_generate_endpoint_rejects_run_config_mismatch(postgres_db):
    from app.api import report_bp

    app = _create_app()
    app.register_blueprint(report_bp, url_prefix="/api/report")
    client = app.test_client()

    config_id, run_id = _run_with_config(client, "proj_report_mismatch")

    report_response = client.post(
        "/api/report/generate",
        json={
            "project_id": "proj_report_mismatch",
            "prediction_run_id": run_id,
            "prediction_config_id": f"{config_id}_wrong",
        },
    )

    assert report_response.status_code == 400
    payload = report_response.get_json()
    assert payload["success"] is False
    assert "prediction_config_id does not match prediction_run_id" in payload["error"]

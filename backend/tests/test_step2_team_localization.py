from __future__ import annotations

from flask import Flask

from app.api import graph_bp
from app.db.models import (
    PredictionCoachDiscussionRecord,
    PredictionConfigRecord,
    PredictionConfigResumeNodeRecord,
    PredictionConfigScenarioCaseRecord,
    ProjectRecord,
)
from app.db.session import get_session
from app.services.prediction_config import PredictionConfigService
from app.services.team_localization import localize_team_strength_rows
from app.utils.locale import set_locale


def test_project_detail_localizes_persisted_step2_preview_by_ui_locale(postgres_db):
    del postgres_db
    _seed_project_with_step2_preview()

    app = Flask(__name__)
    app.register_blueprint(graph_bp, url_prefix="/api/graph")

    en_response = app.test_client().get("/api/graph/project/proj_step2_locale", headers={"Accept-Language": "en"})
    zh_response = app.test_client().get("/api/graph/project/proj_step2_locale", headers={"Accept-Language": "zh"})

    assert en_response.status_code == 200
    en_preview = en_response.get_json()["data"]["project_metadata"]["step2_preview"]
    assert en_preview["home_team"] == "Tunisia"
    assert en_preview["away_team"] == "Japan"
    assert en_preview["match_name"] == "Tunisia vs Japan"
    assert en_preview["dataset_summary"]["home"]["team_name"] == "Tunisia"
    assert en_preview["roster"]["teams"][1]["name"] == "Japan"

    assert zh_response.status_code == 200
    zh_preview = zh_response.get_json()["data"]["project_metadata"]["step2_preview"]
    assert zh_preview["home_team"] == "突尼斯"
    assert zh_preview["away_team"] == "日本"
    assert zh_preview["match_name"] == "突尼斯 vs 日本"


def test_team_strength_rows_localize_by_iso3():
    rows = [
        {"team_role": "home", "team_name": "突尼斯", "team_iso3": "TUN"},
        {"team_role": "away", "team_name": "日本", "metadata": {"team_iso3": "JPN"}},
    ]

    localized = localize_team_strength_rows(rows, locale="en")

    assert [row["team_name"] for row in localized] == ["Tunisia", "Japan"]


def test_config_ui_artifacts_localize_persisted_chinese_labels_by_ui_locale(postgres_db):
    del postgres_db
    _seed_config_with_step2_ui_artifacts()
    service = PredictionConfigService()

    set_locale("en")
    cases = service.list_scenario_cases("cfg_step2_ui_locale")
    nodes = service.list_resume_nodes("cfg_step2_ui_locale")
    discussions = service.list_coach_discussions("cfg_step2_ui_locale")
    config = service.get_config("cfg_step2_ui_locale")

    assert cases[0]["scenario_name"] == "Baseline trend"
    assert cases[0]["key_drivers"] == ["Both teams perform normally", "Stable tempo", "Standard shot quality"]
    assert cases[0]["risk_factors"] == ["Early goal changes tempo"]
    assert nodes[0]["label"] == "Extract team context"
    assert nodes[0]["ui_replay_summary"] == "Extract team context: recompute"
    assert discussions[0]["topic"] == "02 Scenario Space Design"
    assert "nine-scenario matrix" in discussions[0]["summary"]
    assert config["scenario_design_summary"]["matrix"][0]["scenario_name"] == "Baseline trend"

    set_locale("zh")
    zh_cases = service.list_scenario_cases("cfg_step2_ui_locale")
    zh_nodes = service.list_resume_nodes("cfg_step2_ui_locale")

    assert zh_cases[0]["scenario_name"] == "基准走势"
    assert zh_nodes[0]["label"] == "抽取球队上下文"
    set_locale("en")


def _seed_project_with_step2_preview() -> None:
    with get_session() as session:
        session.add(
            ProjectRecord(
                project_id="proj_step2_locale",
                name="Step2 Locale",
                status="graph_completed",
                files=[],
                total_text_length=0,
                extracted_text="Teams: Tunisia (Team A) vs Japan (Team B).",
                graph_id="graph_step2_locale",
                simulation_requirement="Predict the match",
                simulation_domain="football_match",
                project_metadata={
                    "step2_preview": {
                        "status": "preview_ready",
                        "home_team": "突尼斯",
                        "away_team": "日本",
                        "match_name": "突尼斯 vs 日本",
                        "home_iso3": "TUN",
                        "away_iso3": "JPN",
                        "dataset_summary": {
                            "home": {"team_iso3": "TUN", "team_name": "突尼斯", "players_count": 11},
                            "away": {"team_iso3": "JPN", "team_name": "日本", "players_count": 11},
                        },
                        "roster": {
                            "teams": [
                                {"role": "home", "iso3": "TUN", "name": "突尼斯", "players": []},
                                {"role": "away", "iso3": "JPN", "name": "日本", "players": []},
                            ]
                        },
                    }
                },
            )
        )


def _seed_config_with_step2_ui_artifacts() -> None:
    with get_session() as session:
        config = PredictionConfigRecord(
            prediction_config_id="cfg_step2_ui_locale",
            project_id="proj_step2_ui_locale",
            graph_id="graph_step2_ui_locale",
            match_name="突尼斯 vs 日本",
            home_team="突尼斯",
            away_team="日本",
            status="ready",
            current_phase="ready",
            progress_percent=100,
            fit_status="uniform",
            data_sufficiency="insufficient",
            model_input_snapshot={
                "home_iso3": "TUN",
                "away_iso3": "JPN",
                "squads": {
                    "home": {"team_iso3": "TUN", "team_name": "突尼斯", "players": []},
                    "away": {"team_iso3": "JPN", "team_name": "日本", "players": []},
                },
            },
            scenario_design_summary={
                "matrix": [
                    {
                        "scenario_key": "home_normal_away_normal",
                        "home_state": "normal",
                        "away_state": "normal",
                        "scenario_name": "基准走势",
                        "scenario_space": "baseline",
                        "initial_weight": 22,
                        "final_weight": 22,
                        "key_drivers": ["双方正常发挥", "稳态节奏", "常规射门质量"],
                        "risk_factors": ["早进球改变节奏"],
                    }
                ]
            },
            resume_policy_summary={
                "nodes": [
                    {
                        "event_type": "extract_team_context",
                        "sequence": 50,
                        "label": "抽取球队上下文",
                        "resume_strategy": "recompute",
                    }
                ]
            },
        )
        session.add(config)
        session.flush()
        session.add(
            PredictionConfigScenarioCaseRecord(
                prediction_config_id="cfg_step2_ui_locale",
                home_state="normal",
                away_state="normal",
                scenario_key="home_normal_away_normal",
                scenario_name="基准走势",
                scenario_space="baseline",
                initial_weight=22,
                final_weight=22,
                key_drivers=["双方正常发挥", "稳态节奏", "常规射门质量"],
                risk_factors=["早进球改变节奏"],
                coach_vote_summary={},
                model_constraints={},
            )
        )
        session.add(
            PredictionConfigResumeNodeRecord(
                prediction_config_id="cfg_step2_ui_locale",
                event_type="extract_team_context",
                sequence=50,
                label="抽取球队上下文",
                must_persist=True,
                can_recompute=True,
                resume_strategy="recompute",
                input_artifact_types=["graph_snapshot"],
                output_artifact_types=["team_context"],
                ui_replay_summary="抽取球队上下文：recompute",
                coach_vote_summary={},
            )
        )
        session.add(
            PredictionCoachDiscussionRecord(
                prediction_config_id="cfg_step2_ui_locale",
                discussion_type="scenario_design",
                round_index=1,
                topic="02 场景空间设计",
                prompt="围绕 3x3 九种主客队发挥状态、六个空间归属和权重上限进行教练评审。",
                summary="教练评审团支持保留九场景矩阵；权重不覆盖科学模型，仅作为场景先验权重并控制在 30% 调整上限内。",
                consensus_score=74,
                disagreement_score=26,
                discussion_metadata={},
            )
        )

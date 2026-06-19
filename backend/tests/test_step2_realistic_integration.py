from __future__ import annotations

import time
from typing import Any

import pandas as pd
import pytest

from app.db.models import (
    PredictionConfigRecord,
    PredictionPlayerDatasetRecord,
    PredictionPlayerRecord,
    PredictionTeamMetadataRecord,
    ProjectRecord,
)
from app.db.session import get_session
from app.services.coach_jury import SCENARIO_TEMPLATE
from app.services.graph_evidence_query import GraphFacts
from app.services.prediction_config import PredictionConfigService


DATASET_ID = "wc2026_fifa_v1"


class FakeLLM:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def chat_json(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        content = "\n".join(str(message.get("content", "")) for message in kwargs.get("messages") or [])
        if "prediction_requirement" in content and "competition_meta" in content:
            return {
                "home_iso3": "ARG",
                "away_iso3": "FRA",
                "home_name_zh": "阿根廷",
                "away_name_zh": "法国",
                "competition_meta": {
                    "tournament": "世界杯",
                    "stage": "semi_final",
                    "knockout": True,
                    "neutral_venue": True,
                    "host_country_iso3": "USA",
                },
                "key_narratives": ["阿根廷前场状态稳定", "法国边路冲击强"],
                "injury_reports": [{"player": "France Player 7", "team_iso3": "FRA", "status": "doubtful"}],
                "tactical_notes": [{"team_iso3": "ARG", "note": "中场控球推进"}],
            }
        return _fake_verdict()


class FakeGraphEvidenceQuery:
    def for_match(self, **kwargs: Any) -> GraphFacts:
        del kwargs
        return GraphFacts()


class FakeElo:
    def elo_to_lambda(self, home_elo: float, away_elo: float, **kwargs: Any) -> tuple[float, float]:
        del kwargs
        return (1.55 if home_elo >= away_elo else 1.25, 1.20 if home_elo >= away_elo else 1.45)


class FakeExternalDataPool:
    def __init__(self) -> None:
        self.elo = FakeElo()
        self.sources: list[str | None] = []

    def fetch_for_match(self, *args: Any, **kwargs: Any) -> "FakeExternalDataPool":
        del args
        self.sources = list(kwargs.get("sources") or [])
        return self

    def fit_dataframe(self, cutoff_date: str | None = None) -> pd.DataFrame:
        del cutoff_date
        rows = []
        for index in range(8):
            rows.append(
                {
                    "date": f"2024-{index + 1:02d}-10",
                    "home_iso3": "ARG",
                    "away_iso3": "FRA",
                    "home_score": 2 + index % 2,
                    "away_score": 1,
                    "neutral": True,
                    "tournament": "FIFA World Cup",
                }
            )
            rows.append(
                {
                    "date": f"2024-{index + 1:02d}-20",
                    "home_iso3": "FRA",
                    "away_iso3": "ARG",
                    "home_score": 1,
                    "away_score": 1 + index % 3,
                    "neutral": True,
                    "tournament": "UEFA Nations League",
                }
            )
        return pd.DataFrame(rows)

    def elo_snapshot(self) -> dict[str, float]:
        return {"ARG": 1985.0, "FRA": 1940.0}


@pytest.fixture()
def mock_llm(monkeypatch) -> FakeLLM:
    fake = FakeLLM()
    monkeypatch.setattr("app.utils.llm_client.LLMClient", lambda: fake)
    return fake


@pytest.fixture()
def real_db(postgres_db, monkeypatch):
    del postgres_db
    monkeypatch.setattr("app.services.prediction_config.GraphEvidenceQuery", FakeGraphEvidenceQuery)
    monkeypatch.setattr("app.services.prediction_config.ExternalDataPool", FakeExternalDataPool)
    _seed_project("proj_step2", "graph_step2")
    _seed_team("ARG", "Argentina", "阿根廷")
    _seed_team("FRA", "France", "法国")


def test_full_step2_low_budget_under_8s(real_db, mock_llm):
    started = time.perf_counter()

    result = PredictionConfigService().prepare(
        project_id="proj_step2",
        graph_id="graph_low",
        prediction_requirement="阿根廷 vs 法国 世界杯半决赛",
        home_team="阿根廷",
        away_team="法国",
        llm_budget={"profile_key": "low"},
        player_dataset_id=DATASET_ID,
    )

    assert result["status"] == "ready"
    assert result["llm_budget"]["profile_key"] == "low"
    assert time.perf_counter() - started < 8


def test_full_step2_middle_with_extracted_facts(real_db, mock_llm):
    result = PredictionConfigService().prepare(
        project_id="proj_step2",
        graph_id="graph_middle",
        prediction_requirement="阿根廷 vs 法国 世界杯半决赛，双方都有边路冲击",
        home_team="阿根廷",
        away_team="法国",
        llm_budget={"profile_key": "middle"},
        player_dataset_id=DATASET_ID,
    )

    with get_session() as session:
        config = session.get(PredictionConfigRecord, result["prediction_config_id"])
        extracted = (config.model_input_snapshot or {})["extracted"]

    assert extracted["extracted_by"] == "llm"
    assert extracted["key_narratives"]
    assert extracted["tactical_notes"]


def test_full_step2_max_with_all_8_roles(real_db, mock_llm):
    result = PredictionConfigService().prepare(
        project_id="proj_step2",
        graph_id="graph_max",
        prediction_requirement="阿根廷 vs 法国 世界杯决赛",
        home_team="阿根廷",
        away_team="法国",
        llm_budget={"profile_key": "max"},
        player_dataset_id=DATASET_ID,
    )

    with get_session() as session:
        config = session.get(PredictionConfigRecord, result["prediction_config_id"])
        contributors = (config.coach_jury_summary or {})["contributors"]

    assert {item["role"] for item in contributors} == {
        "head_coach",
        "attack",
        "defense",
        "transition",
        "set_piece",
        "goalkeeper",
        "fitness",
        "risk",
    }


def test_progress_messages_emitted_in_order(real_db, mock_llm):
    result = PredictionConfigService().prepare(
        project_id="proj_step2",
        graph_id="graph_progress",
        prediction_requirement="阿根廷 vs 法国 世界杯半决赛",
        home_team="阿根廷",
        away_team="法国",
        llm_budget={"profile_key": "low"},
        player_dataset_id=DATASET_ID,
    )

    progress = PredictionConfigService().get_progress(result["prediction_config_id"])
    milestones = [message["milestone"] for message in progress["progress_messages"]]

    expected_order = [
        "loading_squads",
        "querying_graph",
        "extracting_facts",
        "fetching_external",
        "fitting_model",
        "estimating_strengths",
        "panel_role_head_coach",
        "panel_role_risk",
        "applying_weights",
        "persisting",
        "ready",
    ]
    assert [milestone for milestone in milestones if milestone in expected_order] == expected_order


def test_fitted_artifacts_persisted(real_db, mock_llm):
    result = PredictionConfigService().prepare(
        project_id="proj_step2",
        graph_id="graph_artifacts",
        prediction_requirement="阿根廷 vs 法国 世界杯半决赛",
        home_team="阿根廷",
        away_team="法国",
        llm_budget={"profile_key": "low"},
        player_dataset_id=DATASET_ID,
    )

    with get_session() as session:
        config = session.get(PredictionConfigRecord, result["prediction_config_id"])
        artifacts = (config.model_input_snapshot or {})["fitted_artifacts"]

    assert artifacts["fit_status"] in {"fitted", "bayesian_hierarchical", "elo_prior", "uniform"}
    assert artifacts["model_name"]
    assert artifacts["diagnostics"]["n_rows"] >= 16
    assert set(artifacts["xg_priors"]) >= {"ARG", "FRA"} or artifacts["attack_coef"]


def test_coach_jury_summary_real_contributors(real_db, mock_llm):
    result = PredictionConfigService().prepare(
        project_id="proj_step2",
        graph_id="graph_contributors",
        prediction_requirement="阿根廷 vs 法国 世界杯半决赛",
        home_team="阿根廷",
        away_team="法国",
        llm_budget={"profile_key": "middle"},
        player_dataset_id=DATASET_ID,
    )

    with get_session() as session:
        config = session.get(PredictionConfigRecord, result["prediction_config_id"])
        contributors = (config.coach_jury_summary or {})["contributors"]

    assert contributors
    assert all(item["summary"].startswith("LLM verdict for") for item in contributors)
    assert all(item["source"] == "coach_llm_panel_v1" for item in contributors)


def test_scenario_design_summary_weight_change_visible(real_db, mock_llm):
    result = PredictionConfigService().prepare(
        project_id="proj_step2",
        graph_id="graph_weights",
        prediction_requirement="阿根廷 vs 法国 世界杯半决赛",
        home_team="阿根廷",
        away_team="法国",
        llm_budget={"profile_key": "middle"},
        player_dataset_id=DATASET_ID,
    )

    with get_session() as session:
        config = session.get(PredictionConfigRecord, result["prediction_config_id"])
        matrix = (config.scenario_design_summary or {})["matrix"]

    assert len(matrix) == 9
    assert any(row["weight_change"]["applied_delta"] != 0 for row in matrix)


def _fake_verdict() -> dict[str, Any]:
    votes = []
    for index, scenario in enumerate(SCENARIO_TEMPLATE):
        delta = ((index % 5) - 2) * 3
        votes.append(
            {
                "scenario_key": scenario["scenario_key"],
                "vote": "adjust" if delta else "support",
                "weight_delta_pct": delta,
                "rationale": f"LLM delta {delta} for {scenario['scenario_key']}",
                "evidence_refs": [{"type": "fit_summary"}],
            }
        )
    return {
        "role": "head_coach",
        "scenario_votes": votes,
        "team_xg_micro_adjustment": {"home": 0.02, "away": -0.01, "rationale": "small edge"},
        "wld_pp_adjustment": None,
        "confidence_delta": 0.02,
        "summary": "LLM verdict for role",
        "metadata": {"source": "coach_llm_panel_v1"},
    }


def _seed_project(project_id: str, graph_id: str) -> None:
    with get_session() as session:
        session.add(
            ProjectRecord(
                project_id=project_id,
                name="Step2 realistic",
                status="graph_completed",
                files=[{"id": "doc_1", "filename": "preview.md"}],
                total_text_length=300,
                extracted_text="阿根廷 vs 法国 世界杯半决赛。阿根廷中场控球，法国边路冲击。",
                analysis_summary="双方都有稳定进攻样本。",
                graph_id=graph_id,
                simulation_requirement="阿根廷 vs 法国 世界杯半决赛",
                simulation_domain="football_match",
                chunk_size=500,
                chunk_overlap=50,
                project_metadata={},
            )
        )


def _seed_team(iso3: str, team_fifa: str, team_zh: str) -> None:
    positions = ["GK", "CB", "CB", "FB", "FB", "DM", "CM", "AM", "WG", "WG", "ST"]
    with get_session() as session:
        if session.get(PredictionPlayerDatasetRecord, DATASET_ID) is None:
            session.add(
                PredictionPlayerDatasetRecord(
                    dataset_id=DATASET_ID,
                    source_label="test",
                    scope_label="fifa_world_cup_2026_squads",
                    ratings_schema={"derived_fields": ["overall", "attack", "defense", "pace", "finishing", "passing", "set_piece", "gk"]},
                    teams_count=2,
                    players_count=44,
                )
            )
        session.add(
            PredictionTeamMetadataRecord(
                id=f"tm_{DATASET_ID}_{iso3}",
                dataset_id=DATASET_ID,
                team_fifa=team_fifa,
                team_iso3=iso3,
                team_zh=team_zh,
            )
        )
        for index in range(22):
            position = positions[index % len(positions)]
            session.add(
                PredictionPlayerRecord(
                    id=f"ply_{DATASET_ID}_{iso3}_{index + 1:02d}",
                    dataset_id=DATASET_ID,
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

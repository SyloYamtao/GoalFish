import pytest

from app.services.football_prediction import FootballPredictionEngine, MATCH_EVENT_TYPES
from app.services.simulation_domains import normalize_simulation_domain


def test_football_prediction_uses_match_scenarios_instead_of_social_agents():
    result = FootballPredictionEngine().run(
        prediction_run_id="run_contract",
        project_id="proj_contract",
        graph_id="graph_contract",
        simulation_requirement="预测阿根廷 vs 法国的比分和关键事件",
        home_team="阿根廷",
        away_team="法国",
    )

    assert len(result["scenario_cases"]) == 9
    assert {space["space_key"] for space in result["scenario_spaces"]} == {
        "baseline",
        "home_upside",
        "away_upside",
        "home_error",
        "away_error",
        "volatility",
    }
    assert {event["event_type"] for event in result["match_events"]}.issubset(MATCH_EVENT_TYPES)
    assert all("POST" not in event["event_type"] for event in result["match_events"])


def test_legacy_public_opinion_domain_is_rejected():
    with pytest.raises(ValueError, match="Unsupported simulation_domain"):
        normalize_simulation_domain("public_opinion")

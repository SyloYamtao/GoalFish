from __future__ import annotations

from app.services.analyst_notes_writer import AnalystNotesWriter
from app.services.llm_budget import LLMCallLedger, LLMBudgetProfile
from app.services.match_simulator import Event, SimulationResult, Trajectory


class FakeJsonLLM:
    def __init__(self, replies: list[dict] | None = None):
        self.replies = list(replies or [])
        self.calls = []

    def chat_json(self, **kwargs):
        self.calls.append(kwargs)
        if self.replies:
            return self.replies.pop(0)
        return {
            "role": "event_simulation",
            "claim": "基准空间更接近低比分走势。",
            "reasoning": "模态轨迹与 WDL 分布均支持保守判断。",
            "confidence": 72,
            "evidence_refs": [{"type": "scenario_space", "id": "baseline"}],
        }


def _budget(*, groups: list[str]) -> LLMBudgetProfile:
    return LLMBudgetProfile.from_dict(
        {
            "profile_key": "custom",
            "overrides": {
                "analyst_note_groups": groups,
                "hard_cap_calls": 20,
            },
        }
    )


def _scenario(scenario_key: str, scenario_space: str, weight: int) -> dict:
    return {
        "scenario_key": scenario_key,
        "scenario_name": scenario_key,
        "scenario_space": scenario_space,
        "final_weight": weight,
        "expected_goals": {"home": 1.2, "away": 0.9},
        "key_drivers": ["节奏稳定"],
        "risk_factors": ["早进球"],
    }


def _sim(score: tuple[int, int] = (1, 0)) -> SimulationResult:
    trajectory = Trajectory(
        events=[Event(minute=34, type="GOAL", side="home", actor_player=None, score_after=score)],
        final_score={"home": score[0], "away": score[1]},
        knockout_winner=None,
        knockout_path=None,
    )
    return SimulationResult(
        trajectories=[trajectory],
        scoreline_distribution=[{"score": f"{score[0]}-{score[1]}", "probability": 0.42}],
        wdl={"home": 0.48, "draw": 0.29, "away": 0.23},
        total_goals_dist={"0-1": 0.25, "2-3": 0.55, "4+": 0.2},
        modal_trajectory=trajectory,
        knockout_path_distribution=None,
        sim_seed=7,
        n_sims=500,
    )


def test_analyst_notes_filtered_by_groups():
    cases = [
        _scenario("home_normal_away_normal", "baseline", 22),
        _scenario("home_overperform_away_normal", "home_upside", 13),
    ]
    sim_results = {case["scenario_key"]: _sim() for case in cases}
    budget = _budget(groups=["baseline"])
    ledger = LLMCallLedger(config_id="cfg", budget=budget)
    writer = AnalystNotesWriter(budget=budget, ledger=ledger, llm_client=FakeJsonLLM())

    notes = writer.write_notes(scenario_cases=cases, sim_results=sim_results, config={"data_sufficiency": "ok"})

    assert [note["scenario_space"] for note in notes] == ["baseline"]
    assert ledger.summary()["by_role"]["analyst_notes"]["calls"] == 1


def test_analyst_notes_cite_evidence_refs():
    llm = FakeJsonLLM(
        [
            {
                "role": "data",
                "claim": "baseline 有稳定样本支撑。",
                "reasoning": "比分分布集中。",
                "confidence": 80,
            }
        ]
    )
    cases = [_scenario("home_normal_away_normal", "baseline", 22)]
    budget = _budget(groups=["baseline"])
    writer = AnalystNotesWriter(
        budget=budget,
        ledger=LLMCallLedger(config_id="cfg", budget=budget),
        llm_client=llm,
    )

    notes = writer.write_notes(
        scenario_cases=cases,
        sim_results={"home_normal_away_normal": _sim()},
        config={"data_sufficiency": "ok"},
    )

    assert notes[0]["evidence_refs"] == [
        {"type": "scenario_space", "id": "baseline"},
        {"type": "simulation_result", "scenario_key": "home_normal_away_normal"},
    ]

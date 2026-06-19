from __future__ import annotations

from app.services.coach_review_writer import CoachReviewWriter
from app.services.llm_budget import LLMCallLedger, LLMBudgetProfile
from app.services.match_simulator import Event, SimulationResult, Trajectory
from app.services.team_strength_estimator import TeamStrength


class FakeJsonLLM:
    def __init__(self, replies: list[dict] | None = None):
        self.replies = list(replies or [])
        self.calls = []

    def chat_json(self, **kwargs):
        self.calls.append(kwargs)
        if self.replies:
            return self.replies.pop(0)
        return {
            "verdict": "support",
            "rationale": "模态轨迹与赛前权重一致。",
            "confidence": 76,
            "evidence_refs": [{"type": "modal_trajectory"}],
        }


def _budget(*, roles: list[str]) -> LLMBudgetProfile:
    return LLMBudgetProfile.from_dict(
        {
            "profile_key": "custom",
            "overrides": {
                "coach_review_roles": roles,
                "hard_cap_calls": 20,
            },
        }
    )


def _scenario(scenario_key: str, scenario_space: str = "baseline") -> dict:
    return {
        "scenario_key": scenario_key,
        "scenario_name": scenario_key,
        "scenario_space": scenario_space,
        "final_weight": 22,
        "key_drivers": ["稳态节奏"],
        "risk_factors": ["早进球"],
        "expected_goals": {"home": 1.3, "away": 1.0},
    }


def _sim() -> SimulationResult:
    trajectory = Trajectory(
        events=[
            Event(minute=20, type="SHOT", side="home", actor_player=None),
            Event(minute=61, type="GOAL", side="away", actor_player=None, score_after=(0, 1)),
        ],
        final_score={"home": 0, "away": 1},
        knockout_winner=None,
        knockout_path=None,
    )
    return SimulationResult(
        trajectories=[trajectory],
        scoreline_distribution=[{"score": "0-1", "probability": 0.31}],
        wdl={"home": 0.34, "draw": 0.3, "away": 0.36},
        total_goals_dist={"0-1": 0.3, "2-3": 0.5, "4+": 0.2},
        modal_trajectory=trajectory,
        knockout_path_distribution=None,
        sim_seed=11,
        n_sims=500,
    )


def _strength(role: str) -> TeamStrength:
    return TeamStrength(
        team_role=role,
        team_iso3=role.upper(),
        team_name=f"{role} team",
        attack_rating=75,
        defense_rating=72,
        possession_rating=73,
        transition_rating=70,
        set_piece_rating=68,
        discipline_rating=None,
        fitness_rating=None,
        goalkeeper_rating=74,
        home_away_adjustment=0.0,
        home_away_adjustment_reason="neutral",
        injury_adjustment=0,
        injury_evidence_refs=[],
        form_adjustment=0,
        form_evidence_refs=[],
        confidence=80,
        evidence_breakdown={},
        metadata={},
    )


def test_coach_review_subset_of_panel_roles():
    budget = _budget(roles=["head_coach", "risk"])
    ledger = LLMCallLedger(config_id="cfg", budget=budget)
    writer = CoachReviewWriter(
        budget=budget,
        ledger=ledger,
        llm_client=FakeJsonLLM(
            replies=[
                {
                    "verdict": "support",
                    "rationale": "主教练认可模态轨迹。",
                    "confidence": 80,
                    "evidence_refs": [{"type": "modal_trajectory"}],
                },
                {
                    "verdict": "watch",
                    "rationale": "风险教练要求观察波动。",
                    "confidence": 70,
                    "evidence_refs": [{"type": "modal_trajectory"}],
                },
            ]
        ),
    )

    review = writer.review(
        scenario_cases=[_scenario("home_normal_away_normal")],
        sim_results={"home_normal_away_normal": _sim()},
        team_strengths=(_strength("home"), _strength("away")),
    )

    assert [item["role"] for item in review["reviews"]] == ["head_coach", "risk"]
    assert review["source"] == "llm"
    assert review["support_votes"] == 1
    assert review["oppose_votes"] == 0
    assert review["abstain_votes"] == 1
    assert review["consensus_score"] == 0.75
    assert review["confidence_delta"] == 0.0
    assert ledger.summary()["by_role"]["step3_review_head_coach"]["calls"] == 1
    assert ledger.summary()["by_role"]["step3_review_risk"]["calls"] == 1


def test_coach_review_consensus_uses_review_verdicts():
    budget = _budget(roles=["head_coach", "attack", "risk"])
    ledger = LLMCallLedger(config_id="cfg", budget=budget)
    writer = CoachReviewWriter(
        budget=budget,
        ledger=ledger,
        llm_client=FakeJsonLLM(
            replies=[
                {"verdict": "support", "rationale": "认可", "confidence": 80},
                {"verdict": "adjust", "rationale": "小修", "confidence": 72},
                {"verdict": "reject", "rationale": "反对", "confidence": 65},
            ]
        ),
    )

    review = writer.review(
        scenario_cases=[_scenario("home_normal_away_normal")],
        sim_results={"home_normal_away_normal": _sim()},
        team_strengths=(_strength("home"), _strength("away")),
    )

    assert review["support_votes"] == 1
    assert review["oppose_votes"] == 1
    assert review["abstain_votes"] == 1
    assert review["consensus_score"] == 0.5
    assert review["confidence_delta"] == -0.04


def test_review_fallback_when_zero_roles():
    budget = _budget(roles=[])
    ledger = LLMCallLedger(config_id="cfg", budget=budget)
    writer = CoachReviewWriter(budget=budget, ledger=ledger, llm_client=FakeJsonLLM())

    review = writer.review(
        scenario_cases=[_scenario("home_normal_away_normal")],
        sim_results={"home_normal_away_normal": _sim()},
        team_strengths=(_strength("home"), _strength("away")),
    )

    assert review["source"] == "coach_review_fallback_v1"
    assert review["roles"] == []
    assert review["reviews"][0]["verdict"] in {"support", "watch"}
    assert review["consensus_score"] in {0.5, 1.0}
    assert review["support_votes"] + review["oppose_votes"] + review["abstain_votes"] == 1
    assert ledger.summary()["total_calls"] == 0

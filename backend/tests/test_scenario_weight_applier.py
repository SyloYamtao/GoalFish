from __future__ import annotations

from types import SimpleNamespace

from app.services.coach_jury import SCENARIO_TEMPLATE
from app.services.coach_llm_panel import CoachVerdict
from app.services.scenario_weight_applier import ScenarioWeightApplier


def _verdict(
    role: str,
    *,
    vote: str = "support",
    default_delta: int = 0,
    deltas: dict[str, int] | None = None,
    rationale: str | None = None,
) -> CoachVerdict:
    deltas = deltas or {}
    scenario_votes = []
    for scenario in SCENARIO_TEMPLATE:
        scenario_key = scenario["scenario_key"]
        delta = deltas.get(scenario_key, default_delta)
        scenario_votes.append(
            {
                "scenario_key": scenario_key,
                "vote": vote if delta else "support",
                "weight_delta_pct": delta,
                "rationale": rationale or f"{role} rationale for {scenario_key}",
                "evidence_refs": [{"type": "unit_test"}],
            }
        )
    return CoachVerdict(
        role=role,
        scenario_votes=scenario_votes,
        team_xg_micro_adjustment={"home": 0.0, "away": 0.0, "rationale": "none"},
        wld_pp_adjustment=None,
        confidence_delta=0.0,
        summary=f"{role} summary",
    )


def _apply(verdicts: list[CoachVerdict]):
    return ScenarioWeightApplier().apply(
        template=list(SCENARIO_TEMPLATE),
        verdicts=verdicts,
        fit_artifacts=SimpleNamespace(fit_status="uniform"),
        team_strengths=(None, None),
    )


def test_weights_sum_to_100():
    cases = _apply([_verdict("head_coach")])

    assert sum(case.final_weight for case in cases) == 100
    assert len(cases) == 9


def test_no_change_when_all_support():
    cases = _apply(
        [
            _verdict("head_coach"),
            _verdict("attack"),
            _verdict("defense"),
            _verdict("transition"),
            _verdict("set_piece"),
            _verdict("goalkeeper"),
            _verdict("fitness"),
            _verdict("risk"),
        ]
    )

    assert [case.final_weight for case in cases] == [scenario["initial_weight"] for scenario in SCENARIO_TEMPLATE]


def test_clip_to_pm_30():
    target = SCENARIO_TEMPLATE[0]["scenario_key"]

    cases = _apply([_verdict("head_coach", vote="adjust", deltas={target: 50})])

    target_case = next(case for case in cases if case.scenario_key == target)
    assert target_case.coach_vote_summary["applied_delta_pct"] == 30
    assert target_case.coach_vote_summary["pre_normalization_weight"] == 29


def test_renormalization_after_adjustment():
    target = SCENARIO_TEMPLATE[0]["scenario_key"]

    cases = _apply([_verdict("head_coach", vote="adjust", deltas={target: 30})])

    target_case = next(case for case in cases if case.scenario_key == target)
    other_cases = [case for case in cases if case.scenario_key != target]
    assert target_case.final_weight > target_case.initial_weight
    assert any(case.final_weight < case.initial_weight for case in other_cases)
    assert sum(case.final_weight for case in cases) == 100


def test_vote_summary_contributors():
    target = SCENARIO_TEMPLATE[1]["scenario_key"]
    rationale = "role-specific tactical rationale"

    cases = _apply([_verdict("attack", vote="adjust", deltas={target: 12}, rationale=rationale)])

    target_case = next(case for case in cases if case.scenario_key == target)
    assert target_case.coach_vote_summary["contributors"] == [
        {
            "role": "attack",
            "vote": "adjust",
            "weight_delta_pct": 12,
            "weight": 1.0,
            "rationale": rationale,
        }
    ]


def test_applied_delta_pct_recorded():
    target = SCENARIO_TEMPLATE[2]["scenario_key"]

    cases = _apply(
        [
            _verdict("attack", vote="adjust", deltas={target: 20}),
            _verdict("defense", vote="adjust", deltas={target: -10}),
        ]
    )

    target_case = next(case for case in cases if case.scenario_key == target)
    assert target_case.coach_vote_summary["applied_delta_pct"] == 5

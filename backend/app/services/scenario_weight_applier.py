"""Apply coach verdict deltas to the fixed nine-scenario weight template."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .coach_jury import SCENARIO_TEMPLATE
from .coach_llm_panel import CoachVerdict

if TYPE_CHECKING:
    from .football_goal_model import FitArtifacts
    from .team_strength_estimator import TeamStrength


ROLE_WEIGHT = {
    "head_coach": 20,
    "attack": 15,
    "defense": 15,
    "transition": 10,
    "set_piece": 10,
    "goalkeeper": 10,
    "fitness": 10,
    "risk": 10,
}

MAX_ADJUSTMENT_PCT = 30


@dataclass(frozen=True)
class ScenarioWeighted:
    scenario_key: str
    scenario_name: str
    scenario_space: str
    initial_weight: int
    final_weight: int
    home_state: str
    away_state: str
    coach_vote_summary: dict[str, Any]
    key_drivers: list[str]
    risk_factors: list[str]


class ScenarioWeightApplier:
    """Aggregate role verdicts into final scenario weights."""

    def apply(
        self,
        *,
        template: Sequence[Mapping[str, Any]] = SCENARIO_TEMPLATE,
        verdicts: Sequence[CoachVerdict],
        fit_artifacts: FitArtifacts | Any = None,
        team_strengths: tuple[TeamStrength, TeamStrength] | Any = None,
    ) -> list[ScenarioWeighted]:
        del fit_artifacts, team_strengths

        cases: list[dict[str, Any]] = []
        role_weights = _role_weights(verdicts)
        total_role_weight = sum(role_weights.values()) or 1

        for tpl in template:
            scenario_key = str(tpl.get("scenario_key") or "")
            initial = _as_int(tpl.get("initial_weight"), default=0)
            weighted_delta = 0.0
            contributors = []

            for verdict in verdicts:
                role = str(getattr(verdict, "role", "") or "")
                role_weight = role_weights.get(role, 0)
                if role_weight <= 0:
                    continue
                contribution_weight = role_weight / total_role_weight

                for vote in getattr(verdict, "scenario_votes", []) or []:
                    if not isinstance(vote, Mapping) or str(vote.get("scenario_key") or "") != scenario_key:
                        continue
                    delta = _as_float(vote.get("weight_delta_pct"), default=0.0)
                    weighted_delta += contribution_weight * delta
                    contributors.append(
                        {
                            "role": role,
                            "vote": str(vote.get("vote") or ""),
                            "weight_delta_pct": _clean_number(delta),
                            "weight": contribution_weight,
                            "rationale": str(vote.get("rationale") or "")[:200],
                        }
                    )

            applied_delta_pct = _clip(weighted_delta, -MAX_ADJUSTMENT_PCT, MAX_ADJUSTMENT_PCT)
            pre_normalization_weight = _bounded_adjusted_weight(initial, applied_delta_pct)
            cases.append(
                {
                    **dict(tpl),
                    "initial_weight": initial,
                    "pre_normalization_weight": pre_normalization_weight,
                    "coach_vote_summary": {
                        "applied_delta_pct": _clean_number(applied_delta_pct),
                        "max_adjustment_pct": MAX_ADJUSTMENT_PCT,
                        "max_weight_adjustment_pct": MAX_ADJUSTMENT_PCT,
                        "applied_weight_delta": pre_normalization_weight - initial,
                        "pre_normalization_weight": pre_normalization_weight,
                        "pre_normalization_weight_delta": pre_normalization_weight - initial,
                        "contributors": contributors,
                        "support_votes": sum(1 for c in contributors if c["vote"] == "support"),
                        "oppose_votes": sum(1 for c in contributors if c["vote"] == "oppose"),
                        "adjust_votes": sum(1 for c in contributors if c["vote"] == "adjust"),
                    },
                }
            )

        normalized_weights = _normalize_to_100([case["pre_normalization_weight"] for case in cases])
        return [_to_weighted(case, final_weight) for case, final_weight in zip(cases, normalized_weights, strict=True)]


def _role_weights(verdicts: Sequence[CoachVerdict]) -> dict[str, int]:
    weights = {}
    for verdict in verdicts:
        role = str(getattr(verdict, "role", "") or "")
        if role in ROLE_WEIGHT:
            weights[role] = ROLE_WEIGHT[role]
    return weights


def _bounded_adjusted_weight(initial: int, delta_pct: float) -> int:
    lower = round(initial * 0.7)
    upper = round(initial * 1.3)
    adjusted = round(initial * (1 + delta_pct / 100))
    return max(lower, min(upper, adjusted))


def _normalize_to_100(weights: list[int]) -> list[int]:
    if not weights:
        return []
    total = sum(weights) or 1
    normalized = [round(weight * 100 / total) for weight in weights]
    diff = 100 - sum(normalized)
    if diff:
        largest_index = max(range(len(normalized)), key=lambda index: normalized[index])
        normalized[largest_index] += diff
    return normalized


def _to_weighted(case: Mapping[str, Any], final_weight: int) -> ScenarioWeighted:
    initial = _as_int(case.get("initial_weight"), default=0)
    summary = dict(case.get("coach_vote_summary") or {})
    summary["final_weight_delta"] = final_weight - initial
    summary["normalization_factor"] = _clean_number(
        final_weight / case["pre_normalization_weight"] if case["pre_normalization_weight"] else 0.0
    )
    return ScenarioWeighted(
        scenario_key=str(case.get("scenario_key") or ""),
        scenario_name=str(case.get("scenario_name") or ""),
        scenario_space=str(case.get("scenario_space") or ""),
        initial_weight=initial,
        final_weight=final_weight,
        home_state=str(case.get("home_state") or ""),
        away_state=str(case.get("away_state") or ""),
        coach_vote_summary=summary,
        key_drivers=list(case.get("key_drivers") or []),
        risk_factors=list(case.get("risk_factors") or []),
    )


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _as_float(value: Any, *, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, *, default: int) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _clean_number(value: float) -> int | float:
    if float(value).is_integer():
        return int(value)
    return round(float(value), 6)

"""Team strength estimation from roster snapshots and graph facts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .roster_loader import PlayerSnapshot, TeamRoster, apply_graph_facts


ATTACK_WEIGHT_BY_POS = {
    "ST": 1.00,
    "WG": 0.85,
    "AM": 0.65,
    "CM": 0.35,
    "DM": 0.15,
    "FB": 0.20,
    "CB": 0.05,
    "GK": 0.00,
}
DEFENSE_WEIGHT_BY_POS = {
    "GK": 0.10,
    "CB": 1.00,
    "FB": 0.85,
    "DM": 0.75,
    "CM": 0.45,
    "AM": 0.20,
    "WG": 0.15,
    "ST": 0.05,
}
GK_WEIGHT_BY_POS = {
    "GK": 1.00,
    "CB": 0.0,
    "FB": 0.0,
    "DM": 0.0,
    "CM": 0.0,
    "AM": 0.0,
    "WG": 0.0,
    "ST": 0.0,
}
PACE_WEIGHT_BY_POS = {
    "WG": 1.0,
    "FB": 0.7,
    "ST": 0.6,
    "AM": 0.5,
    "CM": 0.4,
    "DM": 0.3,
    "CB": 0.3,
    "GK": 0.0,
}
FINISHING_WEIGHT_BY_POS = {
    "ST": 1.0,
    "WG": 0.7,
    "AM": 0.5,
    "CM": 0.2,
    "DM": 0.1,
    "FB": 0.05,
    "CB": 0.02,
    "GK": 0.0,
}
PASSING_WEIGHT_BY_POS = {
    "CM": 1.0,
    "AM": 0.9,
    "DM": 0.85,
    "FB": 0.7,
    "WG": 0.6,
    "CB": 0.5,
    "ST": 0.4,
    "GK": 0.3,
}

ALPHA_BY_FIT = {
    "fitted": 0.40,
    "bayesian_hierarchical": 0.55,
    "elo_prior": 0.70,
    "uniform": 0.95,
}


@dataclass
class TeamStrength:
    team_role: str
    team_iso3: str
    team_name: str
    attack_rating: int
    defense_rating: int
    possession_rating: int
    transition_rating: int
    set_piece_rating: int
    discipline_rating: int | None
    fitness_rating: int | None
    goalkeeper_rating: int
    home_away_adjustment: float
    home_away_adjustment_reason: str
    injury_adjustment: int
    injury_evidence_refs: list[dict]
    form_adjustment: int
    form_evidence_refs: list[dict]
    confidence: int
    evidence_breakdown: dict
    metadata: dict

    def to_dict(self) -> dict:
        return {
            "team_role": self.team_role,
            "team_iso3": self.team_iso3,
            "team_name": self.team_name,
            "attack_rating": self.attack_rating,
            "defense_rating": self.defense_rating,
            "possession_rating": self.possession_rating,
            "transition_rating": self.transition_rating,
            "set_piece_rating": self.set_piece_rating,
            "discipline_rating": self.discipline_rating,
            "fitness_rating": self.fitness_rating,
            "goalkeeper_rating": self.goalkeeper_rating,
            "home_away_adjustment": self.home_away_adjustment,
            "home_away_adjustment_reason": self.home_away_adjustment_reason,
            "injury_adjustment": self.injury_adjustment,
            "injury_evidence_refs": self.injury_evidence_refs,
            "form_adjustment": self.form_adjustment,
            "form_evidence_refs": self.form_evidence_refs,
            "confidence": self.confidence,
            "evidence_breakdown": self.evidence_breakdown,
            "metadata": self.metadata,
        }


class TeamStrengthEstimator:
    """Estimate 8-dimension team strength per spec 03 §3.6 and 05 §5.4."""

    def estimate_pair(
        self,
        *,
        home_roster: TeamRoster,
        away_roster: TeamRoster,
        fit_artifacts: Any = None,
        graph_facts: Any = None,
        competition_meta: dict | None = None,
        external_pool: Any = None,
    ) -> tuple[TeamStrength, TeamStrength]:
        del external_pool
        competition_meta = competition_meta or {}
        host_iso3 = _normalize_iso3(competition_meta.get("host_country_iso3") or "")
        return (
            self._estimate_one(
                role="home",
                roster=home_roster,
                fit_artifacts=fit_artifacts,
                graph_facts=graph_facts,
                competition_meta=competition_meta,
                is_host=home_roster.iso3 == host_iso3,
            ),
            self._estimate_one(
                role="away",
                roster=away_roster,
                fit_artifacts=fit_artifacts,
                graph_facts=graph_facts,
                competition_meta=competition_meta,
                is_host=away_roster.iso3 == host_iso3,
            ),
        )

    def _estimate_one(
        self,
        *,
        role: str,
        roster: TeamRoster,
        fit_artifacts: Any,
        graph_facts: Any,
        competition_meta: dict,
        is_host: bool,
    ) -> TeamStrength:
        apply_graph_facts(roster, graph_facts)

        fit_status = _fit_status(fit_artifacts)
        alpha = ALPHA_BY_FIT.get(fit_status, ALPHA_BY_FIT["uniform"])

        attack_player_score, attack_contributors = _pos_weighted_mean(roster.players, "attack", ATTACK_WEIGHT_BY_POS)
        defense_player_score, defense_contributors = _pos_weighted_mean(roster.players, "defense", DEFENSE_WEIGHT_BY_POS)
        pace_player_score, pace_contributors = _pos_weighted_mean(roster.players, "pace", PACE_WEIGHT_BY_POS)
        finishing_player_score, finishing_contributors = _pos_weighted_mean(
            roster.players, "finishing", FINISHING_WEIGHT_BY_POS
        )
        passing_player_score, passing_contributors = _pos_weighted_mean(roster.players, "passing", PASSING_WEIGHT_BY_POS)
        gk_player_score, gk_contributors = _pos_weighted_mean(roster.players, "gk", GK_WEIGHT_BY_POS)
        set_piece_player_score, set_piece_contributors = _max_topn(roster.players, "set_piece", n=3)

        attack_model_score = _model_score(_coef_for(fit_artifacts, "attack_coef", roster.iso3))
        defense_model_score = _defense_model_score(_coef_for(fit_artifacts, "defense_coef", roster.iso3))
        attack_rating = blend(alpha, attack_player_score, _coef_for(fit_artifacts, "attack_coef", roster.iso3))
        defense_rating = blend(alpha, defense_player_score, _defense_coef_for_rating(fit_artifacts, roster.iso3))
        possession_rating = _clip_int(round((attack_rating + defense_rating) / 2))
        transition_rating = _clip_int(round((pace_player_score + finishing_player_score) / 2))
        set_piece_rating = _clip_int(round(set_piece_player_score))
        goalkeeper_rating = _clip_int(round(gk_player_score))

        injury_adjustment, injury_refs = _compute_injury_adjustment(roster)
        form_adjustment, form_refs = _compute_form_adjustment(graph_facts, roster.iso3)
        home_adjustment, home_reason = _home_away_adjustment(roster, role, competition_meta, is_host)
        confidence = compute_confidence(roster, fit_artifacts, graph_facts, roster.iso3)

        evidence_breakdown = {
            "attack": _rating_evidence(
                alpha=alpha,
                player_score=attack_player_score,
                model_score=attack_model_score,
                blended=attack_rating,
                top_contributors=attack_contributors,
            ),
            "defense": _rating_evidence(
                alpha=alpha,
                player_score=defense_player_score,
                model_score=defense_model_score,
                blended=defense_rating,
                top_contributors=defense_contributors,
            ),
            "pace": _player_evidence(pace_player_score, pace_contributors),
            "finishing": _player_evidence(finishing_player_score, finishing_contributors),
            "passing": _player_evidence(passing_player_score, passing_contributors),
            "possession": _player_evidence((attack_player_score + defense_player_score) / 2, passing_contributors),
            "transition": _player_evidence((pace_player_score + finishing_player_score) / 2, pace_contributors),
            "set_piece": _player_evidence(set_piece_player_score, set_piece_contributors),
            "goalkeeper": _player_evidence(gk_player_score, gk_contributors),
            "injury_adjustment": {
                "value": injury_adjustment,
                "evidence_refs": injury_refs,
            },
            "form_adjustment": {
                "value": form_adjustment,
                "evidence_refs": form_refs,
            },
        }

        return TeamStrength(
            team_role=role,
            team_iso3=roster.iso3,
            team_name=roster.team_fifa,
            attack_rating=attack_rating,
            defense_rating=defense_rating,
            possession_rating=possession_rating,
            transition_rating=transition_rating,
            set_piece_rating=set_piece_rating,
            discipline_rating=None,
            fitness_rating=None,
            goalkeeper_rating=goalkeeper_rating,
            home_away_adjustment=home_adjustment,
            home_away_adjustment_reason=home_reason,
            injury_adjustment=injury_adjustment,
            injury_evidence_refs=injury_refs,
            form_adjustment=form_adjustment,
            form_evidence_refs=form_refs,
            confidence=confidence,
            evidence_breakdown=evidence_breakdown,
            metadata={
                "fit_status": fit_status,
                "players_count": len(roster.players),
                "available_players_count": sum(1 for player in roster.players if player.is_available),
                "available_minutes_share": _available_share(roster),
            },
        )


def blend(alpha: float, player_score: float, model_coef: float | None) -> int:
    """
    Blend player aggregate with fitted coefficient score.

    When no model coefficient exists, the player aggregate is returned unchanged.
    """

    if model_coef is None:
        return _clip_int(round(player_score))
    coef_score = _model_score(model_coef)
    return _clip_int(round(alpha * coef_score + (1 - alpha) * player_score))


def compute_confidence(roster: TeamRoster, fit_artifacts: Any, graph_facts: Any, team_iso3: str) -> int:
    available_share = _available_share(roster)
    fit_bonus = {
        "fitted": 15,
        "bayesian_hierarchical": 10,
        "elo_prior": 5,
        "uniform": 0,
    }.get(_fit_status(fit_artifacts), 0)
    graph_bonus = 5 if graph_facts is not None and _has_facts_for_team(graph_facts, team_iso3) else 0
    return int(_clip(60 + 20 * available_share + fit_bonus + graph_bonus, 40, 95))


def _pos_weighted_mean(players: list[PlayerSnapshot], key: str, position_weights: dict[str, float]) -> tuple[float, list[dict]]:
    contributions = _weighted_contributions(players, key, position_weights)
    total_weight = sum(item["weight"] for item in contributions)
    if total_weight <= 0:
        return 50.0, _top_contributors(contributions, fallback_players=players, key=key)
    score = sum(item["weighted_rating"] for item in contributions) / total_weight
    return score, _top_contributors(contributions, fallback_players=players, key=key)


def _max_topn(players: list[PlayerSnapshot], key: str, n: int = 3) -> tuple[float, list[dict]]:
    ranked = sorted(
        (player for player in players if player.is_available and _rating(player, key) is not None),
        key=lambda player: _rating(player, key) or 0,
        reverse=True,
    )
    top = ranked[:n]
    if not top:
        return 50.0, _top_contributors([], fallback_players=players, key=key)
    max_score = float(_rating(top[0], key) or 0)
    total = sum(float(_rating(player, key) or 0) for player in top) or 1.0
    contributors = [
        {
            "player_id": player.id,
            "name": player.name_en or player.name,
            "contribution_pct": round(float(_rating(player, key) or 0) / total * 100, 1),
            "rating": round(float(_rating(player, key) or 0)),
            "position": player.position_primary,
        }
        for player in top
    ]
    return max_score, _pad_contributors(contributors, players, key)


def _weighted_contributions(players: list[PlayerSnapshot], key: str, position_weights: dict[str, float]) -> list[dict]:
    contributions: list[dict] = []
    for player in players:
        rating = _rating(player, key)
        position_weight = float(position_weights.get(player.position_primary, 0.0))
        if rating is None or position_weight <= 0:
            continue
        weight = _effective_minutes_share(player) * position_weight
        contributions.append(
            {
                "player": player,
                "rating": float(rating),
                "weight": weight,
                "weighted_rating": float(rating) * weight,
            }
        )
    return contributions


def _top_contributors(contributions: list[dict], *, fallback_players: list[PlayerSnapshot], key: str) -> list[dict]:
    total = sum(item["weighted_rating"] for item in contributions)
    ranked = sorted(contributions, key=lambda item: item["weighted_rating"], reverse=True)
    top = []
    for item in ranked[:3]:
        player = item["player"]
        pct = item["weighted_rating"] / total * 100 if total > 0 else 0.0
        top.append(
            {
                "player_id": player.id,
                "name": player.name_en or player.name,
                "contribution_pct": round(pct, 1),
                "rating": round(item["rating"]),
                "position": player.position_primary,
            }
        )
    return _pad_contributors(top, fallback_players, key)


def _pad_contributors(top: list[dict], players: list[PlayerSnapshot], key: str) -> list[dict]:
    seen = {item["player_id"] for item in top}
    ranked_players = sorted(
        (player for player in players if player.id not in seen),
        key=lambda player: float(_rating(player, key) or 0),
        reverse=True,
    )
    for player in ranked_players:
        if len(top) >= 3:
            break
        top.append(
            {
                "player_id": player.id,
                "name": player.name_en or player.name,
                "contribution_pct": 0.0,
                "rating": round(float(_rating(player, key) or 0)),
                "position": player.position_primary,
            }
        )
    return top


def _rating_evidence(
    *,
    alpha: float,
    player_score: float,
    model_score: int | None,
    blended: int,
    top_contributors: list[dict],
) -> dict:
    return {
        "source": "fitted_blend" if model_score is not None else "player",
        "alpha": alpha,
        "player_score": round(player_score),
        "model_score": model_score,
        "blended": blended,
        "top_contributors": top_contributors,
    }


def _player_evidence(player_score: float, top_contributors: list[dict]) -> dict:
    rounded = round(player_score)
    return {
        "source": "player",
        "alpha": 1.0,
        "player_score": rounded,
        "model_score": None,
        "blended": rounded,
        "top_contributors": top_contributors,
    }


def _compute_injury_adjustment(roster: TeamRoster) -> tuple[int, list[dict]]:
    refs: list[dict] = []
    penalty = 0.0
    for player in roster.players:
        status = player.availability.get("status")
        if status not in {"injured", "suspended"}:
            continue
        multiplier = 1.4 if status == "suspended" else 1.0
        penalty -= max(float(player.expected_minutes_share or 0), 0.2) * multiplier
        refs.extend(list(player.availability.get("evidence_refs") or []))

    if penalty == 0:
        return 0, []
    return int(max(round(penalty * 2.5), -5)), refs


def _compute_form_adjustment(graph_facts: Any, team_iso3: str) -> tuple[int, list[dict]]:
    if graph_facts is None:
        return 0, []
    refs = list((getattr(graph_facts, "team_recent_form", {}) or {}).get(_normalize_iso3(team_iso3), []) or [])
    if not refs:
        return 0, []

    score = 0
    for ref in refs:
        text = " ".join(str(value) for value in ref.values()).lower()
        if any(token in text for token in ("win", "胜", "positive", "good", "excellent")):
            score += 1
        if any(token in text for token in ("loss", "负", "negative", "poor", "bad")):
            score -= 1
    if score == 0:
        return 0, refs
    return int(_clip(score, -3, 5)), refs


def _home_away_adjustment(
    roster: TeamRoster,
    role: str,
    competition_meta: dict,
    is_host: bool,
) -> tuple[float, str]:
    neutral = bool(competition_meta.get("neutral_venue", True))
    if is_host:
        return 0.20, "host_country"
    if neutral:
        return 0.0, "neutral_venue"
    if role == "home":
        return 0.20, "home_team"
    return 0.0, "away_team"


def _coef_for(fit_artifacts: Any, attr: str, iso3: str) -> float | None:
    if fit_artifacts is None:
        return None
    value = getattr(fit_artifacts, attr, None)
    if isinstance(value, dict):
        coef = value.get(_normalize_iso3(iso3)) or value.get(iso3)
        return float(coef) if coef is not None else None
    model = getattr(fit_artifacts, "model", None)
    model_value = getattr(model, attr, None)
    if isinstance(model_value, dict):
        coef = model_value.get(_normalize_iso3(iso3)) or model_value.get(iso3)
        return float(coef) if coef is not None else None
    return None


def _model_score(model_coef: float | None) -> int | None:
    if model_coef is None:
        return None
    return _clip_int(round(60 + 30 * model_coef))


def _defense_model_score(model_coef: float | None) -> int | None:
    if model_coef is None:
        return None
    return _model_score(-model_coef)


def _defense_coef_for_rating(fit_artifacts: Any, iso3: str) -> float | None:
    coef = _coef_for(fit_artifacts, "defense_coef", iso3)
    return -coef if coef is not None else None


def _fit_status(fit_artifacts: Any) -> str:
    if fit_artifacts is None:
        return "uniform"
    status = getattr(fit_artifacts, "fit_status", None) or "uniform"
    if status == "hierarchical":
        return "bayesian_hierarchical"
    return status if status in ALPHA_BY_FIT else "uniform"


def _available_share(roster: TeamRoster) -> float:
    return _clip(sum(_effective_minutes_share(player) for player in roster.players if player.is_available) / 11, 0, 1)


def _effective_minutes_share(player: PlayerSnapshot) -> float:
    share = max(float(player.expected_minutes_share or 0), 0.0)
    status = player.availability.get("status")
    if status in {"injured", "suspended"}:
        return 0.0
    if status == "doubtful":
        return share * 0.5
    return share


def _has_facts_for_team(graph_facts: Any, team_iso3: str) -> bool:
    method = getattr(graph_facts, "has_facts_for_team", None)
    if callable(method):
        return bool(method(team_iso3))
    normalized = _normalize_iso3(team_iso3)
    return bool((getattr(graph_facts, "team_recent_form", {}) or {}).get(normalized))


def _rating(player: PlayerSnapshot, key: str) -> float | None:
    value = (player.derived or {}).get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clip_int(value: int) -> int:
    return int(_clip(value, 0, 100))


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _normalize_iso3(value: str) -> str:
    return (value or "").strip().upper()

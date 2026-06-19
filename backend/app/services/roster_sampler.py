"""Roster-based player sampling for match simulations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from .roster_loader import PlayerSnapshot, TeamRoster


ATTACK_FACTOR_BY_POS = {
    "ST": 1.00,
    "WG": 0.85,
    "AM": 0.65,
    "CM": 0.35,
    "DM": 0.15,
    "FB": 0.20,
    "CB": 0.05,
    "GK": 0.01,
}
CREATIVE_FACTOR_BY_POS = {
    "AM": 1.00,
    "CM": 0.90,
    "WG": 0.85,
    "FB": 0.60,
    "DM": 0.55,
    "ST": 0.45,
    "CB": 0.20,
    "GK": 0.05,
}
CARD_FACTOR_BY_POS = {
    "CB": 1.00,
    "DM": 0.90,
    "FB": 0.75,
    "CM": 0.55,
    "AM": 0.35,
    "WG": 0.25,
    "ST": 0.20,
    "GK": 0.08,
}
ROLE_PRIORITY = {"starter": 0, "bench": 1, "rotation": 2, "reserve": 3}
MAX_SUBSTITUTIONS = 5


class RosterSampler:
    """Sample players from the current on-field XI for simulation events."""

    def __init__(self, home: TeamRoster, away: TeamRoster):
        self._rosters = {"home": home, "away": away}
        self._on_field = {
            "home": self._initial_xi(home),
            "away": self._initial_xi(away),
        }
        self._bench = {
            side: self._available_bench(roster, self._on_field[side])
            for side, roster in self._rosters.items()
        }
        self._sub_counts = {"home": 0, "away": 0}

    def on_field(self, side: str) -> tuple[PlayerSnapshot, ...]:
        """Return the current on-field players for tests and downstream callers."""

        return tuple(self._on_field[_normalize_side(side)])

    def sample_goal_actor(self, side: str, rng: np.random.Generator) -> PlayerSnapshot:
        """Sample a scorer by finishing rating and attacking position factor."""

        side = _normalize_side(side)
        players = self._on_field[side] or self._initial_xi(self._rosters[side])
        weights = [
            max(
                _rating(player, "finishing", 60.0)
                * _position_factor(player, ATTACK_FACTOR_BY_POS)
                * max(float(player.expected_minutes_share or 0.2), 0.2),
                1e-3,
            )
            for player in players
        ]
        return _weighted_choice(players, weights, rng)

    def sample_assist(
        self,
        side: str,
        scorer: PlayerSnapshot,
        rng: np.random.Generator,
    ) -> PlayerSnapshot | None:
        """Sample an assister, with 30% probability of an unassisted goal."""

        side = _normalize_side(side)
        if rng.random() < 0.30:
            return None
        candidates = [player for player in self._on_field[side] if player.id != scorer.id]
        if not candidates:
            return None
        weights = [
            max(
                _rating(player, "passing", 60.0)
                * _position_factor(player, CREATIVE_FACTOR_BY_POS)
                * max(float(player.expected_minutes_share or 0.2), 0.2),
                1e-3,
            )
            for player in candidates
        ]
        return _weighted_choice(candidates, weights, rng)

    def sample_card(self, side: str, rng: np.random.Generator) -> tuple[PlayerSnapshot, str]:
        """Sample a booked player and card color from the current XI."""

        side = _normalize_side(side)
        players = self._on_field[side] or self._initial_xi(self._rosters[side])
        weights = [
            max((100.0 - _rating(player, "discipline", 70.0)) * _position_factor(player, CARD_FACTOR_BY_POS), 1e-3)
            for player in players
        ]
        player = _weighted_choice(players, weights, rng)
        color = "red" if rng.random() < 0.05 else "yellow"
        return player, color

    def apply_substitution(
        self,
        side: str,
        minute: int,
        rng: np.random.Generator,
    ) -> tuple[PlayerSnapshot, PlayerSnapshot] | None:
        """Apply one deterministic substitution window update, returning `(out, in)`."""

        del minute
        side = _normalize_side(side)
        if self._sub_counts[side] >= MAX_SUBSTITUTIONS or not self._bench[side]:
            return None

        incoming = self._bench[side].pop(0)
        outgoing = self._choose_outgoing(side, incoming, rng)
        if outgoing is None:
            self._bench[side].insert(0, incoming)
            return None

        self._on_field[side] = [player for player in self._on_field[side] if player.id != outgoing.id]
        self._on_field[side].append(incoming)
        self._sub_counts[side] += 1
        return outgoing, incoming

    def sample_pso_takers(self, side: str, n: int = 5) -> list[PlayerSnapshot]:
        """Return penalty takers sorted by set-piece rating."""

        side = _normalize_side(side)
        candidates = sorted(
            self._on_field[side],
            key=lambda player: (
                _rating(player, "set_piece", 50.0),
                _rating(player, "finishing", 50.0),
                player.expected_minutes_share,
                player.name,
            ),
            reverse=True,
        )
        return candidates[: max(int(n), 0)]

    def _initial_xi(self, roster: TeamRoster) -> list[PlayerSnapshot]:
        available = [player for player in roster.players if player.is_available]
        starters = [player for player in roster.starters if player.is_available]
        if len(starters) >= 11:
            return starters[:11]

        selected = list(starters)
        selected_ids = {player.id for player in selected}
        pool = sorted(
            [player for player in available if player.id not in selected_ids],
            key=_roster_sort_key,
        )
        selected.extend(pool[: 11 - len(selected)])
        if selected:
            return selected[:11]
        return list(roster.players[:11])

    def _available_bench(self, roster: TeamRoster, on_field: Sequence[PlayerSnapshot]) -> list[PlayerSnapshot]:
        on_field_ids = {player.id for player in on_field}
        return sorted(
            [player for player in roster.players if player.is_available and player.id not in on_field_ids],
            key=_roster_sort_key,
        )

    def _choose_outgoing(
        self,
        side: str,
        incoming: PlayerSnapshot,
        rng: np.random.Generator,
    ) -> PlayerSnapshot | None:
        on_field = self._on_field[side]
        same_class = [
            player
            for player in on_field
            if player.position_class == incoming.position_class and player.position_primary != "GK"
        ]
        candidates = same_class or [player for player in on_field if player.position_primary != "GK"] or list(on_field)
        if not candidates:
            return None

        weights = []
        for player in candidates:
            fatigue = max(1.05 - float(player.expected_minutes_share or 0.5), 0.05)
            weights.append(fatigue)
        return _weighted_choice(candidates, weights, rng)


def _normalize_side(side: str) -> str:
    if side not in {"home", "away"}:
        raise ValueError(f"side must be 'home' or 'away', got {side!r}")
    return side


def _rating(player: PlayerSnapshot, key: str, default: float) -> float:
    value = (player.derived or {}).get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _position_factor(player: PlayerSnapshot, mapping: dict[str, float]) -> float:
    if player.position_primary in mapping:
        return mapping[player.position_primary]
    if player.position_class == "FW":
        return mapping.get("ST", 1.0)
    if player.position_class == "MF":
        return mapping.get("CM", 0.5)
    if player.position_class == "DF":
        return mapping.get("CB", 0.2)
    return mapping.get("GK", 0.01)


def _weighted_choice(
    players: Sequence[PlayerSnapshot],
    weights: Sequence[float],
    rng: np.random.Generator,
) -> PlayerSnapshot:
    if not players:
        raise ValueError("cannot sample from an empty player list")
    numeric = np.array([max(float(weight), 0.0) for weight in weights], dtype=float)
    if not np.isfinite(numeric).all() or numeric.sum() <= 0:
        return players[int(rng.integers(0, len(players)))]
    probabilities = numeric / numeric.sum()
    return players[int(rng.choice(len(players), p=probabilities))]


def _roster_sort_key(player: PlayerSnapshot) -> tuple[Any, ...]:
    return (
        ROLE_PRIORITY.get(player.expected_role, 9),
        -float(player.expected_minutes_share or 0.0),
        -_rating(player, "overall", 0.0),
        player.shirt_number if player.shirt_number is not None else 999,
        player.id,
    )

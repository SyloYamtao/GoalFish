"""Monte Carlo match simulator for Step3 football predictions."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

import numpy as np

from .football_goal_model import FitArtifacts
from .roster_loader import PlayerSnapshot, TeamRoster
from .roster_sampler import RosterSampler


SIM_VERSION = "v1"
INTENSITY_WEIGHTS = np.array([0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.13, 0.12, 0.12], dtype=float)
GOAL_EVENT_TYPES = {"GOAL", "ET_GOAL"}
SUBSTITUTION_WINDOWS = (50, 65, 75)
MINOR_EVENT_TYPES = ("SHOT", "CHANCE_CREATED", "PRESSURE_SHIFT", "SAVE")
EVENT_PRIORITY = {"GOAL": 0, "ET_GOAL": 0, "SHOT": 1, "CHANCE_CREATED": 2, "SAVE": 3, "CARD": 4, "PSO": 5}


@dataclass
class Event:
    minute: int
    type: str
    side: str
    actor_player: PlayerSnapshot | None
    assist_player: PlayerSnapshot | None = None
    score_after: tuple[int, int] | None = None
    card_color: str | None = None
    pso_scored: bool | None = None

    @property
    def actor(self) -> PlayerSnapshot | None:
        """Compatibility alias for older spec snippets."""

        return self.actor_player

    @property
    def assist(self) -> PlayerSnapshot | None:
        """Compatibility alias for older spec snippets."""

        return self.assist_player


@dataclass
class Trajectory:
    events: list[Event]
    final_score: dict
    knockout_winner: str | None
    knockout_path: str | None

    @property
    def final_score_str(self) -> str:
        return f"{self.final_score['home']}-{self.final_score['away']}"


@dataclass
class SimulationResult:
    trajectories: list[Trajectory]
    scoreline_distribution: list[dict]
    wdl: dict
    total_goals_dist: dict
    modal_trajectory: Trajectory
    knockout_path_distribution: dict | None
    sim_seed: int
    n_sims: int
    sim_version: str = SIM_VERSION


class MatchSimulator:
    """Run inhomogeneous Poisson match simulations from scenario xG values."""

    SIM_VERSION = SIM_VERSION

    def __init__(
        self,
        *,
        squads: tuple[TeamRoster, TeamRoster],
        fit_artifacts: FitArtifacts,
        competition: dict,
    ):
        self._home_roster, self._away_roster = squads
        self._fit = fit_artifacts
        self._comp = competition
        self._roster_sampler = RosterSampler(self._home_roster, self._away_roster)

    def simulate_match(
        self,
        *,
        home_xg: float,
        away_xg: float,
        n_sims: int,
        knockout: bool,
        seed: int,
    ) -> SimulationResult:
        """Run `n_sims` independent match trajectories and aggregate outcomes."""

        if n_sims <= 0:
            raise ValueError("n_sims must be positive")

        trajectories = [
            self._simulate_one(
                max(float(home_xg), 0.0),
                max(float(away_xg), 0.0),
                knockout,
                np.random.default_rng(int(seed) + index),
            )
            for index in range(n_sims)
        ]
        return SimulationResult(
            trajectories=trajectories,
            scoreline_distribution=self._aggregate_scores(trajectories),
            wdl=self._aggregate_wdl(trajectories),
            total_goals_dist=self._aggregate_total_goals(trajectories),
            modal_trajectory=self._find_modal(trajectories),
            knockout_path_distribution=self._aggregate_knockout(trajectories) if knockout else None,
            sim_seed=int(seed),
            n_sims=n_sims,
            sim_version=self.SIM_VERSION,
        )

    def _simulate_one(
        self,
        home_xg: float,
        away_xg: float,
        knockout: bool,
        rng: np.random.Generator,
    ) -> Trajectory:
        """Simulate one 90-minute match, with ET/PSO if required."""

        roster_sampler = RosterSampler(self._home_roster, self._away_roster)
        events = self._regulation_events(home_xg, away_xg, rng, roster_sampler)
        events.sort(key=_event_sort_key)
        self._annotate_goal_scores(events)

        score_90 = self._compute_score(events, up_to=90)
        if knockout and score_90["home"] == score_90["away"]:
            et_events = self._extra_time(home_xg, away_xg, rng, roster_sampler=roster_sampler)
            events.extend(et_events)
            events.sort(key=_event_sort_key)
            self._annotate_goal_scores(events)
            score_120 = self._compute_score(events, up_to=120)

            if score_120["home"] == score_120["away"]:
                pso_events = self._penalty_shootout(rng, roster_sampler=roster_sampler)
                events.extend(pso_events)
                return Trajectory(
                    events=events,
                    final_score=score_120,
                    knockout_winner=self._pso_winner(pso_events),
                    knockout_path="PSO",
                )

            winner = "home" if score_120["home"] > score_120["away"] else "away"
            return Trajectory(
                events=events,
                final_score=score_120,
                knockout_winner=winner,
                knockout_path="ET",
            )

        return Trajectory(events=events, final_score=score_90, knockout_winner=None, knockout_path=None)

    def _sample_goals(
        self,
        xg: float,
        n_minutes: int,
        rng: np.random.Generator,
    ) -> list[int]:
        """Sample goal minutes from a 10-minute segmented inhomogeneous Poisson process."""

        if xg <= 0 or n_minutes <= 0:
            return []

        n_segments = max(1, min(len(INTENSITY_WEIGHTS), (int(n_minutes) + 9) // 10))
        weights = INTENSITY_WEIGHTS[:n_segments]
        segment_intensities = max(float(xg), 0.0) * weights / weights.sum()

        goal_minutes: list[int] = []
        for seg_idx, intensity in enumerate(segment_intensities):
            seg_start = seg_idx * 10 + 1
            seg_end = min((seg_idx + 1) * 10, int(n_minutes))
            if seg_start > seg_end:
                continue
            n_goals = int(rng.poisson(float(intensity)))
            for _ in range(n_goals):
                goal_minutes.append(int(rng.integers(seg_start, seg_end + 1)))
        return sorted(goal_minutes)

    def _extra_time(
        self,
        home_xg: float,
        away_xg: float,
        rng: np.random.Generator,
        roster_sampler: RosterSampler | None = None,
    ) -> list[Event]:
        """Simulate 30 minutes of extra time at 60% regulation intensity."""

        sampler = roster_sampler or self._roster_sampler
        home_minutes = self._sample_goals(max(float(home_xg), 0.0) * (30.0 / 90.0) * 0.6, 30, rng)
        away_minutes = self._sample_goals(max(float(away_xg), 0.0) * (30.0 / 90.0) * 0.6, 30, rng)
        events: list[Event] = []
        for minute in home_minutes:
            scorer = sampler.sample_goal_actor("home", rng)
            events.append(
                Event(
                    minute=90 + minute,
                    type="ET_GOAL",
                    side="home",
                    actor_player=scorer,
                    assist_player=sampler.sample_assist("home", scorer, rng),
                )
            )
        for minute in away_minutes:
            scorer = sampler.sample_goal_actor("away", rng)
            events.append(
                Event(
                    minute=90 + minute,
                    type="ET_GOAL",
                    side="away",
                    actor_player=scorer,
                    assist_player=sampler.sample_assist("away", scorer, rng),
                )
            )
        return sorted(events, key=_event_sort_key)

    def _penalty_shootout(
        self,
        rng: np.random.Generator,
        roster_sampler: RosterSampler | None = None,
    ) -> list[Event]:
        """Simulate a 5-round penalty shootout plus sudden death."""

        sampler = roster_sampler or self._roster_sampler
        takers_home = sampler.sample_pso_takers("home", 11)
        takers_away = sampler.sample_pso_takers("away", 11)
        if not takers_home or not takers_away:
            raise ValueError("penalty shootout requires at least one taker per side")

        events: list[Event] = []
        score_home = 0
        score_away = 0

        def add_kick(side: str, taker: PlayerSnapshot) -> None:
            nonlocal score_home, score_away
            hit = bool(rng.random() < self._pso_hit_prob(taker))
            if hit and side == "home":
                score_home += 1
            elif hit:
                score_away += 1
            events.append(
                Event(
                    minute=121 + len(events),
                    type="PSO",
                    side=side,
                    actor_player=taker,
                    score_after=(score_home, score_away),
                    pso_scored=hit,
                )
            )

        for index in range(5):
            add_kick("home", takers_home[index % len(takers_home)])
            add_kick("away", takers_away[index % len(takers_away)])
            remaining = 5 - index - 1
            if abs(score_home - score_away) > remaining:
                return events

        sudden_death_pairs = 0
        while score_home == score_away and sudden_death_pairs < 50:
            taker_index = (5 + sudden_death_pairs) % max(len(takers_home), len(takers_away))
            add_kick("home", takers_home[taker_index % len(takers_home)])
            add_kick("away", takers_away[taker_index % len(takers_away)])
            sudden_death_pairs += 1

        if score_home == score_away:
            side = "home" if rng.random() < 0.5 else "away"
            takers = takers_home if side == "home" else takers_away
            taker = takers[(5 + sudden_death_pairs) % len(takers)]
            if side == "home":
                score_home += 1
            else:
                score_away += 1
            events.append(
                Event(
                    minute=121 + len(events),
                    type="PSO",
                    side=side,
                    actor_player=taker,
                    score_after=(score_home, score_away),
                    pso_scored=True,
                )
            )
        return events

    def _find_modal(self, trajectories: list[Trajectory]) -> Trajectory:
        """Pick the median-looking trajectory within the modal scoreline."""

        if not trajectories:
            raise ValueError("trajectories must not be empty")

        score_counts = Counter(trajectory.final_score_str for trajectory in trajectories)
        modal_score = score_counts.most_common(1)[0][0]
        candidates = [trajectory for trajectory in trajectories if trajectory.final_score_str == modal_score]
        if not candidates:
            return trajectories[0]

        med_event_count = float(np.median([len(trajectory.events) for trajectory in candidates]))
        first_goal_mins = [
            min((event.minute for event in trajectory.events if event.type in GOAL_EVENT_TYPES), default=90)
            for trajectory in candidates
        ]
        med_first_goal = float(np.median(first_goal_mins))

        def distance(trajectory: Trajectory) -> float:
            first_goal = min((event.minute for event in trajectory.events if event.type in GOAL_EVENT_TYPES), default=90)
            return abs(len(trajectory.events) - med_event_count) + abs(first_goal - med_first_goal) / 10.0

        return min(enumerate(candidates), key=lambda item: (distance(item[1]), item[0]))[1]

    def _regulation_events(
        self,
        home_xg: float,
        away_xg: float,
        rng: np.random.Generator,
        roster_sampler: RosterSampler,
    ) -> list[Event]:
        markers: list[tuple[int, str, str | None]] = []
        markers.extend((minute, "goal", "home") for minute in self._sample_goals(home_xg, 90, rng))
        markers.extend((minute, "goal", "away") for minute in self._sample_goals(away_xg, 90, rng))

        for minute in (12, 24, 39, 52, 65, 78):
            if rng.random() < 0.30:
                side = "home" if rng.random() < 0.5 else "away"
                markers.append((minute, "minor", side))

        for side in ("home", "away"):
            for _ in range(int(rng.poisson(1.8))):
                markers.append((int(rng.integers(15, 91)), "card", side))

        events: list[Event] = []
        applied_windows: set[int] = set()
        for minute, kind, side in sorted(markers, key=lambda item: (item[0], item[1], item[2] or "")):
            self._apply_substitutions_through(minute, applied_windows, roster_sampler, rng)
            if kind == "goal" and side is not None:
                scorer = roster_sampler.sample_goal_actor(side, rng)
                events.append(
                    Event(
                        minute=minute,
                        type="GOAL",
                        side=side,
                        actor_player=scorer,
                        assist_player=roster_sampler.sample_assist(side, scorer, rng),
                    )
                )
            elif kind == "minor" and side is not None:
                events.append(self._sample_minor_event(minute, side, rng, roster_sampler))
            elif kind == "card" and side is not None:
                player, color = roster_sampler.sample_card(side, rng)
                events.append(Event(minute=minute, type="CARD", side=side, actor_player=player, card_color=color))

        self._apply_substitutions_through(90, applied_windows, roster_sampler, rng)
        return events

    def _sample_minor_event(
        self,
        minute: int,
        side: str,
        rng: np.random.Generator,
        roster_sampler: RosterSampler,
    ) -> Event:
        event_type = str(rng.choice(MINOR_EVENT_TYPES))
        actor = roster_sampler.sample_goal_actor(side, rng)
        return Event(minute=minute, type=event_type, side=side, actor_player=actor)

    def _apply_substitutions_through(
        self,
        minute: int,
        applied_windows: set[int],
        roster_sampler: RosterSampler,
        rng: np.random.Generator,
    ) -> None:
        for window in SUBSTITUTION_WINDOWS:
            if window <= minute and window not in applied_windows:
                roster_sampler.apply_substitution("home", window, rng)
                roster_sampler.apply_substitution("away", window, rng)
                applied_windows.add(window)

    def _aggregate_scores(self, trajectories: list[Trajectory]) -> list[dict]:
        total = len(trajectories)
        counts = Counter(trajectory.final_score_str for trajectory in trajectories)
        return [
            {"score": score, "probability": count / total}
            for score, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        ]

    def _aggregate_wdl(self, trajectories: list[Trajectory]) -> dict:
        total = len(trajectories)
        home_win = sum(1 for trajectory in trajectories if trajectory.final_score["home"] > trajectory.final_score["away"])
        away_win = sum(1 for trajectory in trajectories if trajectory.final_score["home"] < trajectory.final_score["away"])
        draw = total - home_win - away_win
        return {"home_win": home_win / total, "draw": draw / total, "away_win": away_win / total}

    def _aggregate_total_goals(self, trajectories: list[Trajectory]) -> dict:
        total = len(trajectories)
        counts = Counter(trajectory.final_score["home"] + trajectory.final_score["away"] for trajectory in trajectories)
        return {goals: count / total for goals, count in sorted(counts.items())}

    def _aggregate_knockout(self, trajectories: list[Trajectory]) -> dict:
        total = len(trajectories)
        counts = Counter(trajectory.knockout_path or "REGULATION" for trajectory in trajectories)
        return {path: count / total for path, count in sorted(counts.items())}

    def _compute_score(self, events: list[Event], up_to: int) -> dict:
        score = {"home": 0, "away": 0}
        for event in events:
            if event.minute <= up_to and event.type in GOAL_EVENT_TYPES:
                score[event.side] += 1
        return score

    def _annotate_goal_scores(self, events: list[Event]) -> None:
        score_home = 0
        score_away = 0
        for event in sorted(events, key=_event_sort_key):
            if event.type not in GOAL_EVENT_TYPES:
                continue
            if event.side == "home":
                score_home += 1
            else:
                score_away += 1
            event.score_after = (score_home, score_away)

    def _pso_hit_prob(self, player: PlayerSnapshot) -> float:
        base = 0.76
        set_piece = _rating(player, "set_piece", 60.0)
        return _clip(base + (set_piece - 60.0) / 10.0 * 0.04, 0.60, 0.92)

    def _pso_winner(self, pso_events: list[Event]) -> str:
        if not pso_events:
            raise ValueError("pso_events must not be empty")
        home_score, away_score = pso_events[-1].score_after or (0, 0)
        if home_score == away_score:
            return pso_events[-1].side
        return "home" if home_score > away_score else "away"


def _rating(player: PlayerSnapshot, key: str, default: float) -> float:
    value = (player.derived or {}).get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _event_sort_key(event: Event) -> tuple[int, int, str]:
    return (int(event.minute), EVENT_PRIORITY.get(event.type, 99), event.side)

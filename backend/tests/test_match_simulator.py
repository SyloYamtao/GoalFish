from __future__ import annotations

from collections import Counter
import math

import numpy as np

from app.services.football_goal_model import FitArtifacts
from app.services.match_simulator import Event, MatchSimulator, Trajectory
from app.services.roster_loader import PlayerSnapshot, TeamRoster
from app.services.roster_sampler import RosterSampler


def _player(
    index: int,
    *,
    team: str = "HOM",
    position: str = "CM",
    role: str = "starter",
    minutes: float = 0.95,
    finishing: float = 70,
    passing: float = 70,
    set_piece: float = 70,
) -> PlayerSnapshot:
    return PlayerSnapshot(
        id=f"{team}_{index:02d}",
        name=f"{team} Player {index}",
        name_en=f"{team} Player {index}",
        position_primary=position,
        position_class="GK" if position == "GK" else "FW" if position in {"ST", "WG"} else "MF",
        age=25,
        derived={
            "overall": 75,
            "attack": finishing,
            "defense": 65,
            "finishing": finishing,
            "passing": passing,
            "set_piece": set_piece,
            "gk": 85 if position == "GK" else 0,
        },
        expected_role=role,
        expected_minutes_share=minutes,
        availability={"status": "available"},
        shirt_number=index,
        club_fifa="Test FC",
    )


def _roster(team: str) -> TeamRoster:
    positions = ["GK", "CB", "CB", "FB", "FB", "DM", "CM", "AM", "WG", "WG", "ST"]
    starters = [
        _player(
            index + 1,
            team=team,
            position=position,
            role="starter",
            finishing=50 + index * 3,
            passing=55 + index * 2,
            set_piece=60 + index,
        )
        for index, position in enumerate(positions)
    ]
    bench = [
        _player(
            index + 12,
            team=team,
            position=positions[(index + 5) % len(positions)],
            role="bench",
            minutes=0.2,
            finishing=95 - index,
            passing=80,
            set_piece=95 - index,
        )
        for index in range(11)
    ]
    return TeamRoster(iso3=team, team_fifa=team, players=starters + bench)


def _fit() -> FitArtifacts:
    return FitArtifacts(
        model=None,
        fit_status="uniform",
        data_sufficiency="insufficient",
        model_name="uniform_prior",
        diagnostics={},
        home_advantage=0.0,
        xg_priors={"HOM": 1.35, "AWY": 1.35},
    )


def _sim() -> MatchSimulator:
    return MatchSimulator(squads=(_roster("HOM"), _roster("AWY")), fit_artifacts=_fit(), competition={})


def _poisson_prob(lmbda: float, goals: int) -> float:
    return math.exp(-lmbda) * lmbda**goals / math.factorial(goals)


def test_final_distribution_matches_poisson():
    sim = _sim()

    result = sim.simulate_match(home_xg=1.4, away_xg=1.1, n_sims=5000, knockout=False, seed=101)

    observed = Counter(trajectory.final_score_str for trajectory in result.trajectories)
    for home_goals in range(4):
        for away_goals in range(4):
            score = f"{home_goals}-{away_goals}"
            expected = _poisson_prob(1.4, home_goals) * _poisson_prob(1.1, away_goals)
            actual = observed[score] / result.n_sims
            assert actual == pytest_approx(expected, abs=0.025)


def test_seed_produces_identical_trajectory():
    sim = _sim()

    r1 = sim.simulate_match(home_xg=1.5, away_xg=1.2, n_sims=100, knockout=False, seed=42)
    r2 = sim.simulate_match(home_xg=1.5, away_xg=1.2, n_sims=100, knockout=False, seed=42)

    assert r1.trajectories[0].events == r2.trajectories[0].events


def test_modal_trajectory_picks_median_event_count():
    modal_low = Trajectory(
        events=[Event(minute=12, type="GOAL", side="home", actor_player=None, score_after=(1, 0))],
        final_score={"home": 1, "away": 0},
        knockout_winner=None,
        knockout_path=None,
    )
    modal_mid = Trajectory(
        events=[
            Event(minute=33, type="GOAL", side="home", actor_player=None, score_after=(1, 0)),
            Event(minute=70, type="SHOT", side="away", actor_player=None),
        ],
        final_score={"home": 1, "away": 0},
        knockout_winner=None,
        knockout_path=None,
    )
    modal_high = Trajectory(
        events=[
            Event(minute=55, type="GOAL", side="home", actor_player=None, score_after=(1, 0)),
            Event(minute=65, type="SHOT", side="home", actor_player=None),
            Event(minute=80, type="CARD", side="away", actor_player=None),
        ],
        final_score={"home": 1, "away": 0},
        knockout_winner=None,
        knockout_path=None,
    )
    other_score = Trajectory(
        events=[],
        final_score={"home": 0, "away": 0},
        knockout_winner=None,
        knockout_path=None,
    )

    assert _sim()._find_modal([modal_low, modal_mid, modal_high, other_score]) is modal_mid


def test_knockout_extra_time_when_tied(monkeypatch):
    sim = _sim()
    calls = iter([[], [], [5], []])
    monkeypatch.setattr(sim, "_sample_goals", lambda *args, **kwargs: next(calls))

    result = sim.simulate_match(home_xg=1.0, away_xg=1.0, n_sims=1, knockout=True, seed=7)

    assert result.trajectories[0].knockout_path == "ET"
    assert result.trajectories[0].knockout_winner == "home"
    assert any(event.type == "ET_GOAL" for event in result.trajectories[0].events)


def test_penalty_shootout_terminates(monkeypatch):
    sim = _sim()
    monkeypatch.setattr(sim, "_sample_goals", lambda *args, **kwargs: [])

    result = sim.simulate_match(home_xg=1.0, away_xg=1.0, n_sims=1, knockout=True, seed=3)

    trajectory = result.trajectories[0]
    assert trajectory.knockout_path == "PSO"
    assert trajectory.knockout_winner in {"home", "away"}
    assert trajectory.events[-1].type == "PSO"


def test_no_extra_time_when_group_stage(monkeypatch):
    sim = _sim()
    monkeypatch.setattr(sim, "_sample_goals", lambda *args, **kwargs: [])

    result = sim.simulate_match(home_xg=1.0, away_xg=1.0, n_sims=1, knockout=False, seed=3)

    assert result.trajectories[0].final_score == {"home": 0, "away": 0}
    assert result.trajectories[0].knockout_path is None
    assert all(event.type != "PSO" for event in result.trajectories[0].events)


def test_player_actor_only_from_on_field():
    sampler = RosterSampler(_roster("HOM"), _roster("AWY"))
    rng = np.random.default_rng(12)
    on_field_ids = {player.id for player in sampler.on_field("home")}

    actors = [sampler.sample_goal_actor("home", rng) for _ in range(50)]

    assert {actor.id for actor in actors}.issubset(on_field_ids)


def test_substitution_updates_on_field():
    sampler = RosterSampler(_roster("HOM"), _roster("AWY"))
    before_ids = {player.id for player in sampler.on_field("home")}

    substitution = sampler.apply_substitution("home", 65, np.random.default_rng(4))
    after_ids = {player.id for player in sampler.on_field("home")}

    assert substitution is not None
    outgoing, incoming = substitution
    assert outgoing.id in before_ids
    assert incoming.id not in before_ids
    assert outgoing.id not in after_ids
    assert incoming.id in after_ids
    assert len(after_ids) == 11


def test_pso_takers_sorted_by_set_piece():
    sampler = RosterSampler(_roster("HOM"), _roster("AWY"))
    expected = sorted(sampler.on_field("home"), key=lambda player: player.derived["set_piece"], reverse=True)[:5]

    assert sampler.sample_pso_takers("home") == expected


def pytest_approx(value: float, *, abs: float):
    import pytest

    return pytest.approx(value, abs=abs)

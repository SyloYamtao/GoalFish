from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from app.services.graph_evidence_query import GraphFacts, PlayerAvailability
from app.services.roster_loader import PlayerSnapshot, TeamRoster
from app.services.team_strength_estimator import (
    ALPHA_BY_FIT,
    TeamStrengthEstimator,
    blend,
    compute_confidence,
)


def _player(
    index: int,
    *,
    position: str = "CM",
    attack: float = 75,
    defense: float = 75,
    set_piece: float = 65,
    gk: float = 0,
    role: str = "starter",
    minutes: float = 1.0,
    status: str = "available",
) -> PlayerSnapshot:
    return PlayerSnapshot(
        id=f"ply_{index}",
        name=f"Player {index}",
        name_en=f"Player {index}",
        position_primary=position,
        position_class="GK" if position == "GK" else "FW" if position in {"ST", "WG"} else "MF",
        age=24 + index % 10,
        derived={
            "overall": (attack + defense) / 2,
            "attack": attack,
            "defense": defense,
            "pace": 70 + index % 10,
            "finishing": attack,
            "passing": 72 + index % 8,
            "set_piece": set_piece,
            "gk": gk,
        },
        expected_role=role,
        expected_minutes_share=minutes,
        availability={"status": status},
        shirt_number=index,
        club_fifa="Club",
    )


def _roster(iso3: str = "TST", players: list[PlayerSnapshot] | None = None) -> TeamRoster:
    if players is None:
        players = [
            _player(1, position="GK", attack=20, defense=60, gk=88),
            _player(2, position="CB", attack=35, defense=86),
            _player(3, position="CB", attack=35, defense=84),
            _player(4, position="FB", attack=60, defense=82),
            _player(5, position="FB", attack=62, defense=80),
            _player(6, position="DM", attack=65, defense=80),
            _player(7, position="CM", attack=76, defense=74),
            _player(8, position="AM", attack=82, defense=55),
            _player(9, position="WG", attack=86, defense=45, set_piece=91),
            _player(10, position="WG", attack=84, defense=44, set_piece=86),
            _player(11, position="ST", attack=90, defense=35, set_piece=83),
        ]
    return TeamRoster(iso3=iso3, team_fifa=f"Team {iso3}", players=players)


def _fit(status: str = "fitted"):
    return SimpleNamespace(
        fit_status=status,
        attack_coef={"TST": 0.80, "OPP": -0.20, "USA": 0.50},
        defense_coef={"TST": 0.20, "OPP": 0.10, "USA": 0.10},
    )


def test_alpha_blending_per_fit_status():
    assert ALPHA_BY_FIT["fitted"] == 0.40
    assert ALPHA_BY_FIT["uniform"] == 0.95
    assert blend(0.40, 80, 0.50) == 78
    assert blend(0.95, 80, None) == 80

    fitted_home, _ = TeamStrengthEstimator().estimate_pair(
        home_roster=_roster("TST"),
        away_roster=_roster("OPP"),
        fit_artifacts=_fit("fitted"),
    )
    uniform_home, _ = TeamStrengthEstimator().estimate_pair(
        home_roster=_roster("TST"),
        away_roster=_roster("OPP"),
        fit_artifacts=_fit("uniform"),
    )

    assert fitted_home.evidence_breakdown["attack"]["alpha"] == 0.40
    assert uniform_home.evidence_breakdown["attack"]["alpha"] == 0.95


def test_attack_rating_uses_position_weights():
    players = [
        _player(1, position="GK", attack=0, defense=70, gk=80),
        _player(2, position="CB", attack=100, defense=80),
        _player(3, position="ST", attack=20, defense=30),
    ]
    roster = _roster("TST", players)

    strength, _ = TeamStrengthEstimator().estimate_pair(
        home_roster=roster,
        away_roster=_roster("OPP"),
        fit_artifacts=None,
    )

    assert strength.attack_rating < 30
    assert strength.evidence_breakdown["attack"]["top_contributors"][0]["position"] == "ST"


def test_set_piece_uses_top_takers():
    roster = _roster("TST")
    roster.players[4].derived["set_piece"] = 99

    strength, _ = TeamStrengthEstimator().estimate_pair(
        home_roster=roster,
        away_roster=_roster("OPP"),
        fit_artifacts=None,
    )

    assert strength.set_piece_rating == 99
    assert strength.evidence_breakdown["set_piece"]["top_contributors"][0]["player_id"] == roster.players[4].id


def test_evidence_breakdown_lists_top_contributors():
    strength, _ = TeamStrengthEstimator().estimate_pair(
        home_roster=_roster("TST"),
        away_roster=_roster("OPP"),
        fit_artifacts=_fit("fitted"),
    )

    for key in ("attack", "defense", "possession", "transition", "set_piece", "goalkeeper"):
        assert len(strength.evidence_breakdown[key]["top_contributors"]) == 3
        assert {"player_id", "name", "contribution_pct", "rating", "position"} <= set(
            strength.evidence_breakdown[key]["top_contributors"][0]
        )


def test_injury_adjustment_with_graph_evidence():
    roster = _roster("TST")
    injured_id = roster.players[10].id
    facts = GraphFacts(
        player_availability={
            injured_id: PlayerAvailability(
                status="injured",
                evidence_refs=[{"type": "graph_node", "id": "node_inj_st", "summary": "starter injured"}],
            )
        },
        player_team_iso3={injured_id: "TST"},
    )

    strength, _ = TeamStrengthEstimator().estimate_pair(
        home_roster=roster,
        away_roster=_roster("OPP"),
        fit_artifacts=None,
        graph_facts=facts,
    )

    assert strength.injury_adjustment <= -2
    assert strength.injury_evidence_refs[0]["id"] == "node_inj_st"
    assert strength.evidence_breakdown["injury_adjustment"]["value"] == strength.injury_adjustment


def test_confidence_includes_available_share():
    full_roster = _roster("TST")
    depleted_roster = _roster("TST", [replace(player) for player in full_roster.players])
    for player in depleted_roster.players[:3]:
        player.availability = {"status": "injured"}
        player.expected_minutes_share = 0.0

    full = compute_confidence(full_roster, _fit("uniform"), None, "TST")
    depleted = compute_confidence(depleted_roster, _fit("uniform"), None, "TST")

    assert depleted < full


def test_neutral_venue_no_home_advantage():
    strength, _ = TeamStrengthEstimator().estimate_pair(
        home_roster=_roster("TST"),
        away_roster=_roster("OPP"),
        fit_artifacts=None,
        competition_meta={"neutral_venue": True, "host_country_iso3": "USA"},
    )

    assert strength.home_away_adjustment == 0
    assert strength.home_away_adjustment_reason == "neutral_venue"


def test_host_country_gets_advantage():
    strength, _ = TeamStrengthEstimator().estimate_pair(
        home_roster=_roster("USA"),
        away_roster=_roster("OPP"),
        fit_artifacts=None,
        competition_meta={"neutral_venue": True, "host_country_iso3": "USA"},
    )

    assert strength.home_away_adjustment == 0.20
    assert strength.home_away_adjustment_reason == "host_country"


def test_legacy_fit_artifacts_none_works():
    strength, _ = TeamStrengthEstimator().estimate_pair(
        home_roster=_roster("TST"),
        away_roster=_roster("OPP"),
        fit_artifacts=None,
    )

    assert strength.evidence_breakdown["attack"]["alpha"] == 0.95
    assert strength.evidence_breakdown["attack"]["model_score"] is None
    assert 40 <= strength.confidence <= 95

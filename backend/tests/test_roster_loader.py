from __future__ import annotations

import pytest

from app.config import Config
from app.db.models import (
    PredictionPlayerDatasetRecord,
    PredictionPlayerRecord,
    PredictionTeamMetadataRecord,
)
from app.db.session import get_session, init_db, reset_engine
from app.services.graph_evidence_query import GraphFacts, PlayerAvailability
from app.services.roster_loader import RosterLoader, apply_graph_facts, apply_source_availability


@pytest.fixture()
def player_db(monkeypatch, tmp_path):
    db_path = tmp_path / "players.sqlite"
    monkeypatch.setattr(Config, "DATABASE_URL", f"sqlite+pysqlite:///{db_path}")
    monkeypatch.setattr(Config, "SQLALCHEMY_ECHO", False)
    reset_engine()
    init_db()
    try:
        yield
    finally:
        reset_engine()


def _seed_team(dataset_id: str, iso3: str, team_fifa: str, count: int = 22) -> None:
    positions = ["GK", "CB", "CB", "FB", "FB", "DM", "CM", "AM", "WG", "WG", "ST"]
    with get_session() as session:
        if session.get(PredictionPlayerDatasetRecord, dataset_id) is None:
            session.add(
                PredictionPlayerDatasetRecord(
                    dataset_id=dataset_id,
                    source_label="test",
                    scope_label="fifa_world_cup_2026_squads",
                    ratings_schema={"derived_fields": ["overall", "attack", "defense", "pace", "finishing", "passing", "set_piece", "gk"]},
                    teams_count=2,
                    players_count=44,
                )
            )
        session.add(
            PredictionTeamMetadataRecord(
                id=f"tm_{dataset_id}_{iso3}",
                dataset_id=dataset_id,
                team_fifa=team_fifa,
                team_iso3=iso3,
                team_zh=team_fifa,
            )
        )
        for index in range(count):
            position = positions[index % len(positions)]
            is_starter = index < 11
            session.add(
                PredictionPlayerRecord(
                    id=f"ply_{dataset_id}_{iso3}_{index + 1:02d}",
                    dataset_id=dataset_id,
                    team_name=team_fifa,
                    team_iso3=iso3,
                    player_external_id=f"{iso3}_{index + 1}",
                    full_name=f"{team_fifa} Player {index + 1}",
                    full_name_en=f"{team_fifa} Player {index + 1}",
                    full_name_alt=[],
                    position_primary=position,
                    position_secondary=[],
                    age=24 + index % 8,
                    foot="R",
                    height_cm=180,
                    ratings={},
                    derived={
                        "overall": 80 + index % 5,
                        "attack": 76 + index % 10,
                        "defense": 74 + index % 9,
                        "pace": 75 + index % 12,
                        "finishing": 73 + index % 11,
                        "passing": 77 + index % 8,
                        "set_piece": 70 + index % 15,
                        "gk": 86 if position == "GK" else 0,
                    },
                    availability={"status": "available"},
                    expected_role="starter" if is_starter else "bench",
                    expected_minutes_share=0.95 if is_starter else 0.20,
                    shirt_number=index + 1,
                    position_class="GK" if position == "GK" else "FW" if position in {"ST", "WG"} else "MF",
                    caps_intl=10,
                    goals_intl=2,
                    club_fifa="Test FC",
                )
            )


def test_roster_loader_reads_wc2026_dataset(player_db):
    _seed_team("wc2026_fifa_v1", "BRA", "Brazil")
    _seed_team("wc2026_fifa_v1", "ARG", "Argentina")

    home, away = RosterLoader().snapshot("wc2026_fifa_v1", "BRA", "ARG")

    assert len(home.players) >= 20
    assert len(away.players) >= 20
    assert home.iso3 == "BRA"
    assert home.team_fifa == "Brazil"
    assert home.starters[0].expected_role == "starter"
    assert home.goalkeepers[0].position_primary == "GK"


def test_roster_loader_to_from_snapshot_roundtrip(player_db):
    _seed_team("wc2026_fifa_v1", "BRA", "Brazil")
    _seed_team("wc2026_fifa_v1", "ARG", "Argentina")
    loader = RosterLoader()
    home, away = loader.snapshot("wc2026_fifa_v1", "BRA", "ARG")

    restored_home, restored_away = loader.from_snapshot(loader.to_snapshot(home, away))

    assert restored_home.iso3 == "BRA"
    assert restored_away.iso3 == "ARG"
    assert restored_home.players[0].id == home.players[0].id
    assert restored_home.players[0].is_available is True


def test_apply_graph_facts_overrides_player_availability(player_db):
    _seed_team("wc2026_fifa_v1", "BRA", "Brazil")
    home, _ = RosterLoader().snapshot("wc2026_fifa_v1", "BRA", "BRA")
    player_id = home.players[0].id
    facts = GraphFacts(
        player_availability={
            player_id: PlayerAvailability(
                status="injured",
                evidence_refs=[{"type": "graph_node", "id": "inj_1", "summary": "injury"}],
            )
        }
    )

    apply_graph_facts(home, facts)

    assert home.players[0].availability["status"] == "injured"
    assert home.players[0].is_available is False
    assert home.players[0].availability["evidence_refs"][0]["id"] == "inj_1"


def test_apply_source_availability_marks_named_suspensions(player_db):
    _seed_team("wc2026_fifa_v1", "RSA", "South Africa")
    home, _ = RosterLoader().snapshot("wc2026_fifa_v1", "RSA", "RSA")
    home.players[4].name = "Yaya Sithole"
    home.players[4].name_en = "Yaya Sithole"
    home.players[5].name = "Thalente Mbatha"
    home.players[5].name_en = "Thalente Mbatha"
    home.players[7].name = "Themba Zwane"
    home.players[7].name_en = "Themba Zwane"
    source_text = """
    - 停赛球员：Sphephelo/Yaya Sithole 停赛；Themba Zwane 停赛。
    - 停赛最终口径：Zwane 被延长为 3 场停赛，不代表 3 名球员停赛。
    - 对第二轮影响：Sithole 停赛迫使 Thalente Mbatha 或其他中场替代；Zwane 停赛进一步削弱前腰创造。
    """

    apply_source_availability(home, source_text)

    suspended = [player for player in home.players if player.availability["status"] == "suspended"]
    assert [player.name_en for player in suspended] == ["Yaya Sithole", "Themba Zwane"]
    assert home.players[5].availability["status"] == "available"
    assert all(player.is_available is False for player in suspended)
    assert suspended[0].availability["evidence_refs"][0]["type"] == "source_document"

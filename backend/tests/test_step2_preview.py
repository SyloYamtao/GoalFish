from __future__ import annotations

from typing import Any

from app.db.models import (
    PredictionPlayerDatasetRecord,
    PredictionPlayerRecord,
    PredictionTeamMetadataRecord,
    ProjectRecord,
)
from app.db.session import get_session
from app.services.graph_evidence_query import GraphFacts
from app.services.step2_preview import STEP2_PREVIEW_METADATA_KEY, Step2PreviewService


class FakeGraphEvidenceQuery:
    def for_match(self, **kwargs: Any) -> GraphFacts:
        del kwargs
        return GraphFacts()


class FakeExternalSource:
    def __init__(self, key: str, rows: int):
        self.key = key
        self.rows = rows

    def fingerprint(self) -> dict[str, Any]:
        return {
            "row_count": self.rows,
            "fetched_at": "2026-06-18T00:00:00+00:00",
            "etag": f"etag-{self.key}",
        }


class FakeExternalDataPool:
    def __init__(self):
        self.intl_results = FakeExternalSource("intl_results", 120)
        self.elo = FakeExternalSource("national_elo", 80)

    def fetch_for_match(self, *args: Any, **kwargs: Any) -> "FakeExternalDataPool":
        del args, kwargs
        return self


def test_step2_preview_persists_roster_and_sources(postgres_db, monkeypatch):
    del postgres_db
    monkeypatch.setattr("app.services.step2_preview.GraphEvidenceQuery", FakeGraphEvidenceQuery)
    monkeypatch.setattr("app.services.step2_preview.ExternalDataPool", FakeExternalDataPool)
    _seed_project()
    _seed_dataset("wc2026_fifa_v2", [("ARG", "Argentina", "阿根廷"), ("FRA", "France", "法国")])

    preview = Step2PreviewService().build_preview(
        project_id="proj_preview",
        graph_id="graph_preview",
        force=True,
    )

    assert preview["match_name"] == "阿根廷 vs 法国"
    assert preview["dataset_summary"]["home"]["players_count"] == 11
    assert preview["dataset_summary"]["away"]["players_count"] == 11
    assert preview["roster"]["teams"][0]["players"][0]["name_zh"].startswith("阿根廷")
    assert {row["key"] for row in preview["external_sources"]} >= {"intl_results", "national_elo", "fifa_ranking"}

    with get_session() as session:
        project = session.get(ProjectRecord, "proj_preview")
        stored = project.project_metadata[STEP2_PREVIEW_METADATA_KEY]

    assert stored["player_dataset_id"] == "wc2026_fifa_v2"
    assert stored["roster"]["teams"][1]["iso3"] == "FRA"


def test_step2_preview_applies_source_document_suspensions(postgres_db, monkeypatch):
    del postgres_db
    monkeypatch.setattr("app.services.step2_preview.GraphEvidenceQuery", FakeGraphEvidenceQuery)
    monkeypatch.setattr("app.services.step2_preview.ExternalDataPool", FakeExternalDataPool)
    _seed_project(
        project_id="proj_preview_susp",
        graph_id="graph_preview_susp",
        extracted_text=(
            "捷克 vs 南非\n"
            "停赛球员：Sphephelo/Yaya Sithole 停赛；Themba Zwane 停赛。\n"
            "Zwane 被延长为 3 场停赛。"
        ),
        simulation_requirement="捷克 vs 南非",
    )
    _seed_dataset(
        "wc2026_fifa_v2",
        [("CZE", "Czechia", "捷克"), ("RSA", "South Africa", "南非")],
        rename_players={
            ("RSA", 7): ("Yaya Sithole", "Yaya Sithole"),
            ("RSA", 8): ("Themba Zwane", "Themba Zwane"),
        },
    )

    preview = Step2PreviewService().build_preview(
        project_id="proj_preview_susp",
        graph_id="graph_preview_susp",
        force=True,
    )

    assert preview["match_name"] == "捷克 vs 南非"
    assert preview["dataset_summary"]["away"]["suspended"] == 2
    away_team = next(team for team in preview["roster"]["teams"] if team["iso3"] == "RSA")
    suspended_names = [player["name_en"] for player in away_team["players"] if player["availability"]["status"] == "suspended"]
    assert suspended_names == ["Yaya Sithole", "Themba Zwane"]


def _seed_project(
    *,
    project_id: str = "proj_preview",
    graph_id: str = "graph_preview",
    extracted_text: str = "阿根廷 vs 法国 世界杯小组赛",
    simulation_requirement: str = "阿根廷 vs 法国",
) -> None:
    with get_session() as session:
        session.add(
            ProjectRecord(
                project_id=project_id,
                name="Preview Project",
                status="graph_completed",
                files=[],
                total_text_length=0,
                extracted_text=extracted_text,
                analysis_summary="阿根廷 vs 法国",
                graph_id=graph_id,
                simulation_requirement=simulation_requirement,
                simulation_domain="football_match",
                chunk_size=500,
                chunk_overlap=50,
                project_metadata={},
            )
        )


def _seed_dataset(
    dataset_id: str,
    teams: list[tuple[str, str, str]],
    *,
    rename_players: dict[tuple[str, int], tuple[str, str]] | None = None,
) -> None:
    positions = ["GK", "CB", "CB", "FB", "FB", "DM", "CM", "AM", "WG", "WG", "ST"]
    rename_players = rename_players or {}
    with get_session() as session:
        session.add(
            PredictionPlayerDatasetRecord(
                dataset_id=dataset_id,
                source_label="test",
                scope_label="fifa_world_cup_2026_squads",
                ratings_schema={},
                teams_count=len(teams),
                players_count=len(teams) * len(positions),
            )
        )
        for iso3, team_fifa, team_zh in teams:
            session.add(
                PredictionTeamMetadataRecord(
                    id=f"tm_{dataset_id}_{iso3}",
                    dataset_id=dataset_id,
                    team_fifa=team_fifa,
                    team_iso3=iso3,
                    team_zh=team_zh,
                )
            )
            for index, position in enumerate(positions, start=1):
                name_zh, name_en = rename_players.get((iso3, index), (f"{team_zh}球员{index}", f"{team_fifa} Player {index}"))
                session.add(
                    PredictionPlayerRecord(
                        id=f"ply_{dataset_id}_{iso3}_{index:02d}",
                        dataset_id=dataset_id,
                        team_name=team_fifa,
                        team_iso3=iso3,
                        player_external_id=f"{iso3}_{index}",
                        full_name=name_zh,
                        full_name_en=name_en,
                        full_name_alt=[],
                        position_primary=position,
                        position_secondary=[],
                        age=24 + index % 8,
                        foot="R",
                        height_cm=180,
                        ratings={},
                        derived={"overall": 70 + index, "gk": 82 if position == "GK" else 0},
                        availability={"status": "available"},
                        expected_role="starter" if index <= 11 else "bench",
                        expected_minutes_share=0.95,
                        shirt_number=index,
                        position_class="GK" if position == "GK" else "FW" if position in {"ST", "WG"} else "MF",
                        caps_intl=10,
                        goals_intl=2,
                        club_fifa="Test FC",
                        player_metadata={},
                    )
                )

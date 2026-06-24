from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any

from flask import Flask

from app.api import prediction_bp
from app.db.models import PredictionConfigRecord, ProjectRecord, utc_now
from app.db.session import get_session
from app.services.external_data.team_name_normalizer import TeamNameNormalizer
from app.services.graph_evidence_query import GraphFacts
from app.services.prediction_config import (
    PredictionConfigService,
    _is_reusable_ready_config,
    _resolve_match_identity,
)


class FakeGraphEvidenceQuery:
    def for_match(self, **kwargs: Any) -> GraphFacts:
        del kwargs
        return GraphFacts()


class FakeExternalDataPool:
    def fetch_for_match(self, *args: Any, **kwargs: Any) -> "FakeExternalDataPool":
        del args, kwargs
        return self

    def fit_dataframe(self, cutoff_date: str | None = None):
        del cutoff_date
        import pandas as pd

        return pd.DataFrame()

    def elo_snapshot(self) -> dict[str, float]:
        return {}


class FakeLLM:
    def chat_json(self, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        return {
            "role": "head_coach",
            "scenario_votes": [],
            "team_xg_micro_adjustment": {"home": 0, "away": 0, "rationale": "test"},
            "wld_pp_adjustment": None,
            "confidence_delta": 0,
            "summary": "test verdict",
            "metadata": {"source": "coach_llm_panel_v1"},
        }


class MixedReportDataLLM:
    def __init__(self):
        self.calls = []

    def chat_json(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        content = kwargs.get("messages", [{}])[-1].get("content", "")
        if "墨西哥" in content and "韩国" in content and "Czechia" not in content:
            return {
                "home_iso3": "MEX",
                "away_iso3": "KOR",
                "home_name_zh": "墨西哥",
                "away_name_zh": "韩国",
                "competition_meta": {
                    "tournament": "2026 FIFA World Cup",
                    "stage": "group",
                    "knockout": False,
                    "neutral_venue": True,
                    "host_country_iso3": "USA",
                },
                "key_narratives": [],
                "injury_reports": [],
                "tactical_notes": [],
            }
        return {
            "role": "head_coach",
            "scenario_votes": [],
            "team_xg_micro_adjustment": {"home": 0, "away": 0, "rationale": "test"},
            "wld_pp_adjustment": None,
            "confidence_delta": 0,
            "summary": "test verdict",
            "metadata": {"source": "coach_llm_panel_v1"},
        }


def test_force_regenerate_creates_new_config(postgres_db, monkeypatch):
    del postgres_db
    _patch_step2_dependencies(monkeypatch)
    _seed_project("proj_force", "graph_force")
    service = PredictionConfigService()

    first = service.prepare(
        project_id="proj_force",
        graph_id="graph_force",
        prediction_requirement="阿根廷 vs 法国",
        home_team="阿根廷",
        away_team="法国",
        llm_budget={"profile_key": "low"},
    )
    second = service.prepare(
        project_id="proj_force",
        graph_id="graph_force",
        prediction_requirement="阿根廷 vs 法国",
        home_team="阿根廷",
        away_team="法国",
        force_regenerate=True,
        llm_budget={"profile_key": "low"},
    )

    assert first["prediction_config_id"] != second["prediction_config_id"]
    assert second["already_prepared"] is False


def test_existing_ready_config_short_circuit(postgres_db, monkeypatch):
    del postgres_db
    _patch_step2_dependencies(monkeypatch)
    _seed_project("proj_short", "graph_short")
    _seed_prediction_dataset("wc2026_fifa_v2", [("ARG", "Argentina", "阿根廷"), ("FRA", "France", "法国")])
    service = PredictionConfigService()

    first = service.prepare(
        project_id="proj_short",
        graph_id="graph_short",
        prediction_requirement="阿根廷 vs 法国",
        home_team="阿根廷",
        away_team="法国",
        llm_budget={"profile_key": "low"},
    )
    second = service.prepare(
        project_id="proj_short",
        graph_id="graph_short",
        prediction_requirement="阿根廷 vs 法国",
        force_regenerate=False,
        llm_budget={"profile_key": "max"},
    )

    assert second["prediction_config_id"] == first["prediction_config_id"]
    assert second["already_prepared"] is True
    assert second["status"] == "ready"


def test_latest_ready_config_skips_identity_that_conflicts_with_uploaded_body(postgres_db):
    del postgres_db
    project_id = "proj_skip_wrong_ready_identity"
    graph_id = "graph_skip_wrong_ready_identity"
    report = (
        Path(__file__).resolve().parents[2]
        / "docs/sample/research/20260621/04.Tunisia_vs_Japan_Pre-Match_Report_EN.md"
    ).read_text(encoding="utf-8")
    _seed_project(project_id, graph_id, extracted_text=report, simulation_requirement="Predict this match")
    created_at = utc_now()

    with get_session() as session:
        session.add(
            _ready_config_record(
                prediction_config_id="cfg_valid_tun_jpn",
                project_id=project_id,
                graph_id=graph_id,
                home_iso3="TUN",
                away_iso3="JPN",
                home_team="突尼斯",
                away_team="日本",
                created_at=created_at,
            )
        )
        session.add(
            _ready_config_record(
                prediction_config_id="cfg_wrong_tun_swe",
                project_id=project_id,
                graph_id=graph_id,
                home_iso3="TUN",
                away_iso3="SWE",
                home_team="突尼斯",
                away_team="瑞典",
                created_at=created_at + timedelta(seconds=1),
            )
        )

    assert PredictionConfigService().find_ready_config(project_id=project_id, graph_id=graph_id) == "cfg_valid_tun_jpn"


def test_ready_config_with_extracted_team_conflict_is_not_reusable():
    class Config:
        home_team = "埃及"
        away_team = "塞拉利昂"
        model_input_snapshot = {
            "home_team": "埃及",
            "away_team": "塞拉利昂",
            "home_iso3": "EGY",
            "away_iso3": "SLE",
            "squads": {
                "home": {"team_iso3": "EGY"},
                "away": {"team_iso3": "SLE"},
            },
            "extracted": {
                "home_iso3": "BEL",
                "away_iso3": "EGY",
                "home_name_zh": "比利时",
                "away_name_zh": "埃及",
            },
        }

    assert _is_reusable_ready_config(Config()) is False


def test_get_progress_backend_and_endpoint(postgres_db, monkeypatch):
    del postgres_db
    _patch_step2_dependencies(monkeypatch)
    _seed_project("proj_progress_api", "graph_progress_api")
    service = PredictionConfigService()
    result = service.prepare(
        project_id="proj_progress_api",
        graph_id="graph_progress_api",
        prediction_requirement="阿根廷 vs 法国",
        home_team="阿根廷",
        away_team="法国",
        llm_budget={"profile_key": "low"},
    )

    progress = service.get_progress(result["prediction_config_id"])
    assert progress["status"] == "ready"
    assert progress["progress_messages"][-1]["milestone"] == "ready"

    app = Flask(__name__)
    app.register_blueprint(prediction_bp, url_prefix="/api/prediction")
    response = app.test_client().get(f"/api/prediction/configs/{result['prediction_config_id']}/progress")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["progress_messages"][-1]["milestone"] == "ready"


def test_latest_ready_config_backend_and_endpoint(postgres_db, monkeypatch):
    del postgres_db
    _patch_step2_dependencies(monkeypatch)
    _seed_project("proj_latest_config", "graph_latest_config")
    _seed_prediction_dataset("wc2026_fifa_v2", [("ARG", "Argentina", "阿根廷"), ("FRA", "France", "法国")])
    service = PredictionConfigService()
    result = service.prepare(
        project_id="proj_latest_config",
        graph_id="graph_latest_config",
        prediction_requirement="阿根廷 vs 法国",
        home_team="阿根廷",
        away_team="法国",
        llm_budget={"profile_key": "low"},
    )

    latest = service.get_latest_ready_config(project_id="proj_latest_config", graph_id="graph_latest_config")
    assert latest["prediction_config_id"] == result["prediction_config_id"]

    app = Flask(__name__)
    app.register_blueprint(prediction_bp, url_prefix="/api/prediction")
    response = app.test_client().get("/api/prediction/proj_latest_config/configs/latest?graph_id=graph_latest_config")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["prediction_config_id"] == result["prediction_config_id"]


def test_latest_ready_config_skips_superseded_ready_config(postgres_db, monkeypatch):
    del postgres_db
    _patch_step2_dependencies(monkeypatch)
    _seed_project("proj_latest_skip_superseded", "graph_latest_skip_superseded")
    _seed_prediction_dataset("wc2026_fifa_v2", [("ARG", "Argentina", "阿根廷"), ("FRA", "France", "法国")])
    service = PredictionConfigService()
    result = service.prepare(
        project_id="proj_latest_skip_superseded",
        graph_id="graph_latest_skip_superseded",
        prediction_requirement="阿根廷 vs 法国",
        home_team="阿根廷",
        away_team="法国",
        llm_budget={"profile_key": "low"},
    )

    with get_session() as session:
        config = session.get(PredictionConfigRecord, result["prediction_config_id"])
        config.config_metadata = {
            **(config.config_metadata or {}),
            "artifact_status": "superseded",
        }

    latest = service.get_latest_ready_config(
        project_id="proj_latest_skip_superseded",
        graph_id="graph_latest_skip_superseded",
    )

    assert latest is None

    app = Flask(__name__)
    app.register_blueprint(prediction_bp, url_prefix="/api/prediction")
    response = app.test_client().get(
        "/api/prediction/proj_latest_skip_superseded/configs/latest?graph_id=graph_latest_skip_superseded"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"] is None


def test_match_identity_prefers_graph_match_over_text_fallback(monkeypatch):
    class FakeGraphReader:
        def get_all_nodes(self, graph_id: str) -> list[dict[str, Any]]:
            assert graph_id == "graph_match_identity"
            return [
                {
                    "uuid": "match-noise",
                    "name": "瑞典主场对瑞士的世界杯预选赛比赛",
                    "labels": ["Entity", "Match"],
                    "summary": "瑞典在世界杯预选赛中主场对阵瑞士。",
                    "attributes": {"比赛阶段": "世界杯预选赛"},
                },
                {
                    "uuid": "match-1",
                    "name": "Sweden vs Tunisia",
                    "labels": ["Entity", "Match"],
                    "summary": "瑞典 vs 突尼斯 是 2026 FIFA World Cup F 组小组赛 Match 12。",
                    "attributes": {"比赛阶段": "小组赛"},
                },
                {
                    "uuid": "team-1",
                    "name": "瑞典",
                    "labels": ["Entity", "FootballTeam"],
                    "summary": "瑞典国家队",
                    "attributes": {"全称": "瑞典国家男子足球队"},
                },
                {
                    "uuid": "team-2",
                    "name": "突尼斯",
                    "labels": ["Entity", "FootballTeam"],
                    "summary": "突尼斯国家队",
                    "attributes": {"全称": "突尼斯国家男子足球队"},
                },
            ]

        def get_all_edges(self, graph_id: str) -> list[dict[str, Any]]:
            assert graph_id == "graph_match_identity"
            return [
                {
                    "name": "HAS_TEAM_A",
                    "source_node_uuid": "match-1",
                    "target_node_uuid": "team-1",
                    "fact": "The match lists team_a as Sweden.",
                },
                {
                    "name": "HAS_TEAM_B",
                    "source_node_uuid": "match-1",
                    "target_node_uuid": "team-2",
                    "fact": "The match lists team_b as Tunisia.",
                },
            ]

    monkeypatch.setattr("app.services.prediction_config.get_entity_reader", lambda: FakeGraphReader())

    identity = _resolve_match_identity(
        requirement="严谨地预测这场比赛的过程和结果",
        source_text="=== 瑞典vs摩尔多瓦赛前信息报告.md ===\n# 瑞典 vs 摩尔多瓦",
        graph_entities=[],
        graph_id="graph_match_identity",
        home_team=None,
        away_team=None,
        normalizer=TeamNameNormalizer(),
    )

    assert identity == ("SWE", "TUN", "瑞典", "突尼斯")


def test_match_identity_prefers_uploaded_match_declaration_over_graph_noise(monkeypatch):
    class FakeGraphReader:
        def get_all_nodes(self, graph_id: str) -> list[dict[str, Any]]:
            assert graph_id == "graph_uploaded_match"
            return [
                {
                    "uuid": "match-noise",
                    "name": "Sweden vs Netherlands",
                    "labels": ["Entity", "Match"],
                    "summary": "Sweden and Netherlands are both Group F background teams.",
                    "attributes": {},
                },
                {
                    "uuid": "team-1",
                    "name": "Sweden",
                    "labels": ["Entity", "FootballTeam"],
                    "summary": "Sweden national team",
                    "attributes": {},
                },
                {
                    "uuid": "team-2",
                    "name": "Netherlands",
                    "labels": ["Entity", "FootballTeam"],
                    "summary": "Netherlands national team",
                    "attributes": {},
                },
            ]

        def get_all_edges(self, graph_id: str) -> list[dict[str, Any]]:
            assert graph_id == "graph_uploaded_match"
            return [
                {
                    "name": "HAS_TEAM_A",
                    "source_node_uuid": "match-noise",
                    "target_node_uuid": "team-1",
                    "fact": "The match lists team_a as Sweden.",
                },
                {
                    "name": "HAS_TEAM_B",
                    "source_node_uuid": "match-noise",
                    "target_node_uuid": "team-2",
                    "fact": "The match lists team_b as Netherlands.",
                },
            ]

    monkeypatch.setattr("app.services.prediction_config.get_entity_reader", lambda: FakeGraphReader())

    identity = _resolve_match_identity(
        requirement="Predict this match process and result rigorously",
        source_text="Group F background mentions Sweden, Netherlands, Japan and Tunisia.",
        primary_source_text=(
            "# Sweden vs Netherlands Pre-Match Report\n"
            "Main sources:\n"
            "- FIFA report: Netherlands 2-2 Japan and Sweden 5-1 Tunisia.\n"
            "\n"
            "# 1. Match Overview\n"
            "- Teams: Tunisia (Team A) vs Japan (Team B).\n"
            "- Venue: Estadio BBVA, Monterrey.\n"
        ),
        graph_entities=[],
        graph_id="graph_uploaded_match",
        home_team=None,
        away_team=None,
        normalizer=TeamNameNormalizer(),
    )

    assert identity == ("TUN", "JPN", "突尼斯", "日本")


def test_match_identity_uses_uploaded_body_content_for_real_tunisia_japan_report(monkeypatch):
    class FakeGraphReader:
        def get_all_nodes(self, graph_id: str) -> list[dict[str, Any]]:
            assert graph_id == "graph_real_tunisia_japan"
            return [
                {
                    "uuid": "match-noise",
                    "name": "Sweden vs Netherlands",
                    "labels": ["Entity", "Match"],
                    "summary": "Group F background match.",
                    "attributes": {},
                },
                {"uuid": "sweden", "name": "Sweden", "labels": ["Entity", "FootballTeam"], "attributes": {}},
                {"uuid": "netherlands", "name": "Netherlands", "labels": ["Entity", "FootballTeam"], "attributes": {}},
            ]

        def get_all_edges(self, graph_id: str) -> list[dict[str, Any]]:
            assert graph_id == "graph_real_tunisia_japan"
            return [
                {
                    "name": "HAS_TEAM_A",
                    "source_node_uuid": "match-noise",
                    "target_node_uuid": "sweden",
                    "fact": "The match lists team_a as Sweden.",
                },
                {
                    "name": "HAS_TEAM_B",
                    "source_node_uuid": "match-noise",
                    "target_node_uuid": "netherlands",
                    "fact": "The match lists team_b as Netherlands.",
                },
            ]

    monkeypatch.setattr("app.services.prediction_config.get_entity_reader", lambda: FakeGraphReader())
    report = (
        Path(__file__).resolve().parents[2]
        / "docs/sample/research/20260621/04.Tunisia_vs_Japan_Pre-Match_Report_EN.md"
    ).read_text(encoding="utf-8")

    identity = _resolve_match_identity(
        requirement="Predict the uploaded report's match",
        source_text="Group F background mentions Sweden, Netherlands, Japan and Tunisia.",
        primary_source_text=report,
        graph_entities=[],
        graph_id="graph_real_tunisia_japan",
        home_team=None,
        away_team=None,
        normalizer=TeamNameNormalizer(),
    )

    assert identity == ("TUN", "JPN", "突尼斯", "日本")


def test_prepare_keeps_uploaded_body_identity_over_extracted_prior_match_context(postgres_db, monkeypatch):
    class FakeGraphReader:
        def get_all_nodes(self, graph_id: str) -> list[dict[str, Any]]:
            assert graph_id == "graph_prepare_tunisia_japan"
            return [
                {
                    "uuid": "match-noise",
                    "name": "Sweden vs Netherlands",
                    "labels": ["Entity", "Match"],
                    "summary": "Group F background match.",
                    "attributes": {},
                }
            ]

        def get_all_edges(self, graph_id: str) -> list[dict[str, Any]]:
            assert graph_id == "graph_prepare_tunisia_japan"
            return []

    del postgres_db
    _patch_step2_dependencies(monkeypatch)
    monkeypatch.setattr("app.services.prediction_config.get_entity_reader", lambda: FakeGraphReader())
    report = (
        Path(__file__).resolve().parents[2]
        / "docs/sample/research/20260621/04.Tunisia_vs_Japan_Pre-Match_Report_EN.md"
    ).read_text(encoding="utf-8")
    _seed_project(
        "proj_prepare_tunisia_japan",
        "graph_prepare_tunisia_japan",
        extracted_text=report,
        simulation_requirement="Predict the uploaded match",
    )
    dataset_id = "dataset_tunisia_japan_lock"
    _seed_prediction_dataset(
        dataset_id,
        [("TUN", "Tunisia", "突尼斯"), ("JPN", "Japan", "日本"), ("SWE", "Sweden", "瑞典")],
    )
    _add_extra_prediction_players(dataset_id, "SWE", "Sweden", "瑞典", 20)

    result = PredictionConfigService().prepare(
        project_id="proj_prepare_tunisia_japan",
        graph_id="graph_prepare_tunisia_japan",
        prediction_requirement="Predict the uploaded match",
        player_dataset_id=dataset_id,
        force_regenerate=True,
        llm_budget={"profile_key": "low"},
    )

    assert result["home_iso3"] == "TUN"
    assert result["away_iso3"] == "JPN"
    assert result["match_name"] == "Tunisia vs Japan"
    assert result["dataset_summary"]["away"]["team_iso3"] == "JPN"
    assert "match_identity_corrected_from_extracted_context" not in result["warnings"]


def test_prepare_uses_current_match_venue_for_multihost_world_cup(postgres_db, monkeypatch):
    class FakeGraphReader:
        def get_all_nodes(self, graph_id: str) -> list[dict[str, Any]]:
            assert graph_id == "graph_multihost"
            return [
                {
                    "uuid": "match-current",
                    "name": "Mexico vs Korea Republic",
                    "labels": ["Entity", "Match"],
                    "summary": "墨西哥 vs 韩国 是2026 FIFA World Cup A组第二轮小组赛，比赛地点为Guadalajara Stadium / Estadio Akron。",
                    "attributes": {"比赛阶段": "小组赛"},
                },
                {
                    "uuid": "mexico",
                    "name": "Mexico national football team",
                    "labels": ["Entity", "FootballTeam"],
                    "summary": "墨西哥国家队",
                    "attributes": {"中文名": "墨西哥"},
                },
                {
                    "uuid": "korea",
                    "name": "Korea Republic national football team",
                    "labels": ["Entity", "FootballTeam"],
                    "summary": "韩国国家队",
                    "attributes": {"中文名": "韩国"},
                },
            ]

        def get_all_edges(self, graph_id: str) -> list[dict[str, Any]]:
            assert graph_id == "graph_multihost"
            return [
                {
                    "name": "HAS_TEAM",
                    "source_node_uuid": "match-current",
                    "target_node_uuid": "mexico",
                    "fact": '"team_a": "Mexico" in the match record for Mexico vs Korea Republic.',
                },
                {
                    "name": "HAS_TEAM",
                    "source_node_uuid": "match-current",
                    "target_node_uuid": "korea",
                    "fact": '"team_b": "Korea Republic" in the match record for Mexico vs Korea Republic.',
                },
            ]

    del postgres_db
    _patch_step2_dependencies(monkeypatch)
    monkeypatch.setattr("app.services.prediction_config.get_entity_reader", lambda: FakeGraphReader())
    monkeypatch.setattr("app.utils.llm_client.LLMClient", lambda: MixedReportDataLLM())
    _seed_project(
        "proj_multihost",
        "graph_multihost",
        simulation_requirement="严谨地预测这场比赛的过程和结果",
        extracted_text="""
=== 01.捷克vs南非赛前信息报告.md ===
# 捷克vs南非赛前信息报告
- FIFA Match Centre：Czechia vs South Africa，2026 FIFA World Cup Group A，Atlanta Stadium。
- 中立场属性：世界杯中立场。美国是主办国之一，但捷克和南非均非东道主。

=== 04.墨西哥vs韩国赛前信息报告.md ===
# 墨西哥vs韩国赛前信息报告
- 比赛双方：墨西哥 vs 韩国。
- 赛事阶段：A组第二轮小组赛。
- 比赛地点：Guadalajara Stadium，官方常用场馆名对应 Estadio Akron。
- 中立/主客属性：名义上是世界杯中立场，实际观众结构与地缘支持更偏向墨西哥。
""",
    )
    _seed_prediction_dataset("wc2026_fifa_v2", [("MEX", "Mexico", "墨西哥"), ("KOR", "Korea Republic", "韩国")])
    service = PredictionConfigService()

    result = service.prepare(
        project_id="proj_multihost",
        graph_id="graph_multihost",
        prediction_requirement="严谨地预测这场比赛的过程和结果",
        player_dataset_id="wc2026_fifa_v2",
        force_regenerate=True,
        llm_budget={"profile_key": "middle"},
    )
    config = service.get_config(result["prediction_config_id"])
    strengths = service.list_team_strengths(result["prediction_config_id"])
    home = next(row for row in strengths if row["team_role"] == "home")

    assert config["home_team"] == "Mexico"
    assert config["away_team"] == "Korea Republic"
    assert home["team_name"] == "Mexico"
    assert config["competition"]["neutral_venue"] is True
    assert config["competition"]["host_country_iso3"] == "MEX"
    assert home["home_away_adjustment"] == 20
    assert home["home_away_adjustment_reason"] == "host_country"


def test_match_identity_prefers_current_graph_match_over_recent_form_matches(monkeypatch):
    class FakeGraphReader:
        def get_all_nodes(self, graph_id: str) -> list[dict[str, Any]]:
            assert graph_id == "graph_belgium_egypt"
            return [
                {
                    "uuid": "match-recent",
                    "name": "埃及 vs 塞拉利昂",
                    "labels": ["Entity", "Match"],
                    "summary": "消息中列入埃及近10场可核验正式比赛：2025-03-25，埃及 vs 塞拉利昂，赛事为世预赛，结果为埃及1-0取胜。",
                    "attributes": {"比赛时间": "2025-03-25"},
                },
                {
                    "uuid": "match-current",
                    "name": "Belgium vs Egypt",
                    "labels": ["Entity", "Match"],
                    "summary": "比利时 vs 埃及为2026年FIFA世界杯G组小组赛，比赛地点为Seattle Stadium / Lumen Field, Seattle。",
                    "attributes": {
                        "比赛时间": "2026-06-15 19:00 UTC / 2026-06-16 03:00 北京时间",
                        "比赛阶段": "2026年FIFA世界杯G组小组赛（小组首战）",
                    },
                },
                {
                    "uuid": "belgium",
                    "name": "Belgium national football team",
                    "labels": ["Entity", "FootballTeam"],
                    "summary": "比利时国家队",
                    "attributes": {"中文名": "比利时"},
                },
                {
                    "uuid": "egypt",
                    "name": "Egypt national football team",
                    "labels": ["Entity", "FootballTeam"],
                    "summary": "埃及国家队",
                    "attributes": {"中文名": "埃及"},
                },
                {
                    "uuid": "sierra-leone",
                    "name": "塞拉利昂",
                    "labels": ["Entity", "FootballTeam"],
                    "summary": "塞拉利昂国家队",
                    "attributes": {},
                },
            ]

        def get_all_edges(self, graph_id: str) -> list[dict[str, Any]]:
            assert graph_id == "graph_belgium_egypt"
            return [
                {
                    "name": "HAS_PARTICIPANT",
                    "source_node_uuid": "match-recent",
                    "target_node_uuid": "egypt",
                    "fact": "2025-03-25 埃及 vs 塞拉利昂 世预赛 1-0",
                },
                {
                    "name": "HAS_PARTICIPANT",
                    "source_node_uuid": "match-recent",
                    "target_node_uuid": "sierra-leone",
                    "fact": "2025-03-25 埃及 vs 塞拉利昂 世预赛 1-0",
                },
                {
                    "name": "HAS_TEAM",
                    "source_node_uuid": "match-current",
                    "target_node_uuid": "belgium",
                    "fact": '"team_a": "Belgium" in the match record for Belgium vs Egypt.',
                },
                {
                    "name": "HAS_TEAM",
                    "source_node_uuid": "match-current",
                    "target_node_uuid": "egypt",
                    "fact": '"team_b": "Egypt" in the match record for Belgium vs Egypt.',
                },
            ]

    monkeypatch.setattr("app.services.prediction_config.get_entity_reader", lambda: FakeGraphReader())

    identity = _resolve_match_identity(
        requirement="严谨地预测这场比赛的过程和结果",
        source_text=(
            "=== 02.比利时vs埃及赛前信息报告.md ===\n"
            "# 比利时 vs 埃及赛前信息报告\n"
            "- 比赛：比利时 vs 埃及\n"
            "埃及近10场可核验正式比赛包括：2025-03-25 埃及 vs 塞拉利昂 世预赛 1-0。"
        ),
        graph_entities=[],
        graph_id="graph_belgium_egypt",
        home_team=None,
        away_team=None,
        normalizer=TeamNameNormalizer(),
    )

    assert identity == ("BEL", "EGY", "比利时", "埃及")


def test_match_identity_prefers_declared_source_pair_over_graph_first_round_matches(monkeypatch):
    class FakeGraphReader:
        def get_all_nodes(self, graph_id: str) -> list[dict[str, Any]]:
            assert graph_id == "graph_czechia_south_africa"
            return [
                {
                    "uuid": "match-first-round",
                    "name": "PMSR-M02 Korea Republic v Czechia",
                    "labels": ["Entity", "Match"],
                    "summary": "FIFA赛后报告记录的比赛：Korea Republic 2-1 Czechia，属于2026年世界杯A组首轮。",
                    "attributes": {"比赛阶段": "2026 FIFA World Cup group stage"},
                },
                {
                    "uuid": "korea",
                    "name": "Korea Republic",
                    "labels": ["Entity", "FootballTeam"],
                    "summary": "韩国国家队",
                    "attributes": {"中文名": "韩国"},
                },
                {
                    "uuid": "czechia",
                    "name": "Czechia",
                    "labels": ["Entity", "FootballTeam"],
                    "summary": "捷克国家队",
                    "attributes": {"中文名": "捷克"},
                },
            ]

        def get_all_edges(self, graph_id: str) -> list[dict[str, Any]]:
            assert graph_id == "graph_czechia_south_africa"
            return [
                {
                    "name": "HAS_TEAM",
                    "source_node_uuid": "match-first-round",
                    "target_node_uuid": "korea",
                    "fact": "Korea Republic was a participant in PMSR-M02 Korea Republic v Czechia.",
                },
                {
                    "name": "HAS_TEAM",
                    "source_node_uuid": "match-first-round",
                    "target_node_uuid": "czechia",
                    "fact": "Czechia was a participant in PMSR-M02 Korea Republic v Czechia.",
                },
            ]

    monkeypatch.setattr("app.services.prediction_config.get_entity_reader", lambda: FakeGraphReader())

    identity = _resolve_match_identity(
        requirement="严谨地预测这场比赛的过程和结果",
        source_text=(
            "# 捷克vs南非赛前信息报告\n"
            "- 比赛双方：捷克 Czechia vs 南非 South Africa。\n"
            "第一轮复盘：韩国 2-1 捷克；墨西哥 2-0 南非。"
        ),
        graph_entities=[],
        graph_id="graph_czechia_south_africa",
        home_team=None,
        away_team=None,
        normalizer=TeamNameNormalizer(),
    )

    assert identity == ("CZE", "RSA", "捷克", "南非")


def test_match_identity_resolves_democratic_congo_when_text_is_specific(monkeypatch):
    class FakeGraphReader:
        def get_all_nodes(self, graph_id: str) -> list[dict[str, Any]]:
            assert graph_id == "graph_portugal_congo_dr"
            return []

        def get_all_edges(self, graph_id: str) -> list[dict[str, Any]]:
            assert graph_id == "graph_portugal_congo_dr"
            return []

    monkeypatch.setattr("app.services.prediction_config.get_entity_reader", lambda: FakeGraphReader())

    identity = _resolve_match_identity(
        requirement="严谨地预测这场比赛的过程和结果",
        source_text=(
            "# 葡萄牙vs民主刚果赛前信息报告\n"
            "- 比赛双方：葡萄牙 Portugal vs 民主刚果/刚果（金）Congo DR。\n"
            "民主刚果 26 人名单摘要：Brian Cipenga、Yoane Wissa、Cedric Bakambu。"
        ),
        graph_entities=[],
        graph_id="graph_portugal_congo_dr",
        home_team=None,
        away_team=None,
        normalizer=TeamNameNormalizer(),
    )

    assert identity == ("POR", "COD", "葡萄牙", "刚果（金）")


def test_existing_ready_config_with_empty_roster_is_not_reusable():
    class Config:
        home_team = "葡萄牙"
        away_team = "刚果"
        model_input_snapshot = {
            "home_team": "葡萄牙",
            "away_team": "刚果",
            "home_iso3": "POR",
            "away_iso3": "CGO",
            "squads": {
                "home": {
                    "team_iso3": "POR",
                    "players": [{"id": "ply_por_1"}],
                },
                "away": {
                    "team_iso3": "CGO",
                    "players": [],
                },
            },
            "warnings": ["roster_missing_or_empty"],
        }

    assert _is_reusable_ready_config(Config()) is False


def test_team_strength_estimator_used_when_one_roster_side_is_empty(postgres_db, monkeypatch):
    del postgres_db
    _patch_step2_dependencies(monkeypatch)
    _seed_project("proj_missing_roster", "graph_missing_roster")
    _seed_prediction_dataset("dataset_missing_away", [("ARG", "Argentina", "阿根廷")])
    service = PredictionConfigService()

    result = service.prepare(
        project_id="proj_missing_roster",
        graph_id="graph_missing_roster",
        prediction_requirement="阿根廷 vs 法国 世界杯小组赛，中立场",
        home_team="阿根廷",
        away_team="法国",
        player_dataset_id="dataset_missing_away",
        force_regenerate=True,
        llm_budget={"profile_key": "low"},
    )

    strengths = service.list_team_strengths(result["prediction_config_id"])
    home = next(row for row in strengths if row["team_role"] == "home")
    away = next(row for row in strengths if row["team_role"] == "away")

    assert "roster_missing_or_empty" in result["warnings"]
    assert home["home_away_adjustment"] == 0
    assert home["home_away_adjustment_reason"] == "neutral_venue"
    assert home["metadata"]["source"] == "prediction_config_service_v2"
    assert away["team_iso3"] == "FRA"
    assert away["metadata"]["players_count"] == 0
    assert away["form_adjustment"] == 0


def _patch_step2_dependencies(monkeypatch) -> None:
    monkeypatch.setattr("app.services.prediction_config.GraphEvidenceQuery", FakeGraphEvidenceQuery)
    monkeypatch.setattr("app.services.prediction_config.ExternalDataPool", FakeExternalDataPool)
    monkeypatch.setattr("app.utils.llm_client.LLMClient", lambda: FakeLLM())


def _seed_project(
    project_id: str,
    graph_id: str,
    *,
    extracted_text: str = "阿根廷 vs 法国 世界杯半决赛",
    simulation_requirement: str = "阿根廷 vs 法国",
) -> None:
    with get_session() as session:
        session.add(
            ProjectRecord(
                project_id=project_id,
                name="Prediction config",
                status="graph_completed",
                files=[],
                total_text_length=0,
                extracted_text=extracted_text,
                analysis_summary="测试摘要",
                graph_id=graph_id,
                simulation_requirement=simulation_requirement,
                simulation_domain="football_match",
                chunk_size=500,
                chunk_overlap=50,
                project_metadata={},
            )
        )


def _ready_config_record(
    *,
    prediction_config_id: str,
    project_id: str,
    graph_id: str,
    home_iso3: str,
    away_iso3: str,
    home_team: str,
    away_team: str,
    created_at,
) -> PredictionConfigRecord:
    return PredictionConfigRecord(
        prediction_config_id=prediction_config_id,
        project_id=project_id,
        graph_id=graph_id,
        match_name=f"{home_team} vs {away_team}",
        home_team=home_team,
        away_team=away_team,
        status="ready",
        current_phase="ready",
        progress_percent=100,
        fit_status="uniform",
        data_sufficiency="insufficient",
        created_at=created_at,
        updated_at=created_at,
        model_input_snapshot={
            "home_team": home_team,
            "away_team": away_team,
            "home_iso3": home_iso3,
            "away_iso3": away_iso3,
            "squads": {
                "home": {"team_iso3": home_iso3, "team_name": home_team, "players": []},
                "away": {"team_iso3": away_iso3, "team_name": away_team, "players": []},
            },
        },
        config_metadata={},
    )


def _seed_prediction_dataset(dataset_id: str, teams: list[tuple[str, str, str]]) -> None:
    from app.db.models import PredictionPlayerDatasetRecord, PredictionPlayerRecord, PredictionTeamMetadataRecord

    positions = ["GK", "CB", "CB", "FB", "FB", "DM", "CM", "AM", "WG", "WG", "ST"]
    with get_session() as session:
        session.add(
            PredictionPlayerDatasetRecord(
                dataset_id=dataset_id,
                source_label="test",
                scope_label="fifa_world_cup_2026_squads",
                ratings_schema={},
                teams_count=len(teams),
                players_count=len(teams) * 11,
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
                session.add(
                    PredictionPlayerRecord(
                        id=f"ply_{dataset_id}_{iso3}_{index:02d}",
                        dataset_id=dataset_id,
                        team_name=team_fifa,
                        team_iso3=iso3,
                        player_external_id=f"{iso3}_{index}",
                        full_name=f"{team_zh}球员{index}",
                        full_name_en=f"{team_fifa} Player {index}",
                        full_name_alt=[],
                        position_primary=position,
                        position_secondary=[],
                        age=24 + index % 8,
                        foot="R",
                        height_cm=180,
                        ratings={},
                        derived={
                            "overall": 70 + index,
                            "attack": 68 + index,
                            "defense": 66 + index,
                            "pace": 67 + index,
                            "finishing": 65 + index,
                            "passing": 66 + index,
                            "set_piece": 64 + index,
                            "gk": 82 if position == "GK" else 0,
                        },
                        availability={"status": "available"},
                        expected_role="starter",
                        expected_minutes_share=0.95,
                        shirt_number=index,
                        position_class="GK" if position == "GK" else "FW" if position in {"ST", "WG"} else "MF",
                        caps_intl=10,
                        goals_intl=2,
                        club_fifa="Test FC",
                        player_metadata={},
                    )
                )


def _add_extra_prediction_players(dataset_id: str, iso3: str, team_fifa: str, team_zh: str, count: int) -> None:
    from app.db.models import PredictionPlayerRecord

    with get_session() as session:
        for index in range(12, 12 + count):
            session.add(
                PredictionPlayerRecord(
                    id=f"ply_{dataset_id}_{iso3}_extra_{index:02d}",
                    dataset_id=dataset_id,
                    team_name=team_fifa,
                    team_iso3=iso3,
                    player_external_id=f"{iso3}_extra_{index}",
                    full_name=f"{team_zh}替补{index}",
                    full_name_en=f"{team_fifa} Extra {index}",
                    full_name_alt=[],
                    position_primary="MF",
                    position_secondary=[],
                    age=24 + index % 8,
                    foot="R",
                    height_cm=180,
                    ratings={},
                    derived={
                        "overall": 70,
                        "attack": 68,
                        "defense": 66,
                        "pace": 67,
                        "finishing": 65,
                        "passing": 66,
                        "set_piece": 64,
                        "gk": 0,
                    },
                    availability={"status": "available"},
                    expected_role="bench",
                    expected_minutes_share=0.2,
                    shirt_number=index,
                    position_class="MF",
                    caps_intl=5,
                    goals_intl=1,
                    club_fifa="Test FC",
                    player_metadata={},
                )
            )

from pathlib import Path

import pytest

from app.db.models import (
    GraphMetadataRecord,
    PredictionConfigRecord,
    PredictionMatchEventRecord,
    PredictionPlayerDatasetRecord,
    PredictionReportRecord,
    PredictionRunRecord,
    PredictionScenarioCaseRecord,
    PredictionScenarioSpaceRecord,
)
from app.db.session import get_session
from app.services import graphiti_metadata
from app.services.football_prediction import PredictionPersistenceService, PredictionReportAssembler
from app.services.report_agent import ReportManager


@pytest.fixture()
def db_storage(tmp_path, monkeypatch, postgres_db):
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(graphiti_metadata, "GRAPHITI_META_DIR", str(tmp_path / "graphiti"))
    return tmp_path


def test_graphiti_metadata_uses_database_without_local_json(db_storage):
    graphiti_metadata.save_graph_metadata(
        "goalfish_graph_db",
        {"name": "DB Graph", "ontology": {"entities": ["FootballTeam"]}},
    )

    legacy_path = Path(graphiti_metadata.GRAPHITI_META_DIR) / "goalfish_graph_db.json"
    assert not legacy_path.exists()

    loaded = graphiti_metadata.load_graph_metadata("goalfish_graph_db")

    assert loaded["graph_id"] == "goalfish_graph_db"
    assert loaded["name"] == "DB Graph"
    with get_session() as session:
        assert session.get(GraphMetadataRecord, "goalfish_graph_db") is not None


def test_prediction_artifacts_are_database_backed_and_replayable(db_storage):
    status = PredictionPersistenceService().create_completed_prediction(
        project_id="proj_prediction_db",
        graph_id="graph_prediction_db",
        simulation_requirement="预测阿根廷 vs 法国的比分和关键事件",
        home_team="阿根廷",
        away_team="法国",
        competition="世界杯",
    )
    run_id = status["prediction_run_id"]

    assert status["status"] == "completed"
    assert status["counts"]["scenario_cases"] == 9
    assert status["counts"]["scenario_spaces"] == 6
    assert status["counts"]["match_events"] >= 6

    with get_session() as session:
        run = session.get(PredictionRunRecord, run_id)
        assert run is not None
        assert run.match_name == "阿根廷 vs 法国"
        assert run.competition == "世界杯"
        assert session.query(PredictionScenarioCaseRecord).filter_by(prediction_run_id=run_id).count() == 9
        assert session.query(PredictionScenarioSpaceRecord).filter_by(prediction_run_id=run_id).count() == 6
        assert session.query(PredictionMatchEventRecord).filter_by(prediction_run_id=run_id).count() >= 6


def test_prediction_report_progress_and_logs_are_database_backed(db_storage):
    report_id = "report_db_logs"

    ReportManager.update_progress(report_id, "generating", 42, "正在生成", current_section="走势")
    ReportManager.append_agent_log(report_id, {"action": "tool_call", "stage": "generating"})
    ReportManager.append_console_log_line(report_id, "[10:00:00] INFO: hello")

    assert not Path(ReportManager._get_report_folder(report_id)).exists()
    assert ReportManager.get_progress(report_id)["progress"] == 42
    assert ReportManager.get_agent_log(report_id)["logs"][0]["action"] == "tool_call"
    assert ReportManager.get_console_log(report_id)["logs"] == ["[10:00:00] INFO: hello"]

    with get_session() as session:
        record = session.get(ReportManager._report_record_class(), report_id)
        assert record.simulation_domain == "football_match"
        assert record.report_metadata["progress"]["current_section"] == "走势"


def test_prediction_report_sections_are_saved_in_database(db_storage):
    status = PredictionPersistenceService().create_completed_prediction(
        project_id="proj_report_db",
        graph_id="graph_report_db",
        simulation_requirement="预测巴西 vs 德国的胜平负、比分和高波动事件",
    )
    report = PredictionReportAssembler().create_report(status["prediction_run_id"])

    with get_session() as session:
        record = session.get(PredictionReportRecord, report["report_id"])
        assert record is not None
        assert record.status == "completed"
        assert record.simulation_domain == "football_match"
        assert record.markdown_content
        assert [section.title for section in record.sections] == [
            "比赛结论摘要",
            "双方基本面与图谱证据",
            "战术、阵型与预计首发",
            "胜平负与比分预测",
            "关键比赛事件剧本",
            "风险、不确定性与可信度说明",
        ]
        assert "## 01 比赛结论摘要" in record.markdown_content
        assert "一句话结论" in record.markdown_content
        assert "为什么" in record.markdown_content


def test_prediction_report_includes_reader_friendly_credibility_details(db_storage):
    status = PredictionPersistenceService().create_completed_prediction(
        project_id="proj_report_budget",
        graph_id="graph_report_budget",
        simulation_requirement="预测巴西 vs 德国的胜平负、比分和高波动事件",
        home_team="巴西",
        away_team="德国",
    )
    run_id = status["prediction_run_id"]
    config_id = "cfg_report_budget"
    dataset_id = "ds_report_budget"

    with get_session() as session:
        session.add(
            PredictionPlayerDatasetRecord(
                dataset_id=dataset_id,
                source_label="test_upload",
                scope_label="fifa_world_cup_2026_squads",
                ratings_schema={},
                teams_count=2,
                players_count=52,
            )
        )
        session.add(
            PredictionConfigRecord(
                prediction_config_id=config_id,
                project_id="proj_report_budget",
                graph_id="graph_report_budget",
                match_name="巴西 vs 德国",
                home_team="巴西",
                away_team="德国",
                status="ready",
                current_phase="ready",
                progress_percent=100,
                player_dataset_id=dataset_id,
                llm_budget_profile={
                    "profile": {
                        "profile_key": "middle",
                        "coach_panel_roles": ["head_coach", "attack"],
                        "coach_deliberation_rounds": 1,
                        "enable_llm_data_extraction": True,
                        "narrative_polish_count": 1,
                        "analyst_note_groups": ["baseline"],
                        "coach_review_roles": ["risk"],
                        "n_sims": 2000,
                        "enable_statsbomb": True,
                        "hard_cap_calls": 25,
                    },
                    "ledger_summary": {
                        "total_calls": 2,
                        "cached": 1,
                        "spent": 1,
                        "hard_cap": 25,
                        "total_tokens": 1000,
                        "total_cost_usd": 0.003,
                        "avg_latency_ms": 1200,
                        "by_role": {
                            "data_extractor": {"calls": 1, "cached": 0, "tokens": 800, "cost": 0.002},
                            "coach_head_coach": {"calls": 1, "cached": 1, "tokens": 0, "cost": 0},
                        },
                        "failures": [],
                    },
                },
                model_input_snapshot={
                    "external_sources_etag": {
                        "intl_results": {
                            "source": "intl_results",
                            "fetched_at": "2026-06-10T00:00:00Z",
                            "row_count": 47318,
                        }
                    },
                    "squads": {
                        "home": {
                            "team_name": "Brazil",
                            "team_iso3": "BRA",
                            "players": [{} for _ in range(26)],
                            "stats": {"available": 22, "injured": 1, "suspended": 1, "doubtful": 2},
                        },
                        "away": {
                            "team_name": "Germany",
                            "team_iso3": "GER",
                            "players": [{} for _ in range(26)],
                            "stats": {"available": 23, "injured": 0, "suspended": 1, "doubtful": 2},
                        },
                    },
                    "warnings": ["StatsBomb unavailable; using fitted blend fallback"],
                },
                config_metadata={},
            )
        )
        run = session.get(PredictionRunRecord, run_id)
        run.prediction_config_id = config_id
        run.run_metadata = {
            **(run.run_metadata or {}),
            "ledger_summary": {
                "total_calls": 1,
                "cached": 0,
                "spent": 1,
                "hard_cap": 25,
                "total_tokens": 300,
                "total_cost_usd": 0.001,
                "avg_latency_ms": 900,
                "by_role": {
                    "analyst_notes": {"calls": 1, "cached": 0, "tokens": 300, "cost": 0.001},
                },
                "failures": [],
            },
        }

    report = PredictionReportAssembler().create_report(run_id)

    with get_session() as session:
        record = session.get(PredictionReportRecord, report["report_id"])
        markdown = record.markdown_content
        assert "风险、不确定性与可信度说明" in markdown
        assert "数据可信度" in markdown or "可信度" in markdown
        assert "主队可用 22/26" in markdown
        assert "客队可用 23/26" in markdown
        assert "international_results" in markdown
        assert "StatsBomb unavailable; using fitted blend fallback" in markdown
        assert "dataset_id:" not in markdown
        assert "实际调用 3 / 25 次" not in markdown


def test_football_prediction_schema_does_not_include_retired_social_tables(db_storage):
    from sqlalchemy import inspect
    from app.db.session import get_engine

    table_names = set(inspect(get_engine()).get_table_names())

    assert "prediction_runs" in table_names
    assert "prediction_match_events" in table_names
    assert {
        "simulations",
        "simulation_posts",
        "simulation_comments",
        "simulation_actions",
        "simulation_traces",
    }.isdisjoint(table_names)

import shutil
import json
from pathlib import Path

import pytest
from flask import Flask

from app.api import report_bp
from app.db.models import (
    PredictionReportRecord,
    PredictionReportSectionRecord,
    ReportConversationMessageRecord,
    ReportConversationRecord,
)
from app.db.session import get_session
from app.services.report_agent import (
    Report,
    ReportManager,
    ReportOutline,
    ReportSection,
    ReportStatus,
)
from app.services.football_prediction import PredictionPersistenceService, PredictionReportAssembler


@pytest.fixture()
def report_storage(tmp_path, monkeypatch, postgres_db):
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    yield


def _report(
    report_id: str,
    simulation_id: str = "sim_1",
    created_at: str = "2026-06-09T10:00:00",
    markdown_content: str = "# 韩国 vs 捷克预测报告\n\n正文",
) -> Report:
    outline = ReportOutline(
        title="韩国 vs 捷克预测报告",
        summary="预测摘要",
        sections=[
            ReportSection(title="比赛态势"),
            ReportSection(title="关键球员"),
        ],
    )
    return Report(
        report_id=report_id,
        simulation_id=simulation_id,
        graph_id="goalfish_graph_1",
        simulation_requirement="严谨预测比赛过程和结果",
        simulation_domain="football_match",
        status=ReportStatus.COMPLETED,
        outline=outline,
        markdown_content=markdown_content,
        created_at=created_at,
        completed_at="2026-06-09T10:30:00",
    )


def test_save_report_persists_metadata_outline_and_markdown_to_database(report_storage):
    report = _report("report_db_1")

    ReportManager.save_report(report)

    with get_session() as session:
        record = session.get(PredictionReportRecord, report.report_id)
        assert record is not None
        assert record.simulation_id == "sim_1"
        assert record.graph_id == "goalfish_graph_1"
        assert record.simulation_domain == "football_match"
        assert record.status == "completed"
        assert record.title == "韩国 vs 捷克预测报告"
        assert record.summary == "预测摘要"
        assert record.markdown_content == report.markdown_content
        assert record.report_metadata["outline"]["sections"][0]["title"] == "比赛态势"


def test_get_report_reads_from_database_when_files_are_missing(report_storage):
    report = _report("report_db_2")
    ReportManager.save_report(report)
    with get_session() as session:
        record = session.get(PredictionReportRecord, report.report_id)
        record.report_metadata = {
            **(record.report_metadata or {}),
            "evidence_package": {
                "match_events_count": 77,
                "scorelines_count": 9,
            },
        }
    shutil.rmtree(ReportManager._get_report_folder(report.report_id), ignore_errors=True)

    loaded = ReportManager.get_report(report.report_id)

    assert loaded is not None
    assert loaded.report_id == report.report_id
    assert loaded.simulation_id == report.simulation_id
    assert loaded.outline is not None
    assert loaded.outline.title == "韩国 vs 捷克预测报告"
    assert loaded.markdown_content == report.markdown_content
    assert loaded.to_dict()["report_metadata"]["evidence_package"]["match_events_count"] == 77


def test_save_section_persists_section_markdown_to_database(report_storage):
    report = _report("report_db_3")
    ReportManager.save_report(report)

    ReportManager.save_section(
        report.report_id,
        1,
        ReportSection(title="关键球员", content="### 李在城\n他是关键中场。"),
    )
    shutil.rmtree(ReportManager._get_report_folder(report.report_id), ignore_errors=True)

    with get_session() as session:
        section = (
            session.query(PredictionReportSectionRecord)
            .filter_by(report_id=report.report_id, section_index=1)
            .one()
        )
        assert section.title == "关键球员"
        assert section.content.startswith("## 关键球员")
        assert "**李在城**" in section.content

    sections = ReportManager.get_generated_sections(report.report_id)
    assert sections == [
        {
            "filename": "section_01.md",
            "section_index": 1,
            "content": "## 关键球员\n\n**李在城**\n\n他是关键中场。\n\n",
        }
    ]


def test_report_lookup_and_listing_use_database_not_report_directory(report_storage):
    first = _report("report_db_4", simulation_id="sim_old", created_at="2026-06-09T09:00:00")
    second = _report("report_db_5", simulation_id="sim_new", created_at="2026-06-09T11:00:00")
    ReportManager.save_report(first)
    ReportManager.save_report(second)
    shutil.rmtree(ReportManager.REPORTS_DIR, ignore_errors=True)

    by_simulation = ReportManager.get_report_by_simulation("sim_new")
    listed = ReportManager.list_reports(limit=10)
    filtered = ReportManager.list_reports(simulation_id="sim_old", limit=10)

    assert by_simulation is not None
    assert by_simulation.report_id == "report_db_5"
    assert [report.report_id for report in listed] == ["report_db_5", "report_db_4"]
    assert [report.report_id for report in filtered] == ["report_db_4"]


def test_delete_report_removes_database_rows_and_file_artifacts(report_storage):
    report = _report("report_db_6")
    ReportManager.save_report(report)
    ReportManager.save_section(report.report_id, 1, ReportSection(title="比赛态势", content="正文"))
    conversation = ReportManager.get_or_create_conversation(report_id=report.report_id)
    ReportManager.append_conversation_message(
        conversation_id=conversation["id"],
        role="user",
        content="请解释一下比赛走势",
    )
    assert not Path(ReportManager._get_report_folder(report.report_id)).exists()

    deleted = ReportManager.delete_report(report.report_id)

    assert deleted is True
    assert ReportManager.get_report(report.report_id) is None
    with get_session() as session:
        assert session.get(PredictionReportRecord, report.report_id) is None
        assert (
            session.query(ReportConversationRecord)
            .filter_by(report_id=report.report_id)
            .count()
            == 0
        )
        assert session.query(ReportConversationMessageRecord).count() == 0
        assert (
            session.query(PredictionReportSectionRecord)
            .filter_by(report_id=report.report_id)
            .count()
            == 0
        )


def test_report_conversation_messages_are_persisted_in_database(report_storage):
    report = _report("report_db_chat")
    ReportManager.save_report(report)

    conversation = ReportManager.get_or_create_conversation(
        report_id=report.report_id,
        target_type="report_agent",
        title="赛后追问",
    )
    same_conversation = ReportManager.get_or_create_conversation(
        report_id=report.report_id,
        target_type="report_agent",
    )
    user_message = ReportManager.append_conversation_message(
        conversation_id=conversation["id"],
        role="user",
        content="为什么预测 2-1？",
    )
    assistant_message = ReportManager.append_conversation_message(
        conversation_id=conversation["id"],
        role="assistant",
        content="因为主队边路优势更稳定。",
        tool_calls=[{"name": "graph_search"}],
        sources=["球队边路优势"],
    )

    conversations = ReportManager.list_conversations(report.report_id)
    messages = ReportManager.list_conversation_messages(conversation["id"])

    assert same_conversation["id"] == conversation["id"]
    assert conversations[0]["id"] == conversation["id"]
    assert user_message["role"] == "user"
    assert assistant_message["tool_calls"] == [{"name": "graph_search"}]
    assert [message["content"] for message in messages] == [
        "为什么预测 2-1？",
        "因为主队边路优势更稳定。",
    ]

    shutil.rmtree(ReportManager.REPORTS_DIR, ignore_errors=True)
    loaded_messages = ReportManager.list_conversation_messages(conversation["id"])
    assert loaded_messages[-1]["sources"] == ["球队边路优势"]


def test_report_conversation_api_persists_chat_messages(report_storage):
    status = PredictionPersistenceService().create_completed_prediction(
        project_id="proj_api_chat",
        graph_id="graph_api_chat",
        simulation_requirement="预测阿根廷 vs 法国的比分和关键事件",
    )
    report_payload = PredictionReportAssembler().create_report(status["prediction_run_id"])
    report_id = report_payload["report_id"]

    app = Flask(__name__)
    app.register_blueprint(report_bp, url_prefix="/api/report")
    client = app.test_client()

    conversation_response = client.post(
        f"/api/report/{report_id}/conversations",
        json={"target_type": "report_agent"},
    )
    conversation_data = conversation_response.get_json()["data"]

    message_response = client.post(
        f"/api/report/{report_id}/conversations/{conversation_data['id']}/messages",
        json={"message": "请解释比分"},
    )
    messages_response = client.get(
        f"/api/report/{report_id}/conversations/{conversation_data['id']}/messages"
    )

    assert conversation_response.status_code == 200
    assert message_response.status_code == 200
    message_data = message_response.get_json()["data"]
    assert "我基于已保存的足球预测产物回答" not in message_data["assistant_message"]["content"]
    assert "报告" in message_data["assistant_message"]["content"]
    assert "最可能比分" in message_data["assistant_message"]["content"]
    assert message_data["assistant_message"]["tool_calls"][0]["tool_name"] == "scoreline_distribution"
    messages = messages_response.get_json()["data"]["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]


def test_migrate_reports_script_imports_legacy_report_directory(report_storage):
    from scripts.migrate_reports_to_db import migrate_reports_to_db

    report_id = "report_legacy_1"
    report_dir = Path(ReportManager.REPORTS_DIR) / report_id
    report_dir.mkdir(parents=True)
    meta = _report(report_id, simulation_id="sim_legacy").to_dict()
    meta["markdown_content"] = ""
    (report_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    (report_dir / "outline.json").write_text(
        json.dumps(
            {
                "title": "旧报告标题",
                "summary": "旧报告摘要",
                "sections": [{"title": "旧章节"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (report_dir / "full_report.md").write_text("# 旧报告标题\n\n完整正文", encoding="utf-8")
    (report_dir / "section_01.md").write_text("## 旧章节\n\n章节正文", encoding="utf-8")
    (report_dir / "progress.json").write_text(
        json.dumps({"status": "generating", "progress": 50, "message": "处理中"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (report_dir / "agent_log.jsonl").write_text(
        json.dumps({"action": "tool_call", "stage": "generating"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (report_dir / "console_log.txt").write_text("[10:00:00] INFO: legacy\n", encoding="utf-8")

    results = migrate_reports_to_db()

    assert results[0]["report_id"] == report_id
    assert results[0]["status"] == "migrated"
    assert results[0]["sections"] == 1
    assert results[0]["has_progress"] is True
    assert results[0]["agent_log_entries"] == 1
    assert results[0]["console_log_lines"] == 1

    shutil.rmtree(ReportManager.REPORTS_DIR, ignore_errors=True)
    report = ReportManager.get_report(report_id)
    sections = ReportManager.get_generated_sections(report_id)

    assert report is not None
    assert report.markdown_content == "# 旧报告标题\n\n完整正文"
    assert report.outline is not None
    assert report.outline.title == "旧报告标题"
    assert sections[0]["content"] == "## 旧章节\n\n章节正文"
    assert ReportManager.get_progress(report_id)["progress"] == 50
    assert ReportManager.get_agent_log(report_id)["logs"][0]["action"] == "tool_call"
    assert ReportManager.get_console_log(report_id)["logs"] == ["[10:00:00] INFO: legacy"]

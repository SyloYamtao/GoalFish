from __future__ import annotations

import pytest
from flask import Flask

from app.api import projects_bp, report_bp
from app.db.models import (
    PredictionConfigRecord,
    PredictionReportRecord,
    PredictionReportSectionRecord,
    PredictionResultRecord,
    PredictionRunRecord,
    ProjectRecord,
    ReportConversationRecord,
    utc_now,
)
from app.db.session import get_session
from app.models.project import ProjectManager, ProjectStatus
from app.services.football_prediction import PredictionReportAssembler
from app.services.project_workflow import ProjectWorkflowService


def _create_app() -> Flask:
    app = Flask(__name__)
    app.register_blueprint(projects_bp, url_prefix="/api/projects")
    app.register_blueprint(report_bp, url_prefix="/api/report")
    return app


def _seed_completed_workflow(project_id: str = "proj_lineage") -> dict[str, str]:
    graph_id = f"{project_id}_graph"
    config_id = f"{project_id}_config"
    run_id = f"{project_id}_run"
    report_id = f"{project_id}_report"

    with get_session() as session:
        session.add(
            ProjectRecord(
                project_id=project_id,
                name="Lineage Test",
                status="report_completed",
                graph_id=graph_id,
                extracted_text="Portugal vs Congo DR",
                simulation_requirement="预测葡萄牙 vs 刚果（金）",
                project_metadata={
                    "workflow_revision": 1,
                    "current_step": 5,
                    "active_artifacts": {
                        "graph_id": graph_id,
                        "prediction_config_id": config_id,
                        "prediction_run_id": run_id,
                        "report_id": report_id,
                    },
                },
            )
        )
        session.add(
            PredictionConfigRecord(
                prediction_config_id=config_id,
                project_id=project_id,
                graph_id=graph_id,
                match_name="葡萄牙 vs 刚果（金）",
                home_team="葡萄牙",
                away_team="刚果（金）",
                status="ready",
                current_phase="ready",
                progress_percent=100,
                model_name="dixon_coles_decay",
                model_version="v2",
                fit_status="fitted",
                data_sufficiency="sufficient",
                source_document_ids=[],
                graph_snapshot={},
                model_input_snapshot={},
                scenario_design_summary={},
                resume_policy_summary={},
                coach_jury_summary={},
                player_dataset_id="wc2026_fifa_v2",
                llm_budget_profile={},
                progress_messages=[],
                completed_at=utc_now(),
                config_metadata={
                    "artifact_status": "active",
                    "workflow_revision": 1,
                },
            )
        )
        session.add(
            PredictionRunRecord(
                prediction_run_id=run_id,
                prediction_config_id=config_id,
                project_id=project_id,
                graph_id=graph_id,
                match_name="葡萄牙 vs 刚果（金）",
                home_team="葡萄牙",
                away_team="刚果（金）",
                status="completed",
                current_phase="completed",
                progress_percent=100,
                completed_at=utc_now(),
                run_metadata={
                    "artifact_status": "active",
                    "workflow_revision": 1,
                    "prediction_config_id": config_id,
                },
            )
        )
        session.flush()
        session.add(
            PredictionResultRecord(
                prediction_run_id=run_id,
                baseline_prediction={},
                scenario_cases_summary={},
                scenario_spaces_summary={},
                scoreline_summary={
                    "most_likely_score": "2-0",
                    "win_draw_loss_probability": {"home_win": 62, "draw": 22, "away_win": 16},
                },
                match_events_summary={},
                analyst_notes_summary={},
                final_score_hypothesis={"score": "2-0"},
                uncertainty_factors=[],
                confidence=74,
                result_metadata={},
            )
        )
        session.add(
            PredictionReportRecord(
                report_id=report_id,
                simulation_id=run_id,
                graph_id=graph_id,
                simulation_requirement="预测葡萄牙 vs 刚果（金）",
                simulation_domain="football_match",
                status="completed",
                title="葡萄牙 vs 刚果（金）赛事预测报告",
                summary="葡萄牙 2-0 刚果（金）",
                markdown_content="# 报告\n",
                completed_at=utc_now(),
                report_metadata={
                    "artifact_status": "active",
                    "workflow_revision": 1,
                    "prediction_run_id": run_id,
                    "prediction_config_id": config_id,
                },
            )
        )
        session.add(
            PredictionReportSectionRecord(
                report_id=report_id,
                section_index=1,
                title="比赛结论摘要",
                content="## 比赛结论摘要\n",
                section_metadata={"artifact_status": "active", "workflow_revision": 1},
            )
        )
        conversation = ReportConversationRecord(
            report_id=report_id,
            simulation_id=run_id,
            target_type="report_agent",
            title="Report Agent",
            conversation_metadata={"artifact_status": "active", "workflow_revision": 1},
        )
        session.add(conversation)

    return {
        "project_id": project_id,
        "graph_id": graph_id,
        "prediction_config_id": config_id,
        "prediction_run_id": run_id,
        "report_id": report_id,
    }


def _artifact_statuses(ids: dict[str, str]) -> dict[str, str | None]:
    with get_session() as session:
        config = session.get(PredictionConfigRecord, ids["prediction_config_id"])
        run = session.get(PredictionRunRecord, ids["prediction_run_id"])
        report = session.get(PredictionReportRecord, ids["report_id"])
        section = session.query(PredictionReportSectionRecord).filter_by(report_id=ids["report_id"]).one()
        conversation = session.query(ReportConversationRecord).filter_by(report_id=ids["report_id"]).one()
        return {
            "config": (config.config_metadata or {}).get("artifact_status"),
            "run": (run.run_metadata or {}).get("artifact_status"),
            "report": (report.report_metadata or {}).get("artifact_status"),
            "section": (section.section_metadata or {}).get("artifact_status"),
            "conversation": (conversation.conversation_metadata or {}).get("artifact_status"),
        }


def test_regenerate_step2_invalidates_step2_to_step5_active_artifacts(postgres_db):
    ids = _seed_completed_workflow()

    state = ProjectWorkflowService().regenerate_step(ids["project_id"], 2, reason="user_requested")

    assert state["invalidated_steps"] == [2, 3, 4, 5]
    assert state["current_step"] == 2
    assert state["active_artifacts"] == {
        "graph_id": ids["graph_id"],
        "prediction_config_id": None,
        "prediction_run_id": None,
        "report_id": None,
    }
    assert _artifact_statuses(ids) == {
        "config": "superseded",
        "run": "superseded",
        "report": "superseded",
        "section": "superseded",
        "conversation": "superseded",
    }


def test_regenerate_step3_keeps_active_step1_and_step2(postgres_db):
    ids = _seed_completed_workflow("proj_step3")

    state = ProjectWorkflowService().regenerate_step(ids["project_id"], 3, reason="user_requested")

    assert state["invalidated_steps"] == [3, 4, 5]
    assert state["current_step"] == 3
    assert state["active_artifacts"]["graph_id"] == ids["graph_id"]
    assert state["active_artifacts"]["prediction_config_id"] == ids["prediction_config_id"]
    assert state["active_artifacts"]["prediction_run_id"] is None
    assert state["active_artifacts"]["report_id"] is None
    assert _artifact_statuses(ids)["config"] == "active"
    assert _artifact_statuses(ids)["run"] == "superseded"


def test_regenerate_step4_keeps_active_step1_to_step3(postgres_db):
    ids = _seed_completed_workflow("proj_step4")

    state = ProjectWorkflowService().regenerate_step(ids["project_id"], 4, reason="user_requested")

    assert state["invalidated_steps"] == [4, 5]
    assert state["current_step"] == 4
    assert state["active_artifacts"]["graph_id"] == ids["graph_id"]
    assert state["active_artifacts"]["prediction_config_id"] == ids["prediction_config_id"]
    assert state["active_artifacts"]["prediction_run_id"] == ids["prediction_run_id"]
    assert state["active_artifacts"]["report_id"] is None
    statuses = _artifact_statuses(ids)
    assert statuses["config"] == "active"
    assert statuses["run"] == "active"
    assert statuses["report"] == "superseded"
    assert statuses["conversation"] == "superseded"

    project = ProjectManager.get_project(ids["project_id"])
    assert project is not None
    assert project.status == ProjectStatus.PREDICTION_COMPLETED
    assert project.to_dict()["status"] == "prediction_completed"


def test_step4_create_report_rejects_superseded_prediction_run(postgres_db):
    ids = _seed_completed_workflow("proj_superseded_report")
    ProjectWorkflowService().regenerate_step(ids["project_id"], 3, reason="user_requested")

    with pytest.raises(ValueError, match="Step3 场景推演已失效"):
        PredictionReportAssembler().create_report(ids["prediction_run_id"], force_regenerate=True)


def test_workflow_state_recovers_from_database_after_service_restart(postgres_db):
    ids = _seed_completed_workflow("proj_recover")

    state = ProjectWorkflowService().get_state(ids["project_id"])

    assert state["current_step"] == 5
    assert state["workflow_revision"] == 1
    assert state["active_artifacts"]["graph_id"] == ids["graph_id"]
    assert state["active_artifacts"]["prediction_config_id"] == ids["prediction_config_id"]
    assert state["active_artifacts"]["prediction_run_id"] == ids["prediction_run_id"]
    assert state["active_artifacts"]["report_id"] == ids["report_id"]


def test_regenerate_api_returns_workflow_payload(postgres_db):
    ids = _seed_completed_workflow("proj_api_lineage")
    client = _create_app().test_client()

    response = client.post(
        f"/api/projects/{ids['project_id']}/steps/2/regenerate",
        json={"reason": "user_requested", "preserve_history": True},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["project_id"] == ids["project_id"]
    assert payload["regenerated_from_step"] == 2
    assert payload["invalidated_steps"] == [2, 3, 4, 5]
    assert payload["current_step"] == 2
    assert payload["active_artifacts"]["prediction_config_id"] is None


def test_superseded_report_can_be_viewed_but_not_used_for_conversation(postgres_db):
    ids = _seed_completed_workflow("proj_historical_report")
    ProjectWorkflowService().regenerate_step(ids["project_id"], 4, reason="user_requested")
    client = _create_app().test_client()

    detail_response = client.get(f"/api/report/{ids['report_id']}")
    sections_response = client.get(f"/api/report/{ids['report_id']}/sections")
    conversations_response = client.get(f"/api/report/{ids['report_id']}/conversations")

    assert detail_response.status_code == 200
    detail_payload = detail_response.get_json()["data"]
    assert detail_payload["project_id"] == ids["project_id"]
    assert detail_payload["is_active_report"] is False
    assert detail_payload["artifact_status"] == "superseded"
    assert detail_payload["report_metadata"]["is_active_report"] is False
    assert detail_payload["report_metadata"]["project_id"] == ids["project_id"]

    assert sections_response.status_code == 200
    sections_payload = sections_response.get_json()["data"]
    assert sections_payload["sections"][0]["section_index"] == 1
    assert "比赛结论摘要" in sections_payload["sections"][0]["content"]

    assert conversations_response.status_code == 409
    assert "Step4 报告已失效" in conversations_response.get_json()["error"]


def test_report_lineage_treats_non_active_pointer_as_superseded(postgres_db):
    ids = _seed_completed_workflow("proj_legacy_active_report")
    with get_session() as session:
        project = session.get(ProjectRecord, ids["project_id"])
        metadata = dict(project.project_metadata or {})
        workflow = dict(metadata.get("workflow") or {})
        active = dict((workflow.get("active_artifacts") or metadata.get("active_artifacts") or {}))
        active["report_id"] = "report_other_active"
        workflow["active_artifacts"] = active
        metadata["workflow"] = workflow
        metadata["active_artifacts"] = active
        project.project_metadata = metadata

    lineage = ProjectWorkflowService().report_lineage_info(ids["report_id"])

    assert lineage["stored_artifact_status"] == "active"
    assert lineage["artifact_status"] == "superseded"
    assert lineage["is_active_report"] is False
    assert lineage["active_report_id"] == "report_other_active"

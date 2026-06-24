"""Step2 prediction config preparation service."""

from __future__ import annotations

import hashlib
import os
import re
import time
from dataclasses import asdict
from typing import Any

from ..db.models import (
    PredictionCoachAgentRecord,
    PredictionCoachDiscussionRecord,
    PredictionCoachVoteRecord,
    PredictionConfigRecord,
    PredictionConfigResumeNodeRecord,
    PredictionConfigScenarioCaseRecord,
    PredictionPlayerDatasetRecord,
    PredictionPlayerRecord,
    PredictionTeamStrengthRecord,
    ProjectRecord,
    utc_now,
)
from ..db.session import get_session
from .coach_jury import CoachJuryService, SCENARIO_TEMPLATE, resume_policy_summary
from .coach_llm_panel import CoachLLMPanel, CoachPanelInputs, PANEL_VERSION, ROLE_BY_KEY
from .content_language import build_content_language_instruction, detect_content_language
from .external_data.team_name_normalizer import TeamNameNormalizer
from .football_data_extractor import EXTRACTOR_VERSION, FootballDataExtractor, infer_2026_world_cup_host_country
from .football_goal_model import ExternalDataPool, FitArtifacts, FootballGoalModelAdapter, extract_structured_match_inputs
from .football_prediction import FootballPredictionEngine
from .graph_backend_factory import get_entity_reader
from .graph_evidence_query import GraphEvidenceQuery
from .llm_budget import LLMCallLedger, LLMBudgetProfile
from .project_workflow import ProjectWorkflowService
from .roster_loader import RosterLoader, TeamRoster, apply_graph_facts, apply_source_availability
from .scenario_weight_applier import ScenarioWeightApplier
from .team_localization import (
    localize_coach_discussion_rows,
    localize_resume_node_rows,
    localize_scenario_case_rows,
    localize_step2_payload,
    localize_team_strength_rows,
)
from .team_strength_estimator import TeamStrengthEstimator


DEFAULT_PLAYER_DATASET_ID = "wc2026_fifa_v2"

PROGRESS_MILESTONES = [
    "loading_squads",
    "querying_graph",
    "extracting_facts",
    "fetching_external",
    "fitting_model",
    "estimating_strengths",
    "applying_weights",
    "persisting",
    "ready",
]


class DatasetNotFoundError(KeyError):
    """Raised when an API payload references a missing player dataset."""

    def __init__(self, dataset_id: str, available_datasets: list[str] | None = None):
        super().__init__(f"Player dataset '{dataset_id}' not found")
        self.dataset_id = dataset_id
        self.available_datasets = available_datasets or []


class PredictionConfigService:
    """Prepare and replay Step2 prediction configuration artifacts."""

    def prepare(
        self,
        *,
        project_id: str,
        graph_id: str | None,
        prediction_requirement: str,
        force_regenerate: bool = False,
        home_team: str | None = None,
        away_team: str | None = None,
        competition: Any | None = None,
        kickoff_time: str | None = None,
        graph_entities: list[dict[str, Any]] | None = None,
        llm_budget: dict | None = None,
        player_dataset_id: str = DEFAULT_PLAYER_DATASET_ID,
    ) -> dict[str, Any]:
        workflow = ProjectWorkflowService()
        self._ensure_project_record(project_id, graph_id, prediction_requirement)
        if force_regenerate:
            try:
                active_config_id = workflow.get_active_config_id(project_id)
                if active_config_id:
                    workflow.regenerate_step(project_id, 2, reason="force_regenerate")
            except KeyError:
                pass
        if not force_regenerate:
            existing = self.find_ready_config(project_id=project_id, graph_id=graph_id)
            if existing:
                return self._existing_summary(existing)

        prediction_config_id = self._new_config_id(project_id, graph_id)
        started = time.perf_counter()
        project_snapshot = self._project_snapshot(project_id)
        requirement = prediction_requirement or project_snapshot.get("simulation_requirement") or ""
        graph_snapshot = _load_graph_snapshot_for_config(graph_id, graph_entities or [])
        entities = graph_snapshot.get("entities") or []
        source_text = _combined_text(project_snapshot, entities, requirement)
        primary_source_text = _primary_source_text(project_snapshot)
        content_language = detect_content_language(source_text)
        content_language_instruction = build_content_language_instruction(source_text)

        budget = _resolve_prepare_budget(llm_budget)
        ledger = LLMCallLedger(config_id=prediction_config_id, budget=budget)
        normalizer = TeamNameNormalizer()
        home_iso3, away_iso3, home, away = _resolve_match_identity(
            requirement=requirement,
            source_text=source_text,
            primary_source_text=primary_source_text,
            graph_entities=entities,
            graph_id=graph_id,
            home_team=home_team,
            away_team=away_team,
            normalizer=normalizer,
        )
        match_context_text = _match_context_text(
            source_text=source_text,
            requirement=requirement,
            graph_entities=entities,
            home_iso3=home_iso3,
            away_iso3=away_iso3,
            normalizer=normalizer,
        )
        competition_label = _competition_label(competition)
        competition_meta = self._infer_competition(match_context_text or requirement, competition)
        if kickoff_time:
            competition_meta["kickoff_iso"] = kickoff_time
        dataset_id = player_dataset_id or self._default_dataset_id(competition_meta)
        competition_meta, competition_warnings = _normalize_competition_meta_for_prediction(competition_meta)
        warnings: list[str] = list(competition_warnings)

        self._create_preparing_config(
            prediction_config_id=prediction_config_id,
            project_id=project_id,
            graph_id=graph_id,
            home_team=home,
            away_team=away,
            competition=competition_label,
            kickoff_time=kickoff_time,
            dataset_id=dataset_id,
            budget=budget,
            requirement=requirement,
        )

        try:
            loader = RosterLoader()
            home_roster, away_roster = loader.snapshot(dataset_id, home_iso3, away_iso3)
            home_roster = _roster_with_display_name(home_roster, home)
            away_roster = _roster_with_display_name(away_roster, away)
            rosters_complete = bool(home_roster.players and away_roster.players)
            if not rosters_complete:
                warnings.append("roster_missing_or_empty")
            self._emit_progress(
                prediction_config_id,
                "loading_squads",
                f"加载 {home} {away} 名册",
                progress_percent=10,
            )

            graph_facts = GraphEvidenceQuery().for_match(
                home_iso3=home_iso3,
                away_iso3=away_iso3,
                graph_id=graph_id or "",
                dataset_id=dataset_id,
            )
            apply_graph_facts(home_roster, graph_facts)
            apply_graph_facts(away_roster, graph_facts)
            apply_source_availability(home_roster, source_text)
            apply_source_availability(away_roster, source_text)
            player_count = len(home_roster.players) + len(away_roster.players)
            self._emit_progress(
                prediction_config_id,
                "querying_graph",
                f"查询图谱伤停事实 ({player_count} 球员)",
                progress_percent=20,
            )

            extracted_context = FootballDataExtractor().extract(
                prediction_requirement=match_context_text or source_text,
                graph_id=graph_id,
                llm_ledger=ledger,
            )
            extracted = extracted_context.to_dict()
            identity_locked = _identity_locked_by_primary_source(
                primary_source_text=primary_source_text,
                current_home_iso3=home_iso3,
                current_away_iso3=away_iso3,
                normalizer=normalizer,
                home_team=home_team,
                away_team=away_team,
            )
            identity_update = _identity_update_from_extracted(
                current_home_iso3=home_iso3,
                current_away_iso3=away_iso3,
                current_home=home,
                current_away=away,
                extracted=extracted,
                normalizer=normalizer,
                dataset_id=dataset_id,
            )
            if identity_update and not identity_locked:
                home_iso3, away_iso3, home, away = identity_update
                home_roster, away_roster = loader.snapshot(dataset_id, home_iso3, away_iso3)
                home_roster = _roster_with_display_name(home_roster, home)
                away_roster = _roster_with_display_name(away_roster, away)
                if "match_identity_corrected_from_extracted_context" not in warnings:
                    warnings.append("match_identity_corrected_from_extracted_context")
                graph_facts = GraphEvidenceQuery().for_match(
                    home_iso3=home_iso3,
                    away_iso3=away_iso3,
                    graph_id=graph_id or "",
                    dataset_id=dataset_id,
                )
                apply_graph_facts(home_roster, graph_facts)
                apply_graph_facts(away_roster, graph_facts)
                apply_source_availability(home_roster, source_text)
                apply_source_availability(away_roster, source_text)
                rosters_complete = bool(home_roster.players and away_roster.players)
                if rosters_complete and "roster_missing_or_empty" in warnings:
                    warnings = [warning for warning in warnings if warning != "roster_missing_or_empty"]
            structured_inputs = extract_structured_match_inputs(source_text)
            extracted_for_model = {**structured_inputs, **extracted}
            extracted_competition_meta = _extracted_competition_meta_for_match(
                extracted=extracted,
                current_home_iso3=home_iso3,
                current_away_iso3=away_iso3,
            )
            if not extracted_competition_meta and "extracted_context_match_mismatch" not in warnings:
                warnings.append("extracted_context_match_mismatch")
            competition_meta = _merge_competition_meta(
                competition_meta,
                extracted_competition_meta,
                competition=competition,
                kickoff_time=kickoff_time,
            )
            competition_meta = _apply_local_host_country(
                competition_meta,
                match_context_text or source_text,
                home_iso3=home_iso3,
                away_iso3=away_iso3,
                competition=competition,
            )
            competition_meta, competition_warnings = _normalize_competition_meta_for_prediction(competition_meta)
            for warning in competition_warnings:
                if warning not in warnings:
                    warnings.append(warning)
            self._emit_progress(
                prediction_config_id,
                "extracting_facts",
                "LLM 抽取上传文档结构化事实",
                progress_percent=30,
            )

            sources = [
                "intl_results",
                "national_elo",
                "fifa_ranking",
                "statsbomb_xg" if budget.enable_statsbomb else None,
            ]
            external_pool = ExternalDataPool().fetch_for_match(
                home_iso3,
                away_iso3,
                since_year=2014,
                sources=sources,
                offline=_external_offline_enabled(),
            )
            self._emit_progress(
                prediction_config_id,
                "fetching_external",
                f"拉取外部数据源 ({', '.join(source for source in sources if source)})",
                progress_percent=40,
            )

            if rosters_complete:
                fit_artifacts = FootballGoalModelAdapter().fit(
                    external_pool=external_pool,
                    extracted=extracted_for_model,
                    home_iso3=home_iso3,
                    away_iso3=away_iso3,
                    competition_meta=competition_meta,
                )
            else:
                fit_artifacts = _legacy_fit_artifacts(
                    home_iso3=home_iso3,
                    away_iso3=away_iso3,
                    model_diagnostics=FootballGoalModelAdapter().initialize(
                        {
                            "prediction_requirement": requirement,
                            "home_team": home,
                            "away_team": away,
                            **structured_inputs,
                        }
                    ),
                )
            fit_dict = fit_artifacts.to_dict()
            n_rows = int((fit_dict.get("diagnostics") or {}).get("n_rows") or 0)
            self._emit_progress(
                prediction_config_id,
                "fitting_model",
                f"拟合 Dixon-Coles ({n_rows} 场)",
                progress_percent=55,
            )

            team_strength_pair = TeamStrengthEstimator().estimate_pair(
                home_roster=home_roster,
                away_roster=away_roster,
                fit_artifacts=fit_artifacts,
                graph_facts=graph_facts,
                competition_meta=competition_meta,
                external_pool=external_pool,
            )
            team_strength_rows = [
                _team_strength_record_payload(team_strength_pair[0], display_name=home),
                _team_strength_record_payload(team_strength_pair[1], display_name=away),
            ]
            panel_team_strengths: Any = team_strength_pair
            self._emit_progress(
                prediction_config_id,
                "estimating_strengths",
                "聚合球员→球队强度",
                progress_percent=65,
            )

            panel_inputs = CoachPanelInputs.assemble(
                rosters=(home_roster, away_roster),
                team_strengths=panel_team_strengths,
                fit_artifacts=fit_artifacts,
                extracted=extracted_context,
                graph_facts=graph_facts,
                scenario_template=list(SCENARIO_TEMPLATE),
            )
            for role_key in list(budget.coach_panel_roles or []):
                self._emit_progress(
                    prediction_config_id,
                    f"panel_role_{role_key}",
                    f"{_role_label(role_key)} 评审中...",
                    progress_percent=70,
                )
            verdicts = CoachLLMPanel(
                budget=budget,
                ledger=ledger,
                content_language_instruction=content_language_instruction,
            ).deliberate(panel_inputs)

            weighted_cases = ScenarioWeightApplier().apply(
                template=SCENARIO_TEMPLATE,
                verdicts=verdicts,
                fit_artifacts=fit_artifacts,
                team_strengths=panel_team_strengths,
            )
            scenario_rows = [
                _scenario_case_record_payload(case, fit_artifacts=fit_artifacts)
                for case in weighted_cases
            ]
            self._emit_progress(
                prediction_config_id,
                "applying_weights",
                "应用 9 场景权重",
                progress_percent=82,
            )

            jury = CoachJuryService()
            agents = jury.generate_agents(prediction_config_id=prediction_config_id, home_team=home, away_team=away)
            resume_nodes = jury.resume_nodes()
            scenario_summary = _scenario_design_summary(scenario_rows)
            resume_summary = resume_policy_summary(resume_nodes)
            ledger_summary = ledger.summary()
            jury_summary = _coach_jury_summary(
                verdicts=verdicts,
                fit_artifacts=fit_artifacts,
                ledger_summary=ledger_summary,
            )
            model_diagnostics = _model_diagnostics_from_fit(fit_artifacts)
            model_input_snapshot = {
                "prediction_requirement": requirement,
                "home_team": home,
                "away_team": away,
                "home_iso3": home_iso3,
                "away_iso3": away_iso3,
                "competition": competition_meta,
                "competition_meta": competition_meta,
                "kickoff_time": kickoff_time,
                "graph_id": graph_id,
                "graph_entities_count": len(entities),
                "source_text_length": len(source_text),
                "identity_locked_by_primary_source": identity_locked,
                "content_language": {
                    "code": content_language.code,
                    "display_name_zh": content_language.display_name_zh,
                    "display_name_en": content_language.display_name_en,
                    "confidence": content_language.confidence,
                },
                "content_language_instruction": content_language_instruction,
                "squads": loader.to_snapshot(home_roster, away_roster),
                "extracted": extracted,
                "structured_inputs": structured_inputs,
                "structured_recent_matches": structured_inputs.get("structured_recent_matches") or [],
                "structured_xg_samples": structured_inputs.get("structured_xg_samples") or [],
                "external_sources_etag": _external_sources_etag(external_pool),
                "fitted_artifacts": fit_dict,
                "scientific_model_diagnostics": model_diagnostics,
                "team_strengths_prepared": team_strength_rows,
                "warnings": [*warnings, *list(getattr(graph_facts, "warnings", []) or [])],
            }
            config_metadata = {
                "source": "prediction_config_service_v2",
                "already_prepared": False,
                "prediction_requirement": requirement,
                "versions": {
                    "extractor": EXTRACTOR_VERSION,
                    "goal_model": getattr(FootballGoalModelAdapter, "MODEL_VERSION", "v2"),
                    "coach_panel": PANEL_VERSION,
                    "scenario_weight_applier": "v1",
                },
                "scientific_model_diagnostics": model_diagnostics,
                "llm_budget": {
                    "profile": budget.to_dict(),
                    "ledger_summary": ledger_summary,
                },
            }

            self._emit_progress(prediction_config_id, "persisting", "落库", progress_percent=92)
            self._persist_prepared_config(
                prediction_config_id=prediction_config_id,
                project_id=project_id,
                graph_id=graph_id,
                home_team=home,
                away_team=away,
                competition=competition_label,
                kickoff_time=kickoff_time,
                dataset_id=dataset_id,
                budget=budget,
                ledger_summary=ledger_summary,
                fit_artifacts=fit_artifacts,
                source_document_ids=project_snapshot.get("source_document_ids") or [],
                graph_snapshot=graph_snapshot,
                model_input_snapshot=model_input_snapshot,
                scenario_summary=scenario_summary,
                resume_summary=resume_summary,
                jury_summary=jury_summary,
                config_metadata=config_metadata,
                agents=agents,
                scenario_rows=scenario_rows,
                resume_nodes=resume_nodes,
                team_strength_rows=team_strength_rows,
                jury=jury,
            )
            elapsed_ms = round((time.perf_counter() - started) * 1000)
            self._emit_progress(
                prediction_config_id,
                "ready",
                f"配置就绪 (耗时 {elapsed_ms}ms)",
                progress_percent=100,
                status="ready",
            )

            result = {
                "prediction_config_id": prediction_config_id,
                "project_id": project_id,
                "graph_id": graph_id,
                "match_name": f"{home} vs {away}",
                "home_team": home,
                "away_team": away,
                "home_iso3": home_iso3,
                "away_iso3": away_iso3,
                "status": "ready",
                "current_phase": "ready",
                "progress_percent": 100,
                "already_prepared": False,
                "fit_status": fit_dict["fit_status"],
                "data_sufficiency": fit_dict["data_sufficiency"],
                "llm_budget": _llm_budget_contract({"profile": budget.to_dict(), "ledger_summary": ledger_summary}),
                "ledger_summary": ledger_summary,
                "player_dataset_id": dataset_id,
                "dataset_summary": _dataset_summary_contract(
                    dataset_id=dataset_id,
                    source_label=None,
                    scope_label=None,
                    squads=model_input_snapshot.get("squads") or {},
                ),
                "external_sources": _external_sources_contract(model_input_snapshot.get("external_sources_etag") or {}),
                "competition": competition_meta,
                "warnings": model_input_snapshot.get("warnings") or [],
            }
            return localize_step2_payload(result)
        except Exception as exc:
            self._mark_failed(prediction_config_id, exc)
            raise

    def find_ready_config(self, *, project_id: str, graph_id: str | None) -> str | None:
        expected_pair = _primary_source_identity_pair(self._project_snapshot(project_id))
        try:
            active_config_id = ProjectWorkflowService().get_active_config_id(project_id)
        except KeyError:
            active_config_id = None
        if active_config_id:
            with get_session() as session:
                active = session.get(PredictionConfigRecord, active_config_id)
                if (
                    active
                    and active.status == "ready"
                    and (not graph_id or active.graph_id == graph_id)
                    and _is_reusable_ready_config(active)
                    and _config_matches_primary_source_pair(active, expected_pair)
                ):
                    return active.prediction_config_id
        with get_session() as session:
            query = (
                session.query(PredictionConfigRecord)
                .filter_by(project_id=project_id, status="ready")
                .order_by(PredictionConfigRecord.created_at.desc())
            )
            if graph_id:
                query = query.filter_by(graph_id=graph_id)
            for row in query.limit(5).all():
                if _is_reusable_ready_config(row) and _config_matches_primary_source_pair(row, expected_pair):
                    return row.prediction_config_id
            return None

    def get_latest_ready_config(self, *, project_id: str, graph_id: str | None = None) -> dict[str, Any] | None:
        prediction_config_id = self.find_ready_config(project_id=project_id, graph_id=graph_id)
        return self.get_config(prediction_config_id) if prediction_config_id else None

    def get_config(self, prediction_config_id: str) -> dict[str, Any]:
        with get_session() as session:
            config = session.get(PredictionConfigRecord, prediction_config_id)
            if not config:
                raise KeyError(f"prediction config not found: {prediction_config_id}")
            dataset = session.get(PredictionPlayerDatasetRecord, config.player_dataset_id) if config.player_dataset_id else None
            agents_count = session.query(PredictionCoachAgentRecord).filter_by(prediction_config_id=prediction_config_id).count()
            scenario_cases_count = session.query(PredictionConfigScenarioCaseRecord).filter_by(prediction_config_id=prediction_config_id).count()
            resume_nodes_count = session.query(PredictionConfigResumeNodeRecord).filter_by(prediction_config_id=prediction_config_id).count()
            return localize_step2_payload(
                _config_to_dict(
                    config,
                    dataset=dataset,
                    counts={
                        "coach_agents": agents_count,
                        "scenario_cases": scenario_cases_count,
                        "resume_nodes": resume_nodes_count,
                    },
                )
            )

    def get_status(self, prediction_config_id: str) -> dict[str, Any]:
        config = self.get_config(prediction_config_id)
        return {
            "prediction_config_id": config["prediction_config_id"],
            "project_id": config["project_id"],
            "graph_id": config["graph_id"],
            "status": config["status"],
            "current_phase": config["current_phase"],
            "progress_percent": config["progress_percent"],
            "fit_status": config["fit_status"],
            "data_sufficiency": config["data_sufficiency"],
            "counts": config["counts"],
            "error": config["error"],
        }

    def get_progress(self, prediction_config_id: str) -> dict[str, Any]:
        with get_session() as session:
            config = session.get(PredictionConfigRecord, prediction_config_id)
            if not config:
                raise KeyError(f"prediction config not found: {prediction_config_id}")
            messages = list(config.progress_messages or [])
            return {
                "prediction_config_id": config.prediction_config_id,
                "project_id": config.project_id,
                "graph_id": config.graph_id,
                "status": config.status,
                "current_phase": config.current_phase,
                "progress_percent": config.progress_percent,
                "current_milestone": config.current_phase,
                "messages": messages,
                "progress_messages": messages,
                "count": len(messages),
            }

    def list_datasets(self) -> list[dict[str, Any]]:
        with get_session() as session:
            rows = (
                session.query(PredictionPlayerDatasetRecord)
                .order_by(PredictionPlayerDatasetRecord.created_at.desc())
                .all()
            )
            return [_dataset_record_to_dict(row, is_default=row.dataset_id == DEFAULT_PLAYER_DATASET_ID) for row in rows]

    def switch_dataset(self, prediction_config_id: str, player_dataset_id: str) -> dict[str, Any]:
        with get_session() as session:
            config = session.get(PredictionConfigRecord, prediction_config_id)
            if not config:
                raise KeyError(f"prediction config not found: {prediction_config_id}")
            dataset = session.get(PredictionPlayerDatasetRecord, player_dataset_id)
            if not dataset:
                raise DatasetNotFoundError(player_dataset_id, _available_dataset_ids(session))
            previous_dataset_id = config.player_dataset_id
            config.player_dataset_id = player_dataset_id
            config.status = "regenerating"
            config.current_phase = "dataset_switch_requested"
            config.progress_percent = 0
            config.error = None
            emit_progress(
                session,
                prediction_config_id,
                "dataset_switch_requested",
                f"切换数据集 {previous_dataset_id or '-'} -> {player_dataset_id}",
            )
            return {
                "prediction_config_id": prediction_config_id,
                "status": "regenerating",
                "previous_dataset_id": previous_dataset_id,
                "new_dataset_id": player_dataset_id,
            }

    def get_roster(self, prediction_config_id: str) -> dict[str, Any]:
        with get_session() as session:
            config = self._require_config(session, prediction_config_id)
            dataset = session.get(PredictionPlayerDatasetRecord, config.player_dataset_id) if config.player_dataset_id else None
            model_input = config.model_input_snapshot or {}
            roster = _roster_contract(
                dataset_id=config.player_dataset_id,
                dataset=dataset,
                squads=model_input.get("squads") or {},
            )
            return localize_step2_payload({"roster": roster, "model_input_snapshot": model_input})["roster"]

    def _existing_summary(self, prediction_config_id: str) -> dict[str, Any]:
        data = self.get_config(prediction_config_id)
        metadata = data.get("metadata") or {}
        budget = data.get("llm_budget_profile") or metadata.get("llm_budget") or {}
        ledger_summary = (metadata.get("llm_budget") or {}).get("ledger_summary")
        return {
            "prediction_config_id": prediction_config_id,
            "project_id": data["project_id"],
            "graph_id": data["graph_id"],
            "status": data["status"],
            "current_phase": data["current_phase"],
            "progress_percent": data["progress_percent"],
            "already_prepared": True,
            "fit_status": data["fit_status"],
            "data_sufficiency": data["data_sufficiency"],
            "llm_budget": _llm_budget_contract(budget),
            "ledger_summary": ledger_summary,
            "player_dataset_id": data.get("player_dataset_id"),
            "dataset_summary": data.get("dataset_summary"),
            "external_sources": data.get("external_sources"),
            "competition": data.get("competition"),
            "warnings": (data.get("model_input_snapshot") or {}).get("warnings") or [],
        }

    def _create_preparing_config(
        self,
        *,
        prediction_config_id: str,
        project_id: str,
        graph_id: str | None,
        home_team: str,
        away_team: str,
        competition: str | None,
        kickoff_time: str | None,
        dataset_id: str,
        budget: LLMBudgetProfile,
        requirement: str,
    ) -> None:
        with get_session() as session:
            workflow_revision = None
            project = session.get(ProjectRecord, project_id)
            if project:
                workflow_revision = ProjectWorkflowService()._ensure_workflow_state(session, project).get("workflow_revision")
            session.add(
                PredictionConfigRecord(
                    prediction_config_id=prediction_config_id,
                    project_id=project_id,
                    graph_id=graph_id,
                    match_name=f"{home_team} vs {away_team}",
                    home_team=home_team,
                    away_team=away_team,
                    competition=competition,
                    kickoff_time=kickoff_time,
                    status="preparing",
                    current_phase="initializing",
                    progress_percent=1,
                    model_name="prior_poisson",
                    model_version=getattr(FootballGoalModelAdapter, "MODEL_VERSION", "v2"),
                    fit_status="preparing",
                    data_sufficiency="unknown",
                    source_document_ids=[],
                    graph_snapshot={},
                    model_input_snapshot={},
                    scenario_design_summary={},
                    resume_policy_summary={},
                    coach_jury_summary={},
                    player_dataset_id=dataset_id,
                    llm_budget_profile={"profile": budget.to_dict()},
                    progress_messages=[],
                    config_metadata={
                        "source": "prediction_config_service_v2",
                        "prediction_requirement": requirement,
                        "already_prepared": False,
                        "artifact_status": "preparing",
                        "workflow_revision": workflow_revision,
                    },
                )
            )

    def _emit_progress(
        self,
        prediction_config_id: str,
        milestone: str,
        text: str,
        *,
        progress_percent: int | None = None,
        status: str | None = None,
    ) -> None:
        with get_session() as session:
            emit_progress(session, prediction_config_id, milestone, text)
            config = session.get(PredictionConfigRecord, prediction_config_id)
            if config is None:
                raise KeyError(f"prediction config not found: {prediction_config_id}")
            config.current_phase = milestone
            if progress_percent is not None:
                config.progress_percent = max(0, min(100, int(progress_percent)))
            if status:
                config.status = status

    def _mark_failed(self, prediction_config_id: str, exc: Exception) -> None:
        try:
            with get_session() as session:
                config = session.get(PredictionConfigRecord, prediction_config_id)
                if not config:
                    return
                config.status = "failed"
                config.current_phase = "failed"
                config.error = str(exc)
                emit_progress(session, prediction_config_id, "failed", f"配置失败: {exc}")
        except Exception:
            return

    def _infer_competition(self, requirement: str, competition: Any | None) -> dict[str, Any]:
        try:
            meta = FootballDataExtractor()._infer_competition_meta(requirement)
        except Exception:
            meta = {
                "tournament": None,
                "stage": None,
                "knockout": False,
                "neutral_venue": False,
                "host_country_iso3": None,
            }
        if competition:
            meta = _apply_competition_payload(meta, competition)
        return meta

    def _default_dataset_id(self, competition_meta: dict[str, Any]) -> str:
        del competition_meta
        return DEFAULT_PLAYER_DATASET_ID

    def _persist_prepared_config(
        self,
        *,
        prediction_config_id: str,
        project_id: str,
        graph_id: str | None,
        home_team: str,
        away_team: str,
        competition: str | None,
        kickoff_time: str | None,
        dataset_id: str,
        budget: LLMBudgetProfile,
        ledger_summary: dict[str, Any],
        fit_artifacts: FitArtifacts,
        source_document_ids: list[Any],
        graph_snapshot: dict[str, Any],
        model_input_snapshot: dict[str, Any],
        scenario_summary: dict[str, Any],
        resume_summary: dict[str, Any],
        jury_summary: dict[str, Any],
        config_metadata: dict[str, Any],
        agents: list[dict[str, Any]],
        scenario_rows: list[dict[str, Any]],
        resume_nodes: list[dict[str, Any]],
        team_strength_rows: list[dict[str, Any]],
        jury: CoachJuryService,
    ) -> None:
        model_diagnostics = _model_diagnostics_from_fit(fit_artifacts)
        with get_session() as session:
            config = session.get(PredictionConfigRecord, prediction_config_id)
            if not config:
                raise KeyError(f"prediction config not found: {prediction_config_id}")

            config.project_id = project_id
            config.graph_id = graph_id
            config.match_name = f"{home_team} vs {away_team}"
            config.home_team = home_team
            config.away_team = away_team
            config.competition = competition
            config.kickoff_time = kickoff_time
            config.status = "ready"
            config.current_phase = "ready"
            config.progress_percent = 100
            config.model_name = model_diagnostics["model_name"]
            config.model_version = model_diagnostics["model_version"]
            config.fit_status = model_diagnostics["fit_status"]
            config.data_sufficiency = model_diagnostics["data_sufficiency"]
            config.source_document_ids = source_document_ids
            config.graph_snapshot = graph_snapshot
            config.model_input_snapshot = model_input_snapshot
            config.scenario_design_summary = scenario_summary
            config.resume_policy_summary = resume_summary
            config.coach_jury_summary = jury_summary
            config.player_dataset_id = dataset_id
            config.llm_budget_profile = {
                "profile": budget.to_dict(),
                "ledger_summary": ledger_summary,
            }
            config.completed_at = utc_now()
            previous_metadata = dict(config.config_metadata or {})
            merged_metadata = dict(config_metadata or {})
            if previous_metadata.get("workflow_revision") and not merged_metadata.get("workflow_revision"):
                merged_metadata["workflow_revision"] = previous_metadata.get("workflow_revision")
            merged_metadata["artifact_status"] = "active"
            config.config_metadata = merged_metadata
            session.flush()

            for row in agents:
                session.add(PredictionCoachAgentRecord(**row))
            session.flush()
            agent_rows = (
                session.query(PredictionCoachAgentRecord)
                .filter_by(prediction_config_id=prediction_config_id)
                .order_by(PredictionCoachAgentRecord.agent_index.asc())
                .all()
            )

            for row in scenario_rows:
                session.add(PredictionConfigScenarioCaseRecord(prediction_config_id=prediction_config_id, **row))
            for row in resume_nodes:
                session.add(PredictionConfigResumeNodeRecord(prediction_config_id=prediction_config_id, **row))
            session.flush()

            scenario_case_rows = (
                session.query(PredictionConfigScenarioCaseRecord)
                .filter_by(prediction_config_id=prediction_config_id)
                .order_by(PredictionConfigScenarioCaseRecord.created_at.asc())
                .all()
            )
            resume_rows = (
                session.query(PredictionConfigResumeNodeRecord)
                .filter_by(prediction_config_id=prediction_config_id)
                .order_by(PredictionConfigResumeNodeRecord.sequence.asc())
                .all()
            )

            scenario_discussion = PredictionCoachDiscussionRecord(
                **jury.scenario_design_discussion(prediction_config_id=prediction_config_id)
            )
            resume_discussion = PredictionCoachDiscussionRecord(
                **jury.resume_policy_discussion(prediction_config_id=prediction_config_id)
            )
            session.add(scenario_discussion)
            session.add(resume_discussion)
            session.flush()

            agent_ids = [row.id for row in agent_rows]
            for row in jury.scenario_votes(
                prediction_config_id=prediction_config_id,
                discussion_id=scenario_discussion.id,
                agent_ids=agent_ids,
                scenario_case_ids=[row.id for row in scenario_case_rows],
                scenario_keys=[row.scenario_key for row in scenario_case_rows],
            ):
                session.add(PredictionCoachVoteRecord(**row))
            for row in jury.resume_votes(
                prediction_config_id=prediction_config_id,
                discussion_id=resume_discussion.id,
                agent_ids=agent_ids,
                resume_node_ids=[row.id for row in resume_rows],
                event_types=[row.event_type for row in resume_rows],
            ):
                session.add(PredictionCoachVoteRecord(**row))

            for row in team_strength_rows:
                metadata = {**(row.get("metadata") or {}), "source": row.get("metadata", {}).get("source") or "prediction_config_service_v2"}
                session.add(
                    PredictionTeamStrengthRecord(
                        prediction_config_id=prediction_config_id,
                        prediction_run_id=None,
                        **_without(row, "metadata"),
                        strength_metadata=metadata,
                    )
                )
            session.flush()

        ProjectWorkflowService().register_config(project_id, prediction_config_id)

    def list_coach_agents(self, prediction_config_id: str) -> list[dict[str, Any]]:
        with get_session() as session:
            self._require_config(session, prediction_config_id)
            rows = (
                session.query(PredictionCoachAgentRecord)
                .filter_by(prediction_config_id=prediction_config_id)
                .order_by(PredictionCoachAgentRecord.agent_index.asc())
                .all()
            )
            return [_coach_agent_to_dict(row) for row in rows]

    def list_coach_discussions(self, prediction_config_id: str) -> list[dict[str, Any]]:
        with get_session() as session:
            self._require_config(session, prediction_config_id)
            rows = (
                session.query(PredictionCoachDiscussionRecord)
                .filter_by(prediction_config_id=prediction_config_id)
                .order_by(PredictionCoachDiscussionRecord.round_index.asc(), PredictionCoachDiscussionRecord.created_at.asc())
                .all()
            )
            return localize_coach_discussion_rows([_discussion_to_dict(row) for row in rows])

    def list_scenario_cases(self, prediction_config_id: str) -> list[dict[str, Any]]:
        with get_session() as session:
            self._require_config(session, prediction_config_id)
            rows = (
                session.query(PredictionConfigScenarioCaseRecord)
                .filter_by(prediction_config_id=prediction_config_id)
                .order_by(PredictionConfigScenarioCaseRecord.created_at.asc())
                .all()
            )
            return localize_scenario_case_rows([_config_scenario_case_to_dict(row) for row in rows])

    def list_resume_nodes(self, prediction_config_id: str) -> list[dict[str, Any]]:
        with get_session() as session:
            self._require_config(session, prediction_config_id)
            rows = (
                session.query(PredictionConfigResumeNodeRecord)
                .filter_by(prediction_config_id=prediction_config_id)
                .order_by(PredictionConfigResumeNodeRecord.sequence.asc())
                .all()
            )
            return localize_resume_node_rows([_resume_node_to_dict(row) for row in rows])

    def list_team_strengths(self, prediction_config_id: str) -> list[dict[str, Any]]:
        with get_session() as session:
            self._require_config(session, prediction_config_id)
            rows = (
                session.query(PredictionTeamStrengthRecord)
                .filter_by(prediction_config_id=prediction_config_id, prediction_run_id=None)
                .order_by(PredictionTeamStrengthRecord.team_role.asc())
                .all()
            )
            rows = [
                {
                    "id": row.id,
                    "prediction_config_id": row.prediction_config_id,
                    "team_role": row.team_role,
                    "team_name": row.team_name,
                    "team_iso3": (row.strength_metadata or {}).get("team_iso3"),
                    "attack_rating": row.attack_rating,
                    "defense_rating": row.defense_rating,
                    "possession_rating": row.possession_rating,
                    "transition_rating": row.transition_rating,
                    "set_piece_rating": row.set_piece_rating,
                    "discipline_rating": row.discipline_rating,
                    "fitness_rating": row.fitness_rating,
                    "goalkeeper_rating": row.goalkeeper_rating,
                    "home_away_adjustment": row.home_away_adjustment,
                    "injury_adjustment": row.injury_adjustment,
                    "form_adjustment": row.form_adjustment,
                    "evidence": row.evidence,
                    "evidence_breakdown": row.evidence if isinstance(row.evidence, dict) else {},
                    "injury_evidence_refs": (row.strength_metadata or {}).get("injury_evidence_refs") or [],
                    "form_evidence_refs": (row.strength_metadata or {}).get("form_evidence_refs") or [],
                    "home_away_adjustment_reason": (row.strength_metadata or {}).get("home_away_adjustment_reason"),
                    "confidence": row.confidence,
                    "metadata": row.strength_metadata or {},
                }
                for row in rows
            ]
            return localize_team_strength_rows(rows)

    def _require_config(self, session, prediction_config_id: str) -> PredictionConfigRecord:
        config = session.get(PredictionConfigRecord, prediction_config_id)
        if not config:
            raise KeyError(f"prediction config not found: {prediction_config_id}")
        return config

    def _project_snapshot(self, project_id: str) -> dict[str, Any]:
        with get_session() as session:
            project = session.get(ProjectRecord, project_id)
            if not project:
                return {}
            return {
                "project_id": project.project_id,
                "simulation_requirement": project.simulation_requirement or "",
                "files": project.files or [],
                "source_document_ids": [
                    str(item.get("id") or item.get("filename") or index)
                    for index, item in enumerate(project.files or [])
                ],
                "extracted_text": project.extracted_text or "",
                "analysis_summary": project.analysis_summary or "",
            }

    def _ensure_project_record(self, project_id: str, graph_id: str | None, requirement: str) -> None:
        with get_session() as session:
            project = session.get(ProjectRecord, project_id)
            if project:
                if graph_id and not project.graph_id:
                    project.graph_id = graph_id
                if requirement and not project.simulation_requirement:
                    project.simulation_requirement = requirement
                    project.extracted_text = project.extracted_text or requirement
                ProjectWorkflowService()._ensure_workflow_state(session, project)
                return
            project = ProjectRecord(
                project_id=project_id,
                name=project_id,
                status="graph_completed" if graph_id else "created",
                graph_id=graph_id,
                files=[],
                total_text_length=0,
                extracted_text=requirement or "",
                ontology=None,
                analysis_summary=None,
                simulation_requirement=requirement or "",
                simulation_domain="football_match",
                project_metadata={},
            )
            session.add(project)
            session.flush()
            ProjectWorkflowService()._ensure_workflow_state(session, project)

    def _new_config_id(self, project_id: str, graph_id: str | None) -> str:
        seed = f"{project_id}:{graph_id}:{utc_now().isoformat()}"
        return "cfg_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]


def _combined_text(project_snapshot: dict[str, Any], graph_entities: list[dict[str, Any]], requirement: str) -> str:
    entity_text = "\n".join(
        f"{entity.get('name', '')} {entity.get('summary', '')} {entity.get('description', '')}"
        for entity in graph_entities
    )
    return "\n".join(
        [
            requirement or "",
            project_snapshot.get("extracted_text") or "",
            project_snapshot.get("analysis_summary") or "",
            entity_text,
        ]
    )


def _primary_source_text(project_snapshot: dict[str, Any]) -> str:
    """Return uploaded document body text only, excluding filenames and graph text."""

    return str(project_snapshot.get("extracted_text") or "")


def _load_graph_snapshot_for_config(graph_id: str | None, supplied_entities: list[dict[str, Any]]) -> dict[str, Any]:
    if supplied_entities:
        return {
            "graph_id": graph_id,
            "entities_count": len(supplied_entities),
            "relationships_count": 0,
            "entities": supplied_entities[:80],
            "relationships": [],
            "source": "request_payload",
        }
    if not graph_id:
        return {
            "graph_id": graph_id,
            "entities_count": 0,
            "relationships_count": 0,
            "entities": [],
            "relationships": [],
            "source": "empty_graph_id",
        }
    try:
        reader = get_entity_reader()
        nodes = [_node_mapping(item) for item in reader.get_all_nodes(graph_id)]
        edges = []
        if hasattr(reader, "get_all_edges"):
            edges = [_edge_mapping(item) for item in reader.get_all_edges(graph_id)]
        return {
            "graph_id": graph_id,
            "entities_count": len(nodes),
            "relationships_count": len(edges),
            "entities": [_compact_config_graph_node(node) for node in nodes[:80]],
            "relationships": [_compact_config_graph_edge(edge) for edge in edges[:120]],
            "source": "graph_reader",
        }
    except Exception as exc:  # noqa: BLE001 - graph reads are evidence enrichment, not a hard dependency.
        return {
            "graph_id": graph_id,
            "entities_count": 0,
            "relationships_count": 0,
            "entities": [],
            "relationships": [],
            "source": "graph_reader_failed",
            "warnings": [f"graph_snapshot_read_failed: {exc}"],
        }


def _compact_config_graph_node(node: dict[str, Any]) -> dict[str, Any]:
    attributes = node.get("attributes") if isinstance(node.get("attributes"), dict) else {}
    return {
        "id": _node_id(node),
        "name": node.get("name"),
        "labels": node.get("labels") or node.get("entity_type") or node.get("type"),
        "summary": str(node.get("summary") or node.get("description") or attributes.get("summary") or "")[:600],
        "attributes": {
            key: value
            for key, value in attributes.items()
            if key in {"team_iso3", "status", "position", "competition", "date", "source"}
        },
    }


def _compact_config_graph_edge(edge: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": edge.get("name"),
        "fact": str(edge.get("fact") or "")[:500],
        "source_node_uuid": edge.get("source_node_uuid") or edge.get("source"),
        "target_node_uuid": edge.get("target_node_uuid") or edge.get("target"),
    }


def _resolve_prepare_budget(llm_budget: dict | None) -> LLMBudgetProfile:
    if llm_budget:
        return LLMBudgetProfile.resolve(llm_budget)
    data = LLMBudgetProfile.LOW.to_dict()
    data.update(
        {
            "profile_key": "custom",
            "coach_panel_roles": [],
            "coach_deliberation_rounds": 1,
            "enable_llm_data_extraction": False,
            "narrative_polish_count": 0,
            "analyst_note_groups": [],
            "coach_review_roles": [],
            "n_sims": 500,
            "enable_statsbomb": False,
            "hard_cap_calls": 1,
        }
    )
    return LLMBudgetProfile.from_dict(data)


def _config_to_dict(
    config: PredictionConfigRecord,
    *,
    dataset: PredictionPlayerDatasetRecord | None = None,
    counts: dict[str, int],
) -> dict[str, Any]:
    model_input = config.model_input_snapshot or {}
    metadata = config.config_metadata or {}
    llm_budget_profile = config.llm_budget_profile or {}
    squads = model_input.get("squads") or {}
    competition = _competition_contract(model_input, config.competition)
    contract_metadata = {
        **metadata,
        "versions": _versions_contract(metadata.get("versions") or {}, config.model_version),
        "llm_ledger": (llm_budget_profile.get("ledger_summary") or (metadata.get("llm_budget") or {}).get("ledger_summary") or {}),
    }
    return {
        "prediction_config_id": config.prediction_config_id,
        "project_id": config.project_id,
        "graph_id": config.graph_id,
        "match_name": config.match_name,
        "home_team": config.home_team,
        "away_team": config.away_team,
        "home_iso3": model_input.get("home_iso3") or (squads.get("home") or {}).get("team_iso3"),
        "away_iso3": model_input.get("away_iso3") or (squads.get("away") or {}).get("team_iso3"),
        "competition": competition,
        "competition_label": config.competition,
        "kickoff_time": config.kickoff_time,
        "status": config.status,
        "current_phase": config.current_phase,
        "progress_percent": config.progress_percent,
        "model_name": config.model_name,
        "model_version": config.model_version,
        "fit_status": config.fit_status,
        "data_sufficiency": config.data_sufficiency,
        "source_document_ids": config.source_document_ids or [],
        "graph_snapshot": config.graph_snapshot or {},
        "model_input_snapshot": config.model_input_snapshot or {},
        "scenario_design_summary": config.scenario_design_summary or {},
        "resume_policy_summary": config.resume_policy_summary or {},
        "coach_jury_summary": config.coach_jury_summary or {},
        "player_dataset_id": config.player_dataset_id,
        "llm_budget_profile": config.llm_budget_profile or {},
        "llm_budget": _llm_budget_contract(llm_budget_profile),
        "dataset_summary": _dataset_summary_contract(
            dataset_id=config.player_dataset_id,
            source_label=dataset.source_label if dataset else None,
            scope_label=dataset.scope_label if dataset else None,
            squads=squads,
        ),
        "external_sources": _external_sources_contract(model_input.get("external_sources_etag") or {}),
        "progress_messages": config.progress_messages or [],
        "error": config.error,
        "created_at": _iso(config.created_at),
        "updated_at": _iso(config.updated_at),
        "completed_at": _iso(config.completed_at),
        "config_metadata": contract_metadata,
        "metadata": contract_metadata,
        "counts": counts,
    }


def _dataset_record_to_dict(row: PredictionPlayerDatasetRecord, *, is_default: bool) -> dict[str, Any]:
    metadata = row.dataset_metadata or {}
    tournament = metadata.get("tournament") or _scope_tournament(row.scope_label)
    return {
        "dataset_id": row.dataset_id,
        "source_label": row.source_label,
        "scope_label": row.scope_label,
        "teams_count": row.teams_count,
        "players_count": row.players_count,
        "created_at": _iso(row.created_at),
        "is_default": bool(is_default or metadata.get("is_default", False)),
        "match_scope": {
            "tournament": tournament,
            "matches_compatible": bool(metadata.get("matches_compatible", True)),
        },
        "metadata": metadata,
    }


def _available_dataset_ids(session: Any) -> list[str]:
    return [
        row.dataset_id
        for row in session.query(PredictionPlayerDatasetRecord)
        .order_by(PredictionPlayerDatasetRecord.created_at.desc())
        .all()
    ]


def _is_reusable_ready_config(config: PredictionConfigRecord) -> bool:
    config_metadata = getattr(config, "config_metadata", None)
    metadata = config_metadata if isinstance(config_metadata, dict) else {}
    if metadata.get("artifact_status") in {"superseded", "archived", "failed"}:
        return False

    if _is_placeholder_team(config.home_team) or _is_placeholder_team(config.away_team):
        return False

    model_input = config.model_input_snapshot or {}
    squads = model_input.get("squads") or {}
    home_squad = squads.get("home") or {}
    away_squad = squads.get("away") or {}
    if _is_placeholder_iso3(home_squad.get("team_iso3")) or _is_placeholder_iso3(away_squad.get("team_iso3")):
        return False
    warnings = model_input.get("warnings") or []
    if isinstance(home_squad.get("players"), list) and isinstance(away_squad.get("players"), list):
        home_empty = not home_squad["players"]
        away_empty = not away_squad["players"]
        if home_empty != away_empty:
            return False
    snapshot_home = model_input.get("home_team")
    snapshot_away = model_input.get("away_team")
    if _is_placeholder_team(snapshot_home) or _is_placeholder_team(snapshot_away):
        return False

    extracted = model_input.get("extracted") or {}
    if isinstance(extracted, dict):
        extracted_home = str(extracted.get("home_iso3") or "").strip().upper()
        extracted_away = str(extracted.get("away_iso3") or "").strip().upper()
        snapshot_home_iso3 = str(model_input.get("home_iso3") or home_squad.get("team_iso3") or "").strip().upper()
        snapshot_away_iso3 = str(model_input.get("away_iso3") or away_squad.get("team_iso3") or "").strip().upper()
        if (
            extracted_home
            and extracted_away
            and snapshot_home_iso3
            and snapshot_away_iso3
            and (extracted_home, extracted_away) != (snapshot_home_iso3, snapshot_away_iso3)
            and not model_input.get("identity_locked_by_primary_source")
        ):
            return False

    return True


def _primary_source_identity_pair(project_snapshot: dict[str, Any]) -> tuple[str, str] | None:
    primary_source_text = _primary_source_text(project_snapshot)
    if not primary_source_text:
        return None
    normalizer = TeamNameNormalizer()
    extractor = FootballDataExtractor(normalizer=normalizer)
    home_iso3, away_iso3 = _resolve_primary_source_pair(primary_source_text, extractor)
    if not home_iso3 or not away_iso3:
        return None
    return _normalize_iso3(home_iso3), _normalize_iso3(away_iso3)


def _config_matches_primary_source_pair(
    config: PredictionConfigRecord,
    expected_pair: tuple[str, str] | None,
) -> bool:
    if not expected_pair:
        return True
    model_input = config.model_input_snapshot or {}
    squads = model_input.get("squads") if isinstance(model_input.get("squads"), dict) else {}
    home_squad = squads.get("home") if isinstance(squads.get("home"), dict) else {}
    away_squad = squads.get("away") if isinstance(squads.get("away"), dict) else {}
    config_pair = (
        _normalize_iso3(model_input.get("home_iso3") or home_squad.get("team_iso3")),
        _normalize_iso3(model_input.get("away_iso3") or away_squad.get("team_iso3")),
    )
    return config_pair == expected_pair


def _is_placeholder_team(value: Any) -> bool:
    return str(value or "").strip() in {"", "主队", "客队", "home", "away", "Home", "Away"}


def _is_placeholder_iso3(value: Any) -> bool:
    return str(value or "").strip().upper() in {"HOM", "AWY", "HOME", "AWAY"}


def _llm_budget_contract(value: Any) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else payload
    ledger = payload.get("ledger_summary") if isinstance(payload.get("ledger_summary"), dict) else {}
    if not isinstance(profile, dict):
        profile = {}
    if not isinstance(ledger, dict):
        ledger = {}

    profile_key = str(profile.get("profile_key") or "legacy")
    hard_cap = int(profile.get("hard_cap_calls") or ledger.get("hard_cap") or 0)
    return {
        **profile,
        "profile_key": profile_key,
        "calls_planned": _estimated_calls(profile),
        "calls_used": int(ledger.get("total_calls") or ledger.get("spent") or 0),
        "calls_cached": int(ledger.get("cached") or 0),
        "hard_cap": hard_cap,
        "total_cost_usd": float(ledger.get("total_cost_usd") or 0.0),
    }


def _estimated_calls(profile: dict[str, Any]) -> int:
    try:
        return int(LLMBudgetProfile.from_dict(profile).estimated_calls)
    except Exception:
        if "coach_panel_roles" not in profile:
            return 0
        roles = profile.get("coach_panel_roles") or []
        rounds = int(profile.get("coach_deliberation_rounds") or 1)
        calls = len(roles) * rounds
        if profile.get("enable_llm_data_extraction"):
            calls += 1
        calls += int(profile.get("narrative_polish_count") or 0) * 8
        calls += len(profile.get("analyst_note_groups") or [])
        calls += len(profile.get("coach_review_roles") or []) * 9
        hard_cap = int(profile.get("hard_cap_calls") or calls or 0)
        return min(calls, hard_cap) if hard_cap else calls


def _dataset_summary_contract(
    *,
    dataset_id: str | None,
    source_label: str | None,
    scope_label: str | None,
    squads: dict[str, Any],
) -> dict[str, Any] | None:
    if not dataset_id and not squads:
        return None
    return {
        "dataset_id": dataset_id,
        "source_label": source_label,
        "scope_label": scope_label,
        "home": _team_dataset_summary(squads.get("home") or {}),
        "away": _team_dataset_summary(squads.get("away") or {}),
    }


def _team_dataset_summary(team: dict[str, Any]) -> dict[str, Any]:
    players = list(team.get("players") or [])
    stats = dict(team.get("stats") or {})
    return {
        "team_iso3": team.get("team_iso3"),
        "team_name": team.get("team_name"),
        "players_count": len(players),
        "available": int(stats.get("available") or _count_availability(players, "available")),
        "doubtful": int(stats.get("doubtful") or _count_availability(players, "doubtful")),
        "injured": int(stats.get("injured") or _count_availability(players, "injured")),
        "suspended": int(stats.get("suspended") or _count_availability(players, "suspended")),
        "avg_overall": stats.get("avg_overall"),
        "gk_max": _max_rating(players, "gk"),
    }


def _count_availability(players: list[dict[str, Any]], status: str) -> int:
    return sum(1 for player in players if (player.get("availability") or {}).get("status") == status)


def _max_rating(players: list[dict[str, Any]], key: str) -> int | None:
    values = []
    for player in players:
        try:
            values.append(int(round(float((player.get("derived") or {}).get(key)))))
        except (TypeError, ValueError):
            continue
    return max(values) if values else None


def _external_sources_contract(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not payload:
        return []
    rows = []
    for key, value in payload.items():
        if key == "sources":
            continue
        source = value if isinstance(value, dict) else {"fingerprint": value}
        rows.append(
            {
                "key": key,
                "status": "synced" if "error" not in source else "error",
                "rows": source.get("row_count") or source.get("rows"),
                "fetched_at": source.get("fetched_at"),
                "etag": source.get("etag") or source.get("sha256_first_kb") or source.get("fingerprint"),
                **({"error": source.get("error")} if source.get("error") else {}),
            }
        )
    for key in payload.get("sources") or []:
        if not any(row["key"] == key for row in rows):
            rows.append({"key": key, "status": "synced", "rows": None, "fetched_at": None, "etag": None})
    return rows


def _competition_contract(model_input: dict[str, Any], fallback: str | None) -> dict[str, Any]:
    raw = model_input.get("competition_meta") or model_input.get("competition")
    if isinstance(raw, dict):
        normalized, _warnings = _normalize_competition_meta_for_prediction(raw)
        return {
            "tournament": raw.get("tournament") or raw.get("name") or fallback,
            "stage": normalized.get("stage"),
            "knockout": bool(normalized.get("knockout")),
            "neutral_venue": bool(normalized.get("neutral_venue")),
            "host_country_iso3": normalized.get("host_country_iso3"),
            **{key: value for key, value in raw.items() if key not in {"tournament", "name", "stage", "knockout", "neutral_venue", "host_country_iso3"}},
        }
    return {
        "tournament": fallback,
        "stage": None,
        "knockout": False,
        "neutral_venue": False,
        "host_country_iso3": None,
    }


def _versions_contract(value: dict[str, Any], model_version: str | None) -> dict[str, Any]:
    return {
        **value,
        "model_version": value.get("model_version") or value.get("goal_model") or model_version,
        "extractor_version": value.get("extractor_version") or value.get("extractor"),
        "coach_jury_version": value.get("coach_jury_version") or value.get("coach_panel"),
        "narrative_version": value.get("narrative_version") or "v1",
    }


def _roster_contract(
    *,
    dataset_id: str | None,
    dataset: PredictionPlayerDatasetRecord | None,
    squads: dict[str, Any],
    actor_stats: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id,
        "source_label": dataset.source_label if dataset else None,
        "scope_label": dataset.scope_label if dataset else None,
        "snapshot_taken_at": None,
        "teams": [
            _roster_team_contract("home", squads.get("home") or {}, actor_stats=actor_stats),
            _roster_team_contract("away", squads.get("away") or {}, actor_stats=actor_stats),
        ],
    }


def _roster_team_contract(role: str, team: dict[str, Any], *, actor_stats: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "role": role,
        "iso3": team.get("team_iso3"),
        "name": team.get("team_name"),
        "players": [_roster_player_contract(player, actor_stats=actor_stats) for player in (team.get("players") or [])],
    }


def _roster_player_contract(player: dict[str, Any], *, actor_stats: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    player_id = str(player.get("id") or "")
    row = {
        "id": player_id,
        "name": player.get("name"),
        "name_en": player.get("name_en"),
        "name_zh": player.get("name_zh") or player.get("name"),
        "position": player.get("position_primary") or player.get("position"),
        "age": player.get("age"),
        "derived": player.get("derived") or {},
        "availability": player.get("availability") or {"status": "available"},
        "expected_role": player.get("expected_role"),
        "expected_minutes_share": player.get("expected_minutes_share"),
        "shirt_number": player.get("shirt_number"),
        "club_fifa": player.get("club_fifa"),
    }
    if actor_stats is not None:
        row["actor_stats"] = actor_stats.get(player_id) or {
            "goal_share": 0.0,
            "assist_share": 0.0,
            "card_share": 0.0,
            "minutes_played_p50": int(round(float(player.get("expected_minutes_share") or 0) * 90)),
        }
    return row


def _scope_tournament(scope_label: str | None) -> str | None:
    text = str(scope_label or "")
    if "world_cup_2026" in text or "wc2026" in text:
        return "FIFA World Cup 2026"
    if "euro_2024" in text:
        return "UEFA Euro 2024"
    return None


def _coach_agent_to_dict(row: PredictionCoachAgentRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "prediction_config_id": row.prediction_config_id,
        "agent_index": row.agent_index,
        "role": row.role,
        "name": row.name,
        "expertise": row.expertise or [],
        "tactical_preference": row.tactical_preference,
        "risk_tolerance": row.risk_tolerance,
        "evidence_policy": row.evidence_policy,
        "system_prompt": row.system_prompt,
        "metadata": row.agent_metadata or {},
    }


def _discussion_to_dict(row: PredictionCoachDiscussionRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "prediction_config_id": row.prediction_config_id,
        "discussion_type": row.discussion_type,
        "round_index": row.round_index,
        "topic": row.topic,
        "prompt": row.prompt,
        "summary": row.summary,
        "consensus_score": row.consensus_score / 100,
        "disagreement_score": row.disagreement_score / 100,
        "metadata": row.discussion_metadata or {},
    }


def _config_scenario_case_to_dict(row: PredictionConfigScenarioCaseRecord) -> dict[str, Any]:
    vote_summary = row.coach_vote_summary or {}
    return {
        "id": row.id,
        "prediction_config_id": row.prediction_config_id,
        "home_state": row.home_state,
        "away_state": row.away_state,
        "scenario_key": row.scenario_key,
        "scenario_name": row.scenario_name,
        "scenario_space": row.scenario_space,
        "initial_weight": row.initial_weight,
        "final_weight": row.final_weight,
        "key_drivers": row.key_drivers or [],
        "risk_factors": row.risk_factors or [],
        "weight_change": vote_summary.get("weight_change") or {
            "initial": row.initial_weight,
            "final": row.final_weight,
            "applied_delta": row.final_weight - row.initial_weight,
            "applied_weight_delta": row.final_weight - row.initial_weight,
            "applied_delta_pct": vote_summary.get("applied_delta_pct", 0),
            "max_adjustment_pct": vote_summary.get("max_weight_adjustment_pct", 30),
            "contributors": vote_summary.get("contributors") or [],
        },
        "coach_vote_summary": vote_summary,
        "model_constraints": row.model_constraints or {},
    }


def _resume_node_to_dict(row: PredictionConfigResumeNodeRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "prediction_config_id": row.prediction_config_id,
        "event_type": row.event_type,
        "sequence": row.sequence,
        "label": row.label,
        "must_persist": row.must_persist,
        "can_recompute": row.can_recompute,
        "resume_strategy": row.resume_strategy,
        "input_artifact_types": row.input_artifact_types or [],
        "output_artifact_types": row.output_artifact_types or [],
        "ui_replay_summary": row.ui_replay_summary,
        "coach_vote_summary": row.coach_vote_summary or {},
    }


def _iso(value):
    return value.isoformat() if value else None


def _without(row: dict[str, Any], *keys: str) -> dict[str, Any]:
    blocked = set(keys)
    return {key: value for key, value in row.items() if key not in blocked}


def emit_progress(session, prediction_config_id: str, milestone: str, text: str) -> None:
    config = session.get(PredictionConfigRecord, prediction_config_id)
    if config is None:
        raise KeyError(f"prediction config not found: {prediction_config_id}")
    messages = list(config.progress_messages or [])
    messages.append(
        {
            "timestamp": utc_now().isoformat(),
            "milestone": milestone,
            "text": text,
        }
    )
    config.progress_messages = messages
    session.flush()


def _resolve_match_identity(
    *,
    requirement: str,
    source_text: str | None = None,
    primary_source_text: str | None = None,
    graph_entities: list[dict[str, Any]],
    graph_id: str | None = None,
    home_team: str | None,
    away_team: str | None,
    normalizer: TeamNameNormalizer,
) -> tuple[str, str, str, str]:
    extractor = FootballDataExtractor(normalizer=normalizer)
    declared_source_text = primary_source_text or source_text or requirement
    declared_home, declared_away = _resolve_declared_source_pair(declared_source_text, extractor)
    primary_home, primary_away = _resolve_primary_source_pair(primary_source_text, extractor)
    graph_home, graph_away = _resolve_graph_match_pair(
        graph_id=graph_id,
        normalizer=normalizer,
        extractor=extractor,
    )
    pair_home, pair_away = extractor._resolve_team_pair(source_text or requirement)
    home_name, away_name = FootballPredictionEngine()._resolve_teams(
        requirement,
        graph_entities,
        home_team,
        away_team,
    )
    home_iso3 = (
        _team_to_iso3(home_team, normalizer, extractor)
        or declared_home
        or primary_home
        or graph_home
        or pair_home
        or _team_to_iso3(home_name, normalizer, extractor)
        or _fallback_iso3(home_name, "HOM")
    )
    away_iso3 = (
        _team_to_iso3(away_team, normalizer, extractor)
        or declared_away
        or primary_away
        or graph_away
        or pair_away
        or _team_to_iso3(away_name, normalizer, extractor)
        or _fallback_iso3(away_name, "AWY")
    )
    home_display = home_team or (_canonical_zh(normalizer, home_iso3) if home_iso3 in normalizer.alias_map else None) or home_name
    away_display = away_team or (_canonical_zh(normalizer, away_iso3) if away_iso3 in normalizer.alias_map else None) or away_name
    return home_iso3, away_iso3, home_display or home_name, away_display or away_name


def _resolve_primary_source_pair(
    text: str | None,
    extractor: FootballDataExtractor,
) -> tuple[str | None, str | None]:
    """Resolve the match being played from uploaded document body content.

    Filenames, markdown titles, source lists and graph-derived text are noisy for
    Step2. This parser only trusts high-signal body lines such as
    ``Teams: A vs B`` or structured ``team_a``/``team_b`` fields.
    """

    source = str(text or "")
    if not source:
        return None, None

    body = source[:80000]
    structured_home, structured_away = _resolve_structured_primary_pair(body, extractor)
    if structured_home and structured_away and structured_home != structured_away:
        return structured_home, structured_away

    candidates: list[tuple[int, int, tuple[str, str]]] = []
    in_sources = False
    in_match_overview = False
    for index, raw_line in enumerate(body.splitlines()[:800]):
        line = raw_line.strip()
        if not line:
            continue

        lowered = line.casefold()
        if re.match(r"^#{1,6}\s*", line):
            in_match_overview = bool(
                re.search(r"\bmatch\s+overview\b|比赛概览|比赛信息|赛事概览|基本信息", line, flags=re.I)
            )
            in_sources = False
            continue
        if re.match(r"^-{3,}$", line):
            in_sources = False
            continue
        if re.match(r"^(?:main\s+sources?|sources?|参考来源|主要来源)\s*[:：]?\s*$", lowered, flags=re.I):
            in_sources = True
            continue
        if in_sources:
            continue
        if _looks_like_non_content_source_line(line):
            continue

        pair = _resolve_primary_pair_from_line(line, extractor)
        if pair == (None, None) or pair[0] == pair[1]:
            continue

        score = _primary_pair_line_score(line, in_match_overview=in_match_overview)
        if score >= 35:
            candidates.append((score, -index, pair))

    if not candidates:
        return None, None
    return max(candidates)[2]


def _identity_locked_by_primary_source(
    *,
    primary_source_text: str | None,
    current_home_iso3: str,
    current_away_iso3: str,
    normalizer: TeamNameNormalizer,
    home_team: str | None = None,
    away_team: str | None = None,
) -> bool:
    extractor = FootballDataExtractor(normalizer=normalizer)
    explicit_home = _team_to_iso3(home_team, normalizer, extractor)
    explicit_away = _team_to_iso3(away_team, normalizer, extractor)
    if explicit_home and explicit_away:
        return (
            _normalize_iso3(explicit_home),
            _normalize_iso3(explicit_away),
        ) == (_normalize_iso3(current_home_iso3), _normalize_iso3(current_away_iso3))

    primary_home, primary_away = _resolve_primary_source_pair(primary_source_text, extractor)
    if not primary_home or not primary_away:
        return False
    return (
        _normalize_iso3(primary_home),
        _normalize_iso3(primary_away),
    ) == (_normalize_iso3(current_home_iso3), _normalize_iso3(current_away_iso3))


def _resolve_structured_primary_pair(
    text: str,
    extractor: FootballDataExtractor,
) -> tuple[str | None, str | None]:
    team_a_patterns = (
        r"\bteam\s*a\b\s*[：:]\s*\"?(?P<team>[^\"\n\r,，;；()]+)",
        r'"team_a"\s*:\s*"(?P<team>[^"]+)"',
        r"'team_a'\s*:\s*'(?P<team>[^']+)'",
        r"球队\s*A\s*[：:]\s*(?P<team>[^\n\r,，;；()]+)",
    )
    team_b_patterns = (
        r"\bteam\s*b\b\s*[：:]\s*\"?(?P<team>[^\"\n\r,，;；()]+)",
        r'"team_b"\s*:\s*"(?P<team>[^"]+)"',
        r"'team_b'\s*:\s*'(?P<team>[^']+)'",
        r"球队\s*B\s*[：:]\s*(?P<team>[^\n\r,，;；()]+)",
    )
    team_a = _first_declared_team(text, team_a_patterns, extractor)
    team_b = _first_declared_team(text, team_b_patterns, extractor)
    return team_a, team_b


def _resolve_primary_pair_from_line(
    line: str,
    extractor: FootballDataExtractor,
) -> tuple[str | None, str | None]:
    normalized = re.sub(r"\((?:\s*team\s*[ab]\s*|球队\s*[ab]\s*)\)", "", line, flags=re.I)
    normalized = re.sub(r"^\s*[-*]\s*", "", normalized).strip()
    variants = [
        normalized,
        re.sub(
            r"^(?:teams?|match|fixture|target\s+match|main\s+match|比赛|比赛双方|对阵双方|参赛双方|本场双方|对阵|赛事)\s*[：:]\s*",
            "",
            normalized,
            flags=re.I,
        ),
    ]
    for candidate in variants:
        home, away = extractor._resolve_team_pair(candidate)
        if home and away and home != away:
            return home, away
    return None, None


def _primary_pair_line_score(line: str, *, in_match_overview: bool) -> int:
    lowered = line.casefold()
    score = 0
    if in_match_overview:
        score += 45
    if re.search(r"\bteams?\b|比赛双方|对阵双方|参赛双方|本场双方", line, flags=re.I):
        score += 55
    if re.search(r"\bteam\s*a\b|\bteam\s*b\b|球队\s*A|球队\s*B", line, flags=re.I):
        score += 20
    if re.search(r"\bmatch\b|fixture|比赛|对阵|vs\.?| v\.? ", line, flags=re.I):
        score += 20
    if re.search(r"this\s+report|this\s+match|本场|本报告", line, flags=re.I):
        score += 15
    if re.search(r"recent|first[- ]round|round\s+1|\br1\b|review|opponent|score|head[- ]to[- ]head", lowered, flags=re.I):
        score -= 35
    if re.search(r"\b\d+\s*[-:：]\s*\d+\b", line):
        score -= 25
    return score


def _looks_like_non_content_source_line(line: str) -> bool:
    lowered = line.casefold()
    return bool(
        "http://" in lowered
        or "https://" in lowered
        or "retrieved" in lowered
        or re.search(r"\b(?:sources?|references?|citation|citations)\b", lowered)
    )


def _resolve_declared_source_pair(
    text: str | None,
    extractor: FootballDataExtractor,
) -> tuple[str | None, str | None]:
    """Resolve explicitly declared target teams before noisy graph match nodes.

    Uploaded research reports often include first-round match reviews. Those
    reviews can become graph ``Match`` nodes, so only high-signal declarations
    such as "比赛双方" or structured team_a/team_b fields should override graph
    inference.
    """
    source = str(text or "")
    if not source:
        return None, None

    head = source[:12000]
    for line in head.splitlines()[:180]:
        stripped = line.strip()
        if not stripped or not re.search(r"比赛双方|对阵双方|参赛双方|本场双方", stripped, flags=re.I):
            continue
        _, _, fragment = stripped.partition("：")
        if not fragment:
            _, _, fragment = stripped.partition(":")
        if not fragment:
            fragment = stripped
        home, away = extractor._resolve_team_pair(fragment)
        if home and away and home != away:
            return home, away

    team_a_patterns = (
        r"球队\s*A\s*[：:]\s*(?P<team>[^\n\r,，;；]+)",
        r'"team_a"\s*:\s*"(?P<team>[^"]+)"',
        r"'team_a'\s*:\s*'(?P<team>[^']+)'",
    )
    team_b_patterns = (
        r"球队\s*B\s*[：:]\s*(?P<team>[^\n\r,，;；]+)",
        r'"team_b"\s*:\s*"(?P<team>[^"]+)"',
        r"'team_b'\s*:\s*'(?P<team>[^']+)'",
    )
    team_a = _first_declared_team(head, team_a_patterns, extractor)
    team_b = _first_declared_team(head, team_b_patterns, extractor)
    if team_a and team_b and team_a != team_b:
        return team_a, team_b

    return None, None


def _first_declared_team(
    text: str,
    patterns: tuple[str, ...],
    extractor: FootballDataExtractor,
) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)
        if not match:
            continue
        iso3 = extractor._resolve_team_name(match.group("team"))
        if iso3:
            return iso3
    return None


def _identity_update_from_extracted(
    *,
    current_home_iso3: str,
    current_away_iso3: str,
    current_home: str,
    current_away: str,
    extracted: dict[str, Any],
    normalizer: TeamNameNormalizer,
    dataset_id: str,
) -> tuple[str, str, str, str] | None:
    if not isinstance(extracted, dict):
        return None

    extracted_home_iso3 = (
        _valid_iso3(extracted.get("home_iso3"))
        or _team_to_iso3(extracted.get("home_name_zh"), normalizer, FootballDataExtractor(normalizer=normalizer))
    )
    extracted_away_iso3 = (
        _valid_iso3(extracted.get("away_iso3"))
        or _team_to_iso3(extracted.get("away_name_zh"), normalizer, FootballDataExtractor(normalizer=normalizer))
    )
    if not extracted_home_iso3 or not extracted_away_iso3:
        return None

    current_home_iso3 = _normalize_iso3(current_home_iso3)
    current_away_iso3 = _normalize_iso3(current_away_iso3)
    extracted_home_iso3 = _normalize_iso3(extracted_home_iso3)
    extracted_away_iso3 = _normalize_iso3(extracted_away_iso3)
    if (extracted_home_iso3, extracted_away_iso3) == (current_home_iso3, current_away_iso3):
        return None

    current_counts = (
        _dataset_team_player_count(dataset_id, current_home_iso3),
        _dataset_team_player_count(dataset_id, current_away_iso3),
    )
    extracted_counts = (
        _dataset_team_player_count(dataset_id, extracted_home_iso3),
        _dataset_team_player_count(dataset_id, extracted_away_iso3),
    )
    if min(extracted_counts) <= 0 or sum(extracted_counts) <= sum(current_counts):
        return None

    home_name = (
        str(extracted.get("home_name_zh") or "").strip()
        or _canonical_zh(normalizer, extracted_home_iso3)
        or current_home
    )
    away_name = (
        str(extracted.get("away_name_zh") or "").strip()
        or _canonical_zh(normalizer, extracted_away_iso3)
        or current_away
    )
    return extracted_home_iso3, extracted_away_iso3, home_name, away_name


def _dataset_team_player_count(dataset_id: str, iso3: str) -> int:
    if not dataset_id or not iso3:
        return 0
    with get_session() as session:
        return int(
            session.query(PredictionPlayerRecord)
            .filter_by(dataset_id=dataset_id, team_iso3=_normalize_iso3(iso3))
            .count()
        )


def _valid_iso3(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    return text if len(text) == 3 and text.isascii() and text.isalpha() else None


def _normalize_iso3(value: Any) -> str:
    return str(value or "").strip().upper()


def _resolve_graph_match_pair(
    *,
    graph_id: str | None,
    normalizer: TeamNameNormalizer,
    extractor: FootballDataExtractor,
) -> tuple[str | None, str | None]:
    if not graph_id:
        return None, None
    try:
        reader = get_entity_reader()
        nodes = [_node_mapping(item) for item in reader.get_all_nodes(graph_id)]
        edges = []
        if hasattr(reader, "get_all_edges"):
            edges = [_edge_mapping(item) for item in reader.get_all_edges(graph_id)]
    except Exception:
        return None, None

    node_map = {_node_id(node): node for node in nodes if _node_id(node)}
    edge_pair = _resolve_graph_match_pair_from_edges(
        nodes=nodes,
        edges=edges,
        node_map=node_map,
        normalizer=normalizer,
        extractor=extractor,
    )
    if edge_pair != (None, None):
        return edge_pair

    match_nodes = [node for node in nodes if _node_has_label(node, "match")]
    candidates = match_nodes or nodes
    for node in sorted(candidates, key=lambda item: _graph_match_node_priority(item, extractor), reverse=True):
        text = "\n".join(
            value
            for value in [
                str(node.get("name") or ""),
                str(node.get("summary") or ""),
                _attrs_text(node.get("attributes") or {}),
            ]
            if value
        )
        home, away = extractor._resolve_team_pair(text)
        if home and away and home != away:
            return home, away

    team_mentions: list[tuple[int, str]] = []
    for node in nodes:
        if not _node_has_label(node, "footballteam") and not _node_has_label(node, "nationalteam"):
            continue
        text = " ".join(
            value
            for value in [
                str(node.get("name") or ""),
                _attrs_text(node.get("attributes") or {}),
                str(node.get("summary") or ""),
            ]
            if value
        )
        iso3 = _team_to_iso3(text, normalizer, extractor)
        if iso3 and iso3 not in {item[1] for item in team_mentions}:
            team_mentions.append((len(team_mentions), iso3))
        if len(team_mentions) >= 2:
            return team_mentions[0][1], team_mentions[1][1]
    return None, None


def _resolve_graph_match_pair_from_edges(
    *,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    node_map: dict[str, dict[str, Any]],
    normalizer: TeamNameNormalizer,
    extractor: FootballDataExtractor,
) -> tuple[str | None, str | None]:
    if not edges:
        return None, None
    match_nodes = [node for node in nodes if _node_has_label(node, "match")]
    explicit_candidates: list[tuple[int, int, tuple[str, str]]] = []
    for index, match_node in enumerate(match_nodes):
        match_id = _node_id(match_node)
        if not match_id:
            continue
        team_a, team_b = _explicit_match_team_pair(match_id, edges, node_map, normalizer, extractor)
        if team_a and team_b and team_a != team_b:
            explicit_candidates.append((_graph_match_node_priority(match_node, extractor), -index, (team_a, team_b)))

    if explicit_candidates:
        return max(explicit_candidates)[2]

    for match_node in sorted(match_nodes, key=lambda item: _graph_match_node_priority(item, extractor), reverse=True):
        match_id = _node_id(match_node)
        if not match_id:
            continue
        text_home, text_away = _match_node_pair(match_node, extractor)
        participants = set(_teams_from_match_edges(
            match_id,
            edges,
            node_map,
            ("has_team", "has_participant", "features_team", "involved_team", "participates_in"),
            normalizer,
            extractor,
        ))
        if text_home and text_away and {text_home, text_away}.issubset(participants):
            return text_home, text_away
    return None, None


def _explicit_match_team_pair(
    match_id: str,
    edges: list[dict[str, Any]],
    node_map: dict[str, dict[str, Any]],
    normalizer: TeamNameNormalizer,
    extractor: FootballDataExtractor,
) -> tuple[str | None, str | None]:
    team_a = (
        _team_from_match_edges(match_id, edges, node_map, ("has_team_a",), normalizer, extractor)
        or _team_from_match_edges_by_fact(
            match_id,
            edges,
            node_map,
            ("has_team",),
            ("team_a", "team a", "球队 a", "球队a"),
            normalizer,
            extractor,
        )
    )
    team_b = (
        _team_from_match_edges(match_id, edges, node_map, ("has_team_b",), normalizer, extractor)
        or _team_from_match_edges_by_fact(
            match_id,
            edges,
            node_map,
            ("has_team",),
            ("team_b", "team b", "球队 b", "球队b"),
            normalizer,
            extractor,
        )
    )
    return team_a, team_b


def _team_from_match_edges(
    match_id: str,
    edges: list[dict[str, Any]],
    node_map: dict[str, dict[str, Any]],
    edge_names: tuple[str, ...],
    normalizer: TeamNameNormalizer,
    extractor: FootballDataExtractor,
) -> str | None:
    teams = _teams_from_match_edges(match_id, edges, node_map, edge_names, normalizer, extractor)
    return teams[0] if teams else None


def _team_from_match_edges_by_fact(
    match_id: str,
    edges: list[dict[str, Any]],
    node_map: dict[str, dict[str, Any]],
    edge_names: tuple[str, ...],
    fact_markers: tuple[str, ...],
    normalizer: TeamNameNormalizer,
    extractor: FootballDataExtractor,
) -> str | None:
    for edge in edges:
        if _edge_name(edge) not in edge_names:
            continue
        fact = str(edge.get("fact") or "").lower()
        if not any(marker in fact for marker in fact_markers):
            continue
        linked_node = _edge_other_node(edge, match_id, node_map)
        if not linked_node:
            continue
        if not _node_has_label(linked_node, "footballteam") and not _node_has_label(linked_node, "nationalteam"):
            continue
        iso3 = _team_to_iso3(_node_team_text(linked_node), normalizer, extractor)
        if iso3:
            return iso3
    return None


def _teams_from_match_edges(
    match_id: str,
    edges: list[dict[str, Any]],
    node_map: dict[str, dict[str, Any]],
    edge_names: tuple[str, ...],
    normalizer: TeamNameNormalizer,
    extractor: FootballDataExtractor,
) -> list[str]:
    teams: list[str] = []
    for edge in edges:
        if _edge_name(edge) not in edge_names:
            continue
        linked_node = _edge_other_node(edge, match_id, node_map)
        if not linked_node:
            continue
        if not _node_has_label(linked_node, "footballteam") and not _node_has_label(linked_node, "nationalteam"):
            continue
        iso3 = _team_to_iso3(_node_team_text(linked_node), normalizer, extractor)
        if iso3 and iso3 not in teams:
            teams.append(iso3)
    return teams


def _node_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {
        "name": getattr(value, "name", ""),
        "labels": getattr(value, "labels", []) or [],
        "summary": getattr(value, "summary", ""),
        "attributes": getattr(value, "attributes", {}) or {},
    }


def _edge_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {
        "name": getattr(value, "name", ""),
        "fact": getattr(value, "fact", ""),
        "source_node_uuid": getattr(value, "source_node_uuid", ""),
        "target_node_uuid": getattr(value, "target_node_uuid", ""),
    }


def _node_id(node: dict[str, Any]) -> str:
    return str(node.get("uuid") or node.get("id") or node.get("node_id") or "").strip()


def _edge_name(edge: dict[str, Any]) -> str:
    return str(edge.get("name") or "").strip().replace("-", "_").lower()


def _edge_other_node(
    edge: dict[str, Any],
    node_id: str,
    node_map: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    source = str(edge.get("source_node_uuid") or edge.get("source") or "").strip()
    target = str(edge.get("target_node_uuid") or edge.get("target") or "").strip()
    if source == node_id:
        return node_map.get(target)
    if target == node_id:
        return node_map.get(source)
    return None


def _node_has_label(node: dict[str, Any], expected: str) -> bool:
    expected = expected.lower()
    labels = [str(label).lower() for label in (node.get("labels") or [])]
    attrs = node.get("attributes") or {}
    if isinstance(attrs, dict):
        labels.extend(str(label).lower() for label in (attrs.get("labels") or []))
    return expected in labels


def _graph_match_node_priority(node: dict[str, Any], extractor: FootballDataExtractor) -> int:
    text = " ".join([str(node.get("name") or ""), str(node.get("summary") or "")]).lower()
    score = 0
    home, away = _match_node_pair(node, extractor)
    if home and away:
        score += 10
    if "match 12" in text or "小组赛" in text or "group" in text or "world cup" in text or "世界杯" in text:
        score += 3
    if "预选赛" in text or "友谊赛" in text or "非洲杯" in text or "qualification" in text or "friendly" in text:
        score -= 6
    if str(node.get("name") or "").strip().lower() in {"本场", "match 12"}:
        score += 4
    return score


def _match_node_pair(node: dict[str, Any], extractor: FootballDataExtractor) -> tuple[str | None, str | None]:
    text = "\n".join(
        value
        for value in [
            str(node.get("name") or ""),
            str(node.get("summary") or ""),
            _attrs_text(node.get("attributes") or {}),
        ]
        if value
    )
    return extractor._resolve_team_pair(text)


def _node_team_text(node: dict[str, Any]) -> str:
    return " ".join(
        value
        for value in [
            str(node.get("name") or ""),
            _attrs_text(node.get("attributes") or {}),
            str(node.get("summary") or ""),
        ]
        if value
    )


def _attrs_text(attrs: Any) -> str:
    if not isinstance(attrs, dict):
        return ""
    values = []
    for key, value in attrs.items():
        if key == "labels":
            continue
        if isinstance(value, (dict, list)):
            values.append(str(value))
        elif value is not None:
            values.append(str(value))
    return " ".join(values)


def _team_to_iso3(value: str | None, normalizer: TeamNameNormalizer, extractor: FootballDataExtractor) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if len(text) == 3 and text.isascii() and text.isalpha():
        return text.upper()
    return normalizer.to_iso3(text) or extractor._resolve_team_name(text)


def _canonical_zh(normalizer: TeamNameNormalizer, iso3: str) -> str | None:
    try:
        return normalizer.to_canonical_zh(iso3)
    except Exception:
        return None


def _fallback_iso3(team_name: str, fallback: str) -> str:
    ascii_chars = "".join(ch for ch in (team_name or "").upper() if ch.isascii() and ch.isalnum())
    return (ascii_chars[:3] or fallback).ljust(3, "X")[:3]


def _roster_with_display_name(roster: TeamRoster, display_name: str) -> TeamRoster:
    if not display_name or roster.team_fifa == display_name:
        return roster
    return TeamRoster(iso3=roster.iso3, team_fifa=display_name, players=roster.players)


def _competition_label(competition: Any | None) -> str | None:
    if not competition:
        return None
    if isinstance(competition, dict):
        value = competition.get("tournament") or competition.get("name")
        return str(value) if value else None
    return str(competition)


def _apply_competition_payload(base: dict[str, Any], competition: Any | None) -> dict[str, Any]:
    if not competition:
        return dict(base or {})
    merged = dict(base or {})
    if isinstance(competition, dict):
        for key in ("tournament", "stage", "knockout", "neutral_venue", "host_country_iso3"):
            if key in competition:
                merged[key] = competition[key]
        for key, value in competition.items():
            merged.setdefault(key, value)
        return merged
    merged["tournament"] = str(competition)
    return merged


def _match_context_text(
    *,
    source_text: str,
    requirement: str,
    graph_entities: list[dict[str, Any]],
    home_iso3: str,
    away_iso3: str,
    normalizer: TeamNameNormalizer,
) -> str:
    graph_text = "\n".join(
        " ".join(
            value
            for value in [
                str(entity.get("name") or ""),
                str(entity.get("summary") or ""),
                _attrs_text(entity.get("attributes") or {}),
            ]
            if value
        )
        for entity in graph_entities
    )
    current_match_texts = [
        *_collect_match_texts(graph_text, home_iso3, away_iso3, normalizer),
        *_collect_match_texts(source_text, home_iso3, away_iso3, normalizer),
    ]
    if current_match_texts:
        return "\n".join(current_match_texts)
    return requirement or source_text or ""


def _collect_match_texts(
    text: str,
    home_iso3: str,
    away_iso3: str,
    normalizer: TeamNameNormalizer,
) -> list[str]:
    if not text or not home_iso3 or not away_iso3:
        return []

    home_variants = _team_name_variants(home_iso3, normalizer)
    away_variants = _team_name_variants(away_iso3, normalizer)
    lines = [line.strip() for line in re.split(r"[\n\r]+", text) if line.strip()]
    if not lines:
        return []

    scored: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        line_text = line.casefold()
        score = 0
        if any(variant in line_text for variant in home_variants):
            score += 2
        if any(variant in line_text for variant in away_variants):
            score += 2
        if re.search(r"比赛|match|stadium|场地|场馆|地点|venue|开球|kick off", line_text, re.I):
            score += 1
        if score >= 2:
            scored.append((score, -index, line))
    scored.sort(reverse=True)
    return [line for _score, _index, line in scored[:8]]


def _team_name_variants(iso3: str, normalizer: TeamNameNormalizer) -> list[str]:
    variants = {iso3.casefold()}
    try:
        variants.add(normalizer.to_canonical_en(iso3).casefold())
        variants.add(normalizer.to_canonical_zh(iso3).casefold())
    except Exception:
        pass
    return [variant for variant in variants if variant]


def _extracted_competition_meta_for_match(
    *,
    extracted: dict[str, Any],
    current_home_iso3: str,
    current_away_iso3: str,
) -> dict[str, Any]:
    if not isinstance(extracted, dict):
        return {}
    extracted_home_iso3 = _valid_iso3(extracted.get("home_iso3"))
    extracted_away_iso3 = _valid_iso3(extracted.get("away_iso3"))
    if not extracted_home_iso3 or not extracted_away_iso3:
        return {}
    if (extracted_home_iso3, extracted_away_iso3) != (_normalize_iso3(current_home_iso3), _normalize_iso3(current_away_iso3)):
        return {}
    competition_meta = extracted.get("competition_meta") or extracted.get("competition") or {}
    return dict(competition_meta) if isinstance(competition_meta, dict) else {}


def _apply_local_host_country(
    competition_meta: dict[str, Any],
    text: str,
    *,
    home_iso3: str | None = None,
    away_iso3: str | None = None,
    competition: Any | None,
) -> dict[str, Any]:
    merged = dict(competition_meta or {})
    inferred_host = infer_2026_world_cup_host_country(
        text,
        home_iso3=home_iso3,
        away_iso3=away_iso3,
    )
    if inferred_host:
        merged["host_country_iso3"] = inferred_host
    if isinstance(competition, dict):
        explicit_host = _valid_iso3(competition.get("host_country_iso3"))
        if explicit_host:
            merged["host_country_iso3"] = explicit_host
    return merged


_PREDICTION_KNOCKOUT_STAGES = {"round_of_16", "quarter_final", "semi_final", "third_place", "final"}
_PREDICTION_STAGE_ALIASES = {
    "group": "group",
    "group_stage": "group",
    "小组赛": "group",
    "round_of_16": "round_of_16",
    "last_16": "round_of_16",
    "16强": "round_of_16",
    "八分之一决赛": "round_of_16",
    "quarter_final": "quarter_final",
    "quarter-final": "quarter_final",
    "四分之一决赛": "quarter_final",
    "semi_final": "semi_final",
    "semi-final": "semi_final",
    "半决赛": "semi_final",
    "third_place": "third_place",
    "三四名": "third_place",
    "季军赛": "third_place",
    "final": "final",
    "决赛": "final",
}


def _normalize_prediction_stage(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.lower().replace(" ", "_")
    return _PREDICTION_STAGE_ALIASES.get(text) or _PREDICTION_STAGE_ALIASES.get(normalized) or text


def _normalize_competition_meta_for_prediction(meta: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    normalized = dict(meta or {})
    warnings: list[str] = []
    if normalized.pop("_stage_conflict_kept_group", False):
        warnings.append("competition_stage_conflict_kept_group")
    stage = _normalize_prediction_stage(normalized.get("stage"))
    if stage:
        normalized["stage"] = stage
    if stage == "group":
        if bool(normalized.get("knockout")):
            warnings.append("competition_knockout_overridden_for_group_stage")
        normalized["knockout"] = False
    elif stage in _PREDICTION_KNOCKOUT_STAGES:
        normalized["knockout"] = True
    else:
        normalized["knockout"] = bool(normalized.get("knockout"))
    normalized.setdefault("neutral_venue", False)
    normalized.setdefault("host_country_iso3", None)
    return normalized, warnings


def _merge_competition_meta(
    base: dict[str, Any],
    extracted: dict[str, Any],
    *,
    competition: Any | None,
    kickoff_time: str | None,
) -> dict[str, Any]:
    base = dict(base or {})
    extracted = dict(extracted or {})
    base_stage = _normalize_prediction_stage(base.get("stage"))
    extracted_stage = _normalize_prediction_stage(extracted.get("stage"))
    keep_base_group = bool(
        base_stage == "group"
        and extracted_stage in _PREDICTION_KNOCKOUT_STAGES
        and not competition
    )
    if keep_base_group:
        merged = {**base, **{key: value for key, value in extracted.items() if key not in {"stage", "knockout"}}}
        merged["stage"] = "group"
        merged["knockout"] = False
        merged["_stage_conflict_kept_group"] = True
    else:
        merged = {**base, **extracted}
    if competition:
        merged = _apply_competition_payload(merged, competition)
    if kickoff_time:
        merged["kickoff_iso"] = kickoff_time
    stage = _normalize_prediction_stage(merged.get("stage"))
    if stage:
        merged["stage"] = stage
    if stage in _PREDICTION_KNOCKOUT_STAGES:
        merged["knockout"] = True
    merged.setdefault("knockout", False)
    merged.setdefault("neutral_venue", False)
    merged.setdefault("host_country_iso3", None)
    return merged


def _legacy_fit_artifacts(
    *,
    home_iso3: str,
    away_iso3: str,
    model_diagnostics: dict[str, Any],
) -> FitArtifacts:
    return FitArtifacts(
        model=None,
        fit_status=str(model_diagnostics.get("fit_status") or "fallback_prior"),
        data_sufficiency=str(model_diagnostics.get("data_sufficiency") or "partial"),
        model_name=str(model_diagnostics.get("model_name") or "prior_poisson"),
        diagnostics=dict(model_diagnostics.get("diagnostics") or {}),
        home_advantage=0.0,
        xg_priors={home_iso3: 1.35, away_iso3: 1.35},
    )


def _team_strength_record_payload(value: Any, *, display_name: str | None = None) -> dict[str, Any]:
    payload = value.to_dict() if hasattr(value, "to_dict") else dict(value)
    metadata = {
        **(payload.get("metadata") or {}),
        "team_iso3": payload.get("team_iso3"),
        "home_away_adjustment_reason": payload.get("home_away_adjustment_reason"),
        "injury_evidence_refs": payload.get("injury_evidence_refs") or [],
        "form_evidence_refs": payload.get("form_evidence_refs") or [],
    }
    evidence = payload.get("evidence") or payload.get("evidence_breakdown") or []
    return {
        "team_role": payload.get("team_role") or "home",
        "team_name": display_name or payload.get("team_name") or payload.get("team_iso3") or "",
        "attack_rating": _int_rating(payload.get("attack_rating"), 60),
        "defense_rating": _int_rating(payload.get("defense_rating"), 60),
        "possession_rating": _int_rating(payload.get("possession_rating"), 60),
        "transition_rating": _int_rating(payload.get("transition_rating"), 60),
        "set_piece_rating": _int_rating(payload.get("set_piece_rating"), 60),
        "discipline_rating": _int_rating(payload.get("discipline_rating"), 60),
        "fitness_rating": _int_rating(payload.get("fitness_rating"), 60),
        "goalkeeper_rating": _int_rating(payload.get("goalkeeper_rating"), 60),
        "home_away_adjustment": _adjustment_to_int(payload.get("home_away_adjustment")),
        "injury_adjustment": _int_rating(payload.get("injury_adjustment"), 0),
        "form_adjustment": _int_rating(payload.get("form_adjustment"), 0),
        "evidence": evidence,
        "confidence": _int_rating(payload.get("confidence"), 60),
        "metadata": metadata,
    }


def _int_rating(value: Any, default: int) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _adjustment_to_int(value: Any) -> int:
    try:
        numeric = float(value or 0)
    except (TypeError, ValueError):
        return 0
    if abs(numeric) <= 1:
        numeric *= 100
    return int(round(numeric))


def _role_label(role_key: str) -> str:
    role = ROLE_BY_KEY.get(role_key)
    return role.label if role else role_key


def _scenario_case_record_payload(case: Any, *, fit_artifacts: FitArtifacts) -> dict[str, Any]:
    payload = asdict(case) if hasattr(case, "__dataclass_fields__") else dict(case)
    summary = dict(payload.get("coach_vote_summary") or {})
    initial = _int_rating(payload.get("initial_weight"), 0)
    final = _int_rating(payload.get("final_weight"), initial)
    summary.setdefault(
        "weight_change",
        {
            "initial": initial,
            "final": final,
            "applied_delta": final - initial,
            "applied_delta_pct": summary.get("applied_delta_pct", 0),
            "pre_normalization_weight": summary.get("pre_normalization_weight"),
            "pre_normalization_weight_delta": summary.get("pre_normalization_weight_delta"),
        },
    )
    return {
        "home_state": payload.get("home_state") or "",
        "away_state": payload.get("away_state") or "",
        "scenario_key": payload.get("scenario_key") or "",
        "scenario_name": payload.get("scenario_name") or payload.get("scenario_key") or "",
        "scenario_space": payload.get("scenario_space") or "baseline",
        "initial_weight": initial,
        "final_weight": final,
        "key_drivers": list(payload.get("key_drivers") or []),
        "risk_factors": list(payload.get("risk_factors") or []),
        "coach_vote_summary": summary,
        "model_constraints": {
            "fit_status": fit_artifacts.fit_status,
            "model_name": fit_artifacts.model_name,
            "max_weight_adjustment_pct": summary.get("max_weight_adjustment_pct", 30),
        },
    }


def _scenario_design_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": "scenario_design_v2",
        "scenario_cases_count": len(rows),
        "space_groups_count": len({row["scenario_space"] for row in rows}),
        "coach_agents_count": 100,
        "consensus_score": 0.74,
        "disagreement_score": 0.26,
        "matrix": [
            {
                "scenario_key": row["scenario_key"],
                "home_state": row["home_state"],
                "away_state": row["away_state"],
                "scenario_name": row["scenario_name"],
                "scenario_space": row["scenario_space"],
                "initial_weight": row["initial_weight"],
                "final_weight": row["final_weight"],
                "weight_change": (row.get("coach_vote_summary") or {}).get("weight_change")
                or {
                    "initial": row["initial_weight"],
                    "final": row["final_weight"],
                    "applied_delta": row["final_weight"] - row["initial_weight"],
                    "applied_delta_pct": (row.get("coach_vote_summary") or {}).get("applied_delta_pct", 0),
                },
                "key_drivers": row["key_drivers"],
                "risk_factors": row["risk_factors"],
            }
            for row in rows
        ],
    }


def _coach_jury_summary(
    *,
    verdicts: list[Any],
    fit_artifacts: FitArtifacts,
    ledger_summary: dict[str, Any],
) -> dict[str, Any]:
    contributors = []
    for verdict in verdicts:
        payload = verdict.to_dict() if hasattr(verdict, "to_dict") else dict(verdict)
        metadata = dict(payload.get("metadata") or {})
        contributors.append(
            {
                "role": payload.get("role"),
                "summary": payload.get("summary") or "",
                "source": metadata.get("source") or "coach_llm_panel_v1",
                "clipped": bool(payload.get("clipped", False)),
            }
        )
    return {
        "version": "coach_jury_v2",
        "panel_version": PANEL_VERSION,
        "contributors": contributors,
        "fit_status": fit_artifacts.fit_status,
        "ledger_summary": ledger_summary,
    }


def _model_diagnostics_from_fit(fit_artifacts: FitArtifacts) -> dict[str, Any]:
    fit_dict = fit_artifacts.to_dict()
    return {
        "model_name": fit_dict["model_name"],
        "model_version": getattr(FootballGoalModelAdapter, "MODEL_VERSION", "v2"),
        "fit_status": fit_dict["fit_status"],
        "data_sufficiency": fit_dict["data_sufficiency"],
        "diagnostics": fit_dict.get("diagnostics") or {},
        "home_advantage": fit_dict.get("home_advantage", 0.0),
        "xg_priors": fit_dict.get("xg_priors") or {},
        "attack_coef": fit_dict.get("attack_coef") or {},
        "defense_coef": fit_dict.get("defense_coef") or {},
        "intercept": fit_dict.get("intercept", 0.0),
    }


def _external_sources_etag(external_pool: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, source in {
        "intl_results": getattr(external_pool, "intl_results", None),
        "national_elo": getattr(external_pool, "elo", None),
    }.items():
        fingerprint = getattr(source, "fingerprint", None)
        if callable(fingerprint):
            try:
                payload[key] = fingerprint()
            except Exception as exc:
                payload[key] = {"error": f"{type(exc).__name__}: {exc}"}
    for key, error in (getattr(external_pool, "source_errors", None) or {}).items():
        payload[key] = {**(payload.get(key) if isinstance(payload.get(key), dict) else {}), "error": str(error)}
    if getattr(external_pool, "sources", None):
        payload["sources"] = list(getattr(external_pool, "sources"))
    if not payload:
        payload["sha1"] = hashlib.sha1(repr(type(external_pool)).encode("utf-8")).hexdigest()[:12]
    return payload


def _external_offline_enabled() -> bool:
    raw = os.environ.get("EXTERNAL_DATA_OFFLINE")
    if raw is None:
        return True
    return raw.strip().lower() not in {"0", "false", "no", "off"}

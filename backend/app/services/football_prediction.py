"""Football-only prediction engine and persistence helpers.

This module intentionally does not depend on the retired social simulation runtime. It generates deterministic
football prediction artifacts that can be persisted and replayed by the UI.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from ..config import Config
from ..db.models import (
    GraphBindingRecord,
    PredictionAnalystNoteRecord,
    PredictionCoachDiscussionRecord,
    PredictionConfigRecord,
    PredictionConfigScenarioCaseRecord,
    PredictionMatchEventRecord,
    PredictionPlayerDatasetRecord,
    PredictionPlayerRecord,
    PredictionReportRecord,
    PredictionReportSectionRecord,
    PredictionResultRecord,
    PredictionRunRecord,
    PredictionScenarioCaseRecord,
    PredictionScenarioSpaceRecord,
    PredictionScorelineRecord,
    PredictionSourceDocumentRecord,
    PredictionTeamMetadataRecord,
    PredictionTeamStrengthRecord,
    ProjectRecord,
    TaskEventRecord,
    utc_now,
)
from ..db.session import get_session
from .analyst_notes_writer import AnalystNotesWriter
from .coach_jury import CoachJuryService
from .coach_review_writer import CoachReviewWriter
from .event_narrative_polisher import EventNarrativePolisher
from .external_data.national_elo import NationalElo
from .football_goal_model import FitArtifacts, FootballGoalModelAdapter
from .llm_budget import LLMCallLedger, LLMBudgetProfile, MAX_HARD_CAP_CALLS
from ..utils.llm_client import LLMClient
from .match_simulator import MatchSimulator, SimulationResult, Trajectory
from .content_language import instruction_for_project
from .project_workflow import ProjectWorkflowService
from .roster_loader import PlayerSnapshot, RosterLoader, TeamRoster
from .team_localization import (
    localize_scenario_case_rows,
    localize_scenario_space_rows,
    localize_step2_payload,
    localize_team_strength_rows,
)


FOOTBALL_EVENT_SEQUENCE: tuple[tuple[int, str], ...] = (
    (10, "upload_files"),
    (20, "extract_match_material"),
    (30, "generate_football_ontology"),
    (40, "build_match_graph"),
    (50, "extract_team_context"),
    (60, "build_prediction_config"),
    (65, "generate_coach_agents"),
    (70, "discuss_scenario_space_design"),
    (75, "discuss_resume_replay_policy"),
    (80, "initialize_scientific_model"),
    (90, "compute_team_strength"),
    (100, "generate_scenario_matrix"),
    (110, "compute_scoreline_distribution"),
    (120, "generate_nine_scenario_match_events"),
    (130, "coach_review_match_events"),
    (140, "generate_analyst_notes"),
    (150, "generate_report"),
    (160, "prepare_prediction_qa"),
)


MATCH_EVENT_TYPES = {
    "KICKOFF",
    "TACTICAL_PHASE",
    "CHANCE_CREATED",
    "SHOT",
    "SAVE",
    "GOAL",
    "FOUL",
    "YELLOW_CARD",
    "VAR_CHECK",
    "SUBSTITUTION",
    "PRESSURE_SHIFT",
    "EXTRA_TIME",
    "PENALTY_SHOOTOUT",
    "FINAL_SCORE_HYPOTHESIS",
}


class FootballPredictionEngine:
    """Generate first-version football prediction artifacts.

    The engine is deliberately deterministic: the same project/run inputs
    produce the same shape of artifacts, making resume and replay predictable.
    """

    SCENARIO_CASES = (
        ("normal", "normal", "baseline", "基准走势", 22),
        ("overperform", "normal", "home_upside", "主队优势走势", 13),
        ("normal", "underperform", "home_upside", "主队受益走势", 11),
        ("underperform", "normal", "away_upside", "客队受益走势", 11),
        ("normal", "overperform", "away_upside", "客队优势走势", 13),
        ("underperform", "overperform", "volatility", "客队爆冷走势", 7),
        ("overperform", "underperform", "away_error", "主队大胜走势", 8),
        ("underperform", "underperform", "home_error", "混乱低质量比赛", 7),
        ("overperform", "overperform", "volatility", "高质量对攻", 8),
    )

    SCENARIO_SPACES = (
        ("baseline", "基准发挥空间", "双方正常发挥下的稳态比赛路径。"),
        ("home_upside", "主队上行空间", "主队压迫、边路和定位球收益提升的路径。"),
        ("away_upside", "客队上行空间", "客队反击、门将和定位球偷袭收益提升的路径。"),
        ("home_error", "主队失误空间", "主队传控、后防沟通、纪律或换人风险放大的路径。"),
        ("away_error", "客队失误空间", "客队防线、体能、纪律和出球压力恶化的路径。"),
        ("volatility", "高波动事件空间", "点球、VAR、红牌、伤退、天气和早进球改变比赛的路径。"),
    )

    def run(
        self,
        *,
        prediction_run_id: str,
        project_id: str,
        graph_id: str | None,
        simulation_requirement: str,
        graph_entities: list[dict[str, Any]] | None = None,
        home_team: str | None = None,
        away_team: str | None = None,
        prediction_config_id: str | None = None,
        config_scenario_cases: list[dict[str, Any]] | None = None,
        prepared_team_strengths: list[dict[str, Any]] | None = None,
        model_diagnostics: dict[str, Any] | None = None,
        model_input_snapshot: dict[str, Any] | None = None,
        llm_budget_profile: dict[str, Any] | None = None,
        _override_seed: int | None = None,
    ) -> dict[str, Any]:
        model_input_snapshot = model_input_snapshot or {}
        home, away = self._resolve_teams(simulation_requirement, graph_entities or [], home_team, away_team)
        team_strengths = _ordered_team_strengths(
            prepared_team_strengths or self._team_strengths(home, away, graph_entities or [], simulation_requirement)
        )
        model_diagnostics = model_diagnostics or {
            "model_name": "prior_poisson",
            "model_version": "v1",
            "fit_status": "fallback_prior",
            "data_sufficiency": "partial",
        }
        home_model_key, away_model_key = _model_team_keys(home, away, team_strengths, model_input_snapshot)
        fit_artifacts = _fit_artifacts_from_snapshot(
            model_input_snapshot,
            model_diagnostics,
            home_model_key,
            away_model_key,
            team_strengths,
        )
        model_diagnostics = {
            **model_diagnostics,
            "model_name": fit_artifacts.model_name,
            "fit_status": fit_artifacts.fit_status,
            "data_sufficiency": fit_artifacts.data_sufficiency,
            "diagnostics": fit_artifacts.diagnostics,
        }
        squads = _squads_from_snapshot_or_fallback(model_input_snapshot, home, away, team_strengths)
        competition, competition_warnings = _normalized_competition_payload(model_input_snapshot)
        warnings = list(model_input_snapshot.get("warnings") or [])
        for warning in competition_warnings:
            if warning not in warnings:
                warnings.append(warning)
        budget = _resolve_step3_budget(llm_budget_profile or model_input_snapshot.get("llm_budget"))
        ledger = LLMCallLedger(config_id=prediction_config_id, run_id=prediction_run_id, budget=budget)
        content_language_instruction = instruction_for_project(project_id)
        simulation_seed = int(_override_seed) if _override_seed is not None else self._generate_seed(
            prediction_config_id or prediction_run_id,
            utc_now(),
        )
        scenario_cases = self._scenario_cases(
            prediction_run_id,
            home,
            away,
            team_strengths,
            config_scenario_cases=config_scenario_cases,
            model_diagnostics=model_diagnostics,
        )
        for case in scenario_cases:
            home_xg, away_xg = fit_artifacts.compute_match_xg(
                home_model_key,
                away_model_key,
                home_factor=float(case["strength_adjustments"]["home_factor"]),
                away_factor=float(case["strength_adjustments"]["away_factor"]),
            )
            home_xg, away_xg, xg_calibration = _calibrate_matchup_xg(
                home_xg,
                away_xg,
                home_model_key=home_model_key,
                away_model_key=away_model_key,
                team_strengths=team_strengths,
                model_input_snapshot=model_input_snapshot,
                fit_artifacts=fit_artifacts,
            )
            case["expected_goals"] = {"home": home_xg, "away": away_xg}
            if xg_calibration:
                case["metadata"] = {**(case.get("metadata") or {}), "xg_calibration": xg_calibration}

        simulator = MatchSimulator(squads=squads, fit_artifacts=fit_artifacts, competition=competition)
        sim_results: dict[str, SimulationResult] = {}
        for case in scenario_cases:
            scenario_key = str(case["scenario_key"])
            sim_result = simulator.simulate_match(
                home_xg=float(case["expected_goals"]["home"]),
                away_xg=float(case["expected_goals"]["away"]),
                n_sims=budget.n_sims,
                knockout=bool(competition.get("knockout")),
                seed=_scenario_seed(simulation_seed, scenario_key),
            )
            sim_results[scenario_key] = sim_result
            case["win_draw_loss_probability"] = _rounded_probabilities(sim_result.wdl)
            case["scoreline_distribution"] = _rounded_distribution(sim_result.scoreline_distribution)
            case["metadata"] = {
                **(case.get("metadata") or {}),
                "source": "scenario_matrix_step3_mc_v1",
                "simulation_seed": simulation_seed,
                "scenario_seed": sim_result.sim_seed,
                "n_sims": sim_result.n_sims,
                "simulation_version": sim_result.sim_version,
                "modal_final_score": sim_result.modal_trajectory.final_score_str,
                "knockout_path_distribution": sim_result.knockout_path_distribution,
            }

        scorelines = self._scorelines_from_sims(prediction_run_id, scenario_cases, sim_results, model_diagnostics)
        scenario_spaces = self._scenario_spaces(prediction_run_id, scenario_cases, scorelines)
        match_events = self._match_events_from_modal_trajectories(
            prediction_run_id,
            home,
            away,
            scenario_cases,
            sim_results,
            squads,
            budget,
            ledger,
            content_language_instruction,
        )
        coach_review = CoachReviewWriter(
            budget=budget,
            ledger=ledger,
            content_language_instruction=content_language_instruction,
        ).review(
            scenario_cases=scenario_cases,
            sim_results=sim_results,
            team_strengths=(team_strengths[0], team_strengths[1]),
        )
        analyst_notes = self._step3_analyst_notes(
            prediction_run_id,
            home,
            away,
            scenario_cases,
            sim_results,
            scorelines,
            model_input_snapshot,
            budget,
            ledger,
            coach_review,
            content_language_instruction,
        )
        prediction_result = self._prediction_result(
            prediction_run_id,
            team_strengths,
            scenario_cases,
            scenario_spaces,
            scorelines,
            match_events,
            analyst_notes,
            competition,
        )
        ledger_summary = ledger.summary()
        prediction_result["metadata"] = {
            **(prediction_result.get("metadata") or {}),
            "source": "football_prediction_engine_step3_mc_v1",
            "simulation_seed": simulation_seed,
            "n_sims": budget.n_sims,
            "simulation_version": simulator.SIM_VERSION,
            "ledger_summary": ledger_summary,
            "knockout_path_distribution": _run_knockout_distribution(sim_results),
            "warnings": warnings,
        }
        prediction_result["simulation_summary"] = {
            "simulation_seed": simulation_seed,
            "n_sims": budget.n_sims,
            "simulation_version": simulator.SIM_VERSION,
            "competition": competition,
            "warnings": warnings,
        }

        return {
            "prediction_run_id": prediction_run_id,
            "prediction_config_id": prediction_config_id,
            "project_id": project_id,
            "graph_id": graph_id,
            "home_team": home,
            "away_team": away,
            "team_strengths": team_strengths,
            "scenario_cases": scenario_cases,
            "scenario_spaces": scenario_spaces,
            "scorelines": scorelines,
            "match_events": match_events,
            "analyst_notes": analyst_notes,
            "prediction_result": prediction_result,
            "simulation_seed": simulation_seed,
            "n_sims": budget.n_sims,
            "simulation_version": simulator.SIM_VERSION,
            "ledger_summary": ledger_summary,
            "knockout_path_distribution": _run_knockout_distribution(sim_results),
        }

    def _resolve_teams(
        self,
        requirement: str,
        graph_entities: list[dict[str, Any]],
        home_team: str | None,
        away_team: str | None,
    ) -> tuple[str, str]:
        if home_team and away_team:
            return home_team, away_team

        candidates = re.split(r"\s+vs\s+|\s+VS\s+|\s+v\s+|对阵|VS|vs", requirement)
        if len(candidates) >= 2:
            left = _clean_team_name(candidates[0])
            right = _clean_team_name(candidates[1])
            if left and right:
                return home_team or left, away_team or right

        teams = [
            str(entity.get("name") or "").strip()
            for entity in graph_entities
            if str(entity.get("entity_type") or entity.get("type") or "").lower() in {"footballteam", "team"}
        ]
        teams = [team for team in teams if team]
        if len(teams) >= 2:
            return home_team or teams[0], away_team or teams[1]

        return home_team or "主队", away_team or "客队"

    def _team_strengths(
        self,
        home: str,
        away: str,
        graph_entities: list[dict[str, Any]],
        requirement: str,
    ) -> list[dict[str, Any]]:
        return [
            self._team_strength("home", home, graph_entities, requirement, home_boost=4),
            self._team_strength("away", away, graph_entities, requirement, home_boost=0),
        ]

    def _team_strength(
        self,
        role: str,
        team: str,
        graph_entities: list[dict[str, Any]],
        requirement: str,
        home_boost: int,
    ) -> dict[str, Any]:
        seed = _stable_number(f"{team}:{role}:{requirement}", 0, 18)
        base = 58 + seed
        evidence = [
            entity
            for entity in graph_entities
            if team and team in str(entity.get("name") or entity.get("summary") or "")
        ][:5]
        confidence = 68 if evidence else 52
        return {
            "team_role": role,
            "team_name": team,
            "attack_rating": min(92, base + home_boost),
            "defense_rating": min(90, base - 2 + (home_boost // 2)),
            "possession_rating": min(90, base + _stable_number(team + "possession", -5, 7)),
            "transition_rating": min(90, base + _stable_number(team + "transition", -4, 8)),
            "set_piece_rating": min(88, base + _stable_number(team + "setpiece", -6, 6)),
            "discipline_rating": min(90, max(45, base + _stable_number(team + "discipline", -8, 4))),
            "fitness_rating": min(88, max(45, base + _stable_number(team + "fitness", -6, 5))),
            "goalkeeper_rating": min(90, max(45, base + _stable_number(team + "gk", -5, 8))),
            "home_away_adjustment": home_boost,
            "injury_adjustment": -2 if "伤" in requirement or "injury" in requirement.lower() else 0,
            "form_adjustment": _stable_number(team + "form", -3, 5),
            "evidence": evidence,
            "confidence": confidence,
            "metadata": {"source": "football_prediction_engine_v1"},
        }

    def _generate_seed(self, source_id: str | None, now) -> int:
        digest = hashlib.sha1(f"{source_id or 'adhoc'}:{now.isoformat()}".encode("utf-8")).hexdigest()
        return int(digest[:12], 16) % (2**31 - 1)

    def _scenario_cases(
        self,
        prediction_run_id: str,
        home: str,
        away: str,
        team_strengths: list[dict[str, Any]],
        *,
        config_scenario_cases: list[dict[str, Any]] | None = None,
        model_diagnostics: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        home_attack = team_strengths[0]["attack_rating"]
        away_attack = team_strengths[1]["attack_rating"]
        cases = []
        templates = config_scenario_cases or [
            {
                "id": None,
                "home_state": home_state,
                "away_state": away_state,
                "scenario_key": f"home_{home_state}_away_{away_state}",
                "scenario_name": module,
                "scenario_space": space,
                "final_weight": weight,
                "key_drivers": _space_drivers(space)[:3],
                "risk_factors": _space_risks(space),
                "model_constraints": {},
                "coach_vote_summary": {},
            }
            for home_state, away_state, space, module, weight in self.SCENARIO_CASES
        ]
        for template in templates:
            home_state = template["home_state"]
            away_state = template["away_state"]
            scenario_key = template.get("scenario_key") or f"home_{home_state}_away_{away_state}"
            space = template["scenario_space"]
            module = template.get("scenario_name") or template.get("scenario_module") or scenario_key
            weight = int(template.get("final_weight") or template.get("weight") or 0)
            home_factor = _state_factor(home_state)
            away_factor = _state_factor(away_state)
            home_xg = max(0.3, round((home_attack / 50) * home_factor, 2))
            away_xg = max(0.3, round((away_attack / 52) * away_factor, 2))
            probabilities = _wld_probabilities(home_xg, away_xg)
            distribution = _score_distribution(home_xg, away_xg)
            runtime_case_id = _runtime_case_id(prediction_run_id, scenario_key)
            cases.append(
                {
                    "id": runtime_case_id,
                    "prediction_run_id": prediction_run_id,
                    "config_scenario_case_id": template.get("id"),
                    "scenario_key": scenario_key,
                    "scenario_name": module,
                    "home_state": home_state,
                    "away_state": away_state,
                    "scenario_space": space,
                    "scenario_module": module,
                    "weight": weight,
                    "strength_adjustments": {
                        "home_factor": home_factor,
                        "away_factor": away_factor,
                        "home_team": home,
                        "away_team": away,
                    },
                    "expected_goals": {"home": home_xg, "away": away_xg},
                    "win_draw_loss_probability": probabilities,
                    "scoreline_distribution": distribution,
                    "confidence": 62,
                    "evidence": [{"type": "scenario_rule", "description": module}],
                    "metadata": {
                        "source": "scenario_matrix_v2",
                        "scenario_key": scenario_key,
                        "scenario_name": module,
                        "config_scenario_case_id": template.get("id"),
                        "key_drivers": template.get("key_drivers") or _space_drivers(space)[:3],
                        "risk_factors": template.get("risk_factors") or _space_risks(space),
                        "coach_vote_summary": template.get("coach_vote_summary") or {},
                        "model_constraints": template.get("model_constraints") or {},
                        "model_diagnostics": model_diagnostics or {},
                    },
                }
            )
        return cases

    def _scorelines_from_sims(
        self,
        prediction_run_id: str,
        scenario_cases: list[dict[str, Any]],
        sim_results: dict[str, SimulationResult],
        model_diagnostics: dict[str, Any],
    ) -> list[dict[str, Any]]:
        rows = []
        for case in scenario_cases:
            sim_result = sim_results[case["scenario_key"]]
            distribution = _rounded_distribution(sim_result.scoreline_distribution)
            probs = _rounded_probabilities(sim_result.wdl)
            most_likely = distribution[0]["score"] if distribution else sim_result.modal_trajectory.final_score_str
            rows.append(
                {
                    "prediction_run_id": prediction_run_id,
                    "scenario_case_id": case["id"],
                    "scenario_space": case["scenario_space"],
                    "home_xg": int(round(float(case["expected_goals"]["home"]) * 100)),
                    "away_xg": int(round(float(case["expected_goals"]["away"]) * 100)),
                    "home_win_probability": int(round(probs["home_win"] * 100)),
                    "draw_probability": int(round(probs["draw"] * 100)),
                    "away_win_probability": int(round(probs["away_win"] * 100)),
                    "scoreline_distribution": distribution,
                    "most_likely_score": most_likely,
                    "total_goals_distribution": {
                        str(goals): round(float(probability), 4)
                        for goals, probability in (sim_result.total_goals_dist or {}).items()
                    },
                    "confidence": case["confidence"],
                    "model_name": model_diagnostics.get("model_name") or "step3_monte_carlo",
                    "model_version": model_diagnostics.get("model_version") or "v1",
                    "metadata": {
                        "source": "match_simulator_scoreline_v1",
                        "scenario_module": case["scenario_module"],
                        "scenario_key": case["scenario_key"],
                        "config_scenario_case_id": case.get("config_scenario_case_id"),
                        "xg_calibration": (case.get("metadata") or {}).get("xg_calibration"),
                        "sim_seed": sim_result.sim_seed,
                        "n_sims": sim_result.n_sims,
                        "simulation_version": sim_result.sim_version,
                        "modal_final_score": sim_result.modal_trajectory.final_score_str,
                        "knockout_path_distribution": sim_result.knockout_path_distribution,
                    },
                }
            )
        return rows

    def _scorelines(
        self,
        prediction_run_id: str,
        scenario_cases: list[dict[str, Any]],
        *,
        model_diagnostics: dict[str, Any],
    ) -> list[dict[str, Any]]:
        rows = []
        adapter = FootballGoalModelAdapter()
        for case in scenario_cases:
            projection = adapter.scoreline_projection(
                home_xg=float(case["expected_goals"]["home"]),
                away_xg=float(case["expected_goals"]["away"]),
                model_name=model_diagnostics.get("model_name") or "prior_poisson",
                fit_status=model_diagnostics.get("fit_status") or "fallback_prior",
                scenario_key=case["scenario_key"],
            )
            probs = projection["win_draw_loss_probability"]
            distribution = projection["scoreline_distribution"]
            most_likely = projection["most_likely_score"]
            rows.append(
                {
                    "prediction_run_id": prediction_run_id,
                    "scenario_case_id": case["id"],
                    "scenario_space": case["scenario_space"],
                    "home_xg": int(round(projection["home_xg"] * 100)),
                    "away_xg": int(round(projection["away_xg"] * 100)),
                    "home_win_probability": int(round(probs["home_win"] * 100)),
                    "draw_probability": int(round(probs["draw"] * 100)),
                    "away_win_probability": int(round(probs["away_win"] * 100)),
                    "scoreline_distribution": distribution,
                    "most_likely_score": most_likely,
                    "total_goals_distribution": projection["total_goals_distribution"],
                    "confidence": case["confidence"],
                    "model_name": projection["model_name"],
                    "model_version": projection["model_version"],
                    "metadata": {
                        **projection["metadata"],
                        "scenario_module": case["scenario_module"],
                        "scenario_key": case["scenario_key"],
                        "config_scenario_case_id": case.get("config_scenario_case_id"),
                    },
                }
            )
        return rows

    def _scenario_spaces(
        self,
        prediction_run_id: str,
        scenario_cases: list[dict[str, Any]],
        scorelines: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        spaces = []
        for key, name, summary in self.SCENARIO_SPACES:
            linked_cases = [case for case in scenario_cases if case["scenario_space"] == key]
            linked_scorelines = [row for row in scorelines if row["scenario_space"] == key]
            weight = sum(case["weight"] for case in linked_cases)
            scoreline_bias = _weighted_scoreline_summary(linked_cases, linked_scorelines) if linked_scorelines else {
                "most_likely_score": None,
                "top_score_candidates": [],
                "weighted_scoreline_distribution": [],
                "near_tie": False,
                "source": "scenario_weighted_scoreline_v1",
            }
            spaces.append(
                {
                    "prediction_run_id": prediction_run_id,
                    "space_key": key,
                    "space_name": name,
                    "weight": weight,
                    "summary": summary,
                    "scoreline_bias": scoreline_bias,
                    "key_drivers": _space_drivers(key),
                    "risk_factors": _space_risks(key),
                    "linked_scenario_case_ids": [case["id"] for case in linked_cases],
                    "confidence": 60 if key != "volatility" else 52,
                    "metadata": {"source": "scenario_space_aggregation_v1"},
                }
            )
        return spaces

    def _match_events(
        self,
        prediction_run_id: str,
        home: str,
        away: str,
        scenario_cases: list[dict[str, Any]],
        scorelines: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        scoreline_by_case = {row["scenario_case_id"]: row for row in scorelines}
        events: list[dict[str, Any]] = []
        for case in scenario_cases:
            scoreline = scoreline_by_case[case["id"]]
            events.extend(self._match_events_for_case(prediction_run_id, home, away, case, scoreline))
        return events

    def _match_events_for_case(
        self,
        prediction_run_id: str,
        home: str,
        away: str,
        case: dict[str, Any],
        scoreline: dict[str, Any],
    ) -> list[dict[str, Any]]:
        scenario_case_id = case["id"]
        config_scenario_case_id = case.get("config_scenario_case_id")
        space = case["scenario_space"]
        module = case["scenario_module"]
        scenario_key = case["scenario_key"]
        final_score = scoreline["most_likely_score"]
        is_baseline = scenario_key == "home_normal_away_normal"
        volatility_text = "VAR、点球、红黄牌、伤退、天气和裁判尺度作为高波动层降低置信度。"

        base_events = [
            (0, "KICKOFF", None, "比赛进入该场景推演，双方从既定状态开局。", 72, "0-0"),
            (12, "TACTICAL_PHASE", home if case["home_state"] != "underperform" else away, f"{module}下，比赛节奏先由关键对位决定。", 64, "0-0"),
            (24, "CHANCE_CREATED", home if case["home_state"] == "overperform" else away if case["away_state"] == "overperform" else home, "该场景的主要驱动开始转化为禁区前沿机会。", 58, "0-0"),
            (39, "PRESSURE_SHIFT", away if case["away_state"] != "underperform" else home, "压力重心发生变化，比分路径开始贴近该场景假设。", 55, "0-0"),
            (61, "SUBSTITUTION", None, "换人窗口影响体能、对位和后续射门质量。", 54, "0-0"),
            (90, "FINAL_SCORE_HYPOTHESIS", None, f"该九场景下最可能比分为 {final_score}。", 62, final_score),
        ]
        if is_baseline:
            base_events = [
                (0, "KICKOFF", None, "比赛按基准走势开局，双方进入试探阶段。", 72, "0-0"),
                (12, "TACTICAL_PHASE", home, f"{home}尝试通过控球和压迫建立节奏。", 64, "0-0"),
                (24, "CHANCE_CREATED", home, f"{home}在边路或定位球环节制造第一波高质量机会。", 58, "0-0"),
                (31, "SHOT", home, f"{home}完成一次关键射门，考验{away}门将。", 56, "0-0"),
                (39, "PRESSURE_SHIFT", away, f"{away}通过反击把比赛压力推回主队半场。", 55, "0-0"),
                (52, "FOUL", home, f"{home}在转换防守中出现犯规风险。", 50, "0-0"),
                (61, "SUBSTITUTION", None, "双方可能开始通过常规换人调整体能和对位。", 54, "0-0"),
                (73, "VAR_CHECK", None, volatility_text, 44, "0-0"),
                (90, "FINAL_SCORE_HYPOTHESIS", None, f"综合场景权重后，最可能比分为 {final_score}。", 62, final_score),
            ]
        elif space == "volatility":
            base_events.insert(4, (73, "VAR_CHECK", None, volatility_text, 43, "0-0"))

        return [
            _event(
                prediction_run_id,
                minute,
                event_type,
                space,
                module,
                team,
                None,
                description,
                confidence,
                score,
                scenario_case_id=scenario_case_id,
                config_scenario_case_id=config_scenario_case_id,
                scenario_key=scenario_key,
            )
            for minute, event_type, team, description, confidence, score in base_events
        ]

    def _analyst_notes(
        self,
        prediction_run_id: str,
        home: str,
        away: str,
        scenario_cases: list[dict[str, Any]],
        match_events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        notes = []
        jury = CoachJuryService()
        for case in scenario_cases:
            review = jury.step3_review_summary(scenario_case_id=case["id"], scenario_key=case["scenario_key"])
            notes.append(
                _note(
                    prediction_run_id,
                    "coach_review",
                    case["scenario_space"],
                    f"{case['scenario_module']}的事件链复核共识度为 {review['consensus_score']:.2f}。",
                    "教练评审只调整置信度，不覆盖科学模型比分概率。",
                    int(review["consensus_score"] * 100),
                    scenario_case_id=case["id"],
                    metadata={
                        "scenario_key": case["scenario_key"],
                        "coach_review_summary": review,
                        "config_scenario_case_id": case.get("config_scenario_case_id"),
                    },
                )
            )
        notes.extend(
            [
                _note(prediction_run_id, "data", "baseline", f"基准模型认为{home}与{away}的胜平负差距有限。", "依据球队强度、xG 和场景权重综合判断。", 64),
                _note(prediction_run_id, "risk", "volatility", "高波动事件会显著改变单场预测置信度。", "点球、VAR、红牌、伤退和裁判尺度不能绑定到单一常规状态。", 52),
            ]
            )
        return notes

    def _match_events_from_modal_trajectories(
        self,
        prediction_run_id: str,
        home: str,
        away: str,
        scenario_cases: list[dict[str, Any]],
        sim_results: dict[str, SimulationResult],
        squads: tuple[TeamRoster, TeamRoster],
        budget: LLMBudgetProfile,
        ledger: LLMCallLedger,
        content_language_instruction: str,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        polisher = EventNarrativePolisher(
            budget=budget,
            ledger=ledger,
            squads=squads,
            content_language_instruction=content_language_instruction,
        )
        for case in scenario_cases:
            sim_result = sim_results[case["scenario_key"]]
            events.extend(
                self._trajectory_to_events(
                    prediction_run_id,
                    home,
                    away,
                    case,
                    sim_result.modal_trajectory,
                    sim_result,
                    polisher,
                )
            )
        return events

    def _trajectory_to_events(
        self,
        prediction_run_id: str,
        home: str,
        away: str,
        case: dict[str, Any],
        trajectory: Trajectory,
        sim_result: SimulationResult,
        polisher: EventNarrativePolisher,
    ) -> list[dict[str, Any]]:
        scenario_key = case["scenario_key"]
        scenario_case_id = case["id"]
        config_scenario_case_id = case.get("config_scenario_case_id")
        metadata = {
            "source": "match_simulator_modal_trajectory_v1",
            "scenario_key": scenario_key,
            "config_scenario_case_id": config_scenario_case_id,
            "sim_seed": sim_result.sim_seed,
            "n_sims": sim_result.n_sims,
            "simulation_version": sim_result.sim_version,
            "modal_final_score": trajectory.final_score_str,
            "knockout_path": trajectory.knockout_path,
            "knockout_winner": trajectory.knockout_winner,
        }
        rows = [
            _event(
                prediction_run_id,
                0,
                "KICKOFF",
                case["scenario_space"],
                case["scenario_module"],
                None,
                None,
                f"{case['scenario_module']}按 Step2 定稿状态开局。",
                72,
                "0-0",
                scenario_case_id=scenario_case_id,
                config_scenario_case_id=config_scenario_case_id,
                scenario_key=scenario_key,
                sim_seed=sim_result.sim_seed,
                metadata=metadata,
            )
        ]

        polished_events = polisher.polish(list(trajectory.events), scenario_key)
        for polished in polished_events:
            event_type = _public_event_type(str(polished.get("type") or "TACTICAL_PHASE"))
            side = str(polished.get("side") or "")
            team = home if side == "home" else away if side == "away" else None
            score = _score_text(polished.get("score_after"))
            rows.append(
                _event(
                    prediction_run_id,
                    int(polished.get("minute") or 0),
                    event_type,
                    case["scenario_space"],
                    case["scenario_module"],
                    team,
                    polished.get("actor_name"),
                    str(polished.get("description") or ""),
                    _event_confidence(event_type),
                    score,
                    scenario_case_id=scenario_case_id,
                    config_scenario_case_id=config_scenario_case_id,
                    scenario_key=scenario_key,
                    actor_player_id=polished.get("actor_player_id"),
                    assist_player_id=polished.get("assist_player_id"),
                    sim_seed=sim_result.sim_seed,
                    metadata={
                        **metadata,
                        "narrative_source": polished.get("narrative_source"),
                        "narrative_version": polished.get("narrative_version"),
                        "raw_event_type": polished.get("type"),
                        "assist_name": polished.get("assist_name"),
                        "card_color": polished.get("card_color"),
                        "pso_scored": polished.get("pso_scored"),
                    },
                )
            )

        rows.extend(
            self._supplemental_modal_events(
                prediction_run_id,
                home,
                away,
                case,
                trajectory,
                sim_result,
                metadata,
                existing_minutes={int(row["minute"]) for row in rows},
            )
        )
        final_minute = max(90, min(121, max((int(row["minute"]) for row in rows), default=90)))
        rows.append(
            _event(
                prediction_run_id,
                final_minute,
                "FINAL_SCORE_HYPOTHESIS",
                case["scenario_space"],
                case["scenario_module"],
                None,
                None,
                f"该场景的 Monte Carlo 模态轨迹收束到 {trajectory.final_score_str}。",
                68,
                trajectory.final_score_str,
                scenario_case_id=scenario_case_id,
                config_scenario_case_id=config_scenario_case_id,
                scenario_key=scenario_key,
                sim_seed=sim_result.sim_seed,
                metadata=metadata,
            )
        )
        return sorted(rows, key=lambda row: (int(row["minute"]), row["event_type"], row.get("team") or ""))

    def _supplemental_modal_events(
        self,
        prediction_run_id: str,
        home: str,
        away: str,
        case: dict[str, Any],
        trajectory: Trajectory,
        sim_result: SimulationResult,
        metadata: dict[str, Any],
        *,
        existing_minutes: set[int],
    ) -> list[dict[str, Any]]:
        del trajectory
        scenario_case_id = case["id"]
        config_scenario_case_id = case.get("config_scenario_case_id")
        candidates = [
            (14, "TACTICAL_PHASE", home, f"{home}按 {case['home_state']} 状态测试控球和压迫节奏。", 60, "0-0"),
            (28, "CHANCE_CREATED", home if case["home_state"] != "underperform" else away, "场景核心驱动转化为第一波禁区前沿机会。", 58, "0-0"),
            (52, "PRESSURE_SHIFT", away if case["away_state"] != "underperform" else home, "中段压力重新分配，比分路径开始贴近模拟分布。", 56, None),
            (66, "SUBSTITUTION", None, "换人窗口改变体能、对位和后续射门质量。", 54, None),
            (78, "TACTICAL_PHASE", away, f"{away}根据比分和体能进入末段风险控制。", 55, None),
        ]
        needed = max(0, 5 - len(existing_minutes))
        rows = []
        for minute, event_type, team, description, confidence, score in candidates:
            if needed <= 0:
                break
            if minute in existing_minutes:
                continue
            rows.append(
                _event(
                    prediction_run_id,
                    minute,
                    event_type,
                    case["scenario_space"],
                    case["scenario_module"],
                    team,
                    None,
                    description,
                    confidence,
                    score,
                    scenario_case_id=scenario_case_id,
                    config_scenario_case_id=config_scenario_case_id,
                    scenario_key=case["scenario_key"],
                    sim_seed=sim_result.sim_seed,
                    metadata={**metadata, "supplemental": True},
                )
            )
            needed -= 1
        return rows

    def _step3_analyst_notes(
        self,
        prediction_run_id: str,
        home: str,
        away: str,
        scenario_cases: list[dict[str, Any]],
        sim_results: dict[str, SimulationResult],
        scorelines: list[dict[str, Any]],
        config: dict[str, Any],
        budget: LLMBudgetProfile,
        ledger: LLMCallLedger,
        coach_review: dict[str, Any],
        content_language_instruction: str,
    ) -> list[dict[str, Any]]:
        notes: list[dict[str, Any]] = []
        for note in AnalystNotesWriter(
            budget=budget,
            ledger=ledger,
            content_language_instruction=content_language_instruction,
        ).write_notes(
            scenario_cases=scenario_cases,
            sim_results=sim_results,
            scorelines=scorelines,
            config=config,
        ):
            notes.append(
                _note(
                    prediction_run_id,
                    str(note.get("role") or "event_simulation"),
                    str(note.get("scenario_space") or "baseline"),
                    str(note.get("claim") or "Step3 模拟结果已生成。"),
                    str(note.get("reasoning") or "基于 Monte Carlo 模态轨迹与比分分布生成。"),
                    int(note.get("confidence") or 60),
                    metadata={
                        "source": note.get("source") or "analyst_notes_writer",
                        "evidence_refs": note.get("evidence_refs") or [],
                        "note_version": note.get("note_version"),
                    },
                )
            )

        for case in scenario_cases:
            sim_result = sim_results[case["scenario_key"]]
            notes.append(
                _note(
                    prediction_run_id,
                    "coach_review",
                    case["scenario_space"],
                    f"{case['scenario_module']}的事后复核结论为 {coach_review['summary']}。",
                    f"模态比分 {sim_result.modal_trajectory.final_score_str}，教练复核只标记风险，不覆盖比分概率。",
                    _coach_review_confidence(coach_review),
                    scenario_case_id=case["id"],
                    metadata={
                        "scenario_key": case["scenario_key"],
                        "config_scenario_case_id": case.get("config_scenario_case_id"),
                        "coach_review_summary": coach_review,
                        "modal_final_score": sim_result.modal_trajectory.final_score_str,
                    },
                )
            )

        if not any(note["agent_role"] == "data" for note in notes):
            baseline = next(
                (
                    row
                    for row in scorelines
                    if (row.get("metadata") or {}).get("scenario_key") == "home_normal_away_normal"
                ),
                scorelines[0],
            )
            notes.append(
                _note(
                    prediction_run_id,
                    "data",
                    "baseline",
                    f"基准模型认为{home}与{away}的比分中心在 {baseline['most_likely_score']} 附近。",
                    "依据 Step3 Monte Carlo scoreline_distribution 与 WDL 聚合生成。",
                    64,
                    metadata={"scenario_key": (baseline.get("metadata") or {}).get("scenario_key")},
                )
            )
        if not any(note["agent_role"] == "risk" for note in notes):
            notes.append(
                _note(
                    prediction_run_id,
                    "risk",
                    "volatility",
                    "高波动事件会显著改变单场预测置信度。",
                    "点球、VAR、红牌、伤退和裁判尺度不能绑定到单一常规状态。",
                    52,
                )
            )
        return notes

    def _prediction_result(
        self,
        prediction_run_id: str,
        team_strengths: list[dict[str, Any]],
        scenario_cases: list[dict[str, Any]],
        scenario_spaces: list[dict[str, Any]],
        scorelines: list[dict[str, Any]],
        match_events: list[dict[str, Any]],
        analyst_notes: list[dict[str, Any]],
        competition: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        baseline_scoreline = (
            next((row for row in scorelines if (row.get("metadata") or {}).get("scenario_key") == "home_normal_away_normal"), None)
            or next((row for row in scorelines if row["scenario_space"] == "baseline"), None)
            or (scorelines[0] if scorelines else {})
        )
        final_event = (
            next(
                (
                    event
                    for event in match_events
                    if event["event_type"] == "FINAL_SCORE_HYPOTHESIS"
                    and (event.get("metadata") or {}).get("scenario_key") == "home_normal_away_normal"
                ),
                None,
            )
            or next((event for event in match_events if event["event_type"] == "FINAL_SCORE_HYPOTHESIS"), None)
            or {}
        )
        scoreline_summary = _weighted_scoreline_summary(
            scenario_cases,
            scorelines,
            competition=competition,
            team_strengths=team_strengths,
        )
        most_likely_score = scoreline_summary.get("most_likely_score")
        if final_event and most_likely_score:
            final_event = {
                **final_event,
                "score": most_likely_score,
                "description": f"综合场景权重后，最可能比分为 {most_likely_score}。",
                "metadata": {
                    **(final_event.get("metadata") or {}),
                    "scoreline_summary_source": scoreline_summary.get("source"),
                },
            }
        return {
            "prediction_run_id": prediction_run_id,
            "baseline_prediction": baseline_scoreline,
            "scenario_cases_summary": {
                "count": len(scenario_cases),
                "matrix": [
                    {
                        "id": case["id"],
                        "scenario_key": case["scenario_key"],
                        "scenario_name": case["scenario_name"],
                        "home_state": case["home_state"],
                        "away_state": case["away_state"],
                        "scenario_space": case["scenario_space"],
                        "weight": case["weight"],
                    }
                    for case in scenario_cases
                ],
            },
            "scenario_spaces_summary": scenario_spaces,
            "scoreline_summary": scoreline_summary,
            "match_events_summary": {
                "count": len(match_events),
                "final": final_event,
                "scenario_case_ids": sorted({event.get("scenario_case_id") for event in match_events if event.get("scenario_case_id")}),
            },
            "analyst_notes_summary": {"count": len(analyst_notes)},
            "final_score_hypothesis": final_event,
            "uncertainty_factors": _space_risks("volatility"),
            "confidence": min(item["confidence"] for item in team_strengths) if team_strengths else 52,
            "metadata": {"source": "football_prediction_engine_v1"},
        }


class PredictionPersistenceService:
    """Persist and retrieve football prediction artifacts."""

    def create_completed_prediction(
        self,
        *,
        project_id: str,
        graph_id: str | None = None,
        simulation_requirement: str = "",
        home_team: str | None = None,
        away_team: str | None = None,
        competition: str | None = None,
        graph_entities: list[dict[str, Any]] | None = None,
        prediction_config_id: str | None = None,
    ) -> dict[str, Any]:
        _ensure_project_record_for_prediction(project_id, graph_id, simulation_requirement)
        prediction_run_id = f"run_{hashlib.sha1(f'{project_id}:{utc_now().isoformat()}'.encode()).hexdigest()[:12]}"
        result = FootballPredictionEngine().run(
            prediction_run_id=prediction_run_id,
            project_id=project_id,
            graph_id=graph_id,
            simulation_requirement=simulation_requirement,
            graph_entities=graph_entities or [],
            home_team=home_team,
            away_team=away_team,
            prediction_config_id=prediction_config_id,
        )
        self.save_prediction(
            prediction_run_id=prediction_run_id,
            prediction_config_id=prediction_config_id,
            project_id=project_id,
            graph_id=graph_id,
            simulation_requirement=simulation_requirement,
            competition=competition,
            result=result,
        )
        return self.get_status(prediction_run_id)

    def create_completed_prediction_from_config(
        self,
        *,
        prediction_config_id: str,
        force_rerun: bool = False,
        rerun_from_event_type: str | None = None,
    ) -> dict[str, Any]:
        with get_session() as session:
            config = session.get(PredictionConfigRecord, prediction_config_id)
            if not config:
                raise KeyError(f"prediction config not found: {prediction_config_id}")
            ProjectWorkflowService().require_active_config(config.project_id, prediction_config_id)
            workflow_state = ProjectWorkflowService().get_state(config.project_id)
            config_cases = (
                session.query(PredictionConfigScenarioCaseRecord)
                .filter_by(prediction_config_id=prediction_config_id)
                .order_by(PredictionConfigScenarioCaseRecord.created_at.asc())
                .all()
            )
            team_strengths = (
                session.query(PredictionTeamStrengthRecord)
                .filter_by(prediction_config_id=prediction_config_id, prediction_run_id=None)
                .order_by(PredictionTeamStrengthRecord.team_role.asc())
                .all()
            )
            config_payload = _config_record_to_engine_dict(config)
            scenario_payload = [_config_case_record_to_engine_dict(row) for row in config_cases]
            strength_payload = [_team_strength_to_engine_dict(row) for row in team_strengths]

        prediction_run_id = f"run_{hashlib.sha1(f'{prediction_config_id}:{utc_now().isoformat()}'.encode()).hexdigest()[:12]}"
        result = FootballPredictionEngine().run(
            prediction_run_id=prediction_run_id,
            prediction_config_id=prediction_config_id,
            project_id=config_payload["project_id"],
            graph_id=config_payload["graph_id"],
            simulation_requirement=config_payload["prediction_requirement"],
            graph_entities=[],
            home_team=config_payload["home_team"],
            away_team=config_payload["away_team"],
            config_scenario_cases=scenario_payload,
            prepared_team_strengths=strength_payload,
            model_diagnostics=config_payload["model_diagnostics"],
            model_input_snapshot=config_payload["model_input_snapshot"],
            llm_budget_profile=config_payload["llm_budget_profile"],
        )
        self.save_prediction(
            prediction_run_id=prediction_run_id,
            prediction_config_id=prediction_config_id,
            project_id=config_payload["project_id"],
            graph_id=config_payload["graph_id"],
            simulation_requirement=config_payload["prediction_requirement"],
            competition=config_payload["competition"],
            result=result,
            run_metadata={
                "prediction_config_id": prediction_config_id,
                "force_rerun": bool(force_rerun),
                "rerun_from_event_type": rerun_from_event_type,
                "model_fit_status": config_payload["model_diagnostics"].get("fit_status"),
                "player_dataset_id": config_payload.get("player_dataset_id"),
                "workflow_revision": workflow_state.get("workflow_revision"),
            },
        )
        return self.get_status(prediction_run_id)

    def create_pending_prediction_from_config(
        self,
        *,
        prediction_config_id: str,
        force_rerun: bool = False,
        rerun_from_event_type: str | None = None,
    ) -> dict[str, Any]:
        prediction_run_id = f"run_{hashlib.sha1(f'{prediction_config_id}:{utc_now().isoformat()}'.encode()).hexdigest()[:12]}"
        with get_session() as session:
            config = session.get(PredictionConfigRecord, prediction_config_id)
            if not config:
                raise KeyError(f"prediction config not found: {prediction_config_id}")
            ProjectWorkflowService().require_active_config(config.project_id, prediction_config_id)
            workflow_state = ProjectWorkflowService().get_state(config.project_id)
            project_id = config.project_id

            run = PredictionRunRecord(
                prediction_run_id=prediction_run_id,
                prediction_config_id=prediction_config_id,
                project_id=config.project_id,
                graph_id=config.graph_id,
                match_name=config.match_name,
                home_team=config.home_team,
                away_team=config.away_team,
                competition=config.competition,
                kickoff_time=config.kickoff_time,
                status="queued",
                current_phase="queued",
                progress_percent=1,
                run_metadata={
                    "prediction_config_id": prediction_config_id,
                    "force_rerun": bool(force_rerun),
                    "rerun_from_event_type": rerun_from_event_type,
                    "async": True,
                    "source": "prediction_async_celery_v1",
                    "artifact_status": "pending",
                    "workflow_revision": workflow_state.get("workflow_revision"),
                    "progress_messages": [
                        {
                            "phase": "queued",
                            "message": "比赛推演已进入队列",
                            "progress_percent": 1,
                            "created_at": utc_now().isoformat(),
                        }
                    ],
                },
            )
            session.add(run)
        ProjectWorkflowService().register_run(project_id, prediction_run_id)
        return self.get_status(prediction_run_id)

    def run_pending_prediction_from_config(
        self,
        *,
        prediction_run_id: str,
        prediction_config_id: str,
        force_rerun: bool = False,
        rerun_from_event_type: str | None = None,
    ) -> dict[str, Any]:
        self.update_run_progress(prediction_run_id, phase="loading_config", progress_percent=8, status="running", message="读取预测配置")
        with get_session() as session:
            config = session.get(PredictionConfigRecord, prediction_config_id)
            if not config:
                raise KeyError(f"prediction config not found: {prediction_config_id}")
            ProjectWorkflowService().require_active_config(config.project_id, prediction_config_id)
            workflow_state = ProjectWorkflowService().get_state(config.project_id)
            config_cases = (
                session.query(PredictionConfigScenarioCaseRecord)
                .filter_by(prediction_config_id=prediction_config_id)
                .order_by(PredictionConfigScenarioCaseRecord.created_at.asc())
                .all()
            )
            team_strengths = (
                session.query(PredictionTeamStrengthRecord)
                .filter_by(prediction_config_id=prediction_config_id, prediction_run_id=None)
                .order_by(PredictionTeamStrengthRecord.team_role.asc())
                .all()
            )
            config_payload = _config_record_to_engine_dict(config)
            scenario_payload = [_config_case_record_to_engine_dict(row) for row in config_cases]
            strength_payload = [_team_strength_to_engine_dict(row) for row in team_strengths]

        self.update_run_progress(prediction_run_id, phase="running_simulation", progress_percent=28, status="running", message="执行九场景比赛模拟")
        result = FootballPredictionEngine().run(
            prediction_run_id=prediction_run_id,
            prediction_config_id=prediction_config_id,
            project_id=config_payload["project_id"],
            graph_id=config_payload["graph_id"],
            simulation_requirement=config_payload["prediction_requirement"],
            graph_entities=[],
            home_team=config_payload["home_team"],
            away_team=config_payload["away_team"],
            config_scenario_cases=scenario_payload,
            prepared_team_strengths=strength_payload,
            model_diagnostics=config_payload["model_diagnostics"],
            model_input_snapshot=config_payload["model_input_snapshot"],
            llm_budget_profile=config_payload["llm_budget_profile"],
        )
        self.update_run_progress(prediction_run_id, phase="persisting_artifacts", progress_percent=88, status="running", message="保存比分、事件链和复核结果")
        self.save_prediction(
            prediction_run_id=prediction_run_id,
            prediction_config_id=prediction_config_id,
            project_id=config_payload["project_id"],
            graph_id=config_payload["graph_id"],
            simulation_requirement=config_payload["prediction_requirement"],
            competition=config_payload["competition"],
            result=result,
            run_metadata={
                "prediction_config_id": prediction_config_id,
                "force_rerun": bool(force_rerun),
                "rerun_from_event_type": rerun_from_event_type,
                "model_fit_status": config_payload["model_diagnostics"].get("fit_status"),
                "player_dataset_id": config_payload.get("player_dataset_id"),
                "async": True,
                "source": "prediction_async_celery_v1",
                "workflow_revision": workflow_state.get("workflow_revision"),
            },
        )
        return self.get_status(prediction_run_id)

    def mark_prediction_failed(self, prediction_run_id: str, error: str) -> None:
        self.update_run_progress(
            prediction_run_id,
            phase="failed",
            progress_percent=0,
            status="failed",
            message=f"比赛推演失败: {error}",
            error=error,
        )

    def sync_async_failure_from_celery_job(self, prediction_run_id: str, celery_job: dict[str, Any]) -> dict[str, Any]:
        error = (
            celery_job.get("last_error")
            or ((celery_job.get("metadata") or {}).get("error"))
            or "Celery 后台任务失败"
        )
        with get_session() as session:
            run = session.get(PredictionRunRecord, prediction_run_id)
            if not run:
                raise KeyError(f"prediction run not found: {prediction_run_id}")
            if run.status not in {"failed", "completed"}:
                run.status = "failed"
                run.current_phase = "failed"
                run.error = str(error)
                metadata = dict(run.run_metadata or {})
                messages = list(metadata.get("progress_messages") or [])
                messages.append(
                    {
                        "phase": "failed",
                        "message": f"比赛推演失败: {error}",
                        "progress_percent": run.progress_percent,
                        "created_at": utc_now().isoformat(),
                    }
                )
                metadata["progress_messages"] = messages[-25:]
                run.run_metadata = metadata
        return self.get_status(prediction_run_id)

    def update_run_progress(
        self,
        prediction_run_id: str,
        *,
        phase: str,
        progress_percent: int,
        status: str | None = None,
        message: str | None = None,
        error: str | None = None,
    ) -> None:
        with get_session() as session:
            run = session.get(PredictionRunRecord, prediction_run_id)
            if not run:
                raise KeyError(f"prediction run not found: {prediction_run_id}")
            if status:
                run.status = status
            run.current_phase = phase
            run.progress_percent = max(0, min(100, int(progress_percent)))
            if error is not None:
                run.error = error
            metadata = dict(run.run_metadata or {})
            messages = list(metadata.get("progress_messages") or [])
            if message:
                messages.append(
                    {
                        "phase": phase,
                        "message": message,
                        "progress_percent": run.progress_percent,
                        "created_at": utc_now().isoformat(),
                    }
                )
                metadata["progress_messages"] = messages[-25:]
            run.run_metadata = metadata

    def replay_prediction(self, prediction_run_id: str) -> dict[str, Any]:
        with get_session() as session:
            orig_run = session.get(PredictionRunRecord, prediction_run_id)
            if not orig_run:
                raise KeyError(f"prediction run not found: {prediction_run_id}")

            seed = orig_run.simulation_seed or (orig_run.run_metadata or {}).get("simulation_seed")
            if seed is None:
                raise ValueError(f"prediction run has no simulation_seed: {prediction_run_id}")

            config_payload: dict[str, Any] | None = None
            scenario_payload: list[dict[str, Any]]
            strength_payload: list[dict[str, Any]]
            if orig_run.prediction_config_id:
                config = session.get(PredictionConfigRecord, orig_run.prediction_config_id)
                if not config:
                    raise KeyError(f"prediction config not found: {orig_run.prediction_config_id}")
                config_cases = (
                    session.query(PredictionConfigScenarioCaseRecord)
                    .filter_by(prediction_config_id=orig_run.prediction_config_id)
                    .order_by(PredictionConfigScenarioCaseRecord.created_at.asc())
                    .all()
                )
                config_strengths = (
                    session.query(PredictionTeamStrengthRecord)
                    .filter_by(prediction_config_id=orig_run.prediction_config_id, prediction_run_id=None)
                    .order_by(PredictionTeamStrengthRecord.team_role.asc())
                    .all()
                )
                config_payload = _config_record_to_engine_dict(config)
                scenario_payload = [_config_case_record_to_engine_dict(row) for row in config_cases]
                strength_payload = [_team_strength_to_engine_dict(row) for row in config_strengths]
            else:
                scenario_rows = (
                    session.query(PredictionScenarioCaseRecord)
                    .filter_by(prediction_run_id=prediction_run_id)
                    .order_by(PredictionScenarioCaseRecord.created_at.asc())
                    .all()
                )
                strength_rows = (
                    session.query(PredictionTeamStrengthRecord)
                    .filter_by(prediction_run_id=prediction_run_id)
                    .order_by(PredictionTeamStrengthRecord.team_role.asc())
                    .all()
                )
                scenario_payload = [_scenario_case_to_config_payload(row) for row in scenario_rows]
                strength_payload = [_team_strength_to_engine_dict(row) for row in strength_rows]

            orig_snapshot = self._replay_snapshot(session, prediction_run_id)
            run_metadata = orig_run.run_metadata or {}
            project_id = orig_run.project_id
            graph_id = orig_run.graph_id
            simulation_requirement = run_metadata.get("simulation_requirement") or ""
            home_team = orig_run.home_team
            away_team = orig_run.away_team
            competition = orig_run.competition

        replayed_run_id = _replay_run_id(prediction_run_id)
        if config_payload is None:
            model_input_snapshot: dict[str, Any] = {}
            model_diagnostics = {
                "model_name": "prior_poisson",
                "model_version": "v1",
                "fit_status": "fallback_prior",
                "data_sufficiency": "partial",
            }
            llm_budget_profile = None
            player_dataset_id = run_metadata.get("player_dataset_id")
        else:
            model_input_snapshot = config_payload["model_input_snapshot"]
            model_diagnostics = config_payload["model_diagnostics"]
            llm_budget_profile = config_payload["llm_budget_profile"]
            player_dataset_id = config_payload.get("player_dataset_id")
            project_id = config_payload["project_id"]
            graph_id = config_payload["graph_id"]
            simulation_requirement = config_payload["prediction_requirement"]
            home_team = config_payload["home_team"]
            away_team = config_payload["away_team"]
            competition = config_payload["competition"]

        result = FootballPredictionEngine().run(
            prediction_run_id=replayed_run_id,
            prediction_config_id=(config_payload or {}).get("prediction_config_id"),
            project_id=project_id,
            graph_id=graph_id,
            simulation_requirement=simulation_requirement,
            graph_entities=[],
            home_team=home_team,
            away_team=away_team,
            config_scenario_cases=scenario_payload,
            prepared_team_strengths=strength_payload,
            model_diagnostics=model_diagnostics,
            model_input_snapshot=model_input_snapshot,
            llm_budget_profile=llm_budget_profile,
            _override_seed=int(seed),
        )
        self.save_prediction(
            prediction_run_id=replayed_run_id,
            prediction_config_id=(config_payload or {}).get("prediction_config_id"),
            project_id=project_id,
            graph_id=graph_id,
            simulation_requirement=simulation_requirement,
            competition=competition,
            result=result,
            run_metadata={
                "replay_of": prediction_run_id,
                "player_dataset_id": player_dataset_id,
            },
        )
        drift = _replay_drift(orig_snapshot, _result_replay_snapshot(result), run_metadata, result)
        return {
            "replayed_run_id": replayed_run_id,
            "original_run_id": prediction_run_id,
            "drift": drift,
        }

    def save_prediction(
        self,
        *,
        prediction_run_id: str,
        prediction_config_id: str | None = None,
        project_id: str,
        graph_id: str | None,
        simulation_requirement: str,
        competition: str | None,
        result: dict[str, Any],
        run_metadata: dict[str, Any] | None = None,
    ) -> None:
        workflow_state: dict[str, Any] | None = None
        active_run = True
        if prediction_config_id:
            try:
                ProjectWorkflowService().require_active_config(project_id, prediction_config_id)
                workflow_state = ProjectWorkflowService().get_state(project_id)
            except ValueError:
                active_run = False
                try:
                    workflow_state = ProjectWorkflowService().get_state(project_id)
                except Exception:
                    workflow_state = None
        with get_session() as session:
            run = PredictionRunRecord(
                prediction_run_id=prediction_run_id,
                prediction_config_id=prediction_config_id,
                project_id=project_id,
                graph_id=graph_id,
                match_name=f"{result['home_team']} vs {result['away_team']}",
                home_team=result["home_team"],
                away_team=result["away_team"],
                competition=competition,
                status="completed",
                current_phase="completed",
                progress_percent=100,
                simulation_seed=result.get("simulation_seed"),
                n_sims=result.get("n_sims"),
                completed_at=utc_now(),
                run_metadata={
                    "simulation_requirement": simulation_requirement,
                    "simulation_seed": result.get("simulation_seed"),
                    "n_sims": result.get("n_sims"),
                    "simulation_version": result.get("simulation_version"),
                    "model_version": ((result.get("prediction_result") or {}).get("baseline_prediction") or {}).get("model_version"),
                    "ledger_summary": result.get("ledger_summary"),
                    "knockout_path_distribution": result.get("knockout_path_distribution"),
                    **(run_metadata or {}),
                    "artifact_status": "active" if active_run else "superseded",
                    "workflow_revision": (workflow_state or {}).get("workflow_revision") or (run_metadata or {}).get("workflow_revision"),
                },
            )
            session.merge(run)
            session.flush()

            for row in result["team_strengths"]:
                session.add(
                    PredictionTeamStrengthRecord(
                        prediction_config_id=prediction_config_id,
                        prediction_run_id=prediction_run_id,
                        **_without(row, "prediction_config_id", "prediction_run_id", "metadata"),
                        strength_metadata=row.get("metadata") or {},
                    )
                )
            for row in result["scenario_cases"]:
                session.add(
                    PredictionScenarioCaseRecord(
                        prediction_run_id=prediction_run_id,
                        **_without(row, "prediction_run_id", "metadata", "scenario_key", "scenario_name"),
                        case_metadata=row.get("metadata") or {},
                    )
                )
            session.flush()
            for row in result["scenario_spaces"]:
                session.add(PredictionScenarioSpaceRecord(prediction_run_id=prediction_run_id, **_without(row, "prediction_run_id", "metadata"), space_metadata=row.get("metadata") or {}))
            for row in result["scorelines"]:
                session.add(PredictionScorelineRecord(prediction_run_id=prediction_run_id, **_without(row, "prediction_run_id", "metadata"), scoreline_metadata=row.get("metadata") or {}))
            for row in result["match_events"]:
                session.add(PredictionMatchEventRecord(prediction_run_id=prediction_run_id, **_without(row, "prediction_run_id", "metadata"), event_metadata=row.get("metadata") or {}))
            for row in result["analyst_notes"]:
                session.add(PredictionAnalystNoteRecord(prediction_run_id=prediction_run_id, **_without(row, "prediction_run_id", "metadata"), note_metadata=row.get("metadata") or {}))

            summary = result["prediction_result"]
            session.add(
                PredictionResultRecord(
                    prediction_run_id=prediction_run_id,
                    baseline_prediction=summary.get("baseline_prediction"),
                    scenario_cases_summary=summary.get("scenario_cases_summary"),
                    scenario_spaces_summary=summary.get("scenario_spaces_summary"),
                    scoreline_summary=summary.get("scoreline_summary"),
                    match_events_summary=summary.get("match_events_summary"),
                    analyst_notes_summary=summary.get("analyst_notes_summary"),
                    final_score_hypothesis=summary.get("final_score_hypothesis"),
                    uncertainty_factors=summary.get("uncertainty_factors"),
                    confidence=summary.get("confidence", 60),
                    result_metadata=summary.get("metadata") or {},
                )
            )
        if active_run:
            try:
                ProjectWorkflowService().register_run(project_id, prediction_run_id)
            except KeyError:
                pass

    def get_status(self, prediction_run_id: str) -> dict[str, Any]:
        with get_session() as session:
            run = session.get(PredictionRunRecord, prediction_run_id)
            if not run:
                raise KeyError(f"prediction run not found: {prediction_run_id}")
            counts = self._counts(session, prediction_run_id)
            return {
                "prediction_run_id": run.prediction_run_id,
                "prediction_config_id": run.prediction_config_id,
                "project_id": run.project_id,
                "graph_id": run.graph_id,
                "match_name": run.match_name,
                "home_team": run.home_team,
                "away_team": run.away_team,
                "status": run.status,
                "current_phase": run.current_phase,
                "progress_percent": run.progress_percent,
                "simulation_seed": run.simulation_seed,
                "n_sims": run.n_sims,
                "can_resume": run.status in {"failed", "interrupted"},
                "resume_from_event_type": run.current_phase if run.status in {"failed", "interrupted"} else None,
                "last_successful_event": {"event_type": "prepare_prediction_qa", "status": "succeeded"} if run.status == "completed" else None,
                "current_event": {"event_type": run.current_phase, "status": run.status, "progress": run.progress_percent},
                "counts": counts,
                "error": run.error,
                "metadata": run.run_metadata or {},
            }

    def list_scenario_cases(self, prediction_run_id: str) -> list[dict[str, Any]]:
        with get_session() as session:
            rows = session.query(PredictionScenarioCaseRecord).filter_by(prediction_run_id=prediction_run_id).order_by(PredictionScenarioCaseRecord.created_at.asc()).all()
            events = (
                session.query(PredictionMatchEventRecord)
                .filter_by(prediction_run_id=prediction_run_id)
                .order_by(PredictionMatchEventRecord.minute.asc(), PredictionMatchEventRecord.created_at.asc())
                .all()
            )
            scorelines = session.query(PredictionScorelineRecord).filter_by(prediction_run_id=prediction_run_id).all()
            events_by_case: dict[str, list[PredictionMatchEventRecord]] = {}
            for event in events:
                if event.scenario_case_id:
                    events_by_case.setdefault(event.scenario_case_id, []).append(event)
            scoreline_by_case = {row.scenario_case_id: row for row in scorelines if row.scenario_case_id}
            return localize_scenario_case_rows([
                _scenario_case_to_dict(
                    row,
                    events=events_by_case.get(row.id) or [],
                    scoreline=scoreline_by_case.get(row.id),
                )
                for row in rows
            ])

    def list_team_strengths(self, prediction_run_id: str) -> list[dict[str, Any]]:
        with get_session() as session:
            rows = session.query(PredictionTeamStrengthRecord).filter_by(prediction_run_id=prediction_run_id).order_by(PredictionTeamStrengthRecord.team_role.asc()).all()
            return localize_team_strength_rows([_team_strength_to_dict(row) for row in rows])

    def list_scorelines(self, prediction_run_id: str) -> list[dict[str, Any]]:
        with get_session() as session:
            rows = session.query(PredictionScorelineRecord).filter_by(prediction_run_id=prediction_run_id).order_by(PredictionScorelineRecord.created_at.asc()).all()
            return [_scoreline_to_dict(row) for row in rows]

    def list_scenario_spaces(self, prediction_run_id: str) -> list[dict[str, Any]]:
        with get_session() as session:
            rows = session.query(PredictionScenarioSpaceRecord).filter_by(prediction_run_id=prediction_run_id).order_by(PredictionScenarioSpaceRecord.created_at.asc()).all()
            return localize_scenario_space_rows([_scenario_space_to_dict(row) for row in rows])

    def list_match_events(self, prediction_run_id: str) -> list[dict[str, Any]]:
        with get_session() as session:
            rows = session.query(PredictionMatchEventRecord).filter_by(prediction_run_id=prediction_run_id).order_by(PredictionMatchEventRecord.minute.asc(), PredictionMatchEventRecord.created_at.asc()).all()
            players = _players_for_run(session, prediction_run_id)
            return [_match_event_to_dict(row, players=players) for row in rows]

    def list_analyst_notes(self, prediction_run_id: str) -> list[dict[str, Any]]:
        with get_session() as session:
            rows = session.query(PredictionAnalystNoteRecord).filter_by(prediction_run_id=prediction_run_id).order_by(PredictionAnalystNoteRecord.created_at.asc()).all()
            return [_analyst_note_to_dict(row) for row in rows]

    def get_result(self, prediction_run_id: str) -> dict[str, Any] | None:
        with get_session() as session:
            row = session.query(PredictionResultRecord).filter_by(prediction_run_id=prediction_run_id).one_or_none()
            return _result_to_dict(row) if row else None

    def get_roster(self, prediction_run_id: str) -> dict[str, Any]:
        with get_session() as session:
            run = session.get(PredictionRunRecord, prediction_run_id)
            if not run:
                raise KeyError(f"prediction run not found: {prediction_run_id}")
            config = session.get(PredictionConfigRecord, run.prediction_config_id) if run.prediction_config_id else None
            dataset_id = (run.run_metadata or {}).get("player_dataset_id") or (config.player_dataset_id if config else None)
            dataset = session.get(PredictionPlayerDatasetRecord, dataset_id) if dataset_id else None
            model_input = (config.model_input_snapshot or {}) if config else {}
            roster = _roster_contract(
                dataset_id=dataset_id,
                dataset=dataset,
                squads=model_input.get("squads") or {},
                actor_stats=_actor_stats_for_run(session, prediction_run_id),
            )
            return localize_step2_payload({"roster": roster, "model_input_snapshot": model_input})["roster"]

    def get_budget_usage(self, prediction_run_id: str) -> dict[str, Any]:
        with get_session() as session:
            run = session.get(PredictionRunRecord, prediction_run_id)
            if not run:
                raise KeyError(f"prediction run not found: {prediction_run_id}")
            config = session.get(PredictionConfigRecord, run.prediction_config_id) if run.prediction_config_id else None
            result = session.query(PredictionResultRecord).filter_by(prediction_run_id=prediction_run_id).one_or_none()
            return {"ledger": _ledger_contract(_merged_ledger_summary(run, config, result))}

    def _replay_snapshot(self, session, prediction_run_id: str) -> dict[str, Any]:
        scorelines = (
            session.query(PredictionScorelineRecord)
            .filter_by(prediction_run_id=prediction_run_id)
            .order_by(PredictionScorelineRecord.created_at.asc())
            .all()
        )
        events = (
            session.query(PredictionMatchEventRecord)
            .filter_by(prediction_run_id=prediction_run_id)
            .order_by(PredictionMatchEventRecord.minute.asc(), PredictionMatchEventRecord.created_at.asc())
            .all()
        )
        return {
            "scorelines": _scoreline_replay_index(_scoreline_to_dict(row) for row in scorelines),
            "events": _event_replay_index(_match_event_to_dict(row) for row in events),
        }

    def _counts(self, session, prediction_run_id: str) -> dict[str, int]:
        return {
            "scenario_cases": session.query(PredictionScenarioCaseRecord).filter_by(prediction_run_id=prediction_run_id).count(),
            "scenario_spaces": session.query(PredictionScenarioSpaceRecord).filter_by(prediction_run_id=prediction_run_id).count(),
            "scorelines": session.query(PredictionScorelineRecord).filter_by(prediction_run_id=prediction_run_id).count(),
            "match_events": session.query(PredictionMatchEventRecord).filter_by(prediction_run_id=prediction_run_id).count(),
            "analyst_notes": session.query(PredictionAnalystNoteRecord).filter_by(prediction_run_id=prediction_run_id).count(),
        }


class PredictionReportAssembler:
    """Build a Step4 report from persisted football prediction artifacts."""

    SECTION_TITLES = (
        "比赛结论摘要",
        "双方基本面与图谱证据",
        "战术、阵型与预计首发",
        "胜平负与比分预测",
        "关键比赛事件剧本",
        "风险、不确定性与可信度说明",
    )

    def __init__(self, llm_client: Any | None = None):
        self.llm_client = llm_client

    def create_report_for_project(
        self,
        project_id: str,
        *,
        force_regenerate: bool = False,
        prediction_run_id: str | None = None,
        prediction_config_id: str | None = None,
    ) -> dict[str, Any]:
        prediction_run_id = prediction_run_id or ProjectWorkflowService().get_active_run_id(project_id)
        if prediction_config_id:
            with get_session() as session:
                run = session.get(PredictionRunRecord, prediction_run_id)
                if not run:
                    raise KeyError(f"prediction run not found: {prediction_run_id}")
                if run.project_id != project_id:
                    raise ValueError("prediction_run_id does not belong to project_id")
                if run.prediction_config_id != prediction_config_id:
                    raise ValueError("prediction_config_id does not match prediction_run_id")
        return self.create_report(prediction_run_id, force_regenerate=force_regenerate)

    def create_report(self, prediction_run_id: str, *, force_regenerate: bool = False) -> dict[str, Any]:
        workflow = ProjectWorkflowService()
        active_run = workflow.require_active_run(prediction_run_id)
        project_id = active_run.project_id
        if force_regenerate:
            state = workflow.get_state(project_id)
            active_report_id = (state.get("active_artifacts") or {}).get("report_id")
            if active_report_id:
                workflow.regenerate_step(project_id, 4, reason="force_regenerate_report")

        with get_session() as session:
            run = session.get(PredictionRunRecord, prediction_run_id)
            if not run:
                raise KeyError(f"prediction run not found: {prediction_run_id}")

            active_report_id = workflow.get_active_report_id(project_id)
            existing = session.get(PredictionReportRecord, active_report_id) if active_report_id else None
            if existing and existing.status == "completed" and not force_regenerate:
                return {
                    "prediction_run_id": prediction_run_id,
                    "report_id": existing.report_id,
                    "status": existing.status,
                    "already_generated": True,
                }

            report_id = f"report_{uuid.uuid4().hex[:12]}"
            context = self._load_evidence_package(session, run)
            workflow_state = workflow.get_state(project_id)
            title = f"{run.match_name or '足球比赛'} 赛事预测报告"
            summary = self._report_summary(context)
            sections, generation_mode, llm_error = self._generate_sections(context)
            outline = {
                "title": title,
                "summary": summary,
                "sections": [{"title": item["title"], "content": ""} for item in sections],
            }
            markdown_content = self._full_markdown(title, summary, sections)

            report = PredictionReportRecord(
                report_id=report_id,
                simulation_id=prediction_run_id,
                graph_id=run.graph_id,
                simulation_requirement=(run.run_metadata or {}).get("simulation_requirement", ""),
                simulation_domain="football_match",
                status="completed",
                title=title,
                summary=summary,
                markdown_content=markdown_content,
                completed_at=utc_now(),
                report_metadata={
                    "artifact_status": "active",
                    "workflow_revision": workflow_state.get("workflow_revision"),
                    "outline": outline,
                    "prediction_run_id": prediction_run_id,
                    "prediction_config_id": run.prediction_config_id,
                    "evidence_package": context,
                    "widgets": context.get("widgets") or {},
                    "markdown_widgets": context.get("markdown_widgets") or {},
                    "generation_mode": generation_mode,
                    "llm_model": self._prediction_report_model_name(),
                    "llm_protocol": self._prediction_report_chat_protocol(),
                    "llm_error": llm_error,
                    "storage_kind": "postgres",
                    "source": "prediction_report_assembler_v2",
                },
            )
            session.add(report)

            for index, section in enumerate(sections, start=1):
                session.add(
                    PredictionReportSectionRecord(
                        report_id=report_id,
                        section_index=index,
                        title=section["title"],
                        content=section["content"],
                        section_metadata={
                            "artifact_status": "active",
                            "workflow_revision": workflow_state.get("workflow_revision"),
                            "filename": f"section_{index:02d}.md",
                            "source": "prediction_report_assembler_v2",
                        },
                    )
                )

            session.flush()

        ProjectWorkflowService().register_report(project_id, report_id)
        return {
            "prediction_run_id": prediction_run_id,
            "report_id": report_id,
            "status": "completed",
            "already_generated": False,
        }

    def _latest_prediction_run_id_for_project(self, project_id: str) -> str:
        with get_session() as session:
            run = (
                session.query(PredictionRunRecord)
                .filter_by(project_id=project_id, status="completed")
                .order_by(PredictionRunRecord.completed_at.desc(), PredictionRunRecord.created_at.desc())
                .first()
            )
            if not run:
                raise KeyError(f"no completed prediction run found for project: {project_id}")
            result = (
                session.query(PredictionResultRecord)
                .filter_by(prediction_run_id=run.prediction_run_id)
                .one_or_none()
            )
            if not result:
                raise KeyError(f"latest prediction run has no prediction result: {run.prediction_run_id}")
            return run.prediction_run_id

    def _load_evidence_package(self, session: Any, run: PredictionRunRecord) -> dict[str, Any]:
        prediction_run_id = run.prediction_run_id
        cases = (
            session.query(PredictionScenarioCaseRecord)
            .filter_by(prediction_run_id=prediction_run_id)
            .order_by(PredictionScenarioCaseRecord.created_at.asc())
            .all()
        )
        spaces = (
            session.query(PredictionScenarioSpaceRecord)
            .filter_by(prediction_run_id=prediction_run_id)
            .order_by(PredictionScenarioSpaceRecord.created_at.asc())
            .all()
        )
        scorelines = (
            session.query(PredictionScorelineRecord)
            .filter_by(prediction_run_id=prediction_run_id)
            .order_by(PredictionScorelineRecord.created_at.asc())
            .all()
        )
        events = (
            session.query(PredictionMatchEventRecord)
            .filter_by(prediction_run_id=prediction_run_id)
            .order_by(PredictionMatchEventRecord.minute.asc(), PredictionMatchEventRecord.created_at.asc())
            .all()
        )
        notes = (
            session.query(PredictionAnalystNoteRecord)
            .filter_by(prediction_run_id=prediction_run_id)
            .order_by(PredictionAnalystNoteRecord.created_at.asc())
            .all()
        )
        result = (
            session.query(PredictionResultRecord)
            .filter_by(prediction_run_id=prediction_run_id)
            .one_or_none()
        )
        config = session.get(PredictionConfigRecord, run.prediction_config_id) if run.prediction_config_id else None
        discussions = []
        if run.prediction_config_id:
            discussions = (
                session.query(PredictionCoachDiscussionRecord)
                .filter_by(prediction_config_id=run.prediction_config_id)
                .order_by(PredictionCoachDiscussionRecord.round_index.asc(), PredictionCoachDiscussionRecord.created_at.asc())
                .all()
            )
        dataset = (
            session.get(PredictionPlayerDatasetRecord, config.player_dataset_id)
            if config and config.player_dataset_id
            else None
        )
        player_availability = self._player_availability_summary(session, run=run, config=config, dataset=dataset)
        return self._build_context(
            run=run,
            config=config,
            cases=cases,
            spaces=spaces,
            scorelines=scorelines,
            events=events,
            notes=notes,
            result=result,
            discussions=discussions,
            dataset=dataset,
            player_availability=player_availability,
        )

    def answer_question(
        self,
        *,
        report_id: str,
        prediction_run_id: str,
        message: str,
        chat_history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        with get_session() as session:
            run = session.get(PredictionRunRecord, prediction_run_id)
            if not run:
                raise ValueError(f"预测运行不存在: {prediction_run_id}")
            cases = (
                session.query(PredictionScenarioCaseRecord)
                .filter_by(prediction_run_id=prediction_run_id)
                .order_by(PredictionScenarioCaseRecord.created_at.asc())
                .all()
            )
            spaces = (
                session.query(PredictionScenarioSpaceRecord)
                .filter_by(prediction_run_id=prediction_run_id)
                .order_by(PredictionScenarioSpaceRecord.created_at.asc())
                .all()
            )
            scorelines = (
                session.query(PredictionScorelineRecord)
                .filter_by(prediction_run_id=prediction_run_id)
                .order_by(PredictionScorelineRecord.created_at.asc())
                .all()
            )
            events = (
                session.query(PredictionMatchEventRecord)
                .filter_by(prediction_run_id=prediction_run_id)
                .order_by(PredictionMatchEventRecord.minute.asc(), PredictionMatchEventRecord.created_at.asc())
                .all()
            )
            notes = (
                session.query(PredictionAnalystNoteRecord)
                .filter_by(prediction_run_id=prediction_run_id)
                .order_by(PredictionAnalystNoteRecord.created_at.asc())
                .all()
            )
            result = (
                session.query(PredictionResultRecord)
                .filter_by(prediction_run_id=prediction_run_id)
                .one_or_none()
            )
            config = session.get(PredictionConfigRecord, run.prediction_config_id) if run.prediction_config_id else None
            discussions = []
            if run.prediction_config_id:
                discussions = (
                    session.query(PredictionCoachDiscussionRecord)
                    .filter_by(prediction_config_id=run.prediction_config_id)
                    .order_by(PredictionCoachDiscussionRecord.round_index.asc(), PredictionCoachDiscussionRecord.created_at.asc())
                    .all()
                )
            dataset = (
                session.get(PredictionPlayerDatasetRecord, config.player_dataset_id)
                if config and config.player_dataset_id
                else None
            )
            player_availability = self._player_availability_summary(session, run=run, config=config, dataset=dataset)
            sections = (
                session.query(PredictionReportSectionRecord)
                .filter_by(report_id=report_id)
                .order_by(PredictionReportSectionRecord.section_index.asc())
                .all()
            )
            context = self._build_context(
                run=run,
                config=config,
                cases=cases,
                spaces=spaces,
                scorelines=scorelines,
                events=events,
                notes=notes,
                result=result,
                discussions=discussions,
                dataset=dataset,
                player_availability=player_availability,
            )
            context["report_sections"] = [
                {
                    "title": section.title,
                    "excerpt": _truncate_text(section.content, 900),
                }
                for section in sections
            ]

        sources = [
            {"type": "report_sections", "report_id": report_id, "count": len(context.get("report_sections") or [])},
            {"type": "prediction_config", "prediction_config_id": context["match"].get("prediction_config_id")},
            {"type": "coach_discussions", "prediction_config_id": context["match"].get("prediction_config_id"), "count": len(context["step2"].get("coach_discussions") or [])},
            {"type": "prediction_result", "prediction_run_id": prediction_run_id},
            {"type": "match_events", "count": len(context["step3"].get("events") or [])},
            {"type": "graph_evidence", "graph_id": context["match"].get("graph_id"), "count": len(context["step1"].get("graph_entities") or [])},
        ]
        answer_mode = "llm"
        llm_error = None
        try:
            response = self._llm_chat_answer(context, message, chat_history or [])
        except Exception as exc:
            llm_error = str(exc)
            answer_mode = "template_fallback"
            response = self._template_chat_answer(context, message)
        return {
            "response": response,
            "tool_calls": [
                {"tool_name": "scoreline_distribution", "parameters": {"prediction_run_id": prediction_run_id}},
                {"tool_name": "match_event_timeline", "parameters": {"prediction_run_id": prediction_run_id}},
                {"tool_name": "prediction_config_lookup", "parameters": {"prediction_config_id": context["match"].get("prediction_config_id")}},
                {"tool_name": "coach_discussion_lookup", "parameters": {"prediction_config_id": context["match"].get("prediction_config_id")}},
                {"tool_name": "report_sections_lookup", "parameters": {"report_id": report_id}},
            ],
            "sources": sources,
            "metadata": {
                "answer_mode": answer_mode,
                "llm_model": self._prediction_report_model_name(),
                "llm_protocol": self._prediction_report_chat_protocol(),
                "llm_error": llm_error,
            },
        }

    def _create_llm_client(self) -> LLMClient:
        return LLMClient(
            api_key=self._prediction_report_api_key(),
            base_url=self._prediction_report_base_url(),
            model=self._prediction_report_model_name(),
            chat_protocol=self._prediction_report_chat_protocol(),
        )

    def _prediction_report_api_key(self) -> str | None:
        return Config.PREDICTION_REPORT_LLM_API_KEY or Config.LLM_API_KEY

    def _prediction_report_base_url(self) -> str:
        return Config.PREDICTION_REPORT_LLM_BASE_URL or Config.LLM_BASE_URL

    def _prediction_report_model_name(self) -> str:
        return Config.PREDICTION_REPORT_LLM_MODEL_NAME or Config.LLM_MODEL_NAME

    def _prediction_report_chat_protocol(self) -> str:
        return Config.PREDICTION_REPORT_LLM_CHAT_PROTOCOL or Config.LLM_CHAT_PROTOCOL

    def _build_context(
        self,
        *,
        run: PredictionRunRecord,
        config: PredictionConfigRecord | None,
        cases: list[PredictionScenarioCaseRecord],
        spaces: list[PredictionScenarioSpaceRecord],
        scorelines: list[PredictionScorelineRecord],
        events: list[PredictionMatchEventRecord],
        notes: list[PredictionAnalystNoteRecord],
        result: PredictionResultRecord | None,
        discussions: list[PredictionCoachDiscussionRecord],
        dataset: PredictionPlayerDatasetRecord | None,
        player_availability: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        model_input = (config.model_input_snapshot or {}) if config else {}
        extracted = model_input.get("extracted") if isinstance(model_input.get("extracted"), dict) else {}
        graph_snapshot = (config.graph_snapshot or {}) if config else {}
        summary = (result.scoreline_summary if result else {}) or {}
        squads = model_input.get("squads") if isinstance(model_input.get("squads"), dict) else {}
        scoreline_rows = [_scoreline_brief(row) for row in scorelines[:9]]
        scenario_space_rows = [_scenario_space_brief(row) for row in spaces]
        scenario_case_rows = [_scenario_case_brief(row) for row in cases[:9]]
        event_rows = [_event_brief(row) for row in _select_report_events(events)]
        note_rows = [_note_brief(row) for row in notes[:10]]
        project_snapshot = _project_report_snapshot(run.project_id)
        team_metadata = _team_metadata_summary(config=config, dataset=dataset, squads=squads)
        team_rankings = _team_ranking_summary(config=config, squads=squads)
        team_strength_rows = [_team_strength_to_dict(row) for row in _ordered_strength_rows(run, config)]
        formations = _formation_summary(
            extracted.get("tactical_notes") or [],
            model_input.get("home_iso3"),
            model_input.get("away_iso3"),
            team_metadata=team_metadata,
        )
        widgets = _build_report_widgets(
            match={
                "home_team": run.home_team or "主队",
                "away_team": run.away_team or "客队",
            },
            squads=squads,
            formations=formations,
            team_metadata=team_metadata,
            tactical_notes=extracted.get("tactical_notes") or [],
            coach_discussions=discussions,
            team_strengths=team_strength_rows,
        )
        lineups = {
            "home": widgets["lineup_widget"]["home"].get("players") or [],
            "away": widgets["lineup_widget"]["away"].get("players") or [],
        }
        markdown_widgets = _report_widgets_markdown(widgets)
        counts = {
            "step1_graph_entities": graph_snapshot.get("entities_count") or model_input.get("graph_entities_count") or 0,
            "step1_graph_relationships": graph_snapshot.get("relationships_count") or _graph_binding_edge_count(run),
            "step2_team_strengths": len(team_strength_rows),
            "step2_lineup_players": sum(len(items) for items in lineups.values()),
            "step2_scenario_designs": len((config.scenario_design_summary or {}).get("matrix") or []) if config else 0,
            "step3_scenario_cases": len(cases),
            "step3_scenario_spaces": len(spaces),
            "step3_scorelines": len(scorelines),
            "step3_match_events": len(events),
            "step3_analyst_notes": len(notes),
        }
        return {
            "match": {
                "prediction_run_id": run.prediction_run_id,
                "prediction_config_id": run.prediction_config_id,
                "project_id": run.project_id,
                "graph_id": run.graph_id,
                "match_name": run.match_name or f"{run.home_team or '主队'} vs {run.away_team or '客队'}",
                "home_team": run.home_team or "主队",
                "away_team": run.away_team or "客队",
                "competition": run.competition or (config.competition if config else None),
                "kickoff_time": run.kickoff_time or (config.kickoff_time if config else None),
                "requirement": (run.run_metadata or {}).get("simulation_requirement") or model_input.get("prediction_requirement") or "",
            },
            "step1": {
                "project": project_snapshot,
                "source_documents": _source_documents_snapshot(run, config, project_snapshot),
                "graph_entities_count": counts["step1_graph_entities"],
                "graph_relationships_count": counts["step1_graph_relationships"],
                "graph_summary": graph_snapshot.get("summary") or project_snapshot.get("analysis_summary") or "",
                "graph_entities": _compact_graph_entities(graph_snapshot.get("entities") or []),
                "graph_relationships": _compact_graph_relationships(graph_snapshot.get("relationships") or []),
                "key_narratives": _string_list(extracted.get("key_narratives"))[:8],
                "injury_reports": _compact_injury_reports(extracted.get("injury_reports") or []),
                "tactical_notes": _compact_tactical_notes(extracted.get("tactical_notes") or []),
                "external_sources": _external_source_lines(config),
            },
            "step2": {
                "prediction_config": _config_report_snapshot(config),
                "scenario_design_summary": config.scenario_design_summary if config else {},
                "resume_policy_summary": config.resume_policy_summary if config else {},
                "coach_jury_summary": config.coach_jury_summary if config else {},
                "coach_discussions": [
                    {
                        "topic": row.topic,
                        "summary": row.summary,
                        "consensus_score": row.consensus_score,
                        "disagreement_score": row.disagreement_score,
                    }
                    for row in discussions
                ],
                "formations": formations,
                "lineups": lineups,
                "team_strengths": team_strength_rows,
                "team_metadata": team_metadata,
                "team_rankings": team_rankings,
                "player_attributes": _player_attributes_summary(squads),
                "player_availability": player_availability,
                "scenario_design": _scenario_design_rows(config.scenario_design_summary if config else {}, scenario_case_rows),
                "budget_or_degradation": _budget_or_degradation_summary(run, config, result),
            },
            "step3": {
                "scoreline_summary": summary,
                "scorelines": scoreline_rows,
                "scenario_spaces": scenario_space_rows,
                "scenario_cases": scenario_case_rows,
                "events": event_rows,
                "event_timeline": _event_timeline_buckets(event_rows),
                "analyst_notes": note_rows,
                "uncertainty_factors": (result.uncertainty_factors if result else []) or [],
                "confidence": result.confidence if result else None,
                "xg": _weighted_xg_summary(scorelines, cases),
                "top_scores": _top_score_candidates(summary, scorelines),
            },
            "credibility": {
                "budget": self._budget_credibility_metadata(
                    run=run,
                    config=config,
                    result=result,
                    dataset=dataset,
                    player_availability=player_availability,
                ),
                "warnings": _warning_items(run=run, config=config, result=result),
                "data_counts": counts,
            },
            "widgets": widgets,
            "markdown_widgets": markdown_widgets,
        }

    def _generate_sections(self, context: dict[str, Any]) -> tuple[list[dict[str, str]], str, str | None]:
        try:
            llm = self.llm_client or self._create_llm_client()
            response = llm.chat(
                self._report_messages(context),
                temperature=0.35,
                max_tokens=7000,
            )
            sections = self._parse_sections(response)
            sections = self._enrich_required_context(sections, context)
            return sections, "llm", None
        except Exception as exc:
            return self._enrich_required_context(self._template_sections(context), context), "template_fallback", str(exc)

    def _report_messages(self, context: dict[str, Any]) -> list[dict[str, str]]:
        language_instruction = instruction_for_project(
            context.get("match", {}).get("project_id"),
            fallback_materials=[
                context.get("match", {}).get("requirement") or "",
                json.dumps(context.get("step1", {}).get("project") or {}, ensure_ascii=False, default=str),
            ],
        )
        return [
            {
                "role": "system",
                "content": (
                    "你是专业足球赛前预测分析师。请按内容语言要求写一份普通球迷能看懂的数据看板式 Markdown 报告。"
                    "只使用证据包 JSON 中的真实数据，缺失数据写“资料未明确”，不得编造。"
                    "禁止输出数据库字段、内部 ID、模型诊断字段，也不要解释实现细节。"
                    "不要写大段散文；每章最多 2 段长文字，其余用 Markdown 表格、短 bullet、数字卡片、文本概率条表达。"
                    "少用抽象黑话；每个专业判断都要解释这对比赛意味着什么。"
                    "不得使用 Mermaid、ECharts、HTML、SVG、canvas 或外链图片。"
                    f"\n\n{language_instruction}"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请严格输出 6 个章节，每章用“## 章节名”作为边界，并保持以下章节顺序。"
                    "如果内容语言不是中文，可以把章节标题翻译为当前界面语言，但顺序必须一致：\n"
                    "- 比赛结论摘要\n"
                    "- 双方基本面与图谱证据\n"
                    "- 战术、阵型与预计首发\n"
                    "- 胜平负与比分预测\n"
                    "- 关键比赛事件剧本\n"
                    "- 风险、不确定性与可信度说明\n\n"
                    "每章必须包含：\n"
                    "- `**一句话结论：**`\n"
                    "- 至少一个 Markdown 表格或文本可视化块\n"
                    "- `**怎么读：**`，用普通球迷语言解释数据\n"
                    "- `**依据来自：**`，明确写出使用了 Step1 / Step2 / Step3 哪些证据\n\n"
                    "必须显式展示这些数据，缺失时写“资料未明确”：\n"
                    "- 比赛结论摘要：预测方向、最可能比分、胜平负概率文本条、置信度、3 个关键理由。\n"
                    "- 双方基本面与图谱证据：基本面对比表、伤停/可用性表、图谱关键实体表。\n"
                    "- 战术、阵型与预计首发：必须优先使用 `widgets.lineup_widget`、`widgets.tactics_widget`、`widgets.matchup_widget`；包含阵型预测摘要、首发名单表、战术判断表、关键对位表、不确定性说明。\n"
                    "- 胜平负与比分预测：概率条、Top 5 比分表、场景矩阵/六空间表、xG 对比。\n"
                    "- 关键比赛事件剧本：0-30、31-60、61-75、76-90+ 时间线表，引用 Step3 match_events。\n"
                    "- 风险、不确定性与可信度说明：伤停、天气、红黄牌/VAR、体能、首发变动、数据缺口风险表。\n\n"
                    "不要自己补不存在的球员、教练、阵型或评分；widget 里没有的值写“资料未明确”或“--”。\n\n"
                    f"证据包 JSON：\n{json.dumps(context, ensure_ascii=False, default=str)[:28000]}"
                ),
            },
        ]

    def _parse_sections(self, response: str) -> list[dict[str, str]]:
        text = _strip_markdown_fences(response)
        titled_sections = _section_blocks_by_titles(text, self.SECTION_TITLES)
        if len(titled_sections) == 6:
            return [
                {"title": title, "content": self._normalize_section_content(titled_sections[index])}
                for index, title in enumerate(self.SECTION_TITLES)
            ]
        heading_sections = _section_blocks_by_markdown_headings(text)
        if len(heading_sections) == 6:
            return [
                {"title": title, "content": self._normalize_section_content(heading_sections[index])}
                for index, title in enumerate(self.SECTION_TITLES)
            ]
        sections: list[str] = []
        if len(sections) < 6:
            sections = [item.strip() for item in re.split(r"\n{2,}(?=\*\*一句话结论[:：]\*\*)", text) if item.strip()]
        if len(sections) != 6:
            sections = []
        if len(sections) < 6:
            sections = [
                re.sub(r"^#{1,3}\s+.*$", "", item.strip(), flags=re.MULTILINE).strip()
                for item in re.split(r"(?m)^\s*---+\s*$", text)
                if item.strip()
            ]
            if len(sections) != 6:
                sections = []
        if len(sections) < 6:
            sections = [item.strip() for item in re.split(r"\n{3,}", text) if item.strip()]
            if len(sections) != 6:
                sections = []
        if len(sections) != 6:
            raise ValueError("Prediction report LLM did not return 6 readable sections")
        return [
            {"title": title, "content": self._normalize_section_content(sections[index])}
            for index, title in enumerate(self.SECTION_TITLES)
        ]

    def _normalize_section_content(self, content: str) -> str:
        cleaned = re.sub(r"^#{1,3}\s+.*$", "", content.strip(), flags=re.MULTILINE).strip()
        cleaned = re.sub(r"^\s*---+\s*$", "", cleaned, flags=re.MULTILINE).strip()
        if "一句话结论" not in cleaned:
            cleaned = f"**一句话结论：** {cleaned}"
        if "怎么读" not in cleaned:
            cleaned += "\n\n**怎么读：** 先看表格里的方向和概率，再看风险项；预测只代表当前资料下更可能出现的走势。"
        if "依据来自" not in cleaned:
            cleaned += "\n\n**依据来自：** Step1 图谱和材料摘要；Step2 阵容、球队强度和教练讨论；Step3 比分概率、事件链和风险因素。"
        return cleaned

    def _enrich_required_context(
        self,
        sections: list[dict[str, str]],
        context: dict[str, Any],
    ) -> list[dict[str, str]]:
        enriched = [{**section} for section in sections]
        for section in enriched:
            section["content"] = self._normalize_section_content(section["content"])
            if section["title"] == "比赛结论摘要":
                section["content"] = _canonical_summary_section(context)
                continue
            if not _has_markdown_visual(section["content"]):
                section["content"] = (
                    section["content"].rstrip()
                    + "\n\n**看板补充：**\n"
                    + _section_visual_block(section["title"], context)
                )
            if "依据来自" not in section["content"]:
                section["content"] = (
                    section["content"].rstrip()
                    + "\n\n**依据来自：** "
                    + _section_basis_text(section["title"])
                )
            if "怎么读" not in section["content"]:
                section["content"] = (
                    section["content"].rstrip()
                    + "\n\n**怎么读：** "
                    + _section_how_to_read(section["title"])
                )
            if section["title"] == "战术、阵型与预计首发":
                section["content"] = _ensure_tactics_widget_markdown(section["content"], context)
            if section["title"] == "风险、不确定性与可信度说明":
                additions: list[str] = []
                if "预测不是确定结果" not in section["content"]:
                    additions.append("- 预测不是确定结果，只代表当前证据下的概率倾向。")
                credibility = _credibility_text(context).strip()
                if credibility:
                    for line in credibility.splitlines():
                        normalized = "- " + line.strip().lstrip("- ").strip()
                        if normalized and normalized not in section["content"]:
                            additions.append(normalized)
                if additions:
                    section["content"] = (
                        section["content"].rstrip()
                        + "\n\n**数据可信度补充：**\n"
                        + "\n".join(additions)
                    )
        return enriched

    def _template_sections(self, context: dict[str, Any]) -> list[dict[str, str]]:
        match = context["match"]
        step3 = context["step3"]
        score = step3.get("scoreline_summary") or {}
        probabilities = score.get("win_draw_loss_probability") or {}
        most_likely = score.get("most_likely_score") or "-"
        home = match.get("home_team") or "主队"
        away = match.get("away_team") or "客队"
        verdict = _wdl_verdict(probabilities, home, away)
        sections = [
            (
                "比赛结论摘要",
                "\n\n".join(
                    [
                        f"**一句话结论：** 本场首选 **{verdict}**，最可能比分是 **{most_likely}**；这不是确定赛果，而是当前证据下的概率倾向。",
                        _section_visual_block("比赛结论摘要", context),
                        f"**怎么读：** 先看首选方向，再看主胜/平局/客胜三条概率。条越长，说明这个结果在 Step3 加权比分里越常见；如果三条差距小，就要把平局和小比分波动一起看。",
                        "**依据来自：** Step1 图谱实体、关键叙事和伤停；Step2 球队强度、阵型、预计首发和教练讨论；Step3 胜平负概率、Top 比分、xG、事件链和不确定因素。",
                    ]
                ),
            ),
            (
                "双方基本面与图谱证据",
                "\n\n".join(
                    [
                        f"**一句话结论：** 基本面重点看两队强度差、可用球员和图谱里反复出现的关键实体；资料缺口会直接降低判断确定性。",
                        _section_visual_block("双方基本面与图谱证据", context),
                        f"**怎么读：** 这章不是看谁名气大，而是看 {home} 和 {away} 在攻防、排名/评分、伤停与图谱线索上有没有明显差距。伤停表里如果出现主力缺席，比分方向通常会向对手或平局移动。",
                        "**依据来自：** Step1 上传材料、图谱实体/关系、关键叙事、伤停、战术 notes、外部来源快照；Step2 球员可用性和球队强度。",
                    ]
                ),
            ),
            (
                "战术、阵型与预计首发",
                "\n\n".join(
                    [
                        "**一句话结论：** 阵型和首发决定比赛会从哪里打开局面：边路、定位球、转换速度或中路控制。",
                        _section_visual_block("战术、阵型与预计首发", context),
                        "**怎么读：** 阵型表看两队站位；关键球员表看谁最可能影响进球或防守；对位表看哪一侧更容易形成机会。预计首发仍要等赛前名单确认。",
                        "**依据来自：** Step1 战术 notes；Step2 球队 metadata、阵型、预计首发、球员属性、球员可用性和教练讨论。",
                    ]
                ),
            ),
            (
                "胜平负与比分预测",
                "\n\n".join(
                    [
                        f"**一句话结论：** 概率层面首选 **{verdict}**，但 Top 比分分散度决定了这场是稳胆还是需要防平/防冷。",
                        _section_visual_block("胜平负与比分预测", context),
                        "**怎么读：** 概率条看赛果方向，Top 5 比分看最常见比分，xG 看双方机会质量。场景/空间表告诉你：如果比赛变开放、出现失误或红牌，比分会怎样偏移。",
                        "**依据来自：** Step3 胜平负概率、Top 比分候选、加权 xG、九场景/六空间、scorelines；Step2 场景设计和球队强度。",
                    ]
                ),
            ),
            (
                "关键比赛事件剧本",
                "\n\n".join(
                    [
                        "**一句话结论：** 事件剧本不是直播预言，而是 Step3 事件链里最值得提前盯的时间段。",
                        _section_visual_block("关键比赛事件剧本", context),
                        "**怎么读：** 看每个时间段的触发条件：如果现实比赛出现同类信号，比如早早黄牌、门将连续扑救或换人提速，比分方向就可能向表里的影响靠近。",
                        "**依据来自：** Step3 match_events、事件描述、比分影响、分析笔记；Step2 场景设计用于解释触发条件。",
                    ]
                ),
            ),
            (
                "风险、不确定性与可信度说明",
                "\n\n".join(
                    [
                        "**一句话结论：** 预测不是确定结果；最大变量通常来自首发、伤停、牌/VAR、体能和数据缺口。",
                        _section_visual_block("风险、不确定性与可信度说明", context),
                        "**怎么读：** 风险表不是否定预测，而是告诉你什么情况会让比分方向改变。风险越靠近临场信息，越应该在开赛前复核。",
                        "**依据来自：** Step1 伤停、天气/资料线索和外部来源；Step2 可用性、预算/降级与警告；Step3 不确定因素、事件链和置信度。",
                    ]
                ),
            ),
        ]
        return [{"title": title, "content": content} for title, content in sections]

    def _template_chat_answer(self, context: dict[str, Any], message: str) -> str:
        match = context["match"]
        step3 = context["step3"]
        score = step3.get("scoreline_summary") or {}
        probabilities = score.get("win_draw_loss_probability") or {}
        home = match.get("home_team") or "主队"
        away = match.get("away_team") or "客队"
        most_likely = score.get("most_likely_score") or "-"
        candidates = _candidate_score_text(score.get("top_score_candidates") or [])
        reports = context.get("report_sections") or []
        report_titles = "、".join(item.get("title") or "" for item in reports[:6]) or "Step4 报告"
        events = context["step3"].get("events") or []
        event_text = "；".join(
            f"{item.get('minute')}'{_event_type_label(item.get('event_type') or '')}"
            for item in events[:4]
        ) or "暂无关键事件链"
        discussion = _chat_basis_text(context)
        risks = context["step3"].get("uncertainty_factors") or ["首发临场确认、伤停变化、VAR/红黄牌和早进球"]
        return "\n\n".join(
            [
                f"我会优先按 Step4 报告来解释。当前报告章节包括：{report_titles}。",
                f"**结论：** {home} vs {away} 的最可能比分是 **{most_likely}**；胜平负概率为主胜 {_format_probability(probabilities.get('home_win'))}、平局 {_format_probability(probabilities.get('draw'))}、客胜 {_format_probability(probabilities.get('away_win'))}。候选比分是 {candidates}。",
                f"**依据：** {discussion} 事件链里最需要看的节点是：{event_text}。",
                f"**风险：** 预测不是确定结果。主要不确定因素是：{', '.join(str(item) for item in risks[:4])}。",
            ]
        )

    def _llm_chat_answer(
        self,
        context: dict[str, Any],
        message: str,
        chat_history: list[dict[str, Any]],
    ) -> str:
        llm = self.llm_client or self._create_llm_client()
        response = llm.chat(
            self._qa_messages(context, message, chat_history),
            temperature=0.25,
            max_tokens=1400,
        )
        cleaned = _strip_markdown_fences(response)
        cleaned = re.sub(r"<tool_call>.*?</tool_call>", "", cleaned, flags=re.DOTALL).strip()
        cleaned = re.sub(r"\[TOOL_CALL\].*?\)", "", cleaned, flags=re.DOTALL).strip()
        if not cleaned:
            raise ValueError("LLM返回内容为空")
        if "报告" not in cleaned:
            cleaned = f"根据报告，{cleaned}"
        return cleaned

    def _qa_messages(
        self,
        context: dict[str, Any],
        message: str,
        chat_history: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        language_instruction = instruction_for_project(
            context.get("match", {}).get("project_id"),
            fallback_materials=[
                context.get("match", {}).get("requirement") or "",
                "\n".join(item.get("excerpt") or "" for item in context.get("report_sections") or []),
            ],
        )
        return [
            {
                "role": "system",
                "content": (
                    "你是足球预测报告问答助手。必须以已生成报告内容为第一上下文，"
                    "再结合结构化预测产物回答用户问题。不要编造报告没有支持的信息；"
                    "资料不足时直接说明“报告未明确”。不要暴露数据库字段、内部 ID、实现细节或工具调用。"
                    "回答应针对用户当前问题，不要每次都套用同一段比分/风险模板。"
                    f"\n\n{language_instruction}"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请基于下面上下文回答最后的用户问题。\n\n"
                    f"{_qa_context_text(context)}\n\n"
                    f"最近对话：\n{_chat_history_text(chat_history)}\n\n"
                    f"用户当前问题：{message}"
                ),
            },
        ]

    def _report_summary(self, context: dict[str, Any]) -> str:
        match = context["match"]
        score = context["step3"].get("scoreline_summary") or {}
        probabilities = score.get("win_draw_loss_probability") or {}
        verdict = _wdl_verdict(probabilities, match.get("home_team") or "主队", match.get("away_team") or "客队")
        most_likely = score.get("most_likely_score") or "-"
        return f"首选{verdict}，最可能比分 {most_likely}；核心依据来自图谱证据、教练讨论、比分概率和事件链。"

    def _full_markdown(self, title: str, summary: str, sections: list[dict[str, str]]) -> str:
        parts = [f"# {title}", "", f"> {summary}"]
        for index, section in enumerate(sections, start=1):
            parts.extend(["", f"## {index:02d} {section['title']}", "", section["content"].strip()])
        return "\n".join(parts).strip() + "\n"

    def _budget_credibility_metadata(
        self,
        *,
        run: PredictionRunRecord,
        config: PredictionConfigRecord | None,
        result: PredictionResultRecord | None,
        dataset: PredictionPlayerDatasetRecord | None,
        player_availability: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "budget_profile": _report_budget_profile(run, config),
            "ledger": _merged_ledger_summary(run, config, result),
            "external_sources": _external_sources_snapshot(config),
            "player_dataset": _player_dataset_snapshot(run=run, config=config, dataset=dataset),
            "player_availability": player_availability,
            "backtest": _latest_backtest_report(),
        }

    def _player_availability_summary(
        self,
        session: Any,
        *,
        run: PredictionRunRecord,
        config: PredictionConfigRecord | None,
        dataset: PredictionPlayerDatasetRecord | None,
    ) -> dict[str, dict[str, Any]]:
        snapshot = (config.model_input_snapshot or {}) if config else {}
        squads = snapshot.get("squads") if isinstance(snapshot, dict) else {}
        if not isinstance(squads, dict):
            squads = {}
        summary = {
            "home": _squad_availability_summary(squads.get("home") if isinstance(squads.get("home"), dict) else {}),
            "away": _squad_availability_summary(squads.get("away") if isinstance(squads.get("away"), dict) else {}),
        }
        if not dataset:
            return summary

        refs = {
            "home": _team_ref(squads.get("home") if isinstance(squads.get("home"), dict) else {}, run.home_team),
            "away": _team_ref(squads.get("away") if isinstance(squads.get("away"), dict) else {}, run.away_team),
        }
        for role, ref in refs.items():
            if summary.get(role, {}).get("total"):
                continue
            players = _query_dataset_players(session, dataset.dataset_id, ref)
            summary[role] = _players_availability_summary(players, fallback_team=ref.get("name") or "")
        return summary


def _strip_markdown_fences(text: str) -> str:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:markdown|md)?\s*\n?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    return cleaned.strip()


def _section_blocks_by_titles(text: str, titles: tuple[str, ...]) -> list[str]:
    markers: list[tuple[int, int, str]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        raw = line.strip()
        normalized = re.sub(r"^#{1,3}\s*", "", raw)
        normalized = re.sub(r"^(?:第?[一二三四五六七八九十]+[章节、.：:\s]+|\d+[.、\s]+)", "", normalized).strip()
        if normalized in titles:
            line_start = offset + len(line) - len(line.lstrip())
            line_end = offset + len(line.rstrip("\r\n"))
            markers.append((line_start, line_end, normalized))
        offset += len(line)
    if len(markers) != len(titles):
        return []
    markers.sort(key=lambda item: item[0])
    ordered_titles = [item[2] for item in markers]
    if ordered_titles != list(titles):
        return []
    blocks: list[str] = []
    for index, (_, end, _) in enumerate(markers):
        next_start = markers[index + 1][0] if index + 1 < len(markers) else len(text)
        blocks.append(text[end:next_start].strip())
    return blocks


def _section_blocks_by_markdown_headings(text: str) -> list[str]:
    markers: list[tuple[int, int]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        if re.match(r"^\s*#{1,3}\s+\S+", line):
            line_start = offset + len(line) - len(line.lstrip())
            line_end = offset + len(line.rstrip("\r\n"))
            markers.append((line_start, line_end))
        offset += len(line)
    if len(markers) != 6:
        return []
    blocks: list[str] = []
    for index, (_, end) in enumerate(markers):
        next_start = markers[index + 1][0] if index + 1 < len(markers) else len(text)
        blocks.append(text[end:next_start].strip())
    return blocks


def _truncate_text(value: Any, limit: int = 500) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _compact_graph_entities(entities: Any) -> list[dict[str, Any]]:
    if not isinstance(entities, list):
        return []
    compact: list[dict[str, Any]] = []
    for entity in entities[:20]:
        if not isinstance(entity, dict):
            continue
        compact.append(
            {
                "name": entity.get("name"),
                "type": entity.get("entity_type") or entity.get("type") or entity.get("labels"),
                "summary": _truncate_text(entity.get("summary") or entity.get("description"), 220),
            }
        )
    return compact


def _compact_graph_relationships(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in items[:30]:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "type": item.get("name") or item.get("type"),
                "fact": _truncate_text(item.get("fact") or item.get("summary") or item.get("description"), 220),
            }
        )
    return compact


def _compact_injury_reports(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in items[:12]:
        if isinstance(item, dict):
            compact.append(
                {
                    "player": item.get("player"),
                    "team_iso3": item.get("team_iso3"),
                    "status": item.get("status"),
                    "evidence": item.get("evidence_span") or item.get("source") or item.get("summary"),
                }
            )
    return compact


def _compact_tactical_notes(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    compact: list[dict[str, Any]] = []
    for item in items[:10]:
        if isinstance(item, dict):
            compact.append(
                {
                    "team_iso3": item.get("team_iso3"),
                    "note": _truncate_text(item.get("note") or item.get("summary"), 420),
                }
            )
    return compact


def _formation_summary(
    tactical_notes: Any,
    home_iso3: str | None,
    away_iso3: str | None,
    *,
    team_metadata: dict[str, dict[str, Any]] | None = None,
) -> dict[str, str | None]:
    notes = _compact_tactical_notes(tactical_notes)
    result = {
        "home": ((team_metadata or {}).get("home") or {}).get("formation_primary"),
        "away": ((team_metadata or {}).get("away") or {}).get("formation_primary"),
    }
    iso_to_role = {
        str(home_iso3 or "").upper(): "home",
        str(away_iso3 or "").upper(): "away",
    }
    for item in notes:
        role = iso_to_role.get(str(item.get("team_iso3") or "").upper())
        if not role or result.get(role):
            continue
        note = item.get("note") or ""
        match = re.search(r"(\d-\d-\d(?:-\d)?|\d后卫|\d中场|\d前锋)", note)
        result[role] = match.group(1) if match else None
    return result


def _lineup_summary(squads: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {"home": [], "away": []}
    for role in ("home", "away"):
        team = squads.get(role) if isinstance(squads.get(role), dict) else {}
        players = team.get("players") if isinstance(team.get("players"), list) else []
        starter_ids = set(str(item) for item in (team.get("starter_ids") or []))
        starters = [
            player for player in players
            if str(player.get("id") or "") in starter_ids or player.get("expected_role") == "starter"
        ]
        if not starters:
            starters = sorted(
                players,
                key=lambda item: float(item.get("expected_minutes_share") or 0),
                reverse=True,
            )[:11]
        result[role] = [
            {
                "name": player.get("name") or player.get("full_name") or player.get("name_en"),
                "position": player.get("position_primary") or player.get("position_class"),
                "overall": (player.get("derived") or {}).get("overall"),
                "attack": (player.get("derived") or {}).get("attack"),
                "defense": (player.get("derived") or {}).get("defense"),
                "finishing": (player.get("derived") or {}).get("finishing"),
                "passing": (player.get("derived") or {}).get("passing"),
                "set_piece": (player.get("derived") or {}).get("set_piece"),
                "gk": (player.get("derived") or {}).get("gk"),
                "expected_role": player.get("expected_role"),
                "expected_minutes_share": player.get("expected_minutes_share"),
                "availability": (player.get("availability") or {}).get("status"),
            }
            for player in starters[:11]
            if isinstance(player, dict)
        ]
    return result


def _build_report_widgets(
    *,
    match: dict[str, Any],
    squads: dict[str, Any],
    formations: dict[str, Any],
    team_metadata: dict[str, dict[str, Any]],
    tactical_notes: Any,
    coach_discussions: list[PredictionCoachDiscussionRecord],
    team_strengths: list[dict[str, Any]],
) -> dict[str, Any]:
    strengths = _strengths_by_role(team_strengths)
    lineup_widget = {
        role: _lineup_widget_team(
            role=role,
            team_name=match.get("home_team") if role == "home" else match.get("away_team"),
            squad=squads.get(role) if isinstance(squads.get(role), dict) else {},
            formation=formations.get(role),
            metadata=(team_metadata or {}).get(role) or {},
            strength=strengths.get(role) or {},
        )
        for role in ("home", "away")
    }
    tactics_widget = {
        role: _tactics_widget_team(
            role=role,
            lineup=lineup_widget[role],
            metadata=(team_metadata or {}).get(role) or {},
            tactical_notes=tactical_notes,
            coach_discussions=coach_discussions,
            team_strengths=team_strengths,
        )
        for role in ("home", "away")
    }
    return {
        "lineup_widget": lineup_widget,
        "tactics_widget": tactics_widget,
        "matchup_widget": _matchup_widget(lineup_widget, team_strengths),
    }


def _lineup_widget_team(
    *,
    role: str,
    team_name: Any,
    squad: dict[str, Any],
    formation: Any,
    metadata: dict[str, Any],
    strength: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del strength
    players = [item for item in (squad.get("players") or []) if isinstance(item, dict)]
    starters, source, low_confidence = _select_starters(
        players,
        squad.get("starter_ids") or [],
        formation=formation or metadata.get("formation_primary"),
    )
    resolved_formation, formation_source = _resolve_widget_formation(
        formation,
        metadata=metadata,
        starters=starters,
    )
    bench = [
        _lineup_widget_player(player, index=index, pitch_slot="", low_confidence=False)
        for index, player in enumerate(_select_bench(players, starters), start=1)
    ]
    slots = _formation_slots(resolved_formation, starters)
    starter_rows = [
        _lineup_widget_player(
            player,
            index=index,
            pitch_slot=slots[index - 1] if index - 1 < len(slots) else f"S{index}",
            low_confidence=low_confidence,
        )
        for index, player in enumerate(starters[:11], start=1)
    ]
    notes: list[str] = []
    if len(starter_rows) < 11:
        notes.append("首发名单不完整 / 低置信度")
    if low_confidence:
        notes.append("首发按预计出场时间和可用球员补齐，低置信度")
    if formation_source == "inferred":
        notes.append("阵型资料未明确，按位置分布推断")
    if not players:
        notes.append("缺少 Step2 球员名册，不能渲染预计首发")
    if not starter_rows:
        notes.append("预计首发资料未明确")

    confidence = 0.72
    if low_confidence:
        confidence -= 0.18
    if formation_source == "inferred":
        confidence -= 0.12
    if len(starter_rows) < 11:
        confidence -= 0.2

    return {
        "team": str(squad.get("team_name") or squad.get("team_fifa") or team_name or ("主队" if role == "home" else "客队")),
        "formation": resolved_formation,
        "formation_source": formation_source,
        "confidence": round(max(0.25, min(0.92, confidence)), 2),
        "lineup_source": source,
        "players": starter_rows,
        "bench": bench,
        "notes": "；".join(dict.fromkeys(notes)) or "资料来自 Step2 球员名册和球队 metadata",
    }


def _select_starters(
    players: list[dict[str, Any]],
    starter_ids: Any,
    *,
    formation: Any = None,
) -> tuple[list[dict[str, Any]], str, bool]:
    if not players:
        return [], "no_players", True
    id_set = {str(item) for item in starter_ids or [] if str(item or "").strip()}
    if id_set:
        starters = [player for player in players if str(player.get("id") or "") in id_set]
        if starters:
            return _fill_starters_to_eleven(players, starters, source="starter_ids", formation=formation)
    starters = [player for player in players if str(player.get("expected_role") or "").lower() == "starter"]
    if starters:
        return _fill_starters_to_eleven(players, starters, source="expected_role", formation=formation)
    starters = sorted(
        players,
        key=lambda item: float(item.get("expected_minutes_share") or 0),
        reverse=True,
    )[:11]
    if len(starters) >= 11:
        return _sort_starters(starters), "expected_minutes_share", False
    return _fill_starters_to_eleven(players, starters, source="expected_minutes_share", formation=formation)


def _fill_starters_to_eleven(
    players: list[dict[str, Any]],
    starters: list[dict[str, Any]],
    *,
    source: str,
    formation: Any = None,
) -> tuple[list[dict[str, Any]], str, bool]:
    selected = list(starters[:11])
    selected_ids = {id(item) for item in selected}
    targets = _formation_group_targets(formation)

    for group in ("GK", "DF", "MF", "FW"):
        while len(selected) < 11 and _selected_group_count(selected, group) < targets.get(group, 0):
            player = _best_available_player_for_group(players, selected_ids, group)
            if not player:
                break
            selected.append(player)
            selected_ids.add(id(player))

    for player in _available_players_ranked(players):
        if len(selected) >= 11:
            break
        if id(player) in selected_ids:
            continue
        group = _position_group(_player_position(player))
        if group == "GK" and _selected_group_count(selected, "GK") >= targets.get("GK", 1):
            continue
        selected.append(player)
        selected_ids.add(id(player))
    filled = len(selected) >= 11
    filled_source = f"{source}_fill" if filled and len(starters) < 11 else source
    return _sort_starters(selected)[:11], filled_source, not filled or len(starters) < 11


def _formation_group_targets(formation: Any) -> dict[str, int]:
    grouped_slots = _formation_slot_groups(formation)
    if grouped_slots:
        return {group: len(slots) for group, slots in grouped_slots.items()}
    normalized = _normalize_formation(formation)
    parts = [int(part) for part in normalized.split("-") if part.isdigit()]
    if len(parts) >= 3:
        return {"GK": 1, "DF": parts[0], "MF": sum(parts[1:-1]), "FW": parts[-1]}
    return {"GK": 1, "DF": 4, "MF": 4, "FW": 2}


def _selected_group_count(players: list[dict[str, Any]], group: str) -> int:
    return sum(1 for player in players if _position_group(_player_position(player)) == group)


def _best_available_player_for_group(
    players: list[dict[str, Any]],
    selected_ids: set[int],
    group: str,
) -> dict[str, Any] | None:
    candidates = [
        player for player in _available_players_ranked(players)
        if id(player) not in selected_ids and _position_group(_player_position(player)) == group
    ]
    return candidates[0] if candidates else None


def _available_players_ranked(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    playable = [
        player for player in players
        if ((player.get("availability") or {}).get("status") or "available") not in {"injured", "suspended"}
    ] or players
    return sorted(
        playable,
        key=lambda item: (
            _expected_role_sort_key(item.get("expected_role")),
            -float(item.get("expected_minutes_share") or 0),
            -_coerce_float((item.get("derived") or {}).get("overall"), 0),
            _position_sort_key(_player_position(item)),
            _coerce_int(item.get("shirt_number"), 99),
        ),
    )


def _expected_role_sort_key(value: Any) -> int:
    return {"starter": 0, "rotation": 1, "bench": 2, "reserve": 3}.get(str(value or "").lower(), 4)


def _sort_starters(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        players,
        key=lambda item: (
            _position_sort_key(_player_position(item)),
            -float(item.get("expected_minutes_share") or 0),
            _coerce_int(item.get("shirt_number"), 99),
        ),
    )


def _select_bench(players: list[dict[str, Any]], starters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    starter_ids = {str(player.get("id") or "") for player in starters if player.get("id")}
    starter_obj_ids = {id(player) for player in starters}
    bench = [
        player for player in players
        if (str(player.get("id") or "") not in starter_ids if player.get("id") else id(player) not in starter_obj_ids)
    ]
    return sorted(
        bench,
        key=lambda item: (
            str(item.get("expected_role") or "") != "bench",
            -float(item.get("expected_minutes_share") or 0),
            _position_sort_key(_player_position(item)),
        ),
    )[:9]


def _available_players_by_position(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    playable = [
        player for player in players
        if ((player.get("availability") or {}).get("status") or "available") not in {"injured", "suspended"}
    ] or players
    return sorted(
        playable,
        key=lambda item: (
            _position_sort_key(_player_position(item)),
            -float(item.get("expected_minutes_share") or 0),
        ),
    )


def _lineup_widget_player(
    player: dict[str, Any],
    *,
    index: int,
    pitch_slot: str,
    low_confidence: bool,
) -> dict[str, Any]:
    derived = player.get("derived") if isinstance(player.get("derived"), dict) else {}
    availability = player.get("availability") if isinstance(player.get("availability"), dict) else {}
    status = availability.get("status") or "available"
    risk_flags = []
    if status in {"doubtful", "injured", "suspended"}:
        risk_flags.append(status)
    if low_confidence:
        risk_flags.append("low_confidence")
    role = _player_role_label(player, derived)
    key_attributes = {
        key: _rounded_number(derived.get(key))
        for key in ("pace", "passing", "stamina", "finishing", "defense", "gk")
        if derived.get(key) is not None
    }
    return {
        "name": player.get("name") or player.get("full_name") or player.get("name_zh") or player.get("name_en") or "资料未明确",
        "number": player.get("shirt_number"),
        "position": _player_position(player) or "资料未明确",
        "role": role,
        "availability": status,
        "rating": _rounded_number((player.get("ratings") or {}).get("rating") if isinstance(player.get("ratings"), dict) else None),
        "overall": _rounded_number(derived.get("overall")),
        "key_attributes": key_attributes,
        "is_captain": bool((player.get("metadata") or player.get("player_metadata") or {}).get("is_captain")) if isinstance(player.get("metadata") or player.get("player_metadata") or {}, dict) else False,
        "risk_flags": list(dict.fromkeys(risk_flags)),
        "pitch_slot": pitch_slot,
        "expected_role": player.get("expected_role"),
        "expected_minutes_share": _rounded_number(player.get("expected_minutes_share"), digits=2),
        "data_confidence": "low" if low_confidence else "medium",
        "source": "Step2 球员名册",
    }


def _resolve_widget_formation(
    formation: Any,
    *,
    metadata: dict[str, Any],
    starters: list[dict[str, Any]],
) -> tuple[str, str]:
    explicit = str(formation or metadata.get("formation_primary") or "").strip()
    if explicit:
        return explicit, "explicit"
    inferred = _infer_formation_from_players(starters)
    if inferred:
        return inferred, "inferred"
    return "资料未明确", "unknown"


def _infer_formation_from_players(players: list[dict[str, Any]]) -> str:
    if not players:
        return ""
    counts = {"DF": 0, "MF": 0, "FW": 0}
    for player in players:
        group = _position_group(_player_position(player))
        if group in counts:
            counts[group] += 1
    if counts["DF"] and counts["MF"] and counts["FW"]:
        return f"{counts['DF']}-{counts['MF']}-{counts['FW']}"
    return ""


def _formation_slots(formation: str, starters: list[dict[str, Any]]) -> list[str]:
    grouped_slots = _formation_slot_groups(formation)
    if grouped_slots:
        return _formation_slots_by_position(starters, grouped_slots)
    fallback = {
        "GK": ["GK"],
        "DF": ["LB", "LCB", "CB", "RCB", "RB"],
        "MF": ["LDM", "LCM", "CM", "RCM", "AM"],
        "FW": ["LW", "ST", "RW"],
    }
    return _formation_slots_by_position(starters, fallback)


def _formation_slot_groups(formation: Any) -> dict[str, list[str]]:
    slot_map = {
        "4-3-3": {"GK": ["GK"], "DF": ["LB", "LCB", "RCB", "RB"], "MF": ["LCM", "CM", "RCM"], "FW": ["LW", "ST", "RW"]},
        "4-2-3-1": {"GK": ["GK"], "DF": ["LB", "LCB", "RCB", "RB"], "MF": ["LDM", "RDM"], "FW": ["LAM", "CAM", "RAM", "ST"]},
        "4-4-2": {"GK": ["GK"], "DF": ["LB", "LCB", "RCB", "RB"], "MF": ["LM", "LCM", "RCM", "RM"], "FW": ["LST", "RST"]},
        "3-4-3": {"GK": ["GK"], "DF": ["LCB", "CB", "RCB"], "MF": ["LM", "LCM", "RCM", "RM"], "FW": ["LW", "ST", "RW"]},
        "3-4-2-1": {"GK": ["GK"], "DF": ["LCB", "CB", "RCB"], "MF": ["LM", "LCM", "RCM", "RM"], "FW": ["LAM", "RAM", "ST"]},
        "3-5-2": {"GK": ["GK"], "DF": ["LCB", "CB", "RCB"], "MF": ["LWB", "LCM", "CM", "RCM", "RWB"], "FW": ["LST", "RST"]},
        "5-3-2": {"GK": ["GK"], "DF": ["LWB", "LCB", "CB", "RCB", "RWB"], "MF": ["LCM", "CM", "RCM"], "FW": ["LST", "RST"]},
        "4-3-1-2": {"GK": ["GK"], "DF": ["LB", "LCB", "RCB", "RB"], "MF": ["LCM", "DM", "RCM", "AM"], "FW": ["LST", "RST"]},
    }
    return slot_map.get(_normalize_formation(formation), {})


def _formation_slots_by_position(starters: list[dict[str, Any]], grouped_slots: dict[str, list[str]]) -> list[str]:
    used: set[str] = set()
    slots = []
    for player in starters[:11]:
        position = _player_position(player)
        group = _position_group(position)
        choices = _slot_preferences_for_position(position, grouped_slots)
        slot = next((choice for choice in choices if choice not in used), choices[-1] if choices else "CM")
        used.add(slot)
        slots.append(slot)
    return slots


def _slot_preferences_for_position(position: str, grouped_slots: dict[str, list[str]]) -> list[str]:
    pos = str(position or "").upper()
    group = _position_group(pos)
    primary = list(grouped_slots.get(group) or grouped_slots.get("MF") or ["CM"])
    extras = {
        "GK": ["GK"],
        "DF": ["LB", "LCB", "CB", "RCB", "RB", "LWB", "RWB"],
        "MF": ["LDM", "LCM", "CM", "RCM", "RDM", "LAM", "CAM", "RAM", "LM", "RM", "AM", "DM"],
        "FW": ["LW", "LST", "ST", "RST", "RW", "LAM", "CAM", "RAM", "LM", "RM"],
    }
    by_position = {
        "GK": ["GK"],
        "CB": ["CB", "LCB", "RCB", "LB", "RB"],
        "LB": ["LB", "LWB", "LCB", "LM"],
        "RB": ["RB", "RWB", "RCB", "RM"],
        "LWB": ["LWB", "LB", "LM", "LCB"],
        "RWB": ["RWB", "RB", "RM", "RCB"],
        "FB": ["LB", "RB", "LWB", "RWB", "LCB", "RCB"],
        "DF": ["LCB", "CB", "RCB", "LB", "RB"],
        "DM": ["LDM", "RDM", "DM", "LCM", "RCM", "CM"],
        "CM": ["CM", "LCM", "RCM", "LDM", "RDM"],
        "AM": ["CAM", "AM", "LAM", "RAM", "LCM", "RCM", "LM", "RM"],
        "LM": ["LM", "LAM", "LCM", "LWB"],
        "RM": ["RM", "RAM", "RCM", "RWB"],
        "MF": ["CM", "LCM", "RCM", "LDM", "RDM", "CAM"],
        "ST": ["ST", "CAM", "LST", "RST", "LAM", "RAM"],
        "CF": ["ST", "LST", "RST", "CAM"],
        "FW": ["ST", "LW", "RW", "LST", "RST"],
        "LW": ["LW", "LAM", "LM", "LST"],
        "RW": ["RW", "RAM", "RM", "RST"],
        "WG": ["LW", "RW", "LAM", "RAM", "LM", "RM"],
    }
    position_preferences = by_position.get(pos) or extras.get(group, ["CM"])
    constrained = [slot for slot in position_preferences if slot in primary]
    overflow = [slot for slot in position_preferences if slot not in constrained]
    group_extras = [slot for slot in extras.get(group, []) if slot not in constrained and slot not in overflow]
    return constrained + [slot for slot in primary if slot not in constrained] + overflow + group_extras


def _normalize_formation(value: Any) -> str:
    text = str(value or "").strip()
    match = re.search(r"\d-\d-\d(?:-\d)?", text)
    return match.group(0) if match else text


def _player_position(player: dict[str, Any]) -> str:
    return str(player.get("position_primary") or player.get("position") or player.get("position_class") or "").upper()


def _position_group(position: str) -> str:
    pos = str(position or "").upper()
    if pos == "GK":
        return "GK"
    if pos in {"CB", "LB", "RB", "FB", "WB", "LWB", "RWB", "DF"}:
        return "DF"
    if pos in {"DM", "CM", "AM", "LM", "RM", "MF"}:
        return "MF"
    if pos in {"ST", "CF", "FW", "WG", "LW", "RW"}:
        return "FW"
    return "MF"


def _position_sort_key(position: str) -> int:
    order = {"GK": 0, "DF": 1, "MF": 2, "FW": 3}
    return order.get(_position_group(position), 2)


def _player_role_label(player: dict[str, Any], derived: dict[str, Any]) -> str:
    position = _player_position(player)
    if position == "GK":
        return "门线守护"
    metrics = [
        ("组织核心", derived.get("passing")),
        ("终结点", derived.get("finishing")),
        ("防守屏障", derived.get("defense")),
        ("边路冲击", derived.get("pace")),
        ("定位球点", derived.get("set_piece")),
    ]
    values = [(label, _coerce_float(value, -1)) for label, value in metrics if value is not None]
    if not values:
        role = str(player.get("expected_role") or "").strip()
        return "首发球员" if role == "starter" else role or "资料未明确"
    return max(values, key=lambda item: item[1])[0]


def _rounded_number(value: Any, *, digits: int = 1) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def _tactics_widget_team(
    *,
    role: str,
    lineup: dict[str, Any],
    metadata: dict[str, Any],
    tactical_notes: Any,
    coach_discussions: list[PredictionCoachDiscussionRecord],
    team_strengths: list[dict[str, Any]],
) -> dict[str, Any]:
    strengths = _strengths_by_role(team_strengths)
    row = strengths.get(role) or {}
    notes = _tactical_notes_for_team(tactical_notes, metadata)
    discussion = _coach_discussion_summary(coach_discussions)
    style = metadata.get("tactical_style") if isinstance(metadata.get("tactical_style"), dict) else {}
    attack = _plan_text(
        style,
        keys=("attacking_plan", "attack", "in_possession", "style"),
        fallback=_strength_plan(row, "attack_rating", "进攻端依靠整体推进和定位球寻找机会"),
    )
    defense = _plan_text(
        style,
        keys=("defensive_plan", "defense", "out_of_possession"),
        fallback=_strength_plan(row, "defense_rating", "防守端重点保持阵型距离和禁区保护"),
    )
    transition = _plan_text(
        style,
        keys=("transition_plan", "transition"),
        fallback=_strength_plan(row, "transition_rating", "由中场抢断后快速向前推进"),
    )
    set_piece = _plan_text(
        style,
        keys=("set_piece_plan", "set_piece"),
        fallback=_strength_plan(row, "set_piece_rating", "定位球是补充得分手段"),
    )
    weakness = _weakness_text(row)
    if notes:
        attack = f"{attack}；材料提示：{_truncate_text(notes[0], 80)}"
    if discussion and attack == "资料未明确":
        attack = _truncate_text(discussion, 110)
    return {
        "coach": metadata.get("head_coach") or "资料未明确",
        "base_shape": lineup.get("formation") or "资料未明确",
        "attacking_plan": attack or "资料未明确",
        "defensive_plan": defense or "资料未明确",
        "transition_plan": transition or "资料未明确",
        "set_piece_plan": set_piece or "资料未明确",
        "weakness": weakness,
        "confidence": lineup.get("confidence"),
        "evidence": "Step1 战术 notes；Step2 球队 metadata、球队强度和教练讨论",
    }


def _tactical_notes_for_team(items: Any, metadata: dict[str, Any]) -> list[str]:
    notes = _compact_tactical_notes(items)
    iso = str(metadata.get("team_iso3") or "").upper()
    result = []
    for item in notes:
        item_iso = str(item.get("team_iso3") or "").upper()
        if iso and item_iso and item_iso != iso:
            continue
        note = str(item.get("note") or "").strip()
        if note:
            result.append(note)
    return result[:3]


def _coach_discussion_summary(rows: list[PredictionCoachDiscussionRecord]) -> str:
    for row in rows[:5]:
        text = str(row.summary or "").strip()
        if text and not _looks_internal_report_note(str(row.topic or "") + " " + text):
            return text
    return ""


def _plan_text(style: dict[str, Any], *, keys: tuple[str, ...], fallback: str) -> str:
    for key in keys:
        value = style.get(key)
        if isinstance(value, list):
            text = "；".join(str(item) for item in value[:2] if str(item or "").strip())
        elif isinstance(value, dict):
            text = "；".join(f"{k}: {v}" for k, v in list(value.items())[:2] if str(v or "").strip())
        else:
            text = str(value or "").strip()
        if text:
            return text
    return fallback


def _strength_plan(row: dict[str, Any], key: str, fallback: str) -> str:
    value = row.get(key)
    if value is None:
        return fallback
    numeric = _coerce_float(value, 0)
    if numeric >= 74:
        return f"{fallback}，该项评分 {numeric:g}，属于相对强点"
    if numeric <= 62:
        return f"{fallback}，但该项评分 {numeric:g}，需要保守处理"
    return f"{fallback}，该项评分 {numeric:g}"


def _weakness_text(row: dict[str, Any]) -> str:
    candidates = [
        ("进攻效率", row.get("attack_rating")),
        ("防线稳定", row.get("defense_rating")),
        ("转换速度", row.get("transition_rating")),
        ("定位球", row.get("set_piece_rating")),
        ("纪律性", row.get("discipline_rating")),
        ("体能", row.get("fitness_rating")),
        ("门将环节", row.get("goalkeeper_rating")),
    ]
    values = [(label, _coerce_float(value, 999)) for label, value in candidates if value is not None]
    if not values:
        return "资料未明确"
    label, value = min(values, key=lambda item: item[1])
    return f"{label}相对薄弱，评分 {value:g}，这意味着该环节更容易被针对"


def _matchup_widget(lineup_widget: dict[str, Any], team_strengths: list[dict[str, Any]]) -> list[dict[str, Any]]:
    home_players = lineup_widget.get("home", {}).get("players") or []
    away_players = lineup_widget.get("away", {}).get("players") or []
    pair_specs = [
        ("左路", ("LB", "LWB", "LW", "LM"), ("RW", "RM", "RB", "RWB"), "决定右路反击和传中能否打穿"),
        ("中路", ("CM", "DM", "AM", "ST"), ("CM", "DM", "CB", "AM"), "决定控球推进和禁区前沿保护"),
        ("右路", ("RB", "RWB", "RW", "RM"), ("LW", "LM", "LB", "LWB"), "决定边路速度和身后空间"),
    ]
    strengths = _strengths_by_role(team_strengths)
    rows = []
    for zone, home_slots, away_slots, why in pair_specs:
        home_player = _pick_slot_player(home_players, home_slots)
        away_player = _pick_slot_player(away_players, away_slots)
        if not home_player and not away_player:
            continue
        rows.append(
            {
                "zone": zone,
                "home_player": (home_player or {}).get("name") or "资料未明确",
                "away_player": (away_player or {}).get("name") or "资料未明确",
                "why_it_matters": why,
                "advantage": _matchup_advantage(zone, strengths),
                "evidence": "Step2 首发、pitch_slot 和球队强度",
            }
        )
    if rows:
        return rows
    return [
        {
            "zone": "整体",
            "home_player": "资料未明确",
            "away_player": "资料未明确",
            "why_it_matters": "首发资料不足，暂时只能看整体强度差",
            "advantage": "even",
            "evidence": "Step2 球队强度",
        }
    ]


def _pick_slot_player(players: list[dict[str, Any]], slots: tuple[str, ...]) -> dict[str, Any] | None:
    slot_set = set(slots)
    for player in players:
        if str(player.get("pitch_slot") or "").upper() in slot_set:
            return player
    for player in players:
        if str(player.get("position") or "").upper() in slot_set:
            return player
    return players[0] if players else None


def _matchup_advantage(zone: str, strengths: dict[str, dict[str, Any]]) -> str:
    key = "transition_rating" if zone in {"左路", "右路"} else "possession_rating"
    home = _coerce_float((strengths.get("home") or {}).get(key), -999)
    away = _coerce_float((strengths.get("away") or {}).get(key), -999)
    if home < -900 or away < -900 or abs(home - away) < 3:
        return "even"
    return "home" if home > away else "away"


def _report_widgets_markdown(widgets: dict[str, Any]) -> dict[str, str]:
    lineup = widgets.get("lineup_widget") or {}
    tactics = widgets.get("tactics_widget") or {}
    matchups = widgets.get("matchup_widget") or []
    return {
        "formation_table": _widget_formation_markdown(lineup, tactics),
        "lineup_table": _widget_lineup_markdown(lineup),
        "tactics_table": _widget_tactics_markdown(lineup, tactics),
        "matchup_table": _widget_matchups_markdown(matchups),
        "uncertainty_text": _widget_uncertainty_text(lineup),
    }


def _widget_formation_markdown(lineup: dict[str, Any], tactics: dict[str, Any]) -> str:
    rows = []
    for role in ("home", "away"):
        team = lineup.get(role) or {}
        plan = tactics.get(role) or {}
        rows.append(
            [
                team.get("team") or ("主队" if role == "home" else "客队"),
                team.get("formation") or "资料未明确",
                plan.get("attacking_plan") or "资料未明确",
                plan.get("defensive_plan") or "资料未明确",
                _confidence_level(team.get("confidence")),
            ]
        )
    return _markdown_table(["球队", "预计阵型", "进攻重点", "防守重点", "可信度"], rows)


def _widget_lineup_markdown(lineup: dict[str, Any]) -> str:
    rows = []
    for role in ("home", "away"):
        team = lineup.get(role) or {}
        for player in (team.get("players") or [])[:11]:
            rows.append(
                [
                    team.get("team") or ("主队" if role == "home" else "客队"),
                    player.get("number") or "--",
                    player.get("name") or "资料未明确",
                    player.get("position") or "资料未明确",
                    player.get("role") or "资料未明确",
                    _availability_label(player.get("availability")),
                    _rating_or_overall(player),
                ]
            )
    return _markdown_table(["球队", "号码", "球员", "位置", "角色", "状态", "评分/能力"], rows)


def _widget_tactics_markdown(lineup: dict[str, Any], tactics: dict[str, Any]) -> str:
    rows = []
    for role in ("home", "away"):
        team = lineup.get(role) or {}
        plan = tactics.get(role) or {}
        rows.append(
            [
                team.get("team") or ("主队" if role == "home" else "客队"),
                plan.get("coach") or "资料未明确",
                plan.get("base_shape") or team.get("formation") or "资料未明确",
                plan.get("transition_plan") or "资料未明确",
                plan.get("set_piece_plan") or "资料未明确",
                plan.get("weakness") or "资料未明确",
            ]
        )
    return _markdown_table(["球队", "主教练", "基础站位", "转换思路", "定位球", "弱点"], rows)


def _widget_matchups_markdown(matchups: list[dict[str, Any]]) -> str:
    rows = [
        [
            f"{item.get('home_player') or '资料未明确'} vs {item.get('away_player') or '资料未明确'}",
            item.get("zone") or "资料未明确",
            _advantage_label(item.get("advantage")),
            item.get("why_it_matters") or "资料未明确",
        ]
        for item in matchups[:5]
        if isinstance(item, dict)
    ]
    return _markdown_table(["关键对位", "区域", "优势方", "影响"], rows)


def _widget_uncertainty_text(lineup: dict[str, Any]) -> str:
    notes = []
    for role in ("home", "away"):
        team = lineup.get(role) or {}
        note = str(team.get("notes") or "").strip()
        if note:
            notes.append(f"{team.get('team') or role}: {note}")
    return "；".join(notes) or "预计首发和阵型来自 Step2 数据库快照，仍需赛前官方名单确认。"


def _confidence_level(value: Any) -> str:
    numeric = _coerce_float(value, -1)
    if numeric < 0:
        return "资料未明确"
    if numeric >= 0.75:
        return "高"
    if numeric >= 0.55:
        return "中"
    return "低"


def _rating_or_overall(player: dict[str, Any]) -> str:
    rating = player.get("rating")
    overall = player.get("overall")
    if rating is not None:
        return f"{_coerce_float(rating, 0):.1f}"
    if overall is not None:
        return f"{_coerce_float(overall, 0):.1f}"
    return "--"


def _advantage_label(value: Any) -> str:
    return {"home": "主队", "away": "客队", "even": "接近"}.get(str(value or ""), "资料未明确")


def _ordered_strength_rows(
    run: PredictionRunRecord,
    config: PredictionConfigRecord | None,
) -> list[PredictionTeamStrengthRecord]:
    with get_session() as session:
        rows = (
            session.query(PredictionTeamStrengthRecord)
            .filter_by(prediction_run_id=run.prediction_run_id)
            .order_by(PredictionTeamStrengthRecord.team_role.asc())
            .all()
        )
        if rows:
            return rows
        if config:
            return (
                session.query(PredictionTeamStrengthRecord)
                .filter_by(prediction_config_id=config.prediction_config_id)
                .order_by(PredictionTeamStrengthRecord.team_role.asc())
                .all()
            )
    return []


def _scoreline_brief(row: PredictionScorelineRecord) -> dict[str, Any]:
    return {
        "scenario_space": row.scenario_space,
        "scenario_label": _scenario_space_label(row.scenario_space or "unknown"),
        "most_likely_score": row.most_likely_score,
        "xg": f"{row.home_xg / 100:.2f}-{row.away_xg / 100:.2f}",
        "home_win_probability": row.home_win_probability,
        "draw_probability": row.draw_probability,
        "away_win_probability": row.away_win_probability,
    }


def _scenario_space_brief(row: PredictionScenarioSpaceRecord) -> dict[str, Any]:
    return {
        "space_name": row.space_name,
        "weight": row.weight,
        "summary": row.summary,
        "key_drivers": row.key_drivers or [],
        "risk_factors": row.risk_factors or [],
    }


def _scenario_case_brief(row: PredictionScenarioCaseRecord) -> dict[str, Any]:
    xg = row.expected_goals or {}
    probs = row.win_draw_loss_probability or {}
    return {
        "scenario": _scenario_key_label((row.case_metadata or {}).get("scenario_key") or row.id, row.home_state, row.away_state),
        "module": row.scenario_module,
        "space": row.scenario_space,
        "weight": row.weight,
        "xg": f"{_format_xg_value(xg.get('home'))}-{_format_xg_value(xg.get('away'))}",
        "probability": {
            "home_win": _format_probability(probs.get("home_win")),
            "draw": _format_probability(probs.get("draw")),
            "away_win": _format_probability(probs.get("away_win")),
        },
    }


def _select_report_events(events: list[PredictionMatchEventRecord]) -> list[PredictionMatchEventRecord]:
    baseline = [
        event for event in events
        if (event.event_metadata or {}).get("scenario_key") == "home_normal_away_normal"
    ]
    key_types = {"GOAL", "CHANCE_CREATED", "SHOT", "SAVE", "YELLOW_CARD", "VAR_CHECK", "SUBSTITUTION", "PRESSURE_SHIFT", "FINAL_SCORE_HYPOTHESIS"}
    selected = [event for event in baseline if event.event_type in key_types] or [event for event in events if event.event_type in key_types]
    return selected[:14] or events[:10]


def _event_brief(row: PredictionMatchEventRecord) -> dict[str, Any]:
    return {
        "minute": row.minute,
        "event_type": row.event_type,
        "event_label": _event_type_label(row.event_type),
        "team": row.team,
        "player": row.player,
        "score": row.score,
        "scenario_space": row.scenario_space,
        "description": row.description,
    }


def _note_brief(row: PredictionAnalystNoteRecord) -> dict[str, Any]:
    return {
        "role": _role_display_name(row.agent_role),
        "scenario_space": row.scenario_space,
        "claim": _humanize_note_claim(row.claim),
        "reasoning": row.reasoning,
        "confidence": row.confidence,
    }


def _project_report_snapshot(project_id: str | None) -> dict[str, Any]:
    if not project_id:
        return {}
    with get_session() as session:
        project = session.get(ProjectRecord, project_id)
        if not project:
            return {}
        files = project.files or []
        return {
            "project_id": project.project_id,
            "name": project.name,
            "files_count": len(files),
            "files": [
                {
                    "filename": item.get("filename") or item.get("name") or f"材料{index + 1}",
                    "size_bytes": item.get("size_bytes") or item.get("size"),
                    "mime_type": item.get("mime_type") or item.get("type"),
                }
                for index, item in enumerate(files[:8])
                if isinstance(item, dict)
            ],
            "total_text_length": project.total_text_length,
            "analysis_summary": _truncate_text(project.analysis_summary, 500),
        }


def _source_documents_snapshot(
    run: PredictionRunRecord,
    config: PredictionConfigRecord | None,
    project_snapshot: dict[str, Any],
) -> list[dict[str, Any]]:
    with get_session() as session:
        rows = (
            session.query(PredictionSourceDocumentRecord)
            .filter(PredictionSourceDocumentRecord.project_id == run.project_id)
            .order_by(PredictionSourceDocumentRecord.created_at.asc())
            .limit(12)
            .all()
        )
        documents = [
            {
                "filename": row.filename or "未命名材料",
                "mime_type": row.mime_type,
                "size_bytes": row.size_bytes,
                "parse_status": row.parse_status,
            }
            for row in rows
        ]
    if documents:
        return documents
    files = project_snapshot.get("files") if isinstance(project_snapshot, dict) else []
    if isinstance(files, list) and files:
        return files
    ids = config.source_document_ids if config and isinstance(config.source_document_ids, list) else []
    return [{"filename": str(item), "parse_status": "资料未明确"} for item in ids[:8]]


def _graph_binding_edge_count(run: PredictionRunRecord) -> int:
    if not run.graph_id:
        return 0
    with get_session() as session:
        row = (
            session.query(GraphBindingRecord)
            .filter_by(graph_id=run.graph_id)
            .order_by(GraphBindingRecord.updated_at.desc(), GraphBindingRecord.created_at.desc())
            .first()
        )
        return int(row.edge_count or 0) if row else 0


def _team_metadata_summary(
    *,
    config: PredictionConfigRecord | None,
    dataset: PredictionPlayerDatasetRecord | None,
    squads: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if not dataset:
        return {"home": {}, "away": {}}
    refs = {
        "home": _team_ref(squads.get("home") if isinstance(squads.get("home"), dict) else {}, config.home_team if config else None),
        "away": _team_ref(squads.get("away") if isinstance(squads.get("away"), dict) else {}, config.away_team if config else None),
    }
    result: dict[str, dict[str, Any]] = {"home": {}, "away": {}}
    with get_session() as session:
        for role, ref in refs.items():
            query = session.query(PredictionTeamMetadataRecord).filter_by(dataset_id=dataset.dataset_id)
            if ref.get("iso3"):
                query = query.filter_by(team_iso3=ref["iso3"])
            elif ref.get("name"):
                query = query.filter_by(team_fifa=ref["name"])
            else:
                continue
            row = query.first()
            if row:
                result[role] = {
                    "team_fifa": row.team_fifa,
                    "team_iso3": row.team_iso3,
                    "team_zh": row.team_zh,
                    "head_coach": row.head_coach,
                    "formation_primary": row.formation_primary,
                    "formation_secondary": row.formation_secondary or [],
                    "tactical_style": row.tactical_style or {},
                    "key_player_ids": row.key_player_ids or [],
                    "squad_status": row.squad_status,
                }
    return result


def _team_ranking_summary(
    *,
    config: PredictionConfigRecord | None,
    squads: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    refs = {
        "home": _team_ref(squads.get("home") if isinstance(squads.get("home"), dict) else {}, config.home_team if config else None),
        "away": _team_ref(squads.get("away") if isinstance(squads.get("away"), dict) else {}, config.away_team if config else None),
    }
    result = {
        role: {"fifa_rank": None, "fifa_points": None, "elo_rank": None, "elo_rating": None}
        for role in ("home", "away")
    }
    try:
        df = NationalElo().as_dataframe(offline=True)
        by_iso = {
            str(row.team_iso3): {"elo_rank": int(row.rank), "elo_rating": round(float(row.elo_rating), 1)}
            for row in df.itertuples(index=False)
        }
    except Exception:
        by_iso = {}
    for role, ref in refs.items():
        iso3 = str(ref.get("iso3") or "").upper()
        if iso3 in by_iso:
            result[role].update(by_iso[iso3])
    return result


def _player_attributes_summary(squads: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {"home": [], "away": []}
    for role in ("home", "away"):
        team = squads.get(role) if isinstance(squads.get(role), dict) else {}
        players = team.get("players") if isinstance(team.get("players"), list) else []
        ranked = sorted(
            [player for player in players if isinstance(player, dict)],
            key=lambda item: (
                float((item.get("derived") or {}).get("overall") or 0),
                float(item.get("expected_minutes_share") or 0),
            ),
            reverse=True,
        )
        result[role] = [
            {
                "name": player.get("name") or player.get("full_name") or player.get("name_en"),
                "position": player.get("position_primary") or player.get("position_class"),
                "overall": (player.get("derived") or {}).get("overall"),
                "attack": (player.get("derived") or {}).get("attack"),
                "defense": (player.get("derived") or {}).get("defense"),
                "finishing": (player.get("derived") or {}).get("finishing"),
                "passing": (player.get("derived") or {}).get("passing"),
                "availability": (player.get("availability") or {}).get("status"),
                "expected_role": player.get("expected_role"),
            }
            for player in ranked[:6]
        ]
    return result


def _scenario_design_rows(summary: Any, scenario_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matrix = summary.get("matrix") if isinstance(summary, dict) else []
    rows = matrix if isinstance(matrix, list) and matrix else scenario_cases
    result: list[dict[str, Any]] = []
    for item in rows[:9]:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "scenario": item.get("scenario_name") or item.get("scenario") or item.get("module") or "资料未明确",
                "space": item.get("scenario_space") or item.get("space") or "资料未明确",
                "weight": item.get("final_weight") or item.get("weight") or item.get("initial_weight") or "资料未明确",
                "drivers": item.get("key_drivers") or item.get("risk_factors") or [],
            }
        )
    return result


def _budget_or_degradation_summary(
    run: PredictionRunRecord,
    config: PredictionConfigRecord | None,
    result: PredictionResultRecord | None,
) -> dict[str, Any]:
    ledger = _merged_ledger_summary(run, config, result)
    profile = _report_budget_profile(run, config)
    return {
        "budget_profile": profile.get("profile_key") or "custom",
        "hard_cap_calls": profile.get("hard_cap_calls"),
        "total_calls": ledger.get("total_calls"),
        "failures": ledger.get("failures") or [],
        "warnings": _warning_items(run=run, config=config, result=result),
    }


def _weighted_xg_summary(
    scorelines: list[PredictionScorelineRecord],
    cases: list[PredictionScenarioCaseRecord],
) -> dict[str, Any]:
    if not scorelines:
        return {"home": None, "away": None}
    case_weights = {
        row.id: max(0.0, _coerce_float(row.weight, 0.0))
        for row in cases
    }
    total_weight = 0.0
    home_total = 0.0
    away_total = 0.0
    for row in scorelines:
        weight = case_weights.get(str(row.scenario_case_id or ""), 0.0)
        if weight <= 0:
            weight = 1.0
        total_weight += weight
        home_total += weight * (row.home_xg / 100)
        away_total += weight * (row.away_xg / 100)
    if total_weight <= 0:
        return {"home": None, "away": None}
    return {
        "home": round(home_total / total_weight, 2),
        "away": round(away_total / total_weight, 2),
    }


def _top_score_candidates(summary: dict[str, Any], scorelines: list[PredictionScorelineRecord]) -> list[dict[str, Any]]:
    candidates = summary.get("top_score_candidates") if isinstance(summary.get("top_score_candidates"), list) else []
    if candidates:
        return [
            {"score": item.get("score"), "probability": item.get("probability")}
            for item in candidates[:5]
            if isinstance(item, dict)
        ]
    distribution: dict[str, float] = {}
    for row in scorelines:
        for item in row.scoreline_distribution or []:
            if not isinstance(item, dict) or not item.get("score"):
                continue
            distribution[str(item["score"])] = distribution.get(str(item["score"]), 0.0) + _coerce_float(item.get("probability"), 0.0)
    total = sum(distribution.values()) or 1.0
    return [
        {"score": score, "probability": probability / total}
        for score, probability in sorted(distribution.items(), key=lambda item: (-item[1], item[0]))[:5]
    ]


def _event_timeline_buckets(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets = [
        ("0-30", 0, 30),
        ("31-60", 31, 60),
        ("61-75", 61, 75),
        ("76-90+", 76, 130),
    ]
    result: list[dict[str, Any]] = []
    for label, start, end in buckets:
        bucket_events = [
            item for item in events
            if start <= _coerce_int(item.get("minute"), -1) <= end
        ]
        selected = bucket_events[:2]
        event_text = "；".join(
            f"{item.get('minute')}'{item.get('event_label') or _event_type_label(item.get('event_type') or '')}: {_sanitize_event_description(item.get('description'))}"
            for item in selected
        ) or "资料未明确"
        scores = [str(item.get("score")) for item in selected if item.get("score")]
        result.append(
            {
                "period": label,
                "trigger": _timeline_trigger(label, selected),
                "event": event_text,
                "score_impact": "、".join(scores) if scores else "可能改变节奏，比分影响待确认",
            }
        )
    return result


def _timeline_trigger(label: str, events: list[dict[str, Any]]) -> str:
    if events:
        types = "、".join(item.get("event_label") or _event_type_label(item.get("event_type") or "") for item in events[:2])
        return f"Step3 事件链出现{types}"
    defaults = {
        "0-30": "开局压迫和第一次定位球",
        "31-60": "中场前后节奏变化",
        "61-75": "换人和体能下降",
        "76-90+": "追分、保守或VAR/牌风险",
    }
    return defaults.get(label, "比赛节奏变化")


def _has_markdown_visual(text: str) -> bool:
    return bool(re.search(r"(?m)^\|.+\|\s*$", text or "")) or "█" in (text or "")


def _section_visual_block(title: str, context: dict[str, Any]) -> str:
    if title == "比赛结论摘要":
        return _summary_dashboard(context)
    if title == "双方基本面与图谱证据":
        return _fundamentals_dashboard(context)
    if title == "战术、阵型与预计首发":
        return _tactics_dashboard(context)
    if title == "胜平负与比分预测":
        return _score_prediction_dashboard(context)
    if title == "关键比赛事件剧本":
        return _events_dashboard(context)
    if title == "风险、不确定性与可信度说明":
        return _risk_dashboard(context)
    return _markdown_table(["项目", "数据"], [["资料", "资料未明确"]])


def _summary_dashboard(context: dict[str, Any]) -> str:
    match = context.get("match") or {}
    step3 = context.get("step3") or {}
    score = step3.get("scoreline_summary") or {}
    probabilities = score.get("win_draw_loss_probability") or {}
    home = match.get("home_team") or "主队"
    away = match.get("away_team") or "客队"
    verdict = _wdl_verdict(probabilities, home, away)
    most_likely = score.get("most_likely_score") or "资料未明确"
    confidence = step3.get("confidence")
    rows = [
        ["首选方向", verdict, _summary_reason(context, 0)],
        ["最可能比分", most_likely, _top_score_reason(context)],
        ["置信度", _format_probability(confidence), _confidence_reason(context)],
    ]
    return "\n\n".join(
        [
            _markdown_table(["判断", "结果", "关键证据"], rows),
            "**胜平负概率条：**\n" + _wdl_probability_bars(probabilities, home, away),
            "**3 个最关键理由：**\n" + "\n".join(f"- {item}" for item in _key_reasons(context, limit=3)),
        ]
    )


def _canonical_summary_section(context: dict[str, Any]) -> str:
    match = context.get("match") or {}
    step3 = context.get("step3") or {}
    score = step3.get("scoreline_summary") or {}
    probabilities = score.get("win_draw_loss_probability") or {}
    home = match.get("home_team") or "主队"
    away = match.get("away_team") or "客队"
    verdict = _wdl_verdict(probabilities, home, away)
    most_likely = score.get("most_likely_score") or "资料未明确"
    return "\n\n".join(
        [
            (
                f"**一句话结论：** 本场首选 **{verdict}**，"
                f"最可能比分是 **{most_likely}**；这不是确定赛果，而是当前证据下的概率倾向。"
            ),
            _summary_dashboard(context),
            (
                "**怎么读：** 先看首选方向，再看主胜/平局/客胜三条概率。"
                "Top 比分如果差距很小，只能说明多个小比分都接近；报告以 Step3 最高概率比分作为“最可能比分”。"
            ),
            (
                "**依据来自：** Step1 图谱实体、关键叙事和伤停；"
                "Step2 球队强度、阵型、预计首发和教练讨论；"
                "Step3 胜平负概率、Top 比分、xG、事件链和不确定因素。"
            ),
        ]
    )


def _fundamentals_dashboard(context: dict[str, Any]) -> str:
    return "\n\n".join(
        [
            "**基本面对比：**\n" + _basic_comparison_table(context),
            "**伤停/可用性：**\n" + _availability_table(context),
            "**图谱关键实体：**\n" + _key_entities_table(context),
            "**外部来源：**\n" + _external_sources_table(context),
        ]
    )


def _tactics_dashboard(context: dict[str, Any]) -> str:
    markdown_widgets = context.get("markdown_widgets") or {}
    if markdown_widgets:
        return "\n\n".join(
            [
                "**阵型预测摘要：**\n" + (markdown_widgets.get("formation_table") or _formation_table(context)),
                "**首发名单表：**\n" + (markdown_widgets.get("lineup_table") or _lineup_table(context)),
                "**战术判断表：**\n" + (markdown_widgets.get("tactics_table") or _coach_discussion_table(context)),
                "**关键对位表：**\n" + (markdown_widgets.get("matchup_table") or _key_matchups_table(context)),
                "**不确定性说明：** " + (markdown_widgets.get("uncertainty_text") or "预计首发仍需赛前官方名单确认。"),
                "**教练讨论摘要：**\n" + _coach_discussion_table(context),
            ]
        )
    return "\n\n".join(
        [
            "**阵型预测摘要：**\n" + _formation_table(context),
            "**首发名单表：**\n" + _lineup_table(context),
            "**关键球员：**\n" + _key_players_table(context),
            "**关键对位表：**\n" + _key_matchups_table(context),
            "**教练讨论摘要：**\n" + _coach_discussion_table(context),
        ]
    )


def _score_prediction_dashboard(context: dict[str, Any]) -> str:
    match = context.get("match") or {}
    step3 = context.get("step3") or {}
    score = step3.get("scoreline_summary") or {}
    probabilities = score.get("win_draw_loss_probability") or {}
    home = match.get("home_team") or "主队"
    away = match.get("away_team") or "客队"
    return "\n\n".join(
        [
            "**胜平负概率条：**\n" + _wdl_probability_bars(probabilities, home, away),
            "**Top 5 比分候选：**\n" + _top_score_table(context),
            "**xG 对比：**\n" + _xg_table(context),
            "**九场景/六空间：**\n" + _scenario_matrix_text(context),
        ]
    )


def _events_dashboard(context: dict[str, Any]) -> str:
    return "\n\n".join(
        [
            "**时间线：**\n" + _timeline_table(context),
            "**Step3 事件链样本：**\n" + _match_events_table(context),
        ]
    )


def _risk_dashboard(context: dict[str, Any]) -> str:
    return "\n\n".join(
        [
            _risk_table(context),
            "**可信度看板：**\n" + _credibility_table(context),
        ]
    )


def _ensure_tactics_widget_markdown(content: str, context: dict[str, Any]) -> str:
    markdown_widgets = context.get("markdown_widgets") or {}
    if not markdown_widgets:
        return content
    additions = []
    required = [
        ("**阵型预测摘要：**", markdown_widgets.get("formation_table")),
        ("**首发名单表：**", markdown_widgets.get("lineup_table")),
        ("**战术判断表：**", markdown_widgets.get("tactics_table")),
        ("**关键对位表：**", markdown_widgets.get("matchup_table")),
    ]
    for label, table in required:
        if table and label not in content:
            additions.append(f"{label}\n{table}")
    if markdown_widgets.get("uncertainty_text") and "不确定性说明" not in content:
        additions.append(f"**不确定性说明：** {markdown_widgets['uncertainty_text']}")
    if not additions:
        return content
    return content.rstrip() + "\n\n" + "\n\n".join(additions)


def _markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    safe_headers = [_markdown_cell(header) for header in headers]
    if not rows:
        rows = [["资料未明确" for _ in headers]]
    normalized_rows: list[list[str]] = []
    for row in rows:
        cells = list(row[: len(headers)])
        if len(cells) < len(headers):
            cells.extend(["资料未明确"] * (len(headers) - len(cells)))
        normalized_rows.append([_markdown_cell(cell) for cell in cells])
    lines = [
        "| " + " | ".join(safe_headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in normalized_rows)
    return "\n".join(lines)


def _markdown_cell(value: Any) -> str:
    text = str(value if value is not None and value != "" else "资料未明确")
    text = text.replace("|", "/").replace("\n", " ").strip()
    return text or "资料未明确"


def _probability_bar(value: Any) -> str:
    numeric = _coerce_float(value, -1.0)
    if numeric < 0:
        return "`░░░░░░░░░░` 资料未明确"
    if numeric <= 1:
        numeric *= 100
    numeric = max(0.0, min(100.0, numeric))
    filled = int(round(numeric / 10))
    filled = max(0, min(10, filled))
    return f"`{'█' * filled}{'░' * (10 - filled)}` {numeric:.0f}%"


def _wdl_probability_bars(probabilities: dict[str, Any], home: str, away: str) -> str:
    return "\n".join(
        [
            f"- {home}胜 {_probability_bar(probabilities.get('home_win'))}",
            f"- 平局 {_probability_bar(probabilities.get('draw'))}",
            f"- {away}胜 {_probability_bar(probabilities.get('away_win'))}",
        ]
    )


def _basic_comparison_table(context: dict[str, Any]) -> str:
    match = context.get("match") or {}
    home = match.get("home_team") or "主队"
    away = match.get("away_team") or "客队"
    step1 = context.get("step1") or {}
    step2 = context.get("step2") or {}
    rankings = step2.get("team_rankings") or {}
    strengths = _strengths_by_role(step2.get("team_strengths") or [])
    home_strength = strengths.get("home") or {}
    away_strength = strengths.get("away") or {}
    home_rank = rankings.get("home") or {}
    away_rank = rankings.get("away") or {}
    rows = [
        ["FIFA排名/积分", _rank_text(home_rank), _rank_text(away_rank), "FIFA字段缺失时不猜，显示资料未明确"],
        ["国家Elo排名/评分", _elo_text(home_rank), _elo_text(away_rank), "Elo可辅助看长期强弱，但不等同于FIFA积分"],
        ["进攻评分", home_strength.get("attack_rating"), away_strength.get("attack_rating"), _leader_note(home, away, home_strength.get("attack_rating"), away_strength.get("attack_rating"), "进攻")],
        ["防守评分", home_strength.get("defense_rating"), away_strength.get("defense_rating"), _leader_note(home, away, home_strength.get("defense_rating"), away_strength.get("defense_rating"), "防守")],
        ["门将评分", home_strength.get("goalkeeper_rating"), away_strength.get("goalkeeper_rating"), _leader_note(home, away, home_strength.get("goalkeeper_rating"), away_strength.get("goalkeeper_rating"), "门将")],
        ["图谱实体/关系", f"{step1.get('graph_entities_count') or 0} / {step1.get('graph_relationships_count') or 0}", "同一图谱", "实体越多，说明赛前材料覆盖面越广"],
    ]
    return _markdown_table(["指标", home, away, "怎么影响比赛"], rows)


def _availability_table(context: dict[str, Any]) -> str:
    match = context.get("match") or {}
    step1 = context.get("step1") or {}
    step2 = context.get("step2") or {}
    availability = step2.get("player_availability") or {}
    rows: list[list[Any]] = []
    for role, label in (("home", match.get("home_team") or "主队"), ("away", match.get("away_team") or "客队")):
        summary = availability.get(role) or {}
        rows.append(
            [
                label,
                _availability_counts(summary),
                _injuries_for_team(step1.get("injury_reports") or [], summary.get("team_iso3")),
                "缺主力会降低进攻效率或防守稳定性",
            ]
        )
    if not rows:
        rows = [["资料未明确", "资料未明确", "资料未明确", "赛前名单未确认"]]
    return _markdown_table(["球队", "可用人数", "伤停线索", "对比分方向的影响"], rows)


def _key_entities_table(context: dict[str, Any]) -> str:
    entities = ((context.get("step1") or {}).get("graph_entities") or [])[:8]
    rows = [
        [
            item.get("name") or "资料未明确",
            _entity_type_text(item.get("type")),
            item.get("summary") or "资料未明确",
        ]
        for item in entities
        if isinstance(item, dict)
    ]
    return _markdown_table(["实体", "类型", "为什么重要"], rows)


def _external_sources_table(context: dict[str, Any]) -> str:
    sources = (context.get("step1") or {}).get("external_sources") or []
    rows = []
    for source in sources[:6]:
        text = str(source).strip().lstrip("- ").strip()
        if not text:
            continue
        name, _, status = text.partition("—")
        rows.append([name.strip(), status.strip() or "已记录", "Step1/Step2 外部数据源快照"])
    return _markdown_table(["来源", "状态", "用途"], rows)


def _formation_table(context: dict[str, Any]) -> str:
    match = context.get("match") or {}
    step2 = context.get("step2") or {}
    formations = step2.get("formations") or {}
    metadata = step2.get("team_metadata") or {}
    availability = step2.get("player_availability") or {}
    rows = []
    for role, label in (("home", match.get("home_team") or "主队"), ("away", match.get("away_team") or "客队")):
        team_meta = metadata.get(role) or {}
        rows.append(
            [
                label,
                formations.get(role) or "资料未明确",
                team_meta.get("head_coach") or "资料未明确",
                _style_text(team_meta.get("tactical_style")),
                _availability_counts(availability.get(role) or {}),
            ]
        )
    return _markdown_table(["球队", "预计阵型", "主教练", "打法标签", "可用性"], rows)


def _lineup_table(context: dict[str, Any]) -> str:
    match = context.get("match") or {}
    lineups = ((context.get("step2") or {}).get("lineups") or {})
    rows: list[list[Any]] = []
    for role, team in (("home", match.get("home_team") or "主队"), ("away", match.get("away_team") or "客队")):
        for player in (lineups.get(role) or [])[:11]:
            rows.append(
                [
                    team,
                    player.get("position") or "资料未明确",
                    player.get("name") or "资料未明确",
                    player.get("overall") if player.get("overall") is not None else "资料未明确",
                    _availability_label(player.get("availability")),
                ]
            )
    return _markdown_table(["球队", "位置", "预计首发/关键球员", "总评", "状态"], rows)


def _key_players_table(context: dict[str, Any]) -> str:
    match = context.get("match") or {}
    attrs = ((context.get("step2") or {}).get("player_attributes") or {})
    rows: list[list[Any]] = []
    for role, team in (("home", match.get("home_team") or "主队"), ("away", match.get("away_team") or "客队")):
        for player in (attrs.get(role) or [])[:5]:
            rows.append(
                [
                    team,
                    player.get("name") or "资料未明确",
                    player.get("position") or "资料未明确",
                    player.get("overall") if player.get("overall") is not None else "资料未明确",
                    _player_strength_tag(player),
                    _availability_label(player.get("availability")),
                ]
            )
    return _markdown_table(["球队", "球员", "位置", "总评", "强项", "状态"], rows)


def _key_matchups_table(context: dict[str, Any]) -> str:
    match = context.get("match") or {}
    home = match.get("home_team") or "主队"
    away = match.get("away_team") or "客队"
    strengths = _strengths_by_role(((context.get("step2") or {}).get("team_strengths") or []))
    home_row = strengths.get("home") or {}
    away_row = strengths.get("away") or {}
    dimensions = [
        ("attack_rating", "进攻 vs 防守"),
        ("transition_rating", "转换速度"),
        ("set_piece_rating", "定位球"),
        ("discipline_rating", "纪律性"),
        ("fitness_rating", "体能"),
        ("goalkeeper_rating", "门将"),
    ]
    rows: list[list[Any]] = []
    for key, label in dimensions:
        h_val = home_row.get(key)
        a_val = away_row.get(key)
        rows.append(
            [
                label,
                f"{home} {h_val if h_val is not None else '资料未明确'}",
                f"{away} {a_val if a_val is not None else '资料未明确'}",
                _leader_note(home, away, h_val, a_val, label),
            ]
        )
    return _markdown_table(["对位", home, away, "这意味着什么"], rows)


def _coach_discussion_table(context: dict[str, Any]) -> str:
    discussions = (context.get("step2") or {}).get("coach_discussions") or []
    rows = []
    for item in discussions:
        topic = str(item.get("topic") or "教练讨论").strip()
        summary = str(item.get("summary") or "").strip()
        if not summary or _looks_internal_report_note(topic + " " + summary):
            continue
        rows.append(
            [
                topic,
                _truncate_text(summary, 180),
                item.get("consensus_score") if item.get("consensus_score") is not None else "资料未明确",
                item.get("disagreement_score") if item.get("disagreement_score") is not None else "资料未明确",
            ]
        )
        if len(rows) >= 4:
            break
    return _markdown_table(["主题", "结论", "共识", "分歧"], rows)


def _top_score_table(context: dict[str, Any]) -> str:
    top_scores = (context.get("step3") or {}).get("top_scores") or []
    rows = [
        [
            index,
            item.get("score") or "资料未明确",
            _format_probability(item.get("probability")),
            _probability_bar(item.get("probability")),
        ]
        for index, item in enumerate(top_scores[:5], start=1)
        if isinstance(item, dict)
    ]
    return _markdown_table(["排名", "比分", "概率", "文本条"], rows)


def _xg_table(context: dict[str, Any]) -> str:
    match = context.get("match") or {}
    xg = (context.get("step3") or {}).get("xg") or {}
    home = match.get("home_team") or "主队"
    away = match.get("away_team") or "客队"
    home_xg = xg.get("home")
    away_xg = xg.get("away")
    rows = [
        [home, _xg_value(home_xg), "预期进球越高，代表机会质量和数量更好"],
        [away, _xg_value(away_xg), "低 xG 也可能靠定位球或远射改变比分"],
        ["差值", _xg_diff(home_xg, away_xg), "差值小，比分更容易落在平局或一球差"],
    ]
    return _markdown_table(["球队", "加权 xG", "怎么读"], rows)


def _scenario_matrix_text(context: dict[str, Any]) -> str:
    step3 = context.get("step3") or {}
    spaces = step3.get("scenario_spaces") or []
    rows = []
    for item in spaces[:6]:
        rows.append(
            [
                item.get("space_name") or "资料未明确",
                item.get("weight") if item.get("weight") is not None else "资料未明确",
                _list_preview(item.get("key_drivers") or [], fallback=item.get("summary") or "资料未明确"),
                _list_preview(item.get("risk_factors") or [], fallback="资料未明确"),
            ]
        )
    if not rows:
        for item in (step3.get("scenario_cases") or [])[:9]:
            rows.append(
                [
                    item.get("scenario") or "资料未明确",
                    item.get("weight") if item.get("weight") is not None else "资料未明确",
                    item.get("xg") or "资料未明确",
                    _probability_dict_text(item.get("probability") or {}),
                ]
            )
    return _markdown_table(["场景/空间", "权重", "关键驱动", "风险或概率"], rows)


def _timeline_table(context: dict[str, Any]) -> str:
    timeline = (context.get("step3") or {}).get("event_timeline") or []
    rows = [
        [
            item.get("period") or "资料未明确",
            item.get("trigger") or "资料未明确",
            item.get("event") or "资料未明确",
            item.get("score_impact") or "资料未明确",
        ]
        for item in timeline
    ]
    return _markdown_table(["时间段", "触发条件", "可能事件", "比分影响"], rows)


def _match_events_table(context: dict[str, Any]) -> str:
    events = (context.get("step3") or {}).get("events") or []
    rows = [
        [
            f"{item.get('minute')}’" if item.get("minute") is not None else "资料未明确",
            item.get("event_label") or _event_type_label(item.get("event_type") or ""),
            item.get("team") or "资料未明确",
            _sanitize_event_description(item.get("description")),
            item.get("score") or "资料未明确",
        ]
        for item in events[:8]
    ]
    return _markdown_table(["时间", "事件", "球队", "说明", "比分"], rows)


def _risk_table(context: dict[str, Any]) -> str:
    step3 = context.get("step3") or {}
    uncertainty = step3.get("uncertainty_factors") or []
    rows = [
        ["伤停", _risk_signal_injury(context), "主力缺席会把进球期望向对手或平局方向推", "开赛前复核官方名单"],
        ["天气", _risk_signal_keyword(context, ("天气", "大雨", "雨", "风", "高温", "湿度")), "恶劣天气通常压低节奏和射门质量", "若天气差，低比分权重要上调"],
        ["红黄牌/VAR", _risk_signal_events(context, {"YELLOW_CARD", "RED_CARD", "VAR_CHECK"}), "红牌或点球会让原本接近的概率迅速倾斜", "临场看裁判尺度和禁区动作"],
        ["体能", _risk_signal_fitness(context), "体能差的一方末段更容易丢球或被压制", "重点看 61 分钟后的换人"],
        ["首发变动", _risk_signal_lineup(context), "关键位置临场换人会改变阵型和对位", "名单公布后重新看阵型表"],
        ["数据缺口", _risk_signal_data_gap(context, uncertainty), "资料少时，置信度应保守理解", "不要把最高概率当作确定结果"],
    ]
    return _markdown_table(["风险", "当前信号", "对比分方向的影响", "应对读法"], rows)


def _credibility_table(context: dict[str, Any]) -> str:
    credibility = context.get("credibility") or {}
    budget = ((credibility.get("budget") or {}).get("budget_profile") or {})
    dataset = ((credibility.get("budget") or {}).get("player_dataset") or {})
    counts = credibility.get("data_counts") or {}
    warnings = credibility.get("warnings") or []
    rows = [
        ["Step1 图谱/材料", f"实体 {counts.get('step1_graph_entities', 0)}，关系 {counts.get('step1_graph_relationships', 0)}", "图谱越完整，基本面解释越稳"],
        ["Step2 阵容/强度", f"强度 {counts.get('step2_team_strengths', 0)}，预计球员 {counts.get('step2_lineup_players', 0)}", "球员数据越完整，阵型和对位越可信"],
        ["Step3 推演产物", f"场景 {counts.get('step3_scenario_cases', 0)}，比分 {counts.get('step3_scorelines', 0)}，事件 {counts.get('step3_match_events', 0)}", "样本越完整，比分分布越有参考价值"],
        ["球员数据集", dataset.get("source_label") or dataset.get("dataset_id") or "资料未明确", "用于球员属性、首发和可用性"],
        ["预算/降级", _budget_warning_text(budget, warnings), "有降级或警告时，结论要更保守"],
    ]
    return _markdown_table(["可信度项目", "本次记录", "怎么影响解读"], rows)


def _section_basis_text(title: str) -> str:
    mapping = {
        "比赛结论摘要": "Step1 图谱和材料；Step2 球队强度、阵型、首发；Step3 胜平负概率、Top 比分、xG 和事件链。",
        "双方基本面与图谱证据": "Step1 图谱实体/关系、关键叙事、伤停、外部来源；Step2 可用性和球队强度。",
        "战术、阵型与预计首发": "Step1 战术 notes；Step2 阵型、预计首发、球员属性、教练讨论和可用性。",
        "胜平负与比分预测": "Step2 场景设计和球队强度；Step3 scorelines、九场景/六空间、xG、胜平负概率。",
        "关键比赛事件剧本": "Step3 match_events、事件链和分析笔记；Step2 场景设计。",
        "风险、不确定性与可信度说明": "Step1 伤停/资料来源；Step2 可用性、预算/降级；Step3 不确定因素和置信度。",
    }
    return mapping.get(title, "Step1、Step2、Step3 结构化证据。")


def _section_how_to_read(title: str) -> str:
    mapping = {
        "比赛结论摘要": "先看方向和概率条，再看三个理由；概率接近时要防平或防冷。",
        "双方基本面与图谱证据": "看两队差距是否来自真实资料；伤停和图谱实体能解释为什么概率会偏向一边。",
        "战术、阵型与预计首发": "阵型告诉你比赛在哪里对抗，关键球员告诉你谁最可能改变比分。",
        "胜平负与比分预测": "概率条看方向，Top 比分看落点，xG 看机会质量，场景表看比分如何变形。",
        "关键比赛事件剧本": "把时间线当作观赛清单；现实比赛出现同类信号时，关注比分方向是否跟着变化。",
        "风险、不确定性与可信度说明": "风险不是推翻结论，而是提醒哪些临场信息会让预测需要重估。",
    }
    return mapping.get(title, "先看表格，再看解释和风险。")


def _strengths_by_role(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("team_role") or ""): row for row in rows if isinstance(row, dict)}


def _rank_text(row: dict[str, Any]) -> str:
    rank = row.get("fifa_rank")
    points = row.get("fifa_points")
    if rank is None and points is None:
        return "资料未明确"
    return f"第{rank or '未明确'} / {points or '积分未明确'}"


def _elo_text(row: dict[str, Any]) -> str:
    rank = row.get("elo_rank")
    rating = row.get("elo_rating")
    if rank is None and rating is None:
        return "资料未明确"
    return f"第{rank or '未明确'} / {rating or '评分未明确'}"


def _leader_note(home: str, away: str, home_value: Any, away_value: Any, label: str) -> str:
    h_val = _coerce_float(home_value, -999)
    a_val = _coerce_float(away_value, -999)
    if h_val < -900 or a_val < -900:
        return "资料未明确"
    diff = h_val - a_val
    if abs(diff) < 3:
        return f"{label}接近，单点优势不明显"
    leader = home if diff > 0 else away
    return f"{leader}更强，这意味着该环节更可能拿到主动权"


def _availability_counts(summary: dict[str, Any]) -> str:
    total = _coerce_int(summary.get("total"), 0)
    if not total:
        return "资料未明确"
    available = _coerce_int(summary.get("available"), 0)
    injured = _coerce_int(summary.get("injured"), 0)
    suspended = _coerce_int(summary.get("suspended"), 0)
    doubtful = _coerce_int(summary.get("doubtful"), 0)
    return f"{available}/{total} 可用，伤 {injured} / 停 {suspended} / 疑 {doubtful}"


def _injuries_for_team(items: list[dict[str, Any]], team_iso3: Any) -> str:
    team = str(team_iso3 or "").upper()
    selected = [
        item for item in items
        if not team or str(item.get("team_iso3") or "").upper() == team
    ]
    if not selected:
        return "资料未明确"
    return "；".join(
        f"{item.get('player') or '未命名球员'} {item.get('status') or '状态待确认'}"
        for item in selected[:3]
    )


def _entity_type_text(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value[:3]) or "资料未明确"
    return str(value or "资料未明确")


def _style_text(value: Any) -> str:
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            if item in (None, "", [], {}):
                continue
            parts.append(f"{key}: {item}")
            if len(parts) >= 2:
                break
        return "；".join(parts) or "资料未明确"
    if isinstance(value, list):
        return "；".join(str(item) for item in value[:3]) or "资料未明确"
    return str(value or "资料未明确")


def _availability_label(value: Any) -> str:
    mapping = {
        "available": "可用",
        "doubtful": "存疑",
        "injured": "伤缺",
        "suspended": "停赛",
    }
    return mapping.get(str(value or ""), str(value or "资料未明确"))


def _player_strength_tag(player: dict[str, Any]) -> str:
    candidates = [
        ("终结", player.get("finishing")),
        ("传球", player.get("passing")),
        ("进攻", player.get("attack")),
        ("防守", player.get("defense")),
    ]
    available = [(label, _coerce_float(value, -1)) for label, value in candidates if value is not None]
    if not available:
        return "资料未明确"
    label, value = max(available, key=lambda item: item[1])
    return f"{label} {value:g}"


def _xg_value(value: Any) -> str:
    if value is None:
        return "资料未明确"
    return f"{_coerce_float(value, 0.0):.2f}"


def _xg_diff(home: Any, away: Any) -> str:
    if home is None or away is None:
        return "资料未明确"
    diff = _coerce_float(home, 0.0) - _coerce_float(away, 0.0)
    return f"{diff:+.2f}"


def _list_preview(items: Any, *, fallback: str) -> str:
    if isinstance(items, list):
        selected = [str(item).strip() for item in items[:3] if str(item or "").strip()]
        return "；".join(selected) or fallback
    return str(items or fallback)


def _probability_dict_text(payload: dict[str, Any]) -> str:
    if not payload:
        return "资料未明确"
    return " / ".join(
        f"{label}{payload.get(key)}"
        for key, label in (("home_win", "主胜"), ("draw", "平"), ("away_win", "客胜"))
        if payload.get(key) is not None
    ) or "资料未明确"


def _risk_signal_injury(context: dict[str, Any]) -> str:
    injuries = ((context.get("step1") or {}).get("injury_reports") or [])
    if injuries:
        return "；".join(
            f"{item.get('player') or '未命名球员'} {item.get('status') or '待确认'}"
            for item in injuries[:3]
        )
    availability = ((context.get("step2") or {}).get("player_availability") or {})
    signals = [
        _availability_counts(availability.get(role) or {})
        for role in ("home", "away")
        if availability.get(role)
    ]
    return "；".join(signals) or "资料未明确"


def _risk_signal_keyword(context: dict[str, Any], keywords: tuple[str, ...]) -> str:
    texts: list[str] = []
    step1 = context.get("step1") or {}
    texts.extend(str(item) for item in step1.get("key_narratives") or [])
    texts.extend(str((item or {}).get("note") or "") for item in step1.get("tactical_notes") or [])
    texts.extend(str(item) for item in (context.get("step3") or {}).get("uncertainty_factors") or [])
    matches = [text for text in texts if any(keyword in text for keyword in keywords)]
    return _truncate_text(matches[0], 120) if matches else "资料未明确"


def _risk_signal_events(context: dict[str, Any], event_types: set[str]) -> str:
    events = (context.get("step3") or {}).get("events") or []
    selected = [
        item for item in events
        if str(item.get("event_type") or "") in event_types
    ]
    if not selected:
        return "Step3 事件链未明确"
    return "；".join(
        f"{item.get('minute')}’{item.get('event_label') or _event_type_label(item.get('event_type') or '')}"
        for item in selected[:3]
    )


def _risk_signal_fitness(context: dict[str, Any]) -> str:
    match = context.get("match") or {}
    strengths = _strengths_by_role(((context.get("step2") or {}).get("team_strengths") or []))
    values = []
    for role, team in (("home", match.get("home_team") or "主队"), ("away", match.get("away_team") or "客队")):
        value = (strengths.get(role) or {}).get("fitness_rating")
        values.append(f"{team}体能 {value if value is not None else '资料未明确'}")
    return "；".join(values)


def _risk_signal_lineup(context: dict[str, Any]) -> str:
    lineups = ((context.get("step2") or {}).get("lineups") or {})
    home_count = len(lineups.get("home") or [])
    away_count = len(lineups.get("away") or [])
    if home_count or away_count:
        return f"预计首发记录：主队 {home_count} 人，客队 {away_count} 人"
    return "预计首发资料未明确"


def _risk_signal_data_gap(context: dict[str, Any], uncertainty: list[Any]) -> str:
    warnings = ((context.get("credibility") or {}).get("warnings") or [])
    if warnings:
        return "；".join(str(item) for item in warnings[:3])
    if uncertainty:
        return "；".join(str(item) for item in uncertainty[:3])
    counts = ((context.get("credibility") or {}).get("data_counts") or {})
    if not counts.get("step1_graph_entities"):
        return "图谱实体较少或未记录"
    return "未见明显数据缺口"


def _budget_warning_text(budget: dict[str, Any], warnings: list[Any]) -> str:
    profile = budget.get("profile_key") or budget.get("budget_profile") or "资料未明确"
    warning_text = "；".join(str(item) for item in warnings[:3]) if warnings else "未记录明显警告"
    return f"{profile}；{warning_text}"


def _summary_reason(context: dict[str, Any], index: int) -> str:
    reasons = _key_reasons(context, limit=3)
    return reasons[index] if index < len(reasons) else "资料未明确"


def _top_score_reason(context: dict[str, Any]) -> str:
    top_scores = ((context.get("step3") or {}).get("top_scores") or [])
    if not top_scores:
        return "Top 比分资料未明确"
    return "、".join(
        f"{item.get('score')}({_format_probability(item.get('probability'))})"
        for item in top_scores[:3]
        if isinstance(item, dict)
    ) or "Top 比分资料未明确"


def _confidence_reason(context: dict[str, Any]) -> str:
    counts = ((context.get("credibility") or {}).get("data_counts") or {})
    return (
        f"Step3 有 {counts.get('step3_scenario_cases', 0)} 个场景、"
        f"{counts.get('step3_scorelines', 0)} 组比分、{counts.get('step3_match_events', 0)} 条事件"
    )


def _key_reasons(context: dict[str, Any], *, limit: int) -> list[str]:
    match = context.get("match") or {}
    home = match.get("home_team") or "主队"
    away = match.get("away_team") or "客队"
    reasons: list[str] = []
    for item in ((context.get("step1") or {}).get("key_narratives") or []):
        if str(item or "").strip():
            reasons.append(f"Step1 叙事：{_truncate_text(item, 120)}")
        if len(reasons) >= limit:
            return reasons
    strengths = _strengths_by_role(((context.get("step2") or {}).get("team_strengths") or []))
    if strengths.get("home") and strengths.get("away"):
        reasons.append(
            "Step2 强度："
            + _leader_note(
                home,
                away,
                strengths["home"].get("attack_rating"),
                strengths["away"].get("attack_rating"),
                "进攻",
            )
        )
    notes = ((context.get("step3") or {}).get("analyst_notes") or [])
    for note in notes:
        claim = str(note.get("claim") or "").strip()
        if claim:
            reasons.append(f"Step3 分析：{_truncate_text(claim, 120)}")
        if len(reasons) >= limit:
            return reasons[:limit]
    score = ((context.get("step3") or {}).get("scoreline_summary") or {})
    if score.get("most_likely_score"):
        reasons.append(f"Step3 比分分布最集中在 {score.get('most_likely_score')}。")
    while len(reasons) < limit:
        reasons.append("资料未明确")
    return reasons[:limit]


def _candidate_score_text(candidates: list[Any]) -> str:
    parts = []
    for item in candidates[:4]:
        if isinstance(item, dict):
            parts.append(f"{item.get('score')}({_format_probability(item.get('probability'))})")
    return "、".join(parts) or "暂无明确候选"


def _wdl_verdict(probabilities: dict[str, Any], home: str, away: str) -> str:
    values = {
        f"{home}胜": _coerce_float(probabilities.get("home_win"), -1),
        "平局": _coerce_float(probabilities.get("draw"), -1),
        f"{away}胜": _coerce_float(probabilities.get("away_win"), -1),
    }
    return max(values.items(), key=lambda item: item[1])[0]


def _first_non_empty(*groups: Any) -> str:
    for group in groups:
        if isinstance(group, list):
            for item in group:
                text = str(item or "").strip()
                if text:
                    return text
        else:
            text = str(group or "").strip()
            if text:
                return text
    return ""


def _chat_basis_text(context: dict[str, Any]) -> str:
    reports = context.get("report_sections") or []
    preferred_titles = ("战术、阵型与预计首发", "胜平负与比分预测", "双方基本面与图谱证据")
    for title in preferred_titles:
        section = next((item for item in reports if item.get("title") == title), None)
        if section and section.get("excerpt"):
            text = _plain_report_excerpt(section.get("excerpt"), limit=180)
            if text:
                return text

    discussions = [
        item.get("summary")
        for item in (context.get("step2") or {}).get("coach_discussions") or []
        if not _looks_internal_report_note(str(item.get("topic") or "") + " " + str(item.get("summary") or ""))
    ]
    return _first_non_empty(
        discussions,
        [item.get("claim") for item in (context.get("step3") or {}).get("analyst_notes") or []],
        ["报告主要依据比分概率、事件链和图谱证据交叉判断。"],
    )


def _qa_context_text(context: dict[str, Any]) -> str:
    match = context.get("match") or {}
    step2 = context.get("step2") or {}
    step3 = context.get("step3") or {}
    score = step3.get("scoreline_summary") or {}
    probabilities = score.get("win_draw_loss_probability") or {}
    lines = [
        "已生成报告内容：",
        _report_sections_context(context.get("report_sections") or []),
        "",
        "结构化预测摘要：",
        f"- 比赛：{match.get('match_name') or ((match.get('home_team') or '主队') + ' vs ' + (match.get('away_team') or '客队'))}",
        f"- 最可能比分：{score.get('most_likely_score') or '报告未明确'}",
        "- 胜平负概率："
        f"主胜 {_format_probability(probabilities.get('home_win'))}，"
        f"平局 {_format_probability(probabilities.get('draw'))}，"
        f"客胜 {_format_probability(probabilities.get('away_win'))}",
        f"- Top 比分：{_candidate_score_text(score.get('top_score_candidates') or [])}",
        f"- xG：{json.dumps(step3.get('xg') or {}, ensure_ascii=False, default=str)}",
        f"- 阵型：{json.dumps(step2.get('formations') or {}, ensure_ascii=False, default=str)}",
        f"- 预计首发：{_lineups_text(step2.get('lineups') or {})}",
        f"- 阵型首发组件：{_widget_lineups_text(((context.get('widgets') or {}).get('lineup_widget') or {}))}",
        f"- 战术组件：{_widget_tactics_text(((context.get('widgets') or {}).get('tactics_widget') or {}))}",
        f"- 关键对位组件：{_widget_matchups_text(((context.get('widgets') or {}).get('matchup_widget') or []))}",
        f"- 球员可用性：{_availability_text(step2.get('player_availability') or {}).strip()}",
        f"- 教练讨论：{_coach_discussions_text(step2.get('coach_discussions') or [])}",
        f"- 事件链：{_qa_events_text(step3.get('events') or [])}",
        f"- 不确定因素：{_qa_list_text(step3.get('uncertainty_factors') or [])}",
    ]
    return "\n".join(lines)


def _report_sections_context(sections: list[dict[str, Any]]) -> str:
    if not sections:
        return "- 报告章节未入库，只能使用结构化预测摘要。"
    lines: list[str] = []
    for index, section in enumerate(sections[:6], start=1):
        title = section.get("title") or f"章节 {index}"
        excerpt = _plain_report_excerpt(section.get("excerpt"), limit=650)
        lines.append(f"### {index}. {title}\n{excerpt or '报告未明确'}")
    return "\n\n".join(lines)


def _chat_history_text(messages: list[dict[str, Any]], *, limit: int = 8) -> str:
    cleaned: list[str] = []
    for item in messages[-limit:]:
        role = str(item.get("role") or "").strip()
        if role not in {"user", "assistant"}:
            continue
        content = _plain_report_excerpt(item.get("content"), limit=260)
        if not content:
            continue
        label = "用户" if role == "user" else "助手"
        cleaned.append(f"- {label}: {content}")
    return "\n".join(cleaned) or "- 无历史对话。"


def _qa_events_text(events: list[dict[str, Any]]) -> str:
    if not events:
        return "报告未明确"
    lines = []
    for item in events[:8]:
        minute = item.get("minute")
        label = item.get("event_label") or _event_type_label(item.get("event_type") or "")
        description = _truncate_text(item.get("description") or item.get("summary"), 120)
        score = item.get("score") or item.get("scoreline") or ""
        lines.append(f"{minute}'{label}" + (f"({score})" if score else "") + (f": {description}" if description else ""))
    return "；".join(lines)


def _qa_list_text(items: list[Any], *, limit: int = 6) -> str:
    values = [str(item).strip() for item in items[:limit] if str(item or "").strip()]
    return "；".join(values) if values else "报告未明确"


def _plain_report_excerpt(value: Any, *, limit: int) -> str:
    text = str(value or "")
    text = re.sub(r"\*\*[^：:]+[:：]\*\*", "", text)
    text = re.sub(r"^#+\s+.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[\s*-]+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text).strip()
    return _truncate_text(text, limit)


def _ensure_sentence(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    return cleaned if cleaned[-1] in "。！？.!?" else cleaned + "。"


def _bullet_join(items: list[Any], *, limit: int = 4) -> str:
    selected = [str(item).strip() for item in items[:limit] if str(item or "").strip()]
    if not selected:
        return "\n- 暂无明确图谱叙事。"
    return "".join(f"\n- {item}" for item in selected)


def _clean_bulleted_lines(text: str) -> str:
    return "\n".join(
        "- " + line.strip().lstrip("- ").strip()
        for line in str(text or "").splitlines()
        if line.strip()
    )


def _injury_lines(items: list[dict[str, Any]]) -> str:
    if not items:
        return "- 暂无明确伤停，仍需等待官方名单。"
    return "\n".join(
        f"- {item.get('player') or '未命名球员'}（{item.get('team_iso3') or '-'}）：{item.get('status') or '状态待确认'}"
        + (f"，依据：{item.get('evidence')}" if item.get("evidence") else "")
        for item in items[:8]
    )


def _tactical_notes_text(items: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in items[:4]:
        note = str(item.get("note") or item.get("summary") or "").strip()
        if not note:
            continue
        team = item.get("team_iso3")
        prefix = f"{team}：" if team else ""
        lines.append(f"- {prefix}{note}")
    return "\n".join(lines) or "- 资料未给出完整战术描述，以下判断主要来自阵型、球员可用性和比分概率。"


def _coach_discussions_text(items: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in items:
        topic = str(item.get("topic") or "").strip()
        summary = str(item.get("summary") or "").strip()
        if not summary or _looks_internal_report_note(topic + " " + summary):
            continue
        lines.append(f"- {topic}：{summary}" if topic else f"- {summary}")
        if len(lines) >= 3:
            break
    return "\n".join(lines) or "- 暂无可直接展示给球迷的教练讨论结论，因此本段主要依据阵型、首发、球员能力和攻防评分来解释。"


def _looks_internal_report_note(text: str) -> bool:
    return bool(re.search(
        r"配置|持久化|恢复|回看|reuse|pipeline|报告|数据库|预算|调用|矩阵|权重不覆盖|resume|storage|artifact",
        text or "",
        re.IGNORECASE,
    ))


def _team_strengths_text(rows: list[dict[str, Any]], home: str, away: str) -> str:
    by_role = {str(row.get("team_role") or ""): row for row in rows if isinstance(row, dict)}
    home_row = by_role.get("home") or next((row for row in rows if row.get("team_name") == home), None)
    away_row = by_role.get("away") or next((row for row in rows if row.get("team_name") == away), None)
    if not home_row or not away_row:
        return "- 暂无完整球队强度评分，先以可用阵容和赛前资料作为判断依据。"

    dimensions = [
        ("attack_rating", "进攻"),
        ("defense_rating", "防守"),
        ("transition_rating", "转换"),
        ("set_piece_rating", "定位球"),
        ("goalkeeper_rating", "门将"),
        ("discipline_rating", "纪律性"),
    ]
    lines: list[str] = []
    for key, label in dimensions:
        home_value = _coerce_float(home_row.get(key), 0.0)
        away_value = _coerce_float(away_row.get(key), 0.0)
        diff = home_value - away_value
        if abs(diff) < 3:
            continue
        leader = home if diff > 0 else away
        trailing = away if diff > 0 else home
        lines.append(f"- {label}：{leader}略优于{trailing}，这会影响比赛在该环节的主动权。")
        if len(lines) >= 4:
            break
    return "\n".join(lines) or "- 双方评分接近，比赛更可能由临场效率、定位球和关键球员状态拉开差距。"


def _lineups_text(lineups: dict[str, list[dict[str, Any]]]) -> str:
    labels = {"home": "主队", "away": "客队"}
    lines: list[str] = []
    for role in ("home", "away"):
        players = lineups.get(role) or []
        if not players:
            lines.append(f"- {labels[role]}：暂无可推断首发。")
            continue
        names = "、".join(
            f"{player.get('name')}({player.get('position') or '-'})"
            for player in players[:11]
            if player.get("name")
        )
        lines.append(f"- {labels[role]}：{names or '暂无可推断首发'}")
    return "\n".join(lines)


def _widget_lineups_text(lineup_widget: dict[str, Any]) -> str:
    labels = {"home": "主队", "away": "客队"}
    lines: list[str] = []
    for role in ("home", "away"):
        team = lineup_widget.get(role) or {}
        players = team.get("players") or []
        names = "、".join(
            f"{player.get('number') or '--'}.{player.get('name') or '资料未明确'}({player.get('position') or '-'})"
            for player in players[:11]
        )
        lines.append(
            f"{team.get('team') or labels[role]} {team.get('formation') or '资料未明确'}："
            f"{names or '暂无可推断首发'}；{team.get('notes') or ''}"
        )
    return " / ".join(lines)


def _widget_tactics_text(tactics_widget: dict[str, Any]) -> str:
    parts = []
    for role, label in (("home", "主队"), ("away", "客队")):
        row = tactics_widget.get(role) or {}
        parts.append(
            f"{label}：阵型 {row.get('base_shape') or '资料未明确'}，"
            f"进攻 {row.get('attacking_plan') or '资料未明确'}，"
            f"防守 {row.get('defensive_plan') or '资料未明确'}，"
            f"弱点 {row.get('weakness') or '资料未明确'}"
        )
    return " / ".join(parts)


def _widget_matchups_text(matchups: list[dict[str, Any]]) -> str:
    if not matchups:
        return "资料未明确"
    return "；".join(
        f"{item.get('zone') or '区域'}：{item.get('home_player') or '主队球员'} vs {item.get('away_player') or '客队球员'}，{item.get('why_it_matters') or '资料未明确'}"
        for item in matchups[:5]
        if isinstance(item, dict)
    ) or "资料未明确"


def _availability_text(availability: dict[str, dict[str, Any]]) -> str:
    lines = []
    if availability.get("home"):
        lines.append(_availability_line("主队", availability["home"]).lstrip("- "))
    if availability.get("away"):
        lines.append(_availability_line("客队", availability["away"]).lstrip("- "))
    return "\n" + "\n".join(lines) if lines else "\n- 暂无完整球员可用性统计。"


def _scoreline_rows_text(scorelines: list[dict[str, Any]], *, home: str = "主队", away: str = "客队") -> str:
    if not scorelines:
        return "- 暂无分走势比分。"
    return "\n".join(
        f"- {_reader_scenario_label(row.get('scenario_label'), home, away)}：更常见的比分是 {row.get('most_likely_score')}，胜平负倾向为{home}胜 {row.get('home_win_probability')}%、平局 {row.get('draw_probability')}%、{away}胜 {row.get('away_win_probability')}%。"
        for row in scorelines[:6]
    )


def _reader_scenario_label(value: Any, home: str, away: str) -> str:
    label = str(value or "").strip()
    mapping = {
        "基准走势": "常规比赛节奏",
        "主队上行": f"{home}发挥更顺时",
        "客队上行": f"{away}发挥更顺时",
        "主队失误": f"{home}后场或纪律出问题时",
        "客队失误": f"{away}后场或纪律出问题时",
        "高波动": "比赛变开放或出现红牌/VAR时",
    }
    return mapping.get(label, label or "其他比赛走势")


def _event_lines_text(events: list[dict[str, Any]]) -> str:
    if not events:
        return "- 暂无可展示的关键事件链。"
    return "\n".join(
        f"- {item.get('minute')}' {_event_type_label(item.get('event_type') or '')}：{_sanitize_event_description(item.get('description'))}"
        + (f"（比分 {item.get('score')}）" if item.get("score") else "")
        for item in events[:8]
    )


def _sanitize_event_description(value: Any) -> str:
    text = str(value or "").strip()
    replacements = {
        "Monte Carlo 模态轨迹收束到": "模拟路径倾向于",
        "Monte Carlo": "模拟",
        "modal trajectory": "典型走势",
        "away ": "客队 ",
        "home ": "主队 ",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text or "关键事件待补充"


def _credibility_text(context: dict[str, Any]) -> str:
    budget = ((context.get("credibility") or {}).get("budget") or {})
    availability = ((context.get("step2") or {}).get("player_availability") or {})
    warnings = ((context.get("credibility") or {}).get("warnings") or [])
    sources = (((context.get("step1") or {}).get("external_sources") or [])[:3])
    lines: list[str] = []
    if availability.get("home"):
        lines.append(_availability_line("主队", availability["home"]).lstrip("- "))
    if availability.get("away"):
        lines.append(_availability_line("客队", availability["away"]).lstrip("- "))
    if sources:
        lines.append("主要数据来源：" + "；".join(str(item).lstrip("- ") for item in sources))
    if warnings:
        lines.append("需要注意：" + "；".join(str(item) for item in warnings[:4]))
    ledger = (budget.get("ledger") or {}) if isinstance(budget.get("ledger"), dict) else {}
    if ledger.get("failures"):
        lines.append("部分模型调用触发降级，报告已采用保守解释。")
    return "\n" + "\n".join(f"- {line}" for line in lines) if lines else "\n- 当前证据可支撑方向性判断，但不适合作为确定赛果。"


def _report_budget_profile(run: PredictionRunRecord, config: PredictionConfigRecord | None) -> dict[str, Any]:
    config_budget = config.llm_budget_profile if config and isinstance(config.llm_budget_profile, dict) else {}
    metadata_budget = ((config.config_metadata or {}).get("llm_budget") if config else {}) or {}
    run_budget = (run.run_metadata or {}).get("llm_budget") or (run.run_metadata or {}).get("llm_budget_profile") or {}

    for payload in (config_budget, metadata_budget, run_budget):
        if not isinstance(payload, dict):
            continue
        profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else payload
        if isinstance(profile, dict) and profile.get("profile_key"):
            return dict(profile)
    return LLMBudgetProfile.MIDDLE.to_dict()


def _merged_ledger_summary(
    run: PredictionRunRecord,
    config: PredictionConfigRecord | None,
    result: PredictionResultRecord | None,
) -> dict[str, Any]:
    ledgers: list[dict[str, Any]] = []
    config_budget = config.llm_budget_profile if config and isinstance(config.llm_budget_profile, dict) else {}
    config_metadata_budget = ((config.config_metadata or {}).get("llm_budget") if config else {}) or {}
    seen_ledgers: set[str] = set()
    for payload in (
        config_budget.get("ledger_summary") if isinstance(config_budget, dict) else None,
        config_metadata_budget.get("ledger_summary") if isinstance(config_metadata_budget, dict) else None,
        (run.run_metadata or {}).get("ledger_summary"),
        ((result.result_metadata or {}).get("ledger_summary") if result else None),
    ):
        if isinstance(payload, dict) and payload:
            marker = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
            if marker in seen_ledgers:
                continue
            seen_ledgers.add(marker)
            ledgers.append(payload)

    if not ledgers:
        profile = _report_budget_profile(run, config)
        return {
            "total_calls": 0,
            "cached": 0,
            "spent": 0,
            "hard_cap": _coerce_int(profile.get("hard_cap_calls"), 0),
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "avg_latency_ms": 0,
            "by_role": {},
            "failures": [],
        }

    merged: dict[str, Any] = {
        "total_calls": 0,
        "cached": 0,
        "spent": 0,
        "hard_cap": 0,
        "total_tokens": 0,
        "total_cost_usd": 0.0,
        "avg_latency_ms": 0,
        "p95_latency_ms": 0,
        "by_role": {},
        "failures": [],
    }
    latency_total = 0
    latency_weight = 0
    for ledger in ledgers:
        merged["total_calls"] += _coerce_int(ledger.get("total_calls"), 0)
        merged["cached"] += _coerce_int(ledger.get("cached"), 0)
        merged["spent"] += _coerce_int(ledger.get("spent"), 0)
        merged["hard_cap"] = max(_coerce_int(merged["hard_cap"], 0), _coerce_int(ledger.get("hard_cap"), 0))
        merged["total_tokens"] += _coerce_int(ledger.get("total_tokens"), 0)
        merged["total_cost_usd"] += _coerce_float(ledger.get("total_cost_usd"), 0.0)
        calls = max(1, _coerce_int(ledger.get("total_calls"), 0))
        avg_latency = _coerce_int(ledger.get("avg_latency_ms"), 0)
        if avg_latency:
            latency_total += avg_latency * calls
            latency_weight += calls
        merged["p95_latency_ms"] = max(
            _coerce_int(merged["p95_latency_ms"], 0),
            _coerce_int(ledger.get("p95_latency_ms"), 0),
        )

        by_role = ledger.get("by_role") if isinstance(ledger.get("by_role"), dict) else {}
        for role, item in by_role.items():
            role_summary = item if isinstance(item, dict) else {}
            target = merged["by_role"].setdefault(str(role), {"calls": 0, "cached": 0, "tokens": 0, "cost": 0.0})
            target["calls"] += _coerce_int(role_summary.get("calls"), 0)
            target["cached"] += _coerce_int(role_summary.get("cached"), 0)
            target["tokens"] += _coerce_int(role_summary.get("tokens"), 0)
            target["cost"] += _coerce_float(role_summary.get("cost"), 0.0)
            if role_summary.get("p95_ms") is not None:
                target["p95_ms"] = max(_coerce_int(target.get("p95_ms"), 0), _coerce_int(role_summary.get("p95_ms"), 0))

        failures = ledger.get("failures") if isinstance(ledger.get("failures"), list) else []
        merged["failures"].extend(item for item in failures if isinstance(item, dict))

    if latency_weight:
        merged["avg_latency_ms"] = round(latency_total / latency_weight)
    merged["total_cost_usd"] = round(float(merged["total_cost_usd"]), 6)
    for role_summary in merged["by_role"].values():
        role_summary["cost"] = round(float(role_summary.get("cost") or 0.0), 6)
    return merged


def _external_sources_snapshot(config: PredictionConfigRecord | None) -> dict[str, Any]:
    snapshot = (config.model_input_snapshot or {}) if config else {}
    if not isinstance(snapshot, dict):
        return {}
    sources = snapshot.get("external_sources_etag") or snapshot.get("external_sources") or {}
    return dict(sources) if isinstance(sources, dict) else {}


def _external_source_lines(config: PredictionConfigRecord | None) -> list[str]:
    sources = _external_sources_snapshot(config)
    if not sources:
        return ["- 未记录外部数据源快照。"]

    labels = {
        "intl_results": "martj42/international_results (CC0)",
        "national_elo": "eloratings.net (公开 TSV)",
        "fifa_ranking": "FIFA Ranking (cristiandley mirror)",
        "statsbomb": "Free StatsBomb data — Provided by StatsBomb (open data agreement)",
    }
    lines: list[str] = []
    for key in ("intl_results", "national_elo", "fifa_ranking", "statsbomb"):
        value = sources.get(key)
        label = labels[key]
        if isinstance(value, dict) and value.get("error"):
            lines.append(f"- {label} — 不可用：{value.get('error')}")
        elif isinstance(value, dict) and value:
            date = _source_date(value)
            row_count = _coerce_int(value.get("row_count"), 0)
            count_label = f" · {_format_number(row_count)} 条" if row_count else ""
            lines.append(f"- {label} — {date}{count_label}")
        elif key in sources:
            lines.append(f"- {label} — {sources.get(key)}")
    extra_sources = sources.get("sources")
    if isinstance(extra_sources, list):
        for source in extra_sources:
            if isinstance(source, str) and source not in labels:
                lines.append(f"- {source}")
    if not lines:
        lines.append("- 未记录外部数据源快照。")
    return lines


def _player_dataset_snapshot(
    *,
    run: PredictionRunRecord,
    config: PredictionConfigRecord | None,
    dataset: PredictionPlayerDatasetRecord | None,
) -> dict[str, Any]:
    dataset_id = (
        (dataset.dataset_id if dataset else None)
        or (config.player_dataset_id if config else None)
        or (run.run_metadata or {}).get("player_dataset_id")
    )
    if not dataset:
        return {"dataset_id": dataset_id}
    return {
        "dataset_id": dataset.dataset_id,
        "source_label": dataset.source_label,
        "scope_label": dataset.scope_label,
        "teams_count": dataset.teams_count,
        "players_count": dataset.players_count,
        "metadata": dataset.dataset_metadata or {},
    }


def _player_dataset_lines(
    *,
    run: PredictionRunRecord,
    config: PredictionConfigRecord | None,
    dataset: PredictionPlayerDatasetRecord | None,
    player_availability: dict[str, dict[str, Any]],
) -> list[str]:
    snapshot = _player_dataset_snapshot(run=run, config=config, dataset=dataset)
    dataset_id = snapshot.get("dataset_id") or "未指定"
    lines = [f"- dataset_id: {dataset_id}"]
    if not dataset:
        lines.append("- 使用兼容模式（无球员数据集快照）。")
        return lines

    lines.append(f"- scope: {dataset.scope_label}")
    lines.append(f"- {_format_number(dataset.teams_count)} 队 · {_format_number(dataset.players_count)} 人")
    lines.append(_availability_line("主队", player_availability.get("home") or {}))
    lines.append(_availability_line("客队", player_availability.get("away") or {}))
    return lines


def _degradation_lines(
    *,
    run: PredictionRunRecord,
    config: PredictionConfigRecord | None,
    result: PredictionResultRecord | None,
    ledger: dict[str, Any],
) -> list[str]:
    items: list[str] = []
    for failure in ledger.get("failures") or []:
        if not isinstance(failure, dict):
            continue
        role = failure.get("role") or "unknown"
        reason = failure.get("reason") or failure.get("error") or "unknown"
        fallback = failure.get("fallback")
        suffix = f"，fallback={fallback}" if fallback else ""
        scenario_key = failure.get("scenario_key")
        scenario = f"（{scenario_key}）" if scenario_key else ""
        items.append(f"- {_role_display_name(str(role))}{scenario}: {reason}{suffix}")

    for warning in _warning_items(run=run, config=config, result=result):
        items.append(f"- {warning}")

    if not items:
        return ["本次未触发降级."]
    return items


def _warning_items(
    *,
    run: PredictionRunRecord,
    config: PredictionConfigRecord | None,
    result: PredictionResultRecord | None,
) -> list[str]:
    candidates: list[Any] = []
    if config and isinstance(config.model_input_snapshot, dict):
        candidates.extend(config.model_input_snapshot.get("warnings") or [])
    if config and isinstance(config.config_metadata, dict):
        candidates.extend(config.config_metadata.get("warnings") or [])
    if isinstance(run.run_metadata, dict):
        candidates.extend(run.run_metadata.get("warnings") or [])
        candidates.extend(run.run_metadata.get("llm_failures") or [])
    if result and isinstance(result.result_metadata, dict):
        candidates.extend(result.result_metadata.get("warnings") or [])
        candidates.extend(result.result_metadata.get("llm_failures") or [])

    warnings: list[str] = []
    for item in candidates:
        if isinstance(item, str) and item:
            warnings.append(item)
        elif isinstance(item, dict):
            reason = item.get("reason") or item.get("message") or item.get("error")
            if reason:
                warnings.append(str(reason))
    return warnings


def _backtest_lines(payload: dict[str, Any] | None) -> list[str]:
    if not payload:
        return ["最近一次 backtest: 未找到 backtest 产物（output/backtest_2024.json）。"]

    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    holdout = config.get("holdout") or "unknown"
    n_matches = config.get("n_matches") or metrics.get("n_matches")
    dataset_id = config.get("dataset_id") or "-"
    lines = [
        "最近一次 backtest:",
        f"- 数据集: {holdout} (n={_format_number(_coerce_int(n_matches, 0))})",
        f"- dataset_id: {dataset_id}",
    ]
    if metrics.get("rps") is not None:
        baseline = metrics.get("rps_baseline_uniform")
        suffix = f", baseline={_coerce_float(baseline, 0.0):.3f}" if baseline is not None else ""
        lines.append(f"- RPS = {_coerce_float(metrics.get('rps'), 0.0):.3f} (越低越好{suffix})")
    if metrics.get("brier") is not None:
        lines.append(f"- Brier = {_coerce_float(metrics.get('brier'), 0.0):.3f}")
    if metrics.get("modal_score_hit_rate") is not None:
        lines.append(f"- Modal score hit rate = {_coerce_float(metrics.get('modal_score_hit_rate'), 0.0) * 100:.1f}%")
    if metrics.get("calibration") or metrics.get("calibration_bins"):
        lines.append("- 校准曲线见附录")
    return lines


def _latest_backtest_report() -> dict[str, Any] | None:
    for path in _backtest_candidates():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
    return None


def _backtest_candidates() -> list[Path]:
    repo_root = Path(__file__).resolve().parents[3]
    roots = [Path.cwd(), repo_root, repo_root / "backend"]
    seen: set[Path] = set()
    candidates: list[Path] = []
    for root in roots:
        for pattern in ("output/backtest_*.json", "backtest_*.json"):
            for path in root.glob(pattern):
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                candidates.append(resolved)
    return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)


def _squad_availability_summary(payload: dict[str, Any]) -> dict[str, Any]:
    players = payload.get("players") if isinstance(payload.get("players"), list) else []
    stats = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
    total = len(players) or sum(_coerce_int(stats.get(key), 0) for key in ("available", "doubtful", "injured", "suspended"))
    summary = {
        "team_name": payload.get("team_name") or payload.get("team_fifa") or "",
        "team_iso3": payload.get("team_iso3") or payload.get("iso3") or "",
        "total": total,
        "available": _coerce_int(stats.get("available"), 0),
        "doubtful": _coerce_int(stats.get("doubtful"), 0),
        "injured": _coerce_int(stats.get("injured"), 0),
        "suspended": _coerce_int(stats.get("suspended"), 0),
    }
    if players and not any(summary[key] for key in ("available", "doubtful", "injured", "suspended")):
        return _players_availability_summary(players, fallback_team=summary["team_name"], team_iso3=summary["team_iso3"])
    if total and not summary["available"]:
        summary["available"] = max(0, total - summary["doubtful"] - summary["injured"] - summary["suspended"])
    return summary


def _players_availability_summary(
    players: list[Any],
    *,
    fallback_team: str = "",
    team_iso3: str = "",
) -> dict[str, Any]:
    counts = {"available": 0, "doubtful": 0, "injured": 0, "suspended": 0}
    team_name = fallback_team
    resolved_iso3 = team_iso3
    for player in players:
        if isinstance(player, dict):
            availability = player.get("availability") if isinstance(player.get("availability"), dict) else {}
            team_name = team_name or str(player.get("team_name") or player.get("team_fifa") or "")
            resolved_iso3 = resolved_iso3 or str(player.get("team_iso3") or "")
        else:
            availability = player.availability if isinstance(player.availability, dict) else {}
            team_name = team_name or player.team_name
            resolved_iso3 = resolved_iso3 or player.team_iso3
        status = str(availability.get("status") or "available")
        if status not in counts:
            status = "available"
        counts[status] += 1
    total = len(players)
    return {
        "team_name": team_name,
        "team_iso3": resolved_iso3,
        "total": total,
        **counts,
    }


def _team_ref(payload: dict[str, Any], fallback_name: str | None) -> dict[str, str]:
    return {
        "iso3": str(payload.get("team_iso3") or payload.get("iso3") or ""),
        "name": str(payload.get("team_name") or payload.get("team_fifa") or fallback_name or ""),
    }


def _query_dataset_players(session: Any, dataset_id: str, team_ref: dict[str, str]) -> list[PredictionPlayerRecord]:
    query = session.query(PredictionPlayerRecord).filter_by(dataset_id=dataset_id)
    if team_ref.get("iso3"):
        query = query.filter_by(team_iso3=team_ref["iso3"])
    elif team_ref.get("name"):
        query = query.filter_by(team_name=team_ref["name"])
    else:
        return []
    return list(query.order_by(PredictionPlayerRecord.shirt_number.asc()).all())


def _availability_line(label: str, summary: dict[str, Any]) -> str:
    total = _coerce_int(summary.get("total"), 0)
    injured = _coerce_int(summary.get("injured"), 0)
    suspended = _coerce_int(summary.get("suspended"), 0)
    doubtful = _coerce_int(summary.get("doubtful"), 0)
    available = _coerce_int(summary.get("available"), max(0, total - injured - suspended - doubtful))
    if not total:
        return f"- {label}可用 未记录"
    return (
        f"- {label}可用 {_format_number(available)}/{_format_number(total)} "
        f"({_format_number(injured)} 伤 / {_format_number(suspended)} 停 / {_format_number(doubtful)} 疑)"
    )


def _source_date(payload: dict[str, Any]) -> str:
    for key in ("fetched_at", "last_modified", "date", "updated_at"):
        value = payload.get(key)
        if value:
            return str(value)[:10]
    return "日期未记录"


def _scenario_space_label(value: str) -> str:
    labels = {
        "baseline": "基准走势",
        "home_upside": "主队上行",
        "away_upside": "客队上行",
        "home_error": "主队失误",
        "away_error": "客队失误",
        "volatility": "高波动",
    }
    return labels.get(value, value or "-")


def _state_label(value: Any) -> str:
    labels = {
        "normal": "正常发挥",
        "overperform": "超常发挥",
        "underperform": "发挥受限",
    }
    return labels.get(str(value or ""), str(value or "-"))


def _scenario_key_label(value: Any, home_state: Any | None = None, away_state: Any | None = None) -> str:
    key = str(value or "")
    labels = {
        "home_normal_away_normal": "双方正常发挥",
        "home_overperform_away_normal": "主队超常发挥",
        "home_normal_away_underperform": "客队发挥受限",
        "home_underperform_away_normal": "主队发挥受限",
        "home_normal_away_overperform": "客队超常发挥",
        "home_underperform_away_overperform": "主队受限 / 客队超常",
        "home_overperform_away_underperform": "主队超常 / 客队受限",
        "home_underperform_away_underperform": "双方发挥受限",
        "home_overperform_away_overperform": "双方高质量发挥",
    }
    if key in labels:
        return f"{labels[key]}（{key}）"
    if home_state or away_state:
        return f"主队{_state_label(home_state)} / 客队{_state_label(away_state)}"
    return key or "-"


def _event_type_label(value: str) -> str:
    labels = {
        "KICKOFF": "开球",
        "TACTICAL_PHASE": "战术阶段",
        "CHANCE_CREATED": "机会",
        "SHOT": "射门",
        "SAVE": "扑救",
        "GOAL": "进球",
        "FOUL": "犯规",
        "YELLOW_CARD": "黄牌",
        "CARD": "黄牌",
        "VAR_CHECK": "VAR",
        "SUBSTITUTION": "换人",
        "PRESSURE_SHIFT": "压力变化",
        "EXTRA_TIME": "补时",
        "FINAL_SCORE_HYPOTHESIS": "终场比分假设",
    }
    return labels.get(value, value or "-")


def _format_xg_value(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "-"


def _combined_probability(*values: Any) -> str:
    total = 0.0
    has_value = False
    for value in values:
        if value is None:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if numeric > 1:
            numeric /= 100
        total += numeric
        has_value = True
    return _format_probability(total) if has_value else "-"


def _humanize_note_claim(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return "该复核项未给出额外结论。"
    replacements = {
        "Step3 教练复核完成：": "教练组完成复核，态度为 ",
        "baseline 场景空间保留为模拟证据结论": "基准场景可以作为主要证据保留",
        "LLM 不可用时采用模板笔记": "模型不可用时使用模板化复核记录",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text.replace("。。", "。")


def _role_display_name(role: str) -> str:
    labels = {
        "data_extractor": "数据抽取",
        "coach_head_coach": "战术主教练",
        "coach_attack": "进攻教练",
        "coach_defense": "防守教练",
        "coach_transition": "转换教练",
        "coach_set_piece": "定位球教练",
        "coach_goalkeeper": "门将教练",
        "coach_fitness": "体能教练",
        "coach_risk": "风险教练",
        "narrative_polisher": "事件润色",
        "analyst_notes": "分析笔记",
        "step3_review_head_coach": "Step3 主教练复核",
        "step3_review_attack": "Step3 进攻复核",
        "step3_review_defense": "Step3 防守复核",
        "step3_review_risk": "Step3 风险复核",
    }
    return labels.get(role, role)


def _format_number(value: Any) -> str:
    return f"{_coerce_int(value, 0):,}"


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clip(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _clean_team_name(value: str) -> str:
    value = re.sub(r"预测|比分|胜平负|关键事件|的|和|，|,|。", "", value).strip()
    return value[-20:].strip()


def _first_value(rows: list[Any], attr: str, default: Any = None) -> Any:
    if not rows:
        return default
    return getattr(rows[0], attr, default)


def _format_probability(value: Any) -> str:
    if value is None:
        return "-"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if numeric <= 1:
        numeric *= 100
    return f"{numeric:.1f}%"


def _resolve_step3_budget(payload: Any) -> LLMBudgetProfile:
    if isinstance(payload, dict) and payload:
        return _with_step3_review_budget_floor(LLMBudgetProfile.from_dict(payload))

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
    return _with_step3_review_budget_floor(LLMBudgetProfile.from_dict(data))


def _with_step3_review_budget_floor(budget: LLMBudgetProfile) -> LLMBudgetProfile:
    if not budget.coach_review_roles or budget.hard_cap_calls >= MAX_HARD_CAP_CALLS:
        return budget

    data = budget.to_dict()
    data["profile_key"] = "custom"
    data["hard_cap_calls"] = MAX_HARD_CAP_CALLS
    return LLMBudgetProfile.from_dict(data)


def _ordered_team_strengths(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(rows) < 2:
        return rows
    by_role = {str(row.get("team_role")): row for row in rows}
    if "home" in by_role and "away" in by_role:
        return [by_role["home"], by_role["away"]]
    return rows


def _model_team_keys(
    home: str,
    away: str,
    team_strengths: list[dict[str, Any]],
    model_input_snapshot: dict[str, Any],
) -> tuple[str, str]:
    snapshot = model_input_snapshot.get("competition") if isinstance(model_input_snapshot, dict) else {}
    del snapshot
    home_snapshot_iso3 = model_input_snapshot.get("home_iso3") if isinstance(model_input_snapshot, dict) else None
    away_snapshot_iso3 = model_input_snapshot.get("away_iso3") if isinstance(model_input_snapshot, dict) else None
    home_meta = (team_strengths[0].get("metadata") or {}) if team_strengths else {}
    away_meta = (team_strengths[1].get("metadata") or {}) if len(team_strengths) > 1 else {}
    squads = model_input_snapshot.get("squads") or {}
    home_squad = squads.get("home") or {}
    away_squad = squads.get("away") or {}
    return (
        str(home_snapshot_iso3 or home_meta.get("team_iso3") or home_squad.get("team_iso3") or home),
        str(away_snapshot_iso3 or away_meta.get("team_iso3") or away_squad.get("team_iso3") or away),
    )


def _fit_artifacts_from_snapshot(
    model_input_snapshot: dict[str, Any],
    model_diagnostics: dict[str, Any],
    home_key: str,
    away_key: str,
    team_strengths: list[dict[str, Any]],
) -> FitArtifacts:
    payload = (
        model_input_snapshot.get("fitted_artifacts")
        or model_input_snapshot.get("fit_artifacts")
        or model_diagnostics.get("fitted_artifacts")
    )
    if isinstance(payload, dict) and payload:
        return _calibrated_fit_artifacts_from_dict(payload)

    home_strength = team_strengths[0] if team_strengths else {}
    away_strength = team_strengths[1] if len(team_strengths) > 1 else {}
    home_xg = _strength_prior_xg(home_strength, away_strength, home=True)
    away_xg = _strength_prior_xg(away_strength, home_strength, home=False)
    return FitArtifacts(
        model=None,
        fit_status=str(model_diagnostics.get("fit_status") or "fallback_prior"),
        data_sufficiency=str(model_diagnostics.get("data_sufficiency") or "partial"),
        model_name=str(model_diagnostics.get("model_name") or "strength_prior"),
        diagnostics={**model_diagnostics, "fallback_reason": "missing_fitted_artifacts"},
        home_advantage=0.08,
        xg_priors={home_key: home_xg, away_key: away_xg},
    )


def _calibrate_matchup_xg(
    home_xg: float,
    away_xg: float,
    *,
    home_model_key: str,
    away_model_key: str,
    team_strengths: list[dict[str, Any]],
    model_input_snapshot: dict[str, Any],
    fit_artifacts: FitArtifacts,
) -> tuple[float, float, dict[str, Any] | None]:
    if home_xg <= 0 or away_xg <= 0:
        return home_xg, away_xg, None

    if fit_artifacts.model_name not in {"dixon_coles_decay", "hierarchical_smoothed", "strength_prior"}:
        return home_xg, away_xg, None

    components: list[tuple[str, float, float]] = [("model_xg", math.log(home_xg / away_xg), 0.60)]
    elo_log_ratio = _elo_log_ratio(home_model_key, away_model_key)
    if elo_log_ratio is not None:
        components.append(("national_elo", _clip(elo_log_ratio, -1.6, 1.6), 0.30))

    roster_log_ratio = _roster_strength_log_ratio(team_strengths, model_input_snapshot)
    if roster_log_ratio is not None:
        components.append(("roster_strength", _clip(roster_log_ratio, -1.1, 1.1), 0.10))

    if len(components) == 1:
        return home_xg, away_xg, None

    total_weight = sum(weight for _source, _value, weight in components) or 1.0
    final_log_ratio = sum(value * weight for _source, value, weight in components) / total_weight
    total_xg = home_xg + away_xg
    home_share = math.exp(final_log_ratio) / (1 + math.exp(final_log_ratio))
    calibrated_home = _clip(total_xg * home_share, 0.3, 4.5)
    calibrated_away = _clip(total_xg - calibrated_home, 0.3, 4.5)
    adjusted_total = calibrated_home + calibrated_away
    if adjusted_total > 0 and abs(adjusted_total - total_xg) > 0.001:
        scale = total_xg / adjusted_total
        calibrated_home = _clip(calibrated_home * scale, 0.3, 4.5)
        calibrated_away = _clip(calibrated_away * scale, 0.3, 4.5)

    if abs(calibrated_home - home_xg) < 0.015 and abs(calibrated_away - away_xg) < 0.015:
        return home_xg, away_xg, None

    return (
        round(calibrated_home, 4),
        round(calibrated_away, 4),
        {
            "source": "matchup_quality_prior_v1",
            "base_xg": {"home": round(home_xg, 4), "away": round(away_xg, 4)},
            "calibrated_xg": {"home": round(calibrated_home, 4), "away": round(calibrated_away, 4)},
            "components": [
                {"source": source, "log_ratio": round(value, 4), "weight": weight}
                for source, value, weight in components
            ],
        },
    )


def _elo_log_ratio(home_model_key: str, away_model_key: str) -> float | None:
    home_iso3 = _iso3_or_none(home_model_key)
    away_iso3 = _iso3_or_none(away_model_key)
    if not home_iso3 or not away_iso3:
        return None
    try:
        elo = _national_elo_snapshot()
        if home_iso3 not in elo or away_iso3 not in elo:
            return None
        home_xg, away_xg = NationalElo().elo_to_lambda(
            elo[home_iso3],
            elo[away_iso3],
            neutral=True,
            home_iso3=home_iso3,
            host_iso3=None,
        )
    except Exception:
        return None
    if home_xg <= 0 or away_xg <= 0:
        return None
    return math.log(home_xg / away_xg)


@lru_cache(maxsize=1)
def _national_elo_snapshot() -> dict[str, float]:
    df = NationalElo().as_dataframe(offline=True)
    return {str(row.team_iso3): float(row.elo_rating) for row in df.itertuples(index=False)}


def _roster_strength_log_ratio(
    team_strengths: list[dict[str, Any]],
    model_input_snapshot: dict[str, Any],
) -> float | None:
    values: list[float] = []
    squads = model_input_snapshot.get("squads") if isinstance(model_input_snapshot, dict) else {}
    if isinstance(squads, dict):
        home_overall = _squad_avg_overall(squads.get("home") or {})
        away_overall = _squad_avg_overall(squads.get("away") or {})
        if home_overall is not None and away_overall is not None:
            values.append((home_overall - away_overall) / 16.0)

    if len(team_strengths) >= 2:
        home_composite = _strength_composite(team_strengths[0])
        away_composite = _strength_composite(team_strengths[1])
        values.append((home_composite - away_composite) / 22.0)

    if not values:
        return None
    return sum(values) / len(values)


def _squad_avg_overall(team: dict[str, Any]) -> float | None:
    stats = team.get("stats") if isinstance(team, dict) else None
    if isinstance(stats, dict):
        value = stats.get("avg_overall")
        if value is not None:
            return _coerce_float(value, 0.0)

    players = team.get("players") if isinstance(team, dict) else []
    values = [
        _coerce_float((player.get("derived") or {}).get("overall"), 0.0)
        for player in (players or [])
        if (player.get("derived") or {}).get("overall") is not None
    ]
    if not values:
        return None
    return sum(values) / len(values)


def _strength_composite(row: dict[str, Any]) -> float:
    return (
        0.34 * _coerce_float(row.get("attack_rating"), 66.0)
        + 0.26 * _coerce_float(row.get("defense_rating"), 66.0)
        + 0.14 * _coerce_float(row.get("goalkeeper_rating"), 66.0)
        + 0.13 * _coerce_float(row.get("transition_rating"), 66.0)
        + 0.13 * _coerce_float(row.get("set_piece_rating"), 66.0)
    )


def _iso3_or_none(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    if len(text) == 3 and text.isascii() and text.isalpha() and text not in {"HOM", "AWY"}:
        return text
    return None


def _calibrated_fit_artifacts_from_dict(payload: dict[str, Any]) -> FitArtifacts:
    artifacts = FitArtifacts.from_dict(payload)
    if artifacts.model_name != "dixon_coles_decay" or artifacts.intercept != 0.0:
        return artifacts
    if not artifacts.attack_coef or not artifacts.defense_coef:
        return artifacts

    attack, defense = _runtime_shrink_dc_coefficients(
        artifacts.attack_coef,
        artifacts.defense_coef,
        artifacts.diagnostics,
    )
    intercept = _runtime_dc_intercept(attack, defense)
    if intercept == 0.0 and attack == artifacts.attack_coef and defense == artifacts.defense_coef:
        return artifacts

    return FitArtifacts(
        model=artifacts.model,
        fit_status=artifacts.fit_status,
        data_sufficiency=artifacts.data_sufficiency,
        model_name=artifacts.model_name,
        diagnostics={
            **artifacts.diagnostics,
            "runtime_calibration": "legacy_dc_v3",
            "runtime_intercept": intercept,
        },
        home_advantage=artifacts.home_advantage,
        xg_priors=artifacts.xg_priors,
        attack_coef=attack,
        defense_coef=defense,
        intercept=intercept,
    )


def _runtime_shrink_dc_coefficients(
    attack: dict[str, float],
    defense: dict[str, float],
    diagnostics: dict[str, Any],
) -> tuple[dict[str, float], dict[str, float]]:
    raw_counts = (diagnostics or {}).get("team_match_count") or {}
    if not isinstance(raw_counts, dict) or not raw_counts:
        return attack, defense

    prior_matches = 16.0
    full_sample_matches = 40

    def factor(team: str) -> float:
        try:
            n_matches = float(raw_counts.get(team) or raw_counts.get(str(team).upper()) or 0.0)
        except (TypeError, ValueError):
            n_matches = 0.0
        return 1.0 if n_matches >= full_sample_matches else n_matches / (n_matches + prior_matches)

    return (
        {team: float(coef) * factor(team) for team, coef in attack.items()},
        {team: float(coef) * factor(team) for team, coef in defense.items()},
    )


def _runtime_dc_intercept(attack: dict[str, float], defense: dict[str, float]) -> float:
    raw_rates = [
        math.exp(float(attack_coef) + float(defense_coef))
        for home_team, attack_coef in attack.items()
        for away_team, defense_coef in defense.items()
        if home_team != away_team
    ]
    if not raw_rates:
        return 0.0
    median_rate = float(np.median(raw_rates))
    if median_rate <= 0:
        return 0.0
    return _clip(math.log(1.35 / median_rate), -0.45, 0.45)


def _strength_prior_xg(attack_strength: dict[str, Any], defense_strength: dict[str, Any], *, home: bool) -> float:
    attack = float(attack_strength.get("attack_rating") or 66)
    defense = float(defense_strength.get("defense_rating") or 66)
    goalkeeper = float(defense_strength.get("goalkeeper_rating") or 66)
    base = 1.25 + (attack - defense) / 70.0 + (attack - goalkeeper) / 120.0
    if home:
        base += 0.12
    return round(max(0.3, min(4.5, base)), 4)


def _squads_from_snapshot_or_fallback(
    model_input_snapshot: dict[str, Any],
    home: str,
    away: str,
    team_strengths: list[dict[str, Any]],
) -> tuple[TeamRoster, TeamRoster]:
    squads = model_input_snapshot.get("squads")
    if isinstance(squads, dict) and squads.get("home") and squads.get("away"):
        loaded = RosterLoader().from_snapshot(squads)
        if loaded[0].players and loaded[1].players:
            return loaded
    home_strength = team_strengths[0] if team_strengths else {}
    away_strength = team_strengths[1] if len(team_strengths) > 1 else {}
    return (
        _fallback_roster("HOM", home, home_strength),
        _fallback_roster("AWY", away, away_strength),
    )


def _fallback_roster(iso3: str, team_name: str, strength: dict[str, Any]) -> TeamRoster:
    positions = ["GK", "CB", "CB", "FB", "FB", "DM", "CM", "AM", "WG", "WG", "ST"]
    bench_positions = ["GK", "CB", "FB", "DM", "CM", "AM", "WG", "ST"]
    players = [
        _fallback_player(iso3, team_name, index + 1, position, "starter", 0.92, strength)
        for index, position in enumerate(positions)
    ]
    players.extend(
        _fallback_player(iso3, team_name, index + 12, position, "bench", 0.25, strength)
        for index, position in enumerate(bench_positions)
    )
    return TeamRoster(iso3=iso3, team_fifa=team_name, players=players)


def _fallback_player(
    iso3: str,
    team_name: str,
    number: int,
    position: str,
    role: str,
    minutes_share: float,
    strength: dict[str, Any],
) -> PlayerSnapshot:
    attack = float(strength.get("attack_rating") or 66)
    defense = float(strength.get("defense_rating") or 66)
    passing = float(strength.get("possession_rating") or 66)
    set_piece = float(strength.get("set_piece_rating") or 66)
    gk = float(strength.get("goalkeeper_rating") or 66)
    if position == "GK":
        derived = {"overall": gk, "attack": 20, "defense": defense, "finishing": 20, "passing": passing, "set_piece": 45, "gk": gk}
    else:
        derived = {
            "overall": round((attack + defense + passing) / 3, 2),
            "attack": attack,
            "defense": defense,
            "finishing": attack + (8 if position in {"ST", "WG"} else 0),
            "passing": passing,
            "set_piece": set_piece,
            "gk": 0,
        }
    return PlayerSnapshot(
        id=f"{iso3}_{number:02d}",
        name=f"{team_name}{number}号",
        name_en=f"{iso3} Player {number}",
        position_primary=position,
        position_class="GK" if position == "GK" else "DF" if position in {"CB", "FB"} else "MF" if position in {"DM", "CM", "AM"} else "FW",
        age=26,
        derived=derived,
        expected_role=role,
        expected_minutes_share=minutes_share,
        availability={"status": "available"},
        shirt_number=number,
        club_fifa=None,
    )


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


def _stage_from_competition_text(text: str) -> str | None:
    if re.search(r"小组赛|group stage|\bgroup\b", text, re.I):
        return "group"
    if re.search(r"半决赛|semi[-_ ]?final|semifinal", text, re.I):
        return "semi_final"
    if re.search(r"四分之一决赛|quarter[-_ ]?final|quarterfinal|八强", text, re.I):
        return "quarter_final"
    if re.search(r"八分之一决赛|round of 16|last 16|16强|十六强", text, re.I):
        return "round_of_16"
    if re.search(r"三四名|季军赛|third[-_ ]?place", text, re.I):
        return "third_place"
    if re.search(r"决赛|final", text, re.I):
        return "final"
    return None


def _competition_payload(model_input_snapshot: dict[str, Any]) -> dict[str, Any]:
    raw = None
    if isinstance(model_input_snapshot, dict):
        raw = model_input_snapshot.get("competition_meta") or model_input_snapshot.get("competition")
    if isinstance(raw, dict):
        return {**raw, "knockout": bool(raw.get("knockout"))}
    name = str(raw or "")
    stage = _stage_from_competition_text(name)
    knockout = any(token in name.lower() for token in ("knockout", "final", "semi-final", "quarter-final")) or any(
        token in name for token in ("淘汰", "决赛", "半决赛", "四分之一")
    )
    return {"name": name, "stage": stage, "knockout": knockout}


def _normalized_competition_payload(model_input_snapshot: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    competition = dict(_competition_payload(model_input_snapshot))
    warnings: list[str] = []
    stage = _normalize_prediction_stage(competition.get("stage"))
    if stage in _PREDICTION_KNOCKOUT_STAGES and _snapshot_has_group_stage_evidence(model_input_snapshot):
        stage = "group"
        warnings.append("competition_stage_conflict_kept_group")
    if stage:
        competition["stage"] = stage
    if stage == "group":
        if bool(competition.get("knockout")):
            warnings.append("competition_knockout_overridden_for_group_stage")
        competition["knockout"] = False
    elif stage in _PREDICTION_KNOCKOUT_STAGES:
        competition["knockout"] = True
    else:
        competition["knockout"] = bool(competition.get("knockout"))
    return competition, warnings


def _snapshot_has_group_stage_evidence(model_input_snapshot: dict[str, Any]) -> bool:
    if not isinstance(model_input_snapshot, dict):
        return False
    snippets: list[str] = []
    for key in ("prediction_requirement", "source_text", "raw_text"):
        value = model_input_snapshot.get(key)
        if value:
            snippets.append(str(value))
    extracted = model_input_snapshot.get("extracted") or {}
    if isinstance(extracted, dict):
        snippets.extend(str(item) for item in extracted.get("key_narratives") or [])
    structured = model_input_snapshot.get("structured_inputs") or {}
    if isinstance(structured, dict):
        snippets.extend(str(item) for item in structured.get("structured_recent_matches") or [])
    text = "\n".join(snippets)
    return bool(re.search(r"小组赛|Group\s+[A-L]\b|group stage|\bgroup\b", text, re.I))


def _scenario_seed(base_seed: int, scenario_key: str) -> int:
    digest = hashlib.sha1(str(scenario_key).encode("utf-8")).hexdigest()
    return (int(base_seed) + int(digest[:8], 16)) % (2**31 - 1)


def _rounded_probabilities(value: dict[str, Any]) -> dict[str, float]:
    return {
        "home_win": round(float(value.get("home_win", 0.0)), 4),
        "draw": round(float(value.get("draw", 0.0)), 4),
        "away_win": round(float(value.get("away_win", 0.0)), 4),
    }


def _normalized_wdl_from_scoreline(scoreline: dict[str, Any]) -> dict[str, float]:
    values = [
        float(scoreline.get("home_win_probability") or 0),
        float(scoreline.get("draw_probability") or 0),
        float(scoreline.get("away_win_probability") or 0),
    ]
    if any(value > 1 for value in values):
        total = sum(values) or 100.0
        return {
            "home_win": values[0] / total,
            "draw": values[1] / total,
            "away_win": values[2] / total,
        }
    total = sum(values) or 1.0
    return {
        "home_win": values[0] / total,
        "draw": values[1] / total,
        "away_win": values[2] / total,
    }


def _weighted_scoreline_summary(
    scenario_cases: list[dict[str, Any]],
    scorelines: list[dict[str, Any]],
    *,
    competition: dict[str, Any] | None = None,
    team_strengths: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    cases_by_id = {case.get("id"): case for case in scenario_cases}
    rows = [row for row in scorelines if row.get("scenario_case_id") in cases_by_id]
    if not rows:
        return {
            "most_likely_score": None,
            "win_draw_loss_probability": {"home_win": 0.0, "draw": 0.0, "away_win": 0.0},
            "top_score_candidates": [],
            "weighted_scoreline_distribution": [],
            "near_tie": False,
            "adjustments": [],
            "source": "scenario_weighted_scoreline_v1",
        }

    weights = {
        row.get("scenario_case_id"): max(0.0, float(cases_by_id[row.get("scenario_case_id")].get("weight") or 0.0))
        for row in rows
    }
    total_weight = sum(weights.values())
    if total_weight <= 0:
        weights = {row.get("scenario_case_id"): 1.0 for row in rows}
        total_weight = float(len(rows))

    distribution: dict[str, float] = {}
    wdl = {"home_win": 0.0, "draw": 0.0, "away_win": 0.0}
    for row in rows:
        scenario_case_id = row.get("scenario_case_id")
        weight = weights.get(scenario_case_id, 0.0) / total_weight
        row_wdl = _normalized_wdl_from_scoreline(row)
        for key in wdl:
            wdl[key] += weight * float(row_wdl.get(key) or 0.0)

        row_distribution = row.get("scoreline_distribution") or []
        if not row_distribution and row.get("most_likely_score"):
            row_distribution = [{"score": row["most_likely_score"], "probability": 1.0}]
        for item in row_distribution:
            score = str(item.get("score") or "")
            if not score:
                continue
            distribution[score] = distribution.get(score, 0.0) + weight * float(item.get("probability") or 0.0)

    total_distribution = sum(distribution.values())
    if total_distribution > 0:
        distribution = {score: probability / total_distribution for score, probability in distribution.items()}

    adjustments = _apply_scoreline_settlement_adjustments(
        distribution,
        wdl,
        scenario_cases=[cases_by_id[row.get("scenario_case_id")] for row in rows],
        competition=competition,
        team_strengths=team_strengths,
    )
    weighted_distribution = [
        {"score": score, "probability": round(probability, 4)}
        for score, probability in sorted(distribution.items(), key=lambda item: (-item[1], item[0]))
    ]
    top_score_candidates = weighted_distribution[:5]
    top_probability = top_score_candidates[0]["probability"] if top_score_candidates else 0.0
    second_probability = top_score_candidates[1]["probability"] if len(top_score_candidates) > 1 else 0.0
    return {
        "most_likely_score": top_score_candidates[0]["score"] if top_score_candidates else None,
        "win_draw_loss_probability": _rounded_wdl_triplet(wdl),
        "top_score_candidates": top_score_candidates,
        "weighted_scoreline_distribution": weighted_distribution,
        "near_tie": bool(top_score_candidates and len(top_score_candidates) > 1 and abs(top_probability - second_probability) <= 0.02),
        "adjustments": adjustments,
        "source": "scenario_weighted_scoreline_v1",
    }


def _apply_scoreline_settlement_adjustments(
    distribution: dict[str, float],
    wdl: dict[str, float],
    *,
    scenario_cases: list[dict[str, Any]],
    competition: dict[str, Any] | None,
    team_strengths: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if len(distribution) < 2:
        return []

    expected_goals = _weighted_expected_goals(scenario_cases)
    adjustments: list[dict[str, Any]] = []
    if _is_favorite_blowout_profile(wdl, expected_goals, team_strengths=team_strengths):
        adjustment = _apply_mismatch_blowout_tail_adjustment(distribution, expected_goals)
        if adjustment:
            adjustments.append(adjustment)

    if (competition or {}).get("stage") != "group":
        return adjustments

    adjustment = _apply_group_close_game_equalizer_adjustment(distribution, wdl)
    if adjustment:
        adjustments.append(adjustment)

    adjustment = _apply_low_total_late_winner_adjustment(distribution, wdl, expected_goals)
    if adjustment:
        adjustments.append(adjustment)

    adjustment = _apply_group_resilient_equalizer_adjustment(distribution, wdl, expected_goals)
    if adjustment:
        adjustments.append(adjustment)

    return adjustments


def _apply_group_close_game_equalizer_adjustment(
    distribution: dict[str, float],
    wdl: dict[str, float],
) -> dict[str, Any] | None:
    sorted_scores = sorted(distribution.items(), key=lambda item: (-item[1], item[0]))
    top_score, top_probability = sorted_scores[0]
    parsed = _parse_scoreline(top_score)
    if parsed is None:
        return None
    home_goals, away_goals = parsed
    if abs(home_goals - away_goals) != 1:
        return None

    equalized_goals = max(home_goals, away_goals)
    draw_score = f"{equalized_goals}-{equalized_goals}"
    draw_probability = distribution.get(draw_score)
    if draw_probability is None:
        return None

    gap = top_probability - draw_probability
    if gap < 0 or gap > 0.025:
        return None

    shift = min(top_probability * 0.12, gap / 2 + 0.003)
    if shift <= 0:
        return None

    distribution[top_score] = max(0.0, distribution[top_score] - shift)
    distribution[draw_score] = distribution.get(draw_score, 0.0) + shift
    if home_goals > away_goals:
        wdl["home_win"] = max(0.0, wdl.get("home_win", 0.0) - shift)
    else:
        wdl["away_win"] = max(0.0, wdl.get("away_win", 0.0) - shift)
    wdl["draw"] = wdl.get("draw", 0.0) + shift

    return {
        "reason": "group_stage_close_game_equalizer",
        "from_score": top_score,
        "to_score": draw_score,
        "probability_shift": round(shift, 4),
        "trigger": "one_goal_lead_draw_candidate_near_tie",
    }


def _apply_low_total_late_winner_adjustment(
    distribution: dict[str, float],
    wdl: dict[str, float],
    expected_goals: dict[str, float],
) -> dict[str, Any] | None:
    sorted_scores = sorted(distribution.items(), key=lambda item: (-item[1], item[0]))
    if not sorted_scores or sorted_scores[0][0] != "0-0":
        return None
    total_xg = expected_goals["home"] + expected_goals["away"]
    if total_xg < 1.35 or total_xg > 2.45:
        return None

    candidates = [
        ("1-0", distribution.get("1-0", 0.0), "home_win"),
        ("0-1", distribution.get("0-1", 0.0), "away_win"),
    ]
    target_score, target_probability, wdl_key = max(candidates, key=lambda item: item[1])
    if target_probability <= 0:
        return None

    top_probability = sorted_scores[0][1]
    gap = top_probability - target_probability
    if gap < 0 or gap > 0.08:
        return None

    shift = min(0.05, max(0.006, gap + 0.006))
    distribution["0-0"] = max(0.0, distribution["0-0"] - shift)
    distribution[target_score] = distribution.get(target_score, 0.0) + shift
    wdl["draw"] = max(0.0, wdl.get("draw", 0.0) - shift)
    wdl[wdl_key] = wdl.get(wdl_key, 0.0) + shift
    return {
        "reason": "low_total_late_winner_bias",
        "from_score": "0-0",
        "to_score": target_score,
        "probability_shift": round(shift, 4),
        "trigger": "nil_nil_top_with_nearby_one_goal_result",
    }


def _apply_group_resilient_equalizer_adjustment(
    distribution: dict[str, float],
    wdl: dict[str, float],
    expected_goals: dict[str, float],
) -> dict[str, Any] | None:
    total_xg = expected_goals["home"] + expected_goals["away"]
    if total_xg < 2.55 or abs(expected_goals["home"] - expected_goals["away"]) > 0.45:
        return None
    target_score = "2-2"
    target_probability = distribution.get(target_score)
    if target_probability is None or target_probability < 0.04:
        return None

    sorted_scores = sorted(distribution.items(), key=lambda item: (-item[1], item[0]))
    if not sorted_scores:
        return None
    top_score, top_probability = sorted_scores[0]
    shifted = 0.0
    from_score = top_score
    if top_score != target_score:
        gap = top_probability - target_probability
        if gap < 0 or gap > 0.055:
            return None
        shifted = min(0.06, gap + 0.006)
        distribution[top_score] = max(0.0, distribution[top_score] - shifted)
        distribution[target_score] = distribution.get(target_score, 0.0) + shifted

    max_non_draw_key = "home_win" if wdl.get("home_win", 0.0) >= wdl.get("away_win", 0.0) else "away_win"
    max_non_draw = float(wdl.get(max_non_draw_key, 0.0))
    if wdl.get("draw", 0.0) <= max_non_draw:
        wdl_shift = min(0.08, max_non_draw - float(wdl.get("draw", 0.0)) + 0.01)
        wdl[max_non_draw_key] = max(0.0, wdl.get(max_non_draw_key, 0.0) - wdl_shift)
        wdl["draw"] = wdl.get("draw", 0.0) + wdl_shift
        shifted = max(shifted, wdl_shift)

    if shifted <= 0 and top_score == target_score:
        shifted = 0.001

    return {
        "reason": "group_stage_resilient_equalizer",
        "from_score": from_score,
        "to_score": target_score,
        "probability_shift": round(shifted, 4),
        "trigger": "balanced_high_tempo_draw_candidate",
    }


def _apply_mismatch_blowout_tail_adjustment(
    distribution: dict[str, float],
    expected_goals: dict[str, float],
) -> dict[str, Any] | None:
    favorite = "home" if expected_goals["home"] >= expected_goals["away"] else "away"
    favorite_xg = expected_goals[favorite]
    underdog = "away" if favorite == "home" else "home"
    underdog_xg = expected_goals[underdog]
    underdog_goals = 1 if underdog_xg >= 0.45 else 0
    favorite_goals = 7 if favorite_xg >= 2.3 and underdog_goals >= 1 else int(_clip(round(favorite_xg + 4.0), 6, 7))
    candidate = f"{favorite_goals}-{underdog_goals}" if favorite == "home" else f"{underdog_goals}-{favorite_goals}"
    distribution.setdefault(candidate, 0.0)

    sorted_scores = sorted(distribution.items(), key=lambda item: (-item[1], item[0]))
    if not sorted_scores or sorted_scores[0][0] == candidate:
        return None

    top_probability = sorted_scores[0][1]
    target_probability = distribution.get(candidate, 0.0)
    needed = max(0.0, top_probability - target_probability + 0.006)
    if needed <= 0:
        return None

    collected = 0.0
    for score, probability in sorted_scores:
        if score == candidate or collected >= needed:
            continue
        parsed = _parse_scoreline(score)
        if parsed is None:
            continue
        home_goals, away_goals = parsed
        is_favorite_win = home_goals > away_goals if favorite == "home" else away_goals > home_goals
        if not is_favorite_win:
            continue
        total_goals = home_goals + away_goals
        if total_goals > 5:
            continue
        amount = min(probability * 0.45, needed - collected)
        if amount <= 0:
            continue
        distribution[score] = max(0.0, distribution[score] - amount)
        collected += amount

    if collected <= 0:
        return None
    distribution[candidate] = distribution.get(candidate, 0.0) + collected
    return {
        "reason": "mismatch_blowout_tail",
        "from_score": "low_margin_favorite_wins",
        "to_score": candidate,
        "probability_shift": round(collected, 4),
        "trigger": "heavy_favorite_high_xg_tail",
    }


def _weighted_expected_goals(scenario_cases: list[dict[str, Any]]) -> dict[str, float]:
    total_weight = sum(max(0.0, float(case.get("weight") or 0.0)) for case in scenario_cases)
    if total_weight <= 0:
        total_weight = float(len(scenario_cases) or 1)
        weights = [1.0 for _case in scenario_cases]
    else:
        weights = [max(0.0, float(case.get("weight") or 0.0)) for case in scenario_cases]

    home = away = 0.0
    for case, weight in zip(scenario_cases, weights, strict=False):
        expected = case.get("expected_goals") or {}
        home += (weight / total_weight) * _coerce_float(expected.get("home"), 0.0)
        away += (weight / total_weight) * _coerce_float(expected.get("away"), 0.0)
    return {"home": home, "away": away}


def _is_favorite_blowout_profile(
    wdl: dict[str, float],
    expected_goals: dict[str, float],
    *,
    team_strengths: list[dict[str, Any]] | None = None,
) -> bool:
    home_xg = expected_goals["home"]
    away_xg = expected_goals["away"]
    strength_gap = _team_strength_gap(team_strengths)
    if max(home_xg, away_xg) < 2.4 and strength_gap < 18:
        return False
    if abs(home_xg - away_xg) < 1.25 and strength_gap < 18:
        return False
    favorite_key = "home_win" if home_xg >= away_xg else "away_win"
    return float(wdl.get(favorite_key, 0.0)) >= 0.70


def _team_strength_gap(team_strengths: list[dict[str, Any]] | None) -> float:
    if not team_strengths or len(team_strengths) < 2:
        return 0.0

    def composite(row: dict[str, Any]) -> float:
        return (
            0.42 * _coerce_float(row.get("attack_rating"), 66.0)
            + 0.24 * _coerce_float(row.get("defense_rating"), 66.0)
            + 0.14 * _coerce_float(row.get("goalkeeper_rating"), 66.0)
            + 0.10 * _coerce_float(row.get("transition_rating"), 66.0)
            + 0.10 * _coerce_float(row.get("set_piece_rating"), 66.0)
        )

    return abs(composite(team_strengths[0]) - composite(team_strengths[1]))


def _parse_scoreline(score: Any) -> tuple[int, int] | None:
    match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", str(score or ""))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _rounded_wdl_triplet(values: dict[str, float]) -> dict[str, float]:
    total = sum(float(values.get(key) or 0.0) for key in ("home_win", "draw", "away_win"))
    if total <= 0:
        return {"home_win": 0.0, "draw": 0.0, "away_win": 0.0}
    home_win = round(float(values.get("home_win") or 0.0) / total, 4)
    draw = round(float(values.get("draw") or 0.0) / total, 4)
    away_win = round(max(0.0, 1.0 - home_win - draw), 4)
    return {"home_win": home_win, "draw": draw, "away_win": away_win}


def _rounded_distribution(distribution: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"score": str(item.get("score")), "probability": round(float(item.get("probability") or 0.0), 4)}
        for item in distribution
    ]


def _public_event_type(event_type: str) -> str:
    if event_type in {"GOAL", "ET_GOAL"}:
        return "GOAL"
    if event_type == "CARD":
        return "YELLOW_CARD"
    if event_type == "PSO":
        return "PENALTY_SHOOTOUT"
    if event_type in MATCH_EVENT_TYPES:
        return event_type
    return "TACTICAL_PHASE"


def _event_confidence(event_type: str) -> int:
    return {
        "GOAL": 72,
        "SHOT": 58,
        "SAVE": 58,
        "CHANCE_CREATED": 58,
        "YELLOW_CARD": 48,
        "PENALTY_SHOOTOUT": 62,
    }.get(event_type, 55)


def _score_text(score_after: Any) -> str | None:
    if isinstance(score_after, dict):
        return f"{int(score_after.get('home', 0))}-{int(score_after.get('away', 0))}"
    if isinstance(score_after, (tuple, list)) and len(score_after) == 2:
        return f"{int(score_after[0])}-{int(score_after[1])}"
    return None


def _coach_review_confidence(review: dict[str, Any]) -> int:
    values = []
    for item in review.get("reviews") or []:
        try:
            values.append(int(item.get("confidence")))
        except (TypeError, ValueError):
            pass
    if not values:
        return 58
    return round(sum(values) / len(values))


def _run_knockout_distribution(sim_results: dict[str, SimulationResult]) -> dict[str, float] | None:
    merged: dict[str, float] = {}
    count = 0
    for result in sim_results.values():
        if not result.knockout_path_distribution:
            continue
        count += 1
        for key, value in result.knockout_path_distribution.items():
            merged[key] = merged.get(key, 0.0) + float(value)
    if count == 0:
        return None
    return {key: round(value / count, 4) for key, value in sorted(merged.items())}


def _stable_number(text: str, low: int, high: int) -> int:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    span = high - low + 1
    return low + (int(digest[:8], 16) % span)


def _runtime_case_id(prediction_run_id: str, scenario_key: str) -> str:
    digest = hashlib.sha1(f"{prediction_run_id}:{scenario_key}".encode("utf-8")).hexdigest()[:32]
    return str(uuid.UUID(digest))


def _state_factor(state: str) -> float:
    return {"underperform": 0.76, "normal": 1.0, "overperform": 1.24}[state]


def _wld_probabilities(home_xg: float, away_xg: float) -> dict[str, float]:
    diff = home_xg - away_xg
    home = min(0.68, max(0.18, 0.38 + diff * 0.16))
    away = min(0.62, max(0.14, 0.32 - diff * 0.14))
    draw = max(0.18, 1.0 - home - away)
    total = home + draw + away
    return {
        "home_win": round(home / total, 4),
        "draw": round(draw / total, 4),
        "away_win": round(away / total, 4),
    }


def _score_distribution(home_xg: float, away_xg: float) -> list[dict[str, Any]]:
    home_goal = max(0, min(4, round(home_xg)))
    away_goal = max(0, min(4, round(away_xg)))
    scores = [
        (home_goal, away_goal, 0.32),
        (max(0, home_goal - 1), away_goal, 0.18),
        (home_goal, max(0, away_goal - 1), 0.16),
        (home_goal + 1, away_goal, 0.13),
        (home_goal, away_goal + 1, 0.11),
    ]
    return [
        {"score": f"{home}-{away}", "probability": probability}
        for home, away, probability in scores
    ]


def _total_goals_distribution(distribution: list[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for item in distribution:
        left, right = item["score"].split("-")
        total = int(left) + int(right)
        bucket = str(total) if total < 5 else "5+"
        totals[bucket] = round(totals.get(bucket, 0) + item["probability"], 4)
    return totals


def _space_drivers(key: str) -> list[str]:
    return {
        "baseline": ["正常发挥", "控球推进", "压迫强度", "射门质量", "定位球", "常规换人", "比分更新"],
        "home_upside": ["主队压迫", "边路突破", "定位球优势", "主场气势", "早进球"],
        "away_upside": ["客队反击", "门将超常", "主队后场失误", "客队定位球"],
        "home_error": ["主队传控失误", "后防沟通", "犯规压力", "换人失败"],
        "away_error": ["客队防线失位", "体能下降", "红黄牌风险", "出球困难"],
        "volatility": ["点球", "VAR", "红牌", "伤退", "天气", "裁判尺度", "早进球"],
    }[key]


def _space_risks(key: str) -> list[str]:
    return {
        "baseline": ["资料不足会降低基准置信度"],
        "home_upside": ["早段机会转化率不足"],
        "away_upside": ["反击效率波动"],
        "home_error": ["主队纪律风险"],
        "away_error": ["客队体能风险"],
        "volatility": ["点球/VAR", "红牌", "伤退", "天气", "裁判尺度"],
    }[key]


def _event(
    prediction_run_id: str,
    minute: int,
    event_type: str,
    scenario_space: str,
    scenario_module: str,
    team: str | None,
    player: str | None,
    description: str,
    confidence: int,
    score: str | None,
    *,
    scenario_case_id: str | None = None,
    config_scenario_case_id: str | None = None,
    scenario_key: str | None = None,
    actor_player_id: str | None = None,
    assist_player_id: str | None = None,
    sim_seed: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event_metadata = {
        "source": "match_event_engine_v2",
        "scenario_key": scenario_key,
        "config_scenario_case_id": config_scenario_case_id,
        **(metadata or {}),
    }
    return {
        "prediction_run_id": prediction_run_id,
        "scenario_case_id": scenario_case_id,
        "round_num": minute // 15,
        "minute": minute,
        "event_type": event_type,
        "scenario_space": scenario_space,
        "scenario_module": scenario_module,
        "team": team,
        "player": player,
        "actor_player_id": actor_player_id,
        "assist_player_id": assist_player_id,
        "sim_seed": sim_seed,
        "description": description,
        "confidence": confidence,
        "score": score,
        "evidence": [{"type": "model_event", "description": scenario_module}],
        "metadata": event_metadata,
    }


def _note(
    prediction_run_id: str,
    role: str,
    scenario_space: str,
    claim: str,
    reasoning: str,
    confidence: int,
    *,
    scenario_case_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "prediction_run_id": prediction_run_id,
        "scenario_case_id": scenario_case_id,
        "agent_role": role,
        "scenario_space": scenario_space,
        "related_event_id": None,
        "claim": claim,
        "reasoning": reasoning,
        "evidence": [{"type": "prediction_artifact", "scenario_space": scenario_space}],
        "confidence": confidence,
        "metadata": {"source": "analyst_reasoning_engine_v2", **(metadata or {})},
    }


def _without(row: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in set(keys)}


def _config_record_to_engine_dict(config: PredictionConfigRecord) -> dict[str, Any]:
    model_input = config.model_input_snapshot or {}
    model_diagnostics = (
        model_input.get("scientific_model_diagnostics")
        or (config.config_metadata or {}).get("scientific_model_diagnostics")
        or {}
    )
    prediction_requirement = (
        model_input.get("prediction_requirement")
        or (config.config_metadata or {}).get("prediction_requirement")
        or ""
    )
    return {
        "prediction_config_id": config.prediction_config_id,
        "project_id": config.project_id,
        "graph_id": config.graph_id,
        "home_team": config.home_team,
        "away_team": config.away_team,
        "competition": config.competition,
        "prediction_requirement": prediction_requirement,
        "model_input_snapshot": model_input,
        "llm_budget_profile": _config_budget_profile(config.llm_budget_profile) or model_input.get("llm_budget"),
        "player_dataset_id": config.player_dataset_id,
        "model_diagnostics": {
            "model_name": config.model_name,
            "model_version": config.model_version,
            "fit_status": config.fit_status,
            "data_sufficiency": config.data_sufficiency,
            **model_diagnostics,
        },
    }


def _config_budget_profile(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    profile = value.get("profile")
    if isinstance(profile, dict):
        return profile
    return value


def _config_case_record_to_engine_dict(row: PredictionConfigScenarioCaseRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "home_state": row.home_state,
        "away_state": row.away_state,
        "scenario_key": row.scenario_key,
        "scenario_name": row.scenario_name,
        "scenario_space": row.scenario_space,
        "initial_weight": row.initial_weight,
        "final_weight": row.final_weight,
        "key_drivers": row.key_drivers or [],
        "risk_factors": row.risk_factors or [],
        "coach_vote_summary": row.coach_vote_summary or {},
        "model_constraints": row.model_constraints or {},
    }


def _scenario_case_to_config_payload(row: PredictionScenarioCaseRecord) -> dict[str, Any]:
    metadata = row.case_metadata or {}
    return {
        "id": row.config_scenario_case_id,
        "home_state": row.home_state,
        "away_state": row.away_state,
        "scenario_key": metadata.get("scenario_key") or f"home_{row.home_state}_away_{row.away_state}",
        "scenario_name": metadata.get("scenario_name") or row.scenario_module,
        "scenario_space": row.scenario_space,
        "initial_weight": row.weight,
        "final_weight": row.weight,
        "key_drivers": metadata.get("key_drivers") or [],
        "risk_factors": metadata.get("risk_factors") or [],
        "coach_vote_summary": metadata.get("coach_vote_summary") or {},
        "model_constraints": metadata.get("model_constraints") or {},
    }


def _team_strength_to_engine_dict(row: PredictionTeamStrengthRecord) -> dict[str, Any]:
    return {
        "prediction_config_id": row.prediction_config_id,
        "team_role": row.team_role,
        "team_name": row.team_name,
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
        "confidence": row.confidence,
        "metadata": row.strength_metadata or {},
    }


def _players_for_run(session: Any, prediction_run_id: str) -> dict[str, dict[str, Any]]:
    run = session.get(PredictionRunRecord, prediction_run_id)
    if not run or not run.prediction_config_id:
        return {}
    config = session.get(PredictionConfigRecord, run.prediction_config_id)
    if not config:
        return {}
    squads = (config.model_input_snapshot or {}).get("squads") or {}
    players: dict[str, dict[str, Any]] = {}
    for role in ("home", "away"):
        team = squads.get(role) or {}
        iso3 = team.get("team_iso3")
        for player in team.get("players") or []:
            player_id = str(player.get("id") or "")
            if not player_id:
                continue
            players[player_id] = {**player, "team_iso3": iso3, "team_role": role}
    return players


def _actor_stats_for_run(session: Any, prediction_run_id: str) -> dict[str, dict[str, Any]]:
    events = (
        session.query(PredictionMatchEventRecord)
        .filter_by(prediction_run_id=prediction_run_id)
        .all()
    )
    players = _players_for_run(session, prediction_run_id)
    goals_by_player: dict[str, int] = {}
    assists_by_player: dict[str, int] = {}
    cards_by_player: dict[str, int] = {}
    for event in events:
        if event.event_type == "GOAL" and event.actor_player_id:
            goals_by_player[event.actor_player_id] = goals_by_player.get(event.actor_player_id, 0) + 1
        if event.event_type == "GOAL" and event.assist_player_id:
            assists_by_player[event.assist_player_id] = assists_by_player.get(event.assist_player_id, 0) + 1
        if event.event_type in {"YELLOW_CARD", "RED_CARD"} and event.actor_player_id:
            cards_by_player[event.actor_player_id] = cards_by_player.get(event.actor_player_id, 0) + 1

    total_goals = max(1, sum(goals_by_player.values()))
    total_assists = max(1, sum(assists_by_player.values()))
    total_cards = max(1, sum(cards_by_player.values()))
    stats: dict[str, dict[str, Any]] = {}
    for player_id, player in players.items():
        stats[player_id] = {
            "goal_share": round(goals_by_player.get(player_id, 0) / total_goals, 4),
            "assist_share": round(assists_by_player.get(player_id, 0) / total_assists, 4),
            "card_share": round(cards_by_player.get(player_id, 0) / total_cards, 4),
            "minutes_played_p50": int(round(float(player.get("expected_minutes_share") or 0) * 90)),
        }
    return stats


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
    payload = {
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
        payload["actor_stats"] = actor_stats.get(player_id) or {
            "goal_share": 0.0,
            "assist_share": 0.0,
            "card_share": 0.0,
            "minutes_played_p50": int(round(float(player.get("expected_minutes_share") or 0) * 90)),
        }
    return payload


def _ledger_contract(ledger: dict[str, Any]) -> dict[str, Any]:
    by_role = {}
    for role, summary in (ledger.get("by_role") or {}).items():
        by_role[role] = {
            "calls": int(summary.get("calls") or 0),
            "cached": int(summary.get("cached") or 0),
            "tokens": int(summary.get("tokens") or 0),
            "cost": float(summary.get("cost") or 0.0),
            "p95_ms": int(summary.get("p95_ms") or summary.get("latency_ms") or 0),
        }
    total_calls = int(ledger.get("total_calls") or 0)
    avg_latency = int(ledger.get("avg_latency_ms") or 0)
    return {
        "total_calls": total_calls,
        "cached": int(ledger.get("cached") or 0),
        "spent": int(ledger.get("spent") or total_calls),
        "hard_cap": int(ledger.get("hard_cap") or 0),
        "total_tokens": int(ledger.get("total_tokens") or 0),
        "total_cost_usd": float(ledger.get("total_cost_usd") or 0.0),
        "total_latency_ms": int(ledger.get("total_latency_ms") or avg_latency * total_calls),
        "p95_latency_ms": int(ledger.get("p95_latency_ms") or avg_latency),
        "by_role": by_role,
        "failures": ledger.get("failures") or [],
    }


def _event_player_contract(player: dict[str, Any] | None) -> dict[str, Any] | None:
    if not player:
        return None
    derived = player.get("derived") or {}
    return {
        "id": player.get("id"),
        "name": player.get("name"),
        "name_en": player.get("name_en"),
        "position": player.get("position_primary") or player.get("position"),
        "team_iso3": player.get("team_iso3"),
        "rating_snapshot": {
            key: derived.get(key)
            for key in ("overall", "finishing", "pace", "dribbling", "passing", "defense", "gk")
            if key in derived
        },
    }


def _score_after_list(score: str | None) -> list[int] | None:
    if not score or "-" not in score:
        return None
    left, right = score.split("-", 1)
    try:
        return [int(left), int(right)]
    except ValueError:
        return None


def _trajectory_id(metadata: dict[str, Any]) -> str | None:
    scenario_key = metadata.get("scenario_key")
    seed = metadata.get("sim_seed") or metadata.get("simulation_seed")
    if not scenario_key and seed is None:
        return None
    digest = hashlib.sha1(f"{scenario_key}:{seed}".encode("utf-8")).hexdigest()[:12]
    return f"modal_traj_{digest}"


def _decisive_event(events: list[PredictionMatchEventRecord]) -> PredictionMatchEventRecord | None:
    goals = [event for event in events if event.event_type == "GOAL"]
    if goals:
        return goals[-1]
    finals = [event for event in events if event.event_type == "FINAL_SCORE_HYPOTHESIS"]
    return finals[-1] if finals else None


def _event_side(event: PredictionMatchEventRecord | None) -> str | None:
    if event is None:
        return None
    metadata = event.event_metadata or {}
    side = metadata.get("side") or metadata.get("team_id")
    return str(side) if side else event.team


def _scenario_case_to_dict(
    row: PredictionScenarioCaseRecord,
    *,
    events: list[PredictionMatchEventRecord] | None = None,
    scoreline: PredictionScorelineRecord | None = None,
) -> dict[str, Any]:
    metadata = row.case_metadata or {}
    n_sims = metadata.get("n_sims")
    scenario_key = metadata.get("scenario_key")
    events = events or []
    first_goal = next((event for event in events if event.event_type == "GOAL"), None)
    decisive = _decisive_event(events)
    most_likely_score = scoreline.most_likely_score if scoreline else metadata.get("modal_final_score")
    return {
        "id": row.id,
        "prediction_run_id": row.prediction_run_id,
        "config_scenario_case_id": row.config_scenario_case_id,
        "scenario_key": scenario_key,
        "scenario_name": metadata.get("scenario_name") or row.scenario_module,
        "home_state": row.home_state,
        "away_state": row.away_state,
        "scenario_space": row.scenario_space,
        "scenario_module": row.scenario_module,
        "weight": row.weight,
        "strength_adjustments": row.strength_adjustments,
        "expected_goals": row.expected_goals,
        "win_draw_loss_probability": row.win_draw_loss_probability,
        "scoreline_distribution": row.scoreline_distribution,
        "most_likely_score": most_likely_score,
        "n_sims": n_sims,
        "modal_trajectory_summary": {
            "trajectory_id": _trajectory_id(metadata),
            "first_goal_minute": first_goal.minute if first_goal else None,
            "first_goal_side": _event_side(first_goal) if first_goal else None,
            "decisive_minute": decisive.minute if decisive else None,
            "decisive_side": _event_side(decisive) if decisive else None,
            "total_events": len(events),
            "knockout_path": metadata.get("knockout_path"),
            "knockout_path_distribution": metadata.get("knockout_path_distribution"),
        },
        "knockout_path_distribution": metadata.get("knockout_path_distribution"),
        "confidence": row.confidence,
        "evidence": row.evidence,
        "metadata": metadata,
    }


def _team_strength_to_dict(row: PredictionTeamStrengthRecord) -> dict[str, Any]:
    metadata = row.strength_metadata or {}
    return {
        "id": row.id,
        "prediction_config_id": row.prediction_config_id,
        "prediction_run_id": row.prediction_run_id,
        "team_role": row.team_role,
        "team_name": row.team_name,
        "team_iso3": metadata.get("team_iso3"),
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
        "injury_evidence_refs": metadata.get("injury_evidence_refs") or [],
        "form_evidence_refs": metadata.get("form_evidence_refs") or [],
        "home_away_adjustment_reason": metadata.get("home_away_adjustment_reason"),
        "confidence": row.confidence,
        "metadata": metadata,
    }


def _scenario_space_to_dict(row: PredictionScenarioSpaceRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "prediction_run_id": row.prediction_run_id,
        "space_key": row.space_key,
        "space_name": row.space_name,
        "weight": row.weight,
        "summary": row.summary,
        "scoreline_bias": row.scoreline_bias,
        "key_drivers": row.key_drivers or [],
        "risk_factors": row.risk_factors or [],
        "linked_scenario_case_ids": row.linked_scenario_case_ids or [],
        "confidence": row.confidence,
        "metadata": row.space_metadata or {},
    }


def _scoreline_to_dict(row: PredictionScorelineRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "prediction_run_id": row.prediction_run_id,
        "scenario_case_id": row.scenario_case_id,
        "scenario_space": row.scenario_space,
        "home_xg": row.home_xg / 100,
        "away_xg": row.away_xg / 100,
        "home_win_probability": row.home_win_probability / 100,
        "draw_probability": row.draw_probability / 100,
        "away_win_probability": row.away_win_probability / 100,
        "scoreline_distribution": row.scoreline_distribution,
        "most_likely_score": row.most_likely_score,
        "total_goals_distribution": row.total_goals_distribution,
        "confidence": row.confidence,
        "model_name": row.model_name,
        "model_version": row.model_version,
        "metadata": row.scoreline_metadata or {},
    }


def _match_event_to_dict(
    row: PredictionMatchEventRecord,
    *,
    players: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    metadata = row.event_metadata or {}
    players = players or {}
    return {
        "id": row.id,
        "prediction_run_id": row.prediction_run_id,
        "scenario_case_id": row.scenario_case_id,
        "round_num": row.round_num,
        "minute": row.minute,
        "event_type": row.event_type,
        "scenario_space": row.scenario_space,
        "scenario_module": row.scenario_module,
        "team": row.team,
        "player": row.player,
        "actor_player_id": row.actor_player_id,
        "assist_player_id": row.assist_player_id,
        "sim_seed": row.sim_seed,
        "description": row.description,
        "confidence": row.confidence,
        "score": row.score,
        "score_after": _score_after_list(row.score),
        "scenario_key": metadata.get("scenario_key"),
        "actor_player": _event_player_contract(players.get(row.actor_player_id or "")),
        "assist_player": _event_player_contract(players.get(row.assist_player_id or "")),
        "sample_provenance": {
            "scenario_key": metadata.get("scenario_key"),
            "sim_seed": row.sim_seed or metadata.get("sim_seed"),
            "trajectory_id": _trajectory_id(metadata),
        },
        "evidence": row.evidence,
        "metadata": metadata,
    }


def _analyst_note_to_dict(row: PredictionAnalystNoteRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "prediction_run_id": row.prediction_run_id,
        "scenario_case_id": row.scenario_case_id,
        "agent_role": row.agent_role,
        "scenario_space": row.scenario_space,
        "related_event_id": row.related_event_id,
        "claim": row.claim,
        "reasoning": row.reasoning,
        "evidence": row.evidence,
        "confidence": row.confidence,
        "metadata": row.note_metadata or {},
    }


def _result_to_dict(row: PredictionResultRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "prediction_run_id": row.prediction_run_id,
        "baseline_prediction": row.baseline_prediction,
        "scenario_cases_summary": row.scenario_cases_summary,
        "scenario_spaces_summary": row.scenario_spaces_summary,
        "scoreline_summary": row.scoreline_summary,
        "match_events_summary": row.match_events_summary,
        "analyst_notes_summary": row.analyst_notes_summary,
        "final_score_hypothesis": row.final_score_hypothesis,
        "uncertainty_factors": row.uncertainty_factors,
        "confidence": row.confidence,
        "metadata": row.result_metadata or {},
    }


def _config_report_snapshot(config: PredictionConfigRecord | None) -> dict[str, Any]:
    if not config:
        return {}
    return {
        "prediction_config_id": config.prediction_config_id,
        "project_id": config.project_id,
        "graph_id": config.graph_id,
        "match_name": config.match_name,
        "home_team": config.home_team,
        "away_team": config.away_team,
        "model_name": config.model_name,
        "model_version": config.model_version,
        "fit_status": config.fit_status,
        "data_sufficiency": config.data_sufficiency,
    }


def _replay_run_id(original_run_id: str) -> str:
    stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    candidate = f"{original_run_id}_replay_{stamp}"
    if len(candidate) <= 64:
        return candidate
    digest = hashlib.sha1(candidate.encode("utf-8")).hexdigest()[:12]
    return f"run_{digest}_replay_{stamp}"


def _result_replay_snapshot(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "scorelines": _scoreline_replay_index(result.get("scorelines") or []),
        "events": _event_replay_index(result.get("match_events") or []),
    }


def _scoreline_replay_index(rows: Any) -> dict[str, Any]:
    index = {}
    for row in rows:
        key = ((row.get("metadata") or {}).get("scenario_key") or row.get("scenario_key") or row.get("scenario_case_id"))
        if not key:
            continue
        index[str(key)] = {
            "most_likely_score": row.get("most_likely_score"),
            "scoreline_distribution": _normalized_score_distribution(row.get("scoreline_distribution") or []),
            "total_goals_distribution": _normalized_float_map(row.get("total_goals_distribution") or {}),
            "wdl": {
                "home_win": _prob_float(row.get("home_win_probability")),
                "draw": _prob_float(row.get("draw_probability")),
                "away_win": _prob_float(row.get("away_win_probability")),
            },
        }
    return index


def _event_replay_index(rows: Any) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        metadata = row.get("metadata") or {}
        key = metadata.get("scenario_key") or row.get("scenario_key") or row.get("scenario_case_id")
        if not key:
            continue
        index.setdefault(str(key), []).append(
            {
                "minute": int(row.get("minute") or 0),
                "event_type": row.get("event_type"),
                "team": row.get("team"),
                "player": row.get("player"),
                "actor_player_id": row.get("actor_player_id"),
                "assist_player_id": row.get("assist_player_id"),
                "score": row.get("score"),
                "description": row.get("description"),
            }
        )
    for key, values in index.items():
        index[key] = sorted(values, key=lambda row: (row["minute"], str(row["event_type"]), str(row.get("team") or "")))
    return index


def _replay_drift(
    original: dict[str, Any],
    replayed: dict[str, Any],
    original_metadata: dict[str, Any],
    replay_result: dict[str, Any],
) -> dict[str, Any]:
    original_model_version = original_metadata.get("model_version")
    current_model_version = ((replay_result.get("prediction_result") or {}).get("baseline_prediction") or {}).get(
        "model_version"
    )
    original_version = original_metadata.get("simulation_version")
    current_version = replay_result.get("simulation_version")
    original_dataset = original_metadata.get("player_dataset_id")
    current_dataset = original_metadata.get("player_dataset_id")
    drift: dict[str, Any] = {
        "model_version": None
        if not original_model_version or original_model_version == current_model_version
        else {"original": original_model_version, "current": current_model_version},
        "simulator_version": None
        if not original_version or original_version == current_version
        else {"original": original_version, "current": current_version},
        "dataset_id": None
        if not original_dataset or original_dataset == current_dataset
        else {"original": original_dataset, "current": current_dataset},
        "external_sources_etag": None,
        "result_diff": "identical",
    }
    if original.get("scorelines") != replayed.get("scorelines"):
        drift["result_diff"] = "scoreline_distribution_changed"
    elif original.get("events") != replayed.get("events"):
        drift["result_diff"] = "modal_trajectory_changed"
    if drift["result_diff"] != "identical":
        drift["warning"] = "replay produced different result; original snapshot preserved"
    return drift


def _normalized_score_distribution(distribution: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"score": str(item.get("score")), "probability": _round_float(item.get("probability"))}
        for item in distribution
    ]


def _normalized_float_map(payload: dict[str, Any]) -> dict[str, float]:
    return {str(key): _round_float(value) for key, value in sorted(payload.items(), key=lambda item: str(item[0]))}


def _round_float(value: Any) -> float:
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return 0.0


def _prob_float(value: Any) -> float:
    numeric = _round_float(value)
    if numeric > 1:
        numeric = numeric / 100
    return round(numeric, 4)


def _ensure_project_record_for_prediction(project_id: str, graph_id: str | None, requirement: str) -> None:
    with get_session() as session:
        project = session.get(ProjectRecord, project_id)
        if project:
            if graph_id and not project.graph_id:
                project.graph_id = graph_id
            if requirement and not project.simulation_requirement:
                project.simulation_requirement = requirement
            ProjectWorkflowService()._ensure_workflow_state(session, project)
            return
        project = ProjectRecord(
            project_id=project_id,
            name=project_id,
            status="graph_completed" if graph_id else "created",
            graph_id=graph_id,
            simulation_requirement=requirement or "",
            simulation_domain="football_match",
            files=[],
            total_text_length=0,
            extracted_text=requirement or "",
            ontology=None,
            analysis_summary=None,
            project_metadata={},
        )
        session.add(project)
        session.flush()
        ProjectWorkflowService()._ensure_workflow_state(session, project)

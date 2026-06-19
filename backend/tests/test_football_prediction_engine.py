from app.services.football_goal_model import FitArtifacts
from app.services.football_prediction import FootballPredictionEngine, MATCH_EVENT_TYPES, _resolve_step3_budget
from app.services.llm_budget import MAX_HARD_CAP_CALLS
from app.services.match_simulator import SimulationResult, Trajectory


def test_football_prediction_engine_generates_core_prediction_artifacts():
    result = FootballPredictionEngine().run(
        prediction_run_id="run_test",
        project_id="proj_test",
        graph_id="graph_test",
        simulation_requirement="预测阿根廷 vs 法国的胜平负、比分和关键事件",
        graph_entities=[
            {"name": "阿根廷", "entity_type": "FootballTeam", "summary": "控球和前场压迫稳定"},
            {"name": "法国", "entity_type": "FootballTeam", "summary": "反击速度和边路冲击强"},
        ],
    )

    assert result["prediction_run_id"] == "run_test"
    assert len(result["team_strengths"]) == 2
    assert len(result["scenario_cases"]) == 9
    assert len(result["scenario_spaces"]) == 6
    assert len(result["scorelines"]) == 9
    assert len(result["match_events"]) >= 54
    assert len(result["analyst_notes"]) >= 5
    assert all(row["scenario_case_id"] for row in result["scorelines"])
    assert all(event["scenario_case_id"] for event in result["match_events"])

    event_types = {event["event_type"] for event in result["match_events"]}
    assert "KICKOFF" in event_types
    assert "FINAL_SCORE_HYPOTHESIS" in event_types
    final_events_by_case = {
        event["scenario_case_id"]
        for event in result["match_events"]
        if event["event_type"] == "FINAL_SCORE_HYPOTHESIS"
    }
    assert len(final_events_by_case) == 9

    probabilities = result["prediction_result"]["scoreline_summary"]["win_draw_loss_probability"]
    assert round(
        probabilities["home_win"] + probabilities["draw"] + probabilities["away_win"],
        6,
    ) == 1


def test_scenario_matrix_contains_expected_state_pairs():
    result = FootballPredictionEngine().run(
        prediction_run_id="run_matrix",
        project_id="proj_matrix",
        graph_id=None,
        simulation_requirement="预测主队 vs 客队",
        graph_entities=[],
    )

    pairs = {(case["home_state"], case["away_state"]) for case in result["scenario_cases"]}
    assert pairs == {
        ("normal", "normal"),
        ("overperform", "normal"),
        ("normal", "underperform"),
        ("underperform", "normal"),
        ("normal", "overperform"),
        ("underperform", "overperform"),
        ("overperform", "underperform"),
        ("underperform", "underperform"),
        ("overperform", "overperform"),
    }


def test_football_prediction_engine_runs_step3_monte_carlo_reproducibly():
    kwargs = {
        "prediction_run_id": "run_mc",
        "project_id": "proj_mc",
        "graph_id": None,
        "simulation_requirement": "预测巴西 vs 德国的比分和关键事件",
        "home_team": "巴西",
        "away_team": "德国",
        "_override_seed": 20260612,
    }

    first = FootballPredictionEngine().run(**kwargs)
    second = FootballPredictionEngine().run(**kwargs)

    assert first["simulation_seed"] == 20260612
    assert first["n_sims"] >= 500
    assert first["ledger_summary"]["hard_cap"] >= 1
    assert {event["event_type"] for event in first["match_events"]}.issubset(MATCH_EVENT_TYPES)
    assert all((event["metadata"] or {}).get("source") == "match_simulator_modal_trajectory_v1" for event in first["match_events"])
    assert all((row["metadata"] or {}).get("simulation_version") for row in first["scorelines"])

    first_events = [
        (
            event["metadata"]["scenario_key"],
            event["minute"],
            event["event_type"],
            event["team"],
            event["score"],
            event["description"],
        )
        for event in first["match_events"]
    ]
    second_events = [
        (
            event["metadata"]["scenario_key"],
            event["minute"],
            event["event_type"],
            event["team"],
            event["score"],
            event["description"],
        )
        for event in second["match_events"]
    ]
    assert first_events == second_events
    assert [
        ((row["metadata"] or {}).get("scenario_key"), row["scoreline_distribution"])
        for row in first["scorelines"]
    ] == [
        ((row["metadata"] or {}).get("scenario_key"), row["scoreline_distribution"])
        for row in second["scorelines"]
    ]


def test_step3_budget_lifts_undersized_custom_cap_when_coach_review_enabled():
    payload = {
        "profile_key": "custom",
        "coach_panel_roles": ["head_coach", "attack", "defense", "risk"],
        "coach_deliberation_rounds": 1,
        "enable_llm_data_extraction": True,
        "narrative_polish_count": 3,
        "analyst_note_groups": [
            "baseline",
            "home_upside",
            "away_upside",
            "home_error",
            "away_error",
            "volatility",
        ],
        "coach_review_roles": ["head_coach", "risk"],
        "n_sims": 1000,
        "enable_statsbomb": False,
        "hard_cap_calls": 12,
    }

    budget = _resolve_step3_budget(payload)

    assert budget.hard_cap_calls == MAX_HARD_CAP_CALLS
    assert budget.coach_review_roles == ["head_coach", "risk"]


def test_step3_budget_preserves_custom_cap_without_coach_review():
    payload = {
        "profile_key": "custom",
        "coach_panel_roles": ["head_coach", "risk"],
        "coach_deliberation_rounds": 1,
        "enable_llm_data_extraction": False,
        "narrative_polish_count": 0,
        "analyst_note_groups": ["baseline"],
        "coach_review_roles": [],
        "n_sims": 1000,
        "enable_statsbomb": False,
        "hard_cap_calls": 12,
    }

    budget = _resolve_step3_budget(payload)

    assert budget.hard_cap_calls == 12


def test_group_stage_overrides_bad_knockout_flag():
    result = FootballPredictionEngine().run(
        prediction_run_id="run_group_dirty_knockout",
        project_id="proj_group_dirty_knockout",
        graph_id=None,
        simulation_requirement="预测加拿大 vs 波黑世界杯小组赛",
        home_team="加拿大",
        away_team="波黑",
        prepared_team_strengths=_strengths(),
        model_input_snapshot={
            "competition": {"stage": "group", "knockout": True, "neutral_venue": True},
            "fitted_artifacts": _fit_snapshot(),
        },
        _override_seed=20260615,
    )

    assert result["knockout_path_distribution"] is None
    assert result["prediction_result"]["simulation_summary"]["competition"]["knockout"] is False
    assert "competition_knockout_overridden_for_group_stage" in result["prediction_result"]["metadata"]["warnings"]


def test_legacy_dixon_coles_snapshot_is_runtime_calibrated():
    result = FootballPredictionEngine().run(
        prediction_run_id="run_legacy_dc_calibration",
        project_id="proj_legacy_dc_calibration",
        graph_id=None,
        simulation_requirement="预测科特迪瓦 vs 厄瓜多尔世界杯小组赛",
        home_team="科特迪瓦",
        away_team="厄瓜多尔",
        config_scenario_cases=[
            _case("home_normal_away_normal", "normal", "normal", "baseline", 100),
        ],
        prepared_team_strengths=_strengths(),
        model_input_snapshot={
            "home_iso3": "CIV",
            "away_iso3": "ECU",
            "competition": {"stage": "group", "knockout": False},
            "fitted_artifacts": {
                "fit_status": "fitted",
                "data_sufficiency": "sufficient",
                "model_name": "dixon_coles_decay",
                "diagnostics": {"team_match_count": {"CIV": 19, "ECU": 10}},
                "home_advantage": 0.0,
                "xg_priors": {},
                "attack_coef": {"CIV": 1.4846579708193972, "ECU": 1.1612416542528816},
                "defense_coef": {"CIV": -1.662589217423727, "ECU": -2.49998519632294},
                "intercept": 0.0,
            },
        },
        _override_seed=20260615,
    )

    baseline = result["scenario_cases"][0]

    assert baseline["expected_goals"]["home"] >= 0.8
    assert baseline["expected_goals"]["away"] >= 0.7
    assert baseline["metadata"]["model_diagnostics"]["diagnostics"]["runtime_calibration"] == "legacy_dc_v3"


def test_step3_legacy_snapshot_keeps_group_stage_from_narrative():
    result = FootballPredictionEngine().run(
        prediction_run_id="run_legacy_group_stage",
        project_id="proj_legacy_group_stage",
        graph_id=None,
        simulation_requirement="严谨地预测这场比赛的过程和结果",
        home_team="荷兰",
        away_team="日本",
        prepared_team_strengths=_strengths(),
        model_input_snapshot={
            "competition": {"stage": "quarter_final", "knockout": True},
            "extracted": {
                "key_narratives": [
                    "比赛：荷兰 vs 日本，2026 世界杯 F 组小组赛，Dallas Stadium",
                ],
            },
            "fitted_artifacts": _fit_snapshot(),
        },
        _override_seed=20260615,
    )

    simulation_summary = result["prediction_result"]["simulation_summary"]

    assert simulation_summary["competition"]["stage"] == "group"
    assert simulation_summary["competition"]["knockout"] is False
    assert "competition_stage_conflict_kept_group" in simulation_summary["warnings"]


def test_scoreline_summary_uses_weighted_scenario_distribution(monkeypatch):
    monkeypatch.setattr("app.services.football_prediction.MatchSimulator", _FakeWeightedSimulator)

    result = FootballPredictionEngine().run(
        prediction_run_id="run_weighted_summary",
        project_id="proj_weighted_summary",
        graph_id=None,
        simulation_requirement="预测加拿大 vs 波黑世界杯小组赛",
        home_team="加拿大",
        away_team="波黑",
        config_scenario_cases=[
            _case("home_normal_away_normal", "normal", "normal", "baseline", 20),
            _case("home_normal_away_overperform", "normal", "overperform", "away_upside", 80),
        ],
        prepared_team_strengths=_strengths(),
        model_input_snapshot={"competition": {"stage": "group", "knockout": False}, "fitted_artifacts": _fit_snapshot()},
        _override_seed=20260615,
    )

    summary = result["prediction_result"]["scoreline_summary"]

    assert summary["most_likely_score"] == "1-1"
    assert summary["top_score_candidates"][0]["score"] == "1-1"
    assert summary["weighted_scoreline_distribution"][0]["score"] == "1-1"
    assert summary["win_draw_loss_probability"]["draw"] > summary["win_draw_loss_probability"]["home_win"]


def test_scenario_space_bias_uses_space_weighted_distribution(monkeypatch):
    monkeypatch.setattr("app.services.football_prediction.MatchSimulator", _FakeWeightedSimulator)

    result = FootballPredictionEngine().run(
        prediction_run_id="run_weighted_space",
        project_id="proj_weighted_space",
        graph_id=None,
        simulation_requirement="预测加拿大 vs 波黑世界杯小组赛",
        home_team="加拿大",
        away_team="波黑",
        config_scenario_cases=[
            _case("home_underperform_away_normal", "normal", "normal", "away_upside", 10),
            _case("home_normal_away_overperform", "normal", "overperform", "away_upside", 90),
        ],
        prepared_team_strengths=_strengths(),
        model_input_snapshot={"competition": {"stage": "group", "knockout": False}, "fitted_artifacts": _fit_snapshot()},
        _override_seed=20260615,
    )

    away_space = next(space for space in result["scenario_spaces"] if space["space_key"] == "away_upside")

    assert away_space["scoreline_bias"]["most_likely_score"] == "1-1"
    assert away_space["scoreline_bias"]["top_score_candidates"][0]["score"] == "1-1"


def test_group_stage_near_tie_applies_draw_settlement_adjustment(monkeypatch):
    monkeypatch.setattr("app.services.football_prediction.MatchSimulator", _FakeNearTieSimulator)

    result = FootballPredictionEngine().run(
        prediction_run_id="run_group_near_tie",
        project_id="proj_group_near_tie",
        graph_id=None,
        simulation_requirement="预测加拿大 vs 波黑世界杯小组赛",
        home_team="加拿大",
        away_team="波黑",
        config_scenario_cases=[
            _case("home_normal_away_normal", "normal", "normal", "baseline", 100),
        ],
        prepared_team_strengths=_strengths(),
        model_input_snapshot={"competition": {"stage": "group", "knockout": False}, "fitted_artifacts": _fit_snapshot()},
        _override_seed=20260615,
    )

    summary = result["prediction_result"]["scoreline_summary"]

    assert summary["most_likely_score"] == "1-1"
    assert summary["weighted_scoreline_distribution"][0]["score"] == "1-1"
    assert summary["win_draw_loss_probability"]["draw"] > summary["win_draw_loss_probability"]["home_win"]
    assert summary["adjustments"][0]["reason"] == "group_stage_close_game_equalizer"


def test_group_stage_low_event_total_prefers_late_one_nil_over_stale_nil_nil(monkeypatch):
    monkeypatch.setattr("app.services.football_prediction.MatchSimulator", _FakeLowTotalSimulator)

    result = FootballPredictionEngine().run(
        prediction_run_id="run_low_total_one_nil",
        project_id="proj_low_total_one_nil",
        graph_id=None,
        simulation_requirement="预测科特迪瓦 vs 厄瓜多尔世界杯小组赛",
        home_team="科特迪瓦",
        away_team="厄瓜多尔",
        config_scenario_cases=[
            _case("home_normal_away_normal", "normal", "normal", "baseline", 70),
            _case("home_overperform_away_underperform", "overperform", "underperform", "away_error", 30),
        ],
        prepared_team_strengths=_strengths(),
        model_input_snapshot={
            "competition": {"stage": "group", "knockout": False},
            "fitted_artifacts": FitArtifacts(
                model=None,
                fit_status="fitted",
                data_sufficiency="sufficient",
                model_name="dixon_coles_decay",
                diagnostics={},
                home_advantage=0.0,
                xg_priors={"HOM": 1.05, "AWY": 0.95},
            ).to_dict(),
        },
        _override_seed=20260615,
    )

    summary = result["prediction_result"]["scoreline_summary"]

    assert summary["most_likely_score"] == "1-0"
    assert summary["top_score_candidates"][0]["score"] == "1-0"
    assert summary["adjustments"][0]["reason"] == "low_total_late_winner_bias"


def test_group_stage_balanced_high_tempo_surfaces_two_two_draw(monkeypatch):
    monkeypatch.setattr("app.services.football_prediction.MatchSimulator", _FakeBalancedHighTempoSimulator)

    result = FootballPredictionEngine().run(
        prediction_run_id="run_balanced_high_tempo",
        project_id="proj_balanced_high_tempo",
        graph_id=None,
        simulation_requirement="预测荷兰 vs 日本世界杯小组赛",
        home_team="荷兰",
        away_team="日本",
        config_scenario_cases=[
            _case("home_normal_away_normal", "normal", "normal", "baseline", 55),
            _case("home_overperform_away_overperform", "overperform", "overperform", "volatility", 45),
        ],
        prepared_team_strengths=_strengths(),
        model_input_snapshot={"competition": {"stage": "group", "knockout": False}, "fitted_artifacts": _fit_snapshot()},
        _override_seed=20260615,
    )

    summary = result["prediction_result"]["scoreline_summary"]

    assert summary["most_likely_score"] == "2-2"
    assert summary["weighted_scoreline_distribution"][0]["score"] == "2-2"
    assert summary["win_draw_loss_probability"]["draw"] > summary["win_draw_loss_probability"]["home_win"]
    assert summary["adjustments"][0]["reason"] == "group_stage_resilient_equalizer"


def test_matchup_quality_prior_corrects_sparse_dc_against_clear_away_quality(monkeypatch):
    monkeypatch.setattr("app.services.football_prediction.MatchSimulator", _FakeDirectionalSimulator)

    result = FootballPredictionEngine().run(
        prediction_run_id="run_ksa_uru_quality_prior",
        project_id="proj_ksa_uru_quality_prior",
        graph_id=None,
        simulation_requirement="预测沙特阿拉伯 vs 乌拉圭世界杯小组赛",
        home_team="沙特阿拉伯",
        away_team="乌拉圭",
        config_scenario_cases=[
            _case("home_normal_away_normal", "normal", "normal", "baseline", 100),
        ],
        prepared_team_strengths=_ksa_uru_strengths(),
        model_input_snapshot={
            "competition": {"stage": "group", "knockout": False, "neutral_venue": True},
            "home_iso3": "KSA",
            "away_iso3": "URU",
            "squads": {
                "home": {"team_iso3": "KSA", "team_name": "沙特阿拉伯", "stats": {"avg_overall": 58.2}},
                "away": {"team_iso3": "URU", "team_name": "乌拉圭", "stats": {"avg_overall": 68.6}},
            },
            "fitted_artifacts": FitArtifacts(
                model=None,
                fit_status="fitted",
                data_sufficiency="sufficient",
                model_name="dixon_coles_decay",
                diagnostics={"team_match_count": {"KSA": 33, "URU": 10}},
                home_advantage=0.0,
                attack_coef={"KSA": 0.9598840676758366, "URU": 0.5239375507187792},
                defense_coef={"KSA": -1.0407478256306981, "URU": -0.8192381860131396},
                intercept=0.29385154571758526,
            ).to_dict(),
        },
        _override_seed=20260615,
    )

    baseline = result["scorelines"][0]

    assert baseline["away_xg"] > baseline["home_xg"]
    assert baseline["most_likely_score"] == "0-1"
    assert baseline["metadata"]["xg_calibration"]["source"] == "matchup_quality_prior_v1"


def test_mismatch_blowout_keeps_high_goal_tail_and_consolation(monkeypatch):
    monkeypatch.setattr("app.services.football_prediction.MatchSimulator", _FakeBlowoutSimulator)

    result = FootballPredictionEngine().run(
        prediction_run_id="run_blowout_tail",
        project_id="proj_blowout_tail",
        graph_id=None,
        simulation_requirement="预测德国 vs 库拉索世界杯小组赛",
        home_team="德国",
        away_team="库拉索",
        config_scenario_cases=[
            _case("home_normal_away_normal", "normal", "normal", "baseline", 45),
            _case("home_overperform_away_normal", "overperform", "normal", "home_upside", 35),
            _case("home_overperform_away_overperform", "overperform", "overperform", "volatility", 20),
        ],
        prepared_team_strengths=_blowout_strengths(),
        model_input_snapshot={
            "competition": {"stage": "group", "knockout": False},
            "fitted_artifacts": FitArtifacts(
                model=None,
                fit_status="fitted",
                data_sufficiency="sufficient",
                model_name="dixon_coles_decay",
                diagnostics={},
                home_advantage=0.0,
                xg_priors={"HOM": 4.2, "AWY": 0.65},
            ).to_dict(),
        },
        _override_seed=20260615,
    )

    summary = result["prediction_result"]["scoreline_summary"]

    assert summary["most_likely_score"] == "7-1"
    assert summary["weighted_scoreline_distribution"][0]["score"] == "7-1"
    assert summary["top_score_candidates"][0]["probability"] > summary["top_score_candidates"][1]["probability"]
    assert summary["adjustments"][0]["reason"] == "mismatch_blowout_tail"


def test_merge_competition_meta_keeps_explicit_group_stage_from_base():
    from app.services.prediction_config import _merge_competition_meta, _normalize_competition_meta_for_prediction

    merged = _merge_competition_meta(
        {"tournament": "2026 FIFA World Cup", "stage": "group", "knockout": False},
        {"tournament": "世界杯", "stage": "quarter_final", "knockout": True},
        competition=None,
        kickoff_time=None,
    )
    normalized, warnings = _normalize_competition_meta_for_prediction(merged)

    assert normalized["stage"] == "group"
    assert normalized["knockout"] is False
    assert "competition_stage_conflict_kept_group" in warnings


class _FakeWeightedSimulator:
    SIM_VERSION = "fake_weighted_v1"

    def __init__(self, **kwargs):
        del kwargs

    def simulate_match(self, *, home_xg: float, away_xg: float, n_sims: int, knockout: bool, seed: int):
        del n_sims, knockout, seed
        if away_xg > home_xg:
            distribution = [{"score": "1-1", "probability": 0.6}, {"score": "1-0", "probability": 0.4}]
            wdl = {"home_win": 0.4, "draw": 0.6, "away_win": 0.0}
            final_score = {"home": 1, "away": 1}
        else:
            distribution = [{"score": "1-0", "probability": 0.7}, {"score": "1-1", "probability": 0.3}]
            wdl = {"home_win": 0.7, "draw": 0.3, "away_win": 0.0}
            final_score = {"home": 1, "away": 0}
        trajectory = Trajectory(events=[], final_score=final_score, knockout_winner=None, knockout_path=None)
        return SimulationResult(
            trajectories=[trajectory],
            scoreline_distribution=distribution,
            wdl=wdl,
            total_goals_dist={sum(final_score.values()): 1.0},
            modal_trajectory=trajectory,
            knockout_path_distribution=None,
            sim_seed=1,
            n_sims=1,
            sim_version=self.SIM_VERSION,
        )


class _FakeNearTieSimulator:
    SIM_VERSION = "fake_near_tie_v1"

    def __init__(self, **kwargs):
        del kwargs

    def simulate_match(self, *, home_xg: float, away_xg: float, n_sims: int, knockout: bool, seed: int):
        del home_xg, away_xg, n_sims, knockout, seed
        trajectory = Trajectory(events=[], final_score={"home": 1, "away": 0}, knockout_winner=None, knockout_path=None)
        return SimulationResult(
            trajectories=[trajectory],
            scoreline_distribution=[{"score": "1-0", "probability": 0.51}, {"score": "1-1", "probability": 0.49}],
            wdl={"home_win": 0.51, "draw": 0.49, "away_win": 0.0},
            total_goals_dist={1: 0.51, 2: 0.49},
            modal_trajectory=trajectory,
            knockout_path_distribution=None,
            sim_seed=1,
            n_sims=1,
            sim_version=self.SIM_VERSION,
        )


class _FakeLowTotalSimulator:
    SIM_VERSION = "fake_low_total_v1"

    def __init__(self, **kwargs):
        del kwargs

    def simulate_match(self, *, home_xg: float, away_xg: float, n_sims: int, knockout: bool, seed: int):
        del away_xg, n_sims, knockout, seed
        if home_xg >= 1.2:
            distribution = [{"score": "1-0", "probability": 0.44}, {"score": "0-0", "probability": 0.40}]
            final_score = {"home": 1, "away": 0}
            wdl = {"home_win": 0.48, "draw": 0.42, "away_win": 0.10}
        else:
            distribution = [{"score": "0-0", "probability": 0.43}, {"score": "1-0", "probability": 0.39}]
            final_score = {"home": 0, "away": 0}
            wdl = {"home_win": 0.40, "draw": 0.45, "away_win": 0.15}
        trajectory = Trajectory(events=[], final_score=final_score, knockout_winner=None, knockout_path=None)
        return SimulationResult(
            trajectories=[trajectory],
            scoreline_distribution=distribution,
            wdl=wdl,
            total_goals_dist={sum(final_score.values()): 1.0},
            modal_trajectory=trajectory,
            knockout_path_distribution=None,
            sim_seed=1,
            n_sims=1,
            sim_version=self.SIM_VERSION,
        )


class _FakeBalancedHighTempoSimulator:
    SIM_VERSION = "fake_balanced_high_tempo_v1"

    def __init__(self, **kwargs):
        del kwargs

    def simulate_match(self, *, home_xg: float, away_xg: float, n_sims: int, knockout: bool, seed: int):
        del n_sims, knockout, seed
        if home_xg + away_xg >= 2.8:
            distribution = [{"score": "2-2", "probability": 0.35}, {"score": "2-1", "probability": 0.32}]
            final_score = {"home": 2, "away": 2}
            wdl = {"home_win": 0.32, "draw": 0.41, "away_win": 0.27}
        else:
            distribution = [{"score": "1-0", "probability": 0.38}, {"score": "2-2", "probability": 0.27}]
            final_score = {"home": 1, "away": 0}
            wdl = {"home_win": 0.43, "draw": 0.30, "away_win": 0.27}
        trajectory = Trajectory(events=[], final_score=final_score, knockout_winner=None, knockout_path=None)
        return SimulationResult(
            trajectories=[trajectory],
            scoreline_distribution=distribution,
            wdl=wdl,
            total_goals_dist={sum(final_score.values()): 1.0},
            modal_trajectory=trajectory,
            knockout_path_distribution=None,
            sim_seed=1,
            n_sims=1,
            sim_version=self.SIM_VERSION,
        )


class _FakeDirectionalSimulator:
    SIM_VERSION = "fake_directional_v1"

    def __init__(self, **kwargs):
        del kwargs

    def simulate_match(self, *, home_xg: float, away_xg: float, n_sims: int, knockout: bool, seed: int):
        del n_sims, knockout, seed
        if away_xg > home_xg:
            distribution = [{"score": "0-1", "probability": 0.58}, {"score": "1-1", "probability": 0.42}]
            final_score = {"home": 0, "away": 1}
            wdl = {"home_win": 0.18, "draw": 0.30, "away_win": 0.52}
        else:
            distribution = [{"score": "1-0", "probability": 0.58}, {"score": "1-1", "probability": 0.42}]
            final_score = {"home": 1, "away": 0}
            wdl = {"home_win": 0.52, "draw": 0.30, "away_win": 0.18}
        trajectory = Trajectory(events=[], final_score=final_score, knockout_winner=None, knockout_path=None)
        return SimulationResult(
            trajectories=[trajectory],
            scoreline_distribution=distribution,
            wdl=wdl,
            total_goals_dist={sum(final_score.values()): 1.0},
            modal_trajectory=trajectory,
            knockout_path_distribution=None,
            sim_seed=1,
            n_sims=1,
            sim_version=self.SIM_VERSION,
        )


class _FakeBlowoutSimulator:
    SIM_VERSION = "fake_blowout_v1"

    def __init__(self, **kwargs):
        del kwargs

    def simulate_match(self, *, home_xg: float, away_xg: float, n_sims: int, knockout: bool, seed: int):
        del n_sims, knockout, seed
        if home_xg >= 5.0 and away_xg >= 0.7:
            distribution = [{"score": "7-1", "probability": 0.11}, {"score": "5-0", "probability": 0.10}]
            final_score = {"home": 7, "away": 1}
        else:
            distribution = [{"score": "3-0", "probability": 0.18}, {"score": "2-0", "probability": 0.17}]
            final_score = {"home": 3, "away": 0}
        trajectory = Trajectory(events=[], final_score=final_score, knockout_winner=None, knockout_path=None)
        return SimulationResult(
            trajectories=[trajectory],
            scoreline_distribution=distribution,
            wdl={"home_win": 0.94, "draw": 0.04, "away_win": 0.02},
            total_goals_dist={sum(final_score.values()): 1.0},
            modal_trajectory=trajectory,
            knockout_path_distribution=None,
            sim_seed=1,
            n_sims=1,
            sim_version=self.SIM_VERSION,
        )


def _case(scenario_key: str, home_state: str, away_state: str, scenario_space: str, weight: int) -> dict:
    return {
        "id": None,
        "home_state": home_state,
        "away_state": away_state,
        "scenario_key": scenario_key,
        "scenario_name": scenario_key,
        "scenario_space": scenario_space,
        "final_weight": weight,
        "key_drivers": [],
        "risk_factors": [],
        "model_constraints": {},
        "coach_vote_summary": {},
    }


def _strengths() -> list[dict]:
    return [
        {
            "team_role": "home",
            "team_name": "加拿大",
            "attack_rating": 70,
            "defense_rating": 68,
            "possession_rating": 69,
            "transition_rating": 70,
            "set_piece_rating": 68,
            "discipline_rating": 65,
            "fitness_rating": 68,
            "goalkeeper_rating": 67,
            "home_away_adjustment": 0,
            "injury_adjustment": 0,
            "form_adjustment": 0,
            "evidence": {},
            "confidence": 70,
            "metadata": {"team_iso3": "HOM"},
        },
        {
            "team_role": "away",
            "team_name": "波黑",
            "attack_rating": 70,
            "defense_rating": 68,
            "possession_rating": 69,
            "transition_rating": 70,
            "set_piece_rating": 72,
            "discipline_rating": 65,
            "fitness_rating": 68,
            "goalkeeper_rating": 67,
            "home_away_adjustment": 0,
            "injury_adjustment": 0,
            "form_adjustment": 0,
            "evidence": {},
            "confidence": 70,
            "metadata": {"team_iso3": "AWY"},
        },
    ]


def _blowout_strengths() -> list[dict]:
    strengths = _strengths()
    strengths[0] = {**strengths[0], "team_name": "德国", "attack_rating": 86, "defense_rating": 78, "goalkeeper_rating": 82}
    strengths[1] = {**strengths[1], "team_name": "库拉索", "attack_rating": 62, "defense_rating": 45, "goalkeeper_rating": 58}
    return strengths


def _ksa_uru_strengths() -> list[dict]:
    strengths = _strengths()
    strengths[0] = {
        **strengths[0],
        "team_name": "沙特阿拉伯",
        "attack_rating": 74,
        "defense_rating": 46,
        "transition_rating": 64,
        "set_piece_rating": 70,
        "goalkeeper_rating": 65,
        "metadata": {"team_iso3": "KSA"},
    }
    strengths[1] = {
        **strengths[1],
        "team_name": "乌拉圭",
        "attack_rating": 70,
        "defense_rating": 55,
        "transition_rating": 66,
        "set_piece_rating": 80,
        "goalkeeper_rating": 66,
        "metadata": {"team_iso3": "URU"},
    }
    return strengths


def _fit_snapshot() -> dict:
    return FitArtifacts(
        model=None,
        fit_status="uniform",
        data_sufficiency="partial",
        model_name="uniform_prior",
        diagnostics={},
        home_advantage=0.0,
        xg_priors={"HOM": 1.2, "AWY": 1.2},
    ).to_dict()

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from app.services.backtest import (
    BacktestPrediction,
    PredictionBacktester,
    WorkflowPredictionRunner,
    brier,
    calibration_curve,
    compute_metrics,
    compute_outcome,
    rps,
)


class StubPredictionRunner:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def predict(self, **kwargs) -> BacktestPrediction:
        self.calls.append(kwargs)
        if kwargs["home_iso3"] == "BRA":
            return BacktestPrediction(
                wld={"home_win": 0.7, "draw": 0.2, "away_win": 0.1},
                modal_score="2-0",
                home_xg=1.8,
                away_xg=0.7,
                fit_status="fitted",
                model_version="v2",
                prediction_run_id="run_bra",
                prediction_config_id="cfg_bra",
            )
        return BacktestPrediction(
            wld={"home_win": 0.2, "draw": 0.5, "away_win": 0.3},
            modal_score="1-1",
            home_xg=1.0,
            away_xg=1.0,
            fit_status="elo_prior",
            model_version="v2",
            prediction_run_id="run_arg",
            prediction_config_id="cfg_arg",
        )


def test_compute_outcome() -> None:
    assert compute_outcome(2, 1) == "home_win"
    assert compute_outcome(1, 1) == "draw"
    assert compute_outcome(0, 2) == "away_win"


def test_metrics_use_ranked_and_multiclass_scores() -> None:
    df = pd.DataFrame(
        [
            {
                "predicted_home_win_prob": 0.8,
                "predicted_draw_prob": 0.1,
                "predicted_away_win_prob": 0.1,
                "actual_outcome": "home_win",
                "predicted_modal_score": "2-0",
                "actual_score": "2-0",
                "fit_status": "fitted",
            },
            {
                "predicted_home_win_prob": 0.2,
                "predicted_draw_prob": 0.2,
                "predicted_away_win_prob": 0.6,
                "actual_outcome": "away_win",
                "predicted_modal_score": "0-1",
                "actual_score": "1-2",
                "fit_status": "elo_prior",
            },
        ]
    )

    assert round(rps(df), 4) == 0.0625
    assert round(brier(df), 4) == 0.05

    metrics = compute_metrics(df)

    assert metrics["n_matches"] == 2
    assert metrics["modal_score_hit_rate"] == 0.5
    assert metrics["by_fit_status"]["fitted"]["n"] == 1
    assert metrics["by_fit_status"]["elo_prior"]["n"] == 1
    assert metrics["rps_baseline_uniform"] > metrics["rps"]
    assert metrics["calibration"] == metrics["calibration_bins"]


def test_calibration_curve_bins_each_outcome() -> None:
    df = pd.DataFrame(
        [
            {
                "predicted_home_win_prob": 0.85,
                "predicted_draw_prob": 0.1,
                "predicted_away_win_prob": 0.05,
                "actual_outcome": "home_win",
            },
            {
                "predicted_home_win_prob": 0.15,
                "predicted_draw_prob": 0.7,
                "predicted_away_win_prob": 0.15,
                "actual_outcome": "draw",
            },
        ]
    )

    curve = calibration_curve(df, bins=5)

    assert set(curve) == {"home_win", "draw", "away_win"}
    assert curve["home_win"][-1]["n"] == 1
    assert curve["home_win"][-1]["observed_frequency"] == 1.0
    assert curve["draw"][3]["n"] == 1


def test_backtester_runs_predictions_with_cutoff_and_writes_report(tmp_path: Path) -> None:
    holdout = tmp_path / "holdout.csv"
    holdout.write_text(
        "\n".join(
            [
                "date,home_iso3,away_iso3,home_score,away_score,knockout,host_iso3,competition",
                "2024-06-01,BRA,COL,2,0,false,,Copa America",
                "2024-06-02,ARG,CHL,1,1,false,,Copa America",
            ]
        ),
        encoding="utf-8",
    )
    output = tmp_path / "backtest.json"
    runner = StubPredictionRunner()

    report = PredictionBacktester(prediction_runner=runner).run(
        holdout_csv=holdout,
        dataset_id="wc2026_v2",
        budget="low",
        output=output,
    )

    assert output.exists()
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted == report
    assert report["config"]["n_matches"] == 2
    assert report["metrics"]["n_matches"] == 2
    assert report["per_match"][0]["predicted_modal_score"] == "2-0"
    assert runner.calls[0]["cutoff_date"] == "2024-06-01"
    assert runner.calls[0]["competition"] == "Copa America"
    assert runner.calls[0]["knockout"] is False


def test_workflow_runner_maps_cutoff_to_prepare_and_reads_baseline_scoreline() -> None:
    class FakeConfigService:
        def __init__(self) -> None:
            self.kwargs = None

        def prepare(self, **kwargs):
            self.kwargs = kwargs
            return {"prediction_config_id": "cfg_1", "fit_status": "fitted"}

    class FakePersistenceService:
        def create_completed_prediction_from_config(self, **kwargs):
            assert kwargs["prediction_config_id"] == "cfg_1"
            assert kwargs["rerun_from_event_type"] == "backtest"
            return {"prediction_run_id": "run_1"}

        def list_scorelines(self, prediction_run_id):
            assert prediction_run_id == "run_1"
            return [
                {
                    "scenario_space": "baseline",
                    "home_win_probability": 0.55,
                    "draw_probability": 0.25,
                    "away_win_probability": 0.2,
                    "most_likely_score": "2-1",
                    "home_xg": 1.7,
                    "away_xg": 1.1,
                    "model_version": "v2",
                    "metadata": {"scenario_key": "home_normal_away_normal"},
                }
            ]

    config_service = FakeConfigService()
    runner = WorkflowPredictionRunner(
        config_service=config_service,
        persistence_service=FakePersistenceService(),
    )

    prediction = runner.predict(
        home_iso3="MEX",
        away_iso3="USA",
        dataset_id="wc2026_fifa_v1",
        budget="low",
        cutoff_date="2024-11-19",
        knockout=True,
        host_iso3="MEX",
        competition="CONCACAF Nations League",
    )

    assert prediction.prediction_run_id == "run_1"
    assert prediction.modal_score == "2-1"
    assert prediction.wld["home_win"] == 0.55
    assert config_service.kwargs["kickoff_time"] == "2024-11-19"
    assert config_service.kwargs["home_team"] == "MEX"
    assert config_service.kwargs["competition"]["knockout"] is True
    assert config_service.kwargs["competition"]["neutral_venue"] is False
    assert config_service.kwargs["llm_budget"]["profile_key"] == "low"

"""Backtest harness for football prediction calibration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import pandas as pd


OUTCOMES = ("home_win", "draw", "away_win")
REQUIRED_HOLDOUT_COLUMNS = {
    "date",
    "home_iso3",
    "away_iso3",
    "home_score",
    "away_score",
    "knockout",
    "host_iso3",
    "competition",
}


@dataclass
class BacktestPrediction:
    """Minimal prediction surface needed by the scoring harness."""

    wld: dict[str, float]
    modal_score: str
    home_xg: float
    away_xg: float
    fit_status: str
    model_version: str = "v2"
    prediction_run_id: str | None = None
    prediction_config_id: str | None = None

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "BacktestPrediction":
        return cls(
            wld=dict(payload.get("wld") or payload.get("win_draw_loss_probability") or {}),
            modal_score=str(payload.get("modal_score") or payload.get("predicted_modal_score") or ""),
            home_xg=float(payload.get("home_xg") or payload.get("predicted_xg_home") or 0.0),
            away_xg=float(payload.get("away_xg") or payload.get("predicted_xg_away") or 0.0),
            fit_status=str(payload.get("fit_status") or "unknown"),
            model_version=str(payload.get("model_version") or "v2"),
            prediction_run_id=payload.get("prediction_run_id"),
            prediction_config_id=payload.get("prediction_config_id"),
        )

    def normalized_wld(self) -> dict[str, float]:
        values = _normalize_probabilities(
            [
                self.wld.get("home_win"),
                self.wld.get("draw"),
                self.wld.get("away_win"),
            ]
        )
        return dict(zip(OUTCOMES, values, strict=True))


class PredictionRunner(Protocol):
    def predict(
        self,
        *,
        home_iso3: str,
        away_iso3: str,
        dataset_id: str,
        budget: Any,
        cutoff_date: str,
        knockout: bool,
        host_iso3: str | None,
        competition: str | None,
    ) -> BacktestPrediction:
        ...


class PredictionBacktester:
    """Run predictions over a holdout CSV and write the JSON report."""

    def __init__(self, *, prediction_runner: PredictionRunner | None = None) -> None:
        self._prediction_runner = prediction_runner or WorkflowPredictionRunner()

    def run(
        self,
        *,
        holdout_csv: str | Path,
        dataset_id: str,
        budget: Any = "middle",
        n_matches: int | None = None,
        output: str | Path,
    ) -> dict[str, Any]:
        holdout_path = Path(holdout_csv)
        holdout = load_holdout_csv(holdout_path, n_matches=n_matches)
        per_match: list[dict[str, Any]] = []
        model_versions: list[str] = []

        for row in holdout.to_dict("records"):
            prediction = self._prediction_runner.predict(
                home_iso3=str(row["home_iso3"]),
                away_iso3=str(row["away_iso3"]),
                dataset_id=dataset_id,
                budget=budget,
                cutoff_date=str(row["date"]),
                knockout=_to_bool(row.get("knockout")),
                host_iso3=_blank_to_none(row.get("host_iso3")),
                competition=_blank_to_none(row.get("competition")),
            )
            if isinstance(prediction, dict):
                prediction = BacktestPrediction.from_mapping(prediction)
            probabilities = prediction.normalized_wld()
            actual_score = _score_text(row["home_score"], row["away_score"])
            model_versions.append(prediction.model_version)
            per_match.append(
                {
                    "date": str(row["date"]),
                    "home_iso3": str(row["home_iso3"]),
                    "away_iso3": str(row["away_iso3"]),
                    "predicted_home_win_prob": probabilities["home_win"],
                    "predicted_draw_prob": probabilities["draw"],
                    "predicted_away_win_prob": probabilities["away_win"],
                    "predicted_modal_score": prediction.modal_score,
                    "predicted_xg_home": float(prediction.home_xg),
                    "predicted_xg_away": float(prediction.away_xg),
                    "actual_outcome": compute_outcome(row["home_score"], row["away_score"]),
                    "actual_score": actual_score,
                    "fit_status": prediction.fit_status,
                    "prediction_run_id": prediction.prediction_run_id,
                    "prediction_config_id": prediction.prediction_config_id,
                }
            )

        df = pd.DataFrame(per_match)
        metrics = compute_metrics(df)
        report = {
            "config": {
                "holdout": holdout_path.name,
                "n_matches": len(per_match),
                "dataset_id": dataset_id,
                "budget": _budget_key(budget),
                "model_version": _common_model_version(model_versions),
                "ran_at": _utc_now_iso(),
            },
            "metrics": metrics,
            "by_fit_status": metrics.get("by_fit_status", {}),
            "per_match": per_match,
        }

        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(_json_safe(report), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return _json_safe(report)


class WorkflowPredictionRunner:
    """Adapter from the persistent Step2+Step3 workflow to backtest rows."""

    def __init__(self, *, config_service: Any | None = None, persistence_service: Any | None = None) -> None:
        self._config_service = config_service
        self._persistence_service = persistence_service

    def predict(
        self,
        *,
        home_iso3: str,
        away_iso3: str,
        dataset_id: str,
        budget: Any,
        cutoff_date: str,
        knockout: bool,
        host_iso3: str | None,
        competition: str | None,
    ) -> BacktestPrediction:
        from .football_prediction import PredictionPersistenceService
        from .llm_budget import LLMBudgetProfile
        from .prediction_config import PredictionConfigService

        budget_profile = budget if isinstance(budget, LLMBudgetProfile) else LLMBudgetProfile.resolve({"profile_key": _budget_key(budget)})
        config_service = self._config_service or PredictionConfigService()
        persistence_service = self._persistence_service or PredictionPersistenceService()

        config_status = config_service.prepare(
            project_id=_backtest_project_id(dataset_id, home_iso3, away_iso3, cutoff_date),
            graph_id=None,
            prediction_requirement=(
                f"Backtest football prediction for {home_iso3} vs {away_iso3} before {cutoff_date}."
            ),
            force_regenerate=True,
            home_team=home_iso3,
            away_team=away_iso3,
            competition=_competition_payload(
                home_iso3=home_iso3,
                away_iso3=away_iso3,
                competition=competition,
                knockout=knockout,
                host_iso3=host_iso3,
            ),
            kickoff_time=cutoff_date,
            graph_entities=[],
            llm_budget=budget_profile.to_dict(),
            player_dataset_id=dataset_id,
        )
        run_status = persistence_service.create_completed_prediction_from_config(
            prediction_config_id=config_status["prediction_config_id"],
            force_rerun=True,
            rerun_from_event_type="backtest",
        )
        prediction_run_id = run_status["prediction_run_id"]
        baseline = _select_baseline_scoreline(persistence_service.list_scorelines(prediction_run_id))
        return BacktestPrediction(
            wld={
                "home_win": baseline.get("home_win_probability"),
                "draw": baseline.get("draw_probability"),
                "away_win": baseline.get("away_win_probability"),
            },
            modal_score=str(baseline.get("most_likely_score") or ""),
            home_xg=float(baseline.get("home_xg") or 0.0),
            away_xg=float(baseline.get("away_xg") or 0.0),
            fit_status=str(config_status.get("fit_status") or "unknown"),
            model_version=str(baseline.get("model_version") or "v2"),
            prediction_run_id=prediction_run_id,
            prediction_config_id=config_status["prediction_config_id"],
        )


def load_holdout_csv(path: Path, *, n_matches: int | None = None) -> pd.DataFrame:
    df = pd.read_csv(path)
    missing = sorted(REQUIRED_HOLDOUT_COLUMNS - set(df.columns))
    if missing:
        raise ValueError(f"Holdout CSV missing required columns: {missing}")
    if n_matches is not None:
        if n_matches <= 0:
            raise ValueError("--n-matches must be positive")
        df = df.head(n_matches)
    df = df.copy()
    for column in ("home_iso3", "away_iso3"):
        df[column] = df[column].astype(str).str.strip().str.upper()
    df["date"] = pd.to_datetime(df["date"], errors="raise").dt.strftime("%Y-%m-%d")
    df["home_score"] = pd.to_numeric(df["home_score"], errors="raise").astype(int)
    df["away_score"] = pd.to_numeric(df["away_score"], errors="raise").astype(int)
    df["knockout"] = df["knockout"].map(_to_bool)
    df["host_iso3"] = df["host_iso3"].map(lambda value: _blank_to_none(value) or "")
    df["competition"] = df["competition"].map(lambda value: _blank_to_none(value) or "")
    return df.reset_index(drop=True)


def compute_metrics(rows: pd.DataFrame | list[dict[str, Any]]) -> dict[str, Any]:
    df = _to_frame(rows)
    by_fit_status = _metrics_by_fit_status(df)
    calibration = calibration_curve(df)
    metrics = {
        "n_matches": int(len(df)),
        "rps": rps(df),
        "rps_baseline_uniform": _uniform_rps_baseline(df),
        "rps_baseline_elo_only": _elo_rps_baseline(df),
        "brier": brier(df),
        "modal_score_hit_rate": modal_hit(df),
        "calibration": calibration,
        "calibration_bins": calibration,
        "by_fit_status": by_fit_status,
    }
    return _json_safe(metrics)


def compute_outcome(home_score: Any, away_score: Any) -> str:
    home = int(float(home_score))
    away = int(float(away_score))
    if home > away:
        return "home_win"
    if home == away:
        return "draw"
    return "away_win"


def rps(rows: pd.DataFrame | list[dict[str, Any]]) -> float:
    df = _to_frame(rows)
    if df.empty:
        return 0.0
    values = []
    for row in df.to_dict("records"):
        actual = _actual_vector(row)
        predicted = _row_probabilities(row)
        cum_predicted = 0.0
        cum_actual = 0.0
        score = 0.0
        for index in range(len(OUTCOMES) - 1):
            cum_predicted += predicted[index]
            cum_actual += actual[index]
            score += (cum_predicted - cum_actual) ** 2
        values.append(score / (len(OUTCOMES) - 1))
    return _round_metric(sum(values) / len(values))


def brier(rows: pd.DataFrame | list[dict[str, Any]]) -> float:
    df = _to_frame(rows)
    if df.empty:
        return 0.0
    values = []
    for row in df.to_dict("records"):
        actual = _actual_vector(row)
        predicted = _row_probabilities(row)
        values.append(sum((predicted[i] - actual[i]) ** 2 for i in range(len(OUTCOMES))) / len(OUTCOMES))
    return _round_metric(sum(values) / len(values))


def modal_hit(rows: pd.DataFrame | list[dict[str, Any]]) -> float:
    df = _to_frame(rows)
    if df.empty or "predicted_modal_score" not in df or "actual_score" not in df:
        return 0.0
    hits = (df["predicted_modal_score"].astype(str) == df["actual_score"].astype(str)).mean()
    return _round_metric(float(hits))


def calibration_curve(rows: pd.DataFrame | list[dict[str, Any]], bins: int = 10) -> dict[str, list[dict[str, Any]]]:
    if bins <= 0:
        raise ValueError("bins must be positive")
    df = _to_frame(rows)
    result: dict[str, list[dict[str, Any]]] = {}
    for outcome_index, outcome in enumerate(OUTCOMES):
        bucket_rows = [
            {
                "bin": index,
                "lower": _round_metric(index / bins),
                "upper": _round_metric((index + 1) / bins),
                "n": 0,
                "mean_predicted_probability": None,
                "observed_frequency": None,
            }
            for index in range(bins)
        ]
        sums = [0.0] * bins
        observed = [0.0] * bins
        for row in df.to_dict("records"):
            probability = _row_probabilities(row)[outcome_index]
            bucket = min(bins - 1, max(0, int(probability * bins)))
            bucket_rows[bucket]["n"] += 1
            sums[bucket] += probability
            observed[bucket] += 1.0 if row.get("actual_outcome") == outcome else 0.0
        for index, bucket in enumerate(bucket_rows):
            n = int(bucket["n"])
            if n:
                bucket["mean_predicted_probability"] = _round_metric(sums[index] / n)
                bucket["observed_frequency"] = _round_metric(observed[index] / n)
        result[outcome] = bucket_rows
    return result


def _metrics_by_fit_status(df: pd.DataFrame) -> dict[str, dict[str, Any]]:
    if df.empty or "fit_status" not in df:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for status, group in df.groupby(df["fit_status"].fillna("unknown")):
        result[str(status)] = {
            "rps": rps(group),
            "brier": brier(group),
            "modal_score_hit_rate": modal_hit(group),
            "n": int(len(group)),
        }
    return result


def _uniform_rps_baseline(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    baseline = df.copy()
    baseline["predicted_home_win_prob"] = 1 / 3
    baseline["predicted_draw_prob"] = 1 / 3
    baseline["predicted_away_win_prob"] = 1 / 3
    return rps(baseline)


def _elo_rps_baseline(df: pd.DataFrame) -> float | None:
    columns = {"elo_home_win_prob", "elo_draw_prob", "elo_away_win_prob"}
    if df.empty or not columns.issubset(df.columns):
        return None
    baseline = df.copy()
    baseline["predicted_home_win_prob"] = baseline["elo_home_win_prob"]
    baseline["predicted_draw_prob"] = baseline["elo_draw_prob"]
    baseline["predicted_away_win_prob"] = baseline["elo_away_win_prob"]
    return rps(baseline)


def _to_frame(rows: pd.DataFrame | list[dict[str, Any]]) -> pd.DataFrame:
    if isinstance(rows, pd.DataFrame):
        return rows.copy()
    return pd.DataFrame(list(rows or []))


def _actual_vector(row: dict[str, Any]) -> list[int]:
    actual = str(row.get("actual_outcome") or "")
    return [1 if actual == outcome else 0 for outcome in OUTCOMES]


def _row_probabilities(row: dict[str, Any]) -> list[float]:
    return _normalize_probabilities(
        [
            row.get("predicted_home_win_prob"),
            row.get("predicted_draw_prob"),
            row.get("predicted_away_win_prob"),
        ]
    )


def _normalize_probabilities(values: list[Any]) -> list[float]:
    probabilities: list[float] = []
    for value in values:
        try:
            probabilities.append(max(0.0, float(value)))
        except (TypeError, ValueError):
            probabilities.append(0.0)
    total = sum(probabilities)
    if total <= 0:
        return [1 / len(values)] * len(values)
    return [value / total for value in probabilities]


def _score_text(home_score: Any, away_score: Any) -> str:
    return f"{int(float(home_score))}-{int(float(away_score))}"


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "knockout"}


def _blank_to_none(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    text = str(value).strip()
    return text or None


def _budget_key(budget: Any) -> str:
    return str(getattr(budget, "profile_key", None) or budget or "middle").lower()


def _common_model_version(model_versions: list[str]) -> str:
    versions = [version for version in model_versions if version]
    if not versions:
        return "unknown"
    first = versions[0]
    return first if all(version == first for version in versions) else "mixed"


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _backtest_project_id(dataset_id: str, home_iso3: str, away_iso3: str, cutoff_date: str) -> str:
    digest = hashlib.sha1(f"{dataset_id}:{home_iso3}:{away_iso3}:{cutoff_date}".encode("utf-8")).hexdigest()[:16]
    return f"bt_{digest}"


def _competition_payload(
    *,
    home_iso3: str,
    away_iso3: str,
    competition: str | None,
    knockout: bool,
    host_iso3: str | None,
) -> dict[str, Any]:
    host = str(host_iso3 or "").strip().upper() or None
    neutral = host not in {home_iso3.upper(), away_iso3.upper()} if host else True
    return {
        "tournament": competition or "international",
        "stage": "knockout" if knockout else None,
        "knockout": bool(knockout),
        "neutral_venue": bool(neutral),
        "host_country_iso3": host,
    }


def _select_baseline_scoreline(scorelines: list[dict[str, Any]]) -> dict[str, Any]:
    if not scorelines:
        raise ValueError("prediction run produced no scorelines")
    for row in scorelines:
        if (row.get("metadata") or {}).get("scenario_key") == "home_normal_away_normal":
            return row
    for row in scorelines:
        if row.get("scenario_space") == "baseline":
            return row
    return scorelines[0]


def _round_metric(value: Any) -> float:
    return round(float(value), 6)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, float) and pd.isna(value):
        return None
    return value


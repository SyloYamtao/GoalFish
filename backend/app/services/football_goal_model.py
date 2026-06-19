"""Football goal model fitting and scoreline projection."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import math
import re
from typing import Any

import numpy as np
import pandas as pd

from .external_data import IntlResults, NationalElo, TeamNameNormalizer


XI_DECAY = 0.0018
MIN_TEAM_MATCHES_FOR_DC = 8
MIN_ROWS_FOR_DC = 1500
MIN_TEAM_MATCHES_FOR_HIERARCHICAL = 4
DEFAULT_PRIOR_XG = 1.35
MAX_GOALS = 8
COMPETITIVE_TOURNAMENTS = {
    "AFC Asian Cup",
    "African Cup of Nations",
    "CONCACAF Gold Cup",
    "CONCACAF Nations League",
    "Copa America",
    "FIFA World Cup",
    "FIFA World Cup qualification",
    "Oceania Nations Cup",
    "UEFA Euro",
    "UEFA Nations League",
}


@dataclass
class FitArtifacts:
    """Serializable model fit artifacts for Step2 and Step3."""

    model: Any | None
    fit_status: str
    data_sufficiency: str
    model_name: str
    diagnostics: dict[str, Any]
    home_advantage: float
    xg_priors: dict[str, float] = field(default_factory=dict)
    attack_coef: dict[str, float] = field(default_factory=dict)
    defense_coef: dict[str, float] = field(default_factory=dict)
    intercept: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation without the model object."""
        return {
            "fit_status": self.fit_status,
            "data_sufficiency": self.data_sufficiency,
            "model_name": self.model_name,
            "diagnostics": _to_builtin(self.diagnostics),
            "home_advantage": float(self.home_advantage),
            "xg_priors": {str(k): float(v) for k, v in self.xg_priors.items()},
            "attack_coef": {str(k): float(v) for k, v in self.attack_coef.items()},
            "defense_coef": {str(k): float(v) for k, v in self.defense_coef.items()},
            "intercept": float(self.intercept),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FitArtifacts":
        """Rehydrate serializable artifacts; the penaltyblog model is not restored."""
        return cls(
            model=None,
            fit_status=str(d.get("fit_status") or "uniform"),
            data_sufficiency=str(d.get("data_sufficiency") or "insufficient"),
            model_name=str(d.get("model_name") or "uniform_prior"),
            diagnostics=dict(d.get("diagnostics") or {}),
            home_advantage=float(d.get("home_advantage") or 0.0),
            xg_priors={str(k): float(v) for k, v in (d.get("xg_priors") or {}).items()},
            attack_coef={str(k): float(v) for k, v in (d.get("attack_coef") or {}).items()},
            defense_coef={str(k): float(v) for k, v in (d.get("defense_coef") or {}).items()},
            intercept=float(d.get("intercept") or 0.0),
        )

    def compute_match_xg(
        self,
        home_iso3: str,
        away_iso3: str,
        home_factor: float = 1.0,
        away_factor: float = 1.0,
    ) -> tuple[float, float]:
        """Return clipped xG for a fixture using fitted coefficients or priors."""
        if self.attack_coef and self.defense_coef:
            home_xg = math.exp(
                self.intercept
                + self.attack_coef.get(home_iso3, 0.0)
                + self.defense_coef.get(away_iso3, 0.0)
                + self.home_advantage
            )
            away_xg = math.exp(
                self.intercept
                + self.attack_coef.get(away_iso3, 0.0)
                + self.defense_coef.get(home_iso3, 0.0)
            )
        else:
            home_xg = self.xg_priors.get(home_iso3, DEFAULT_PRIOR_XG)
            away_xg = self.xg_priors.get(away_iso3, DEFAULT_PRIOR_XG)

        return (
            round(_clip(home_xg * home_factor, 0.3, 4.5), 4),
            round(_clip(away_xg * away_factor, 0.3, 4.5), 4),
        )


class ExternalDataPool:
    """Light adapter that exposes external football sources to model fitting."""

    def __init__(
        self,
        *,
        intl_results: IntlResults | None = None,
        elo: NationalElo | None = None,
        normalizer: TeamNameNormalizer | None = None,
    ) -> None:
        self.intl_results = intl_results or IntlResults()
        self.elo = elo or NationalElo()
        self.normalizer = normalizer or TeamNameNormalizer()
        self._offline = False
        self._force = False
        self._fit_df: pd.DataFrame | None = None
        self._elo_snapshot: dict[str, float] | None = None

    def fetch_for_match(
        self,
        home_iso3: str,
        away_iso3: str,
        since_year: int = 2014,
        cutoff_date: str | None = None,
        sources: list[str | None] | None = None,
        offline: bool = False,
        force: bool = False,
    ) -> "ExternalDataPool":
        del home_iso3, away_iso3
        self._offline = offline
        self._force = force
        source_set = {source for source in (sources or ["intl_results", "national_elo"]) if source}
        if "intl_results" in source_set:
            normalized_cutoff = _cutoff_datetime(cutoff_date).strftime("%Y-%m-%d") if cutoff_date else None
            self._fit_df = self.intl_results.as_fit_dataframe(
                start_date=f"{since_year}-01-01",
                cutoff_date=normalized_cutoff,
                offline=offline,
                force=force,
                normalizer=self.normalizer,
            )
        if "national_elo" in source_set:
            if offline or force:
                elo_df = self.elo.as_dataframe(offline=offline, force=force)
                self._elo_snapshot = dict(zip(elo_df["team_iso3"], elo_df["elo_rating"], strict=False))
            else:
                self._elo_snapshot = self.elo.fetch_current_snapshot()
        return self

    def fit_dataframe(self, cutoff_date: str | None = None) -> pd.DataFrame:
        if self._fit_df is not None:
            df = self._fit_df.copy()
            if cutoff_date and not df.empty and "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"], errors="coerce")
                df = df[df["date"] < _cutoff_datetime(cutoff_date)]
            return df.reset_index(drop=True)

        normalized_cutoff = _cutoff_datetime(cutoff_date).strftime("%Y-%m-%d") if cutoff_date else None
        return self.intl_results.as_fit_dataframe(
            cutoff_date=normalized_cutoff,
            offline=self._offline,
            force=self._force,
            normalizer=self.normalizer,
        )

    def elo_snapshot(self) -> dict[str, float]:
        if self._elo_snapshot is None:
            if self._offline or self._force:
                elo_df = self.elo.as_dataframe(offline=self._offline, force=self._force)
                self._elo_snapshot = dict(zip(elo_df["team_iso3"], elo_df["elo_rating"], strict=False))
            else:
                self._elo_snapshot = self.elo.fetch_current_snapshot()
        return dict(self._elo_snapshot)


class FootballGoalModelAdapter:
    """Fit Dixon-Coles style goal models with explicit fallbacks."""

    MODEL_VERSION = "v2"
    model_version = MODEL_VERSION

    def initialize(self, model_input_snapshot: dict[str, Any]) -> dict[str, Any]:
        """Legacy Step2 entry point kept stable until orchestration moves to fit()."""
        structured_matches = model_input_snapshot.get("structured_recent_matches") or []
        xg_samples = model_input_snapshot.get("structured_xg_samples") or []
        home_team = model_input_snapshot.get("home_team")
        away_team = model_input_snapshot.get("away_team")
        has_team_evidence = bool(home_team and away_team)

        if len(structured_matches) >= 4 or len(xg_samples) >= 4:
            try:
                import penaltyblog  # noqa: F401

                return {
                    "model_name": "penaltyblog_poisson",
                    "model_version": "v1",
                    "fit_status": "fitted",
                    "data_sufficiency": "sufficient",
                    "diagnostics": {
                        "structured_recent_matches": len(structured_matches),
                        "structured_xg_samples": len(xg_samples),
                        "fallback_reason": None,
                    },
                }
            except Exception as exc:
                return {
                    "model_name": "prior_poisson",
                    "model_version": "v1",
                    "fit_status": "fallback_prior",
                    "data_sufficiency": "partial",
                    "diagnostics": {
                        "structured_recent_matches": len(structured_matches),
                        "structured_xg_samples": len(xg_samples),
                        "fallback_reason": f"penaltyblog_unavailable: {exc}",
                    },
                }

        if has_team_evidence:
            return {
                "model_name": "prior_poisson",
                "model_version": "v1",
                "fit_status": "fallback_prior",
                "data_sufficiency": "partial",
                "diagnostics": {
                    "structured_recent_matches": len(structured_matches),
                    "structured_xg_samples": len(xg_samples),
                    "fallback_reason": "insufficient_structured_match_history",
                },
            }

        return {
            "model_name": "prior_poisson",
            "model_version": "v1",
            "fit_status": "insufficient",
            "data_sufficiency": "insufficient",
            "diagnostics": {
                "structured_recent_matches": 0,
                "structured_xg_samples": 0,
                "fallback_reason": "missing_team_state_evidence",
            },
        }

    def fit(
        self,
        *,
        external_pool: ExternalDataPool,
        extracted: dict[str, Any] | None = None,
        home_iso3: str,
        away_iso3: str,
        competition_meta: dict[str, Any] | None = None,
    ) -> FitArtifacts:
        """Fit Dixon-Coles when data is sufficient, otherwise return explicit priors."""
        competition_meta = competition_meta or {}
        df = self._build_training_set(external_pool, extracted, competition_meta)
        team_match_count = self._team_match_count(df, home_iso3, away_iso3)
        home_advantage = self._home_advantage(competition_meta, home_iso3)
        base_diagnostics = {
            "n_rows": int(len(df)),
            "xi": XI_DECAY,
            "team_match_count": {
                home_iso3: int(team_match_count.get(home_iso3, 0)),
                away_iso3: int(team_match_count.get(away_iso3, 0)),
            },
        }

        if (
            min(team_match_count[home_iso3], team_match_count[away_iso3]) >= MIN_TEAM_MATCHES_FOR_DC
            and len(df) >= MIN_ROWS_FOR_DC
        ):
            try:
                model = self._fit_dixon_coles(df)
                attack_coef, defense_coef, intercept = _extract_model_coefficients(model, df)
                return FitArtifacts(
                    model=model,
                    fit_status="fitted",
                    data_sufficiency="sufficient",
                    model_name="dixon_coles_decay",
                    diagnostics={
                        **base_diagnostics,
                        "aic": _maybe_float(getattr(model, "aic", None)),
                        "log_likelihood": _maybe_float(
                            getattr(model, "log_likelihood", getattr(model, "loglikelihood", None))
                        ),
                    },
                    home_advantage=home_advantage,
                    attack_coef=attack_coef,
                    defense_coef=defense_coef,
                    intercept=intercept,
                )
            except Exception as exc:
                return self._fit_hierarchical(
                    df,
                    home_iso3,
                    away_iso3,
                    competition_meta,
                    diagnostics={**base_diagnostics, "fallback_reason": f"dixon_coles_failed: {exc}"},
                )

        if min(team_match_count[home_iso3], team_match_count[away_iso3]) >= MIN_TEAM_MATCHES_FOR_HIERARCHICAL:
            return self._fit_hierarchical(
                df,
                home_iso3,
                away_iso3,
                competition_meta,
                diagnostics={**base_diagnostics, "fallback_reason": "insufficient_for_dixon_coles"},
            )

        return self._fit_elo_or_uniform(
            external_pool,
            home_iso3,
            away_iso3,
            competition_meta,
            diagnostics={**base_diagnostics, "fallback_reason": "insufficient_team_samples"},
        )

    def scoreline_projection(
        self,
        *,
        fit_artifacts: FitArtifacts | None = None,
        scenario_xg_home: float | None = None,
        scenario_xg_away: float | None = None,
        scenario_key: str,
        home_xg: float | None = None,
        away_xg: float | None = None,
        model_name: str | None = None,
        fit_status: str | None = None,
        home_iso3: str | None = None,
        away_iso3: str | None = None,
    ) -> dict[str, Any]:
        """Project exact scorelines using Dixon-Coles artifacts or Poisson priors."""
        scenario_xg_home = float(scenario_xg_home if scenario_xg_home is not None else home_xg)
        scenario_xg_away = float(scenario_xg_away if scenario_xg_away is not None else away_xg)
        if fit_artifacts is None:
            fit_artifacts = FitArtifacts(
                model=None,
                fit_status=fit_status or "fallback_prior",
                data_sufficiency="partial",
                model_name=model_name or "prior_poisson",
                diagnostics={},
                home_advantage=0.0,
            )

        probability_source = "poisson_prior"
        if fit_artifacts.model is not None:
            try:
                matrix = self._predict_score_matrix(
                    fit_artifacts.model,
                    scenario_xg_home,
                    scenario_xg_away,
                    home_iso3=home_iso3,
                    away_iso3=away_iso3,
                    fit_artifacts=fit_artifacts,
                )
                distribution = self._matrix_to_distribution(matrix)
                probability_source = "dixon_coles_corrected"
            except Exception as exc:
                distribution = self._poisson_score_distribution(scenario_xg_home, scenario_xg_away)
                probability_source = f"poisson_prior_after_model_error:{type(exc).__name__}"
        else:
            distribution = self._poisson_score_distribution(scenario_xg_home, scenario_xg_away)

        probabilities = _win_draw_loss(distribution)
        return {
            "home_xg": round(scenario_xg_home, 2),
            "away_xg": round(scenario_xg_away, 2),
            "win_draw_loss_probability": probabilities,
            "scoreline_distribution": distribution[:8],
            "most_likely_score": distribution[0]["score"],
            "total_goals_distribution": _total_goals_distribution(distribution),
            "model_name": fit_artifacts.model_name,
            "model_version": self.MODEL_VERSION,
            "metadata": {
                "fit_status": fit_artifacts.fit_status,
                "scenario_key": scenario_key,
                "probability_source": probability_source,
            },
        }

    def _home_advantage(self, competition_meta: dict[str, Any], home_iso3: str) -> float:
        if not bool(competition_meta.get("neutral_venue", True)):
            return 0.20
        if str(competition_meta.get("host_country_iso3") or "").upper() == home_iso3:
            return 0.20
        return 0.0

    def _build_training_set(
        self,
        external_pool: ExternalDataPool,
        extracted: dict[str, Any] | None,
        competition_meta: dict[str, Any],
    ) -> pd.DataFrame:
        cutoff_date = competition_meta.get("kickoff_iso")
        try:
            df = external_pool.fit_dataframe(cutoff_date=cutoff_date)
        except TypeError:
            df = external_pool.fit_dataframe()
        df = _normalize_training_frame(df)

        extracted_df = self._extracted_to_training_frame(extracted)
        if not extracted_df.empty:
            df = pd.concat([df, extracted_df], ignore_index=True)

        if df.empty:
            return df

        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date", "home_iso3", "away_iso3", "home_score", "away_score"])
        df = df[df["home_iso3"] != df["away_iso3"]]
        today = _cutoff_datetime(cutoff_date)
        days_ago = (today - df["date"]).dt.days.clip(lower=0)
        df["weight"] = np.exp(-XI_DECAY * days_ago)
        df["weight"] *= df.apply(_competition_weight, axis=1)
        df["home_score"] = pd.to_numeric(df["home_score"], errors="coerce").fillna(0).astype(int)
        df["away_score"] = pd.to_numeric(df["away_score"], errors="coerce").fillna(0).astype(int)
        if "neutral" not in df.columns:
            df["neutral"] = False
        df["neutral"] = df["neutral"].map(_to_bool)
        return df.reset_index(drop=True)

    def _extracted_to_training_frame(self, extracted: dict[str, Any] | None) -> pd.DataFrame:
        if not extracted:
            return pd.DataFrame()

        rows: list[dict[str, Any]] = []
        for item in extracted.get("recent_results") or []:
            team_iso3 = item.get("team_iso3")
            opponent_iso3 = item.get("opponent_iso3")
            scored = item.get("scored")
            conceded = item.get("conceded")
            if not team_iso3 or not opponent_iso3 or scored is None or conceded is None:
                continue
            venue = item.get("venue")
            if venue == "away":
                rows.append(
                    {
                        "date": item.get("date"),
                        "home_iso3": opponent_iso3,
                        "away_iso3": team_iso3,
                        "home_score": conceded,
                        "away_score": scored,
                        "neutral": False,
                        "tournament": item.get("competition") or "extracted",
                    }
                )
            else:
                rows.append(
                    {
                        "date": item.get("date"),
                        "home_iso3": team_iso3,
                        "away_iso3": opponent_iso3,
                        "home_score": scored,
                        "away_score": conceded,
                        "neutral": venue == "neutral",
                        "tournament": item.get("competition") or "extracted",
                    }
                )

        for item in extracted.get("head_to_head") or []:
            rows.append(item)

        return _normalize_training_frame(pd.DataFrame(rows))

    def _fit_dixon_coles(self, df: pd.DataFrame) -> Any:
        import penaltyblog as pb

        model = pb.models.DixonColesGoalModel(
            np.asarray(df["home_score"], dtype=np.int64).copy(order="C"),
            np.asarray(df["away_score"], dtype=np.int64).copy(order="C"),
            np.asarray(df["home_iso3"], dtype=str).copy(order="C"),
            np.asarray(df["away_iso3"], dtype=str).copy(order="C"),
            weights=np.asarray(df["weight"], dtype=float).copy(order="C"),
            neutral_venue=np.asarray(df["neutral"].astype(int), dtype=np.int64).copy(order="C"),
        )
        model.fit()
        return model

    def _fit_hierarchical(
        self,
        df: pd.DataFrame,
        home_iso3: str,
        away_iso3: str,
        competition_meta: dict[str, Any],
        diagnostics: dict[str, Any],
    ) -> FitArtifacts:
        coefficients = _smoothed_team_coefficients(df)
        if not coefficients[0]:
            return self._uniform_artifacts(
                home_iso3,
                away_iso3,
                diagnostics={**diagnostics, "fallback_reason": "hierarchical_no_training_rows"},
            )

        attack_coef, defense_coef, intercept = coefficients
        return FitArtifacts(
            model=None,
            fit_status="bayesian_hierarchical",
            data_sufficiency="partial",
            model_name="hierarchical_smoothed",
            diagnostics={
                **diagnostics,
                "method": "empirical_bayes_shrinkage",
                "home_advantage": self._home_advantage(competition_meta, home_iso3),
            },
            home_advantage=self._home_advantage(competition_meta, home_iso3),
            attack_coef=attack_coef,
            defense_coef=defense_coef,
            intercept=intercept,
            xg_priors={
                home_iso3: DEFAULT_PRIOR_XG,
                away_iso3: DEFAULT_PRIOR_XG,
            },
        )

    def _fit_elo_or_uniform(
        self,
        external_pool: ExternalDataPool,
        home_iso3: str,
        away_iso3: str,
        competition_meta: dict[str, Any],
        diagnostics: dict[str, Any],
    ) -> FitArtifacts:
        try:
            elo = external_pool.elo_snapshot()
            if home_iso3 in elo and away_iso3 in elo:
                neutral = bool(competition_meta.get("neutral_venue", True))
                host_iso3 = str(competition_meta.get("host_country_iso3") or "").upper() or None
                elo_host_iso3 = host_iso3
                if self._home_advantage(competition_meta, home_iso3) > 0 and not neutral:
                    elo_host_iso3 = home_iso3
                home_xg, away_xg = external_pool.elo.elo_to_lambda(
                    elo[home_iso3],
                    elo[away_iso3],
                    neutral=neutral,
                    home_iso3=home_iso3,
                    host_iso3=elo_host_iso3,
                )
                if self._home_advantage(competition_meta, home_iso3) > 0 and neutral and host_iso3 == home_iso3:
                    home_xg = _clip(home_xg * math.exp(0.20), 0.3, 4.5)
                return FitArtifacts(
                    model=None,
                    fit_status="elo_prior",
                    data_sufficiency="partial",
                    model_name="elo_prior",
                    diagnostics={
                        **diagnostics,
                        "home_elo": float(elo[home_iso3]),
                        "away_elo": float(elo[away_iso3]),
                        "home_xg_prior": float(home_xg),
                        "away_xg_prior": float(away_xg),
                    },
                    home_advantage=self._home_advantage(competition_meta, home_iso3),
                    xg_priors={home_iso3: float(home_xg), away_iso3: float(away_xg)},
                )
        except Exception as exc:
            diagnostics = {**diagnostics, "elo_error": f"{type(exc).__name__}: {exc}"}

        return self._uniform_artifacts(
            home_iso3,
            away_iso3,
            diagnostics={**diagnostics, "fallback_reason": "no_elo_no_history"},
        )

    def _uniform_artifacts(
        self,
        home_iso3: str,
        away_iso3: str,
        diagnostics: dict[str, Any],
    ) -> FitArtifacts:
        return FitArtifacts(
            model=None,
            fit_status="uniform",
            data_sufficiency="insufficient",
            model_name="uniform_prior",
            diagnostics=diagnostics,
            home_advantage=0.0,
            xg_priors={home_iso3: DEFAULT_PRIOR_XG, away_iso3: DEFAULT_PRIOR_XG},
        )

    def _team_match_count(self, df: pd.DataFrame, home_iso3: str, away_iso3: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        if not df.empty:
            combined = pd.concat([df["home_iso3"], df["away_iso3"]])
            counts = {str(k): int(v) for k, v in combined.value_counts().to_dict().items()}
        counts.setdefault(home_iso3, 0)
        counts.setdefault(away_iso3, 0)
        return counts

    def _predict_score_matrix(
        self,
        model: Any,
        home_xg: float,
        away_xg: float,
        *,
        home_iso3: str | None,
        away_iso3: str | None,
        fit_artifacts: FitArtifacts,
    ) -> np.ndarray:
        if hasattr(model, "predict_score_matrix"):
            return np.asarray(
                model.predict_score_matrix(
                    home_xg=home_xg,
                    away_xg=away_xg,
                    max_goals=MAX_GOALS,
                ),
                dtype=float,
            )

        rho = _model_rho(model)
        return _dixon_coles_xg_matrix(home_xg, away_xg, rho=rho, max_goals=MAX_GOALS)

    def _matrix_to_distribution(self, matrix: Any) -> list[dict[str, Any]]:
        matrix_arr = np.asarray(matrix, dtype=float)
        total = float(matrix_arr.sum())
        if total > 0:
            matrix_arr = matrix_arr / total
        distribution = []
        for home_goals in range(matrix_arr.shape[0]):
            for away_goals in range(matrix_arr.shape[1]):
                distribution.append(
                    {
                        "score": f"{home_goals}-{away_goals}",
                        "probability": round(float(matrix_arr[home_goals, away_goals]), 4),
                    }
                )
        distribution.sort(key=lambda item: item["probability"], reverse=True)
        return distribution

    def _poisson_score_distribution(self, home_xg: float, away_xg: float) -> list[dict[str, Any]]:
        return _poisson_score_distribution(home_xg, away_xg, max_goals=MAX_GOALS)


def extract_structured_match_inputs(text: str) -> dict[str, list[dict[str, Any]]]:
    """Extract lightweight structured evidence from uploaded text snapshots."""
    if not text:
        return {"structured_recent_matches": [], "structured_xg_samples": []}

    normalizer = TeamNameNormalizer()
    score_matches = []
    dated_result_pattern = re.compile(
        r"(?P<date>20\d{2}[-/]\d{1,2}[-/]\d{1,2})\s+"
        r"(?P<home>[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z .'\-]{1,40}?)\s*"
        r"(?:vs\.?|VS|v\.?|对阵|对)\s*"
        r"(?P<away>[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z .'\-]{1,40}?)\s+"
        r"(?P<competition>[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-zA-Z .'\-]{1,20})\s+"
        r"(?P<hg>[0-9])\s*[-:：]\s*(?P<ag>[0-9])"
    )
    for match in dated_result_pattern.finditer(text):
        home_name = _clean_structured_team_name(match.group("home"))
        away_name = _clean_structured_team_name(match.group("away"))
        if not home_name or not away_name:
            continue
        home_iso3 = normalizer.to_iso3(home_name)
        away_iso3 = normalizer.to_iso3(away_name)
        score_matches.append(
            {
                "date": _normalize_structured_date(match.group("date")),
                "home_team": home_name,
                "away_team": away_name,
                "home_goals": int(match.group("hg")),
                "away_goals": int(match.group("ag")),
                "competition": match.group("competition").strip(),
                **({"home_iso3": home_iso3} if home_iso3 else {}),
                **({"away_iso3": away_iso3} if away_iso3 else {}),
            }
        )
        if len(score_matches) >= 12:
            break

    xg_samples = []
    for match in re.finditer(
        r"(?:xG|预期进球)\s*[:：]?\s*(?P<home>[0-9]+(?:\.[0-9]+)?)\s*[-/]\s*(?P<away>[0-9]+(?:\.[0-9]+)?)",
        text,
        re.I,
    ):
        xg_samples.append({"home_xg": float(match.group("home")), "away_xg": float(match.group("away"))})
        if len(xg_samples) >= 12:
            break

    return {
        "structured_recent_matches": score_matches,
        "structured_xg_samples": xg_samples,
    }


def _clean_structured_team_name(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n,，。;；:：()[]【】")
    text = re.sub(r"^[-–—\s]+", "", text)
    return text.strip()


def _normalize_structured_date(value: str) -> str:
    parts = re.split(r"[-/]", str(value or "").strip())
    if len(parts) != 3:
        return str(value or "").strip()
    year, month, day = parts
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _normalize_training_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(
            columns=["date", "home_iso3", "away_iso3", "home_score", "away_score", "neutral", "tournament"]
        )

    normalized = df.copy()
    if "tournament" not in normalized.columns:
        normalized["tournament"] = ""
    if "neutral" not in normalized.columns:
        normalized["neutral"] = False
    required = ["date", "home_iso3", "away_iso3", "home_score", "away_score", "neutral", "tournament"]
    for column in required:
        if column not in normalized.columns:
            normalized[column] = None
    return normalized[required]


def _competition_weight(row: pd.Series) -> float:
    tournament = str(row.get("tournament") or "")
    if tournament in COMPETITIVE_TOURNAMENTS:
        return 1.5
    if "riendly" in tournament:
        return 0.6
    return 1.0


def _extract_model_coefficients(model: Any, df: pd.DataFrame) -> tuple[dict[str, float], dict[str, float], float]:
    params = model.get_params() if hasattr(model, "get_params") else {}
    attack: dict[str, float] = {}
    defense: dict[str, float] = {}
    for key, value in params.items():
        if key.startswith("attack_"):
            attack[key.removeprefix("attack_")] = float(value)
        elif key.startswith("defence_"):
            defense[key.removeprefix("defence_")] = float(value)
        elif key.startswith("defense_"):
            defense[key.removeprefix("defense_")] = float(value)

    if not attack or not defense:
        return _smoothed_team_coefficients(df)

    attack, defense = _shrink_sparse_dc_coefficients(attack, defense, df)
    intercept = _dc_intercept_from_coefficients(attack, defense)
    return attack, defense, intercept


def _shrink_sparse_dc_coefficients(
    attack: dict[str, float],
    defense: dict[str, float],
    df: pd.DataFrame,
) -> tuple[dict[str, float], dict[str, float]]:
    """Shrink volatile Dixon-Coles team coefficients when international samples are thin."""
    if df.empty:
        return attack, defense

    counts = {
        str(team): int(count)
        for team, count in pd.concat([df["home_iso3"], df["away_iso3"]]).value_counts().to_dict().items()
    }
    if not counts:
        return attack, defense

    prior_matches = 16.0
    full_sample_matches = 40
    shrunk_attack: dict[str, float] = {}
    shrunk_defense: dict[str, float] = {}
    for team, coef in attack.items():
        n_matches = counts.get(team, 0)
        factor = 1.0 if n_matches >= full_sample_matches else n_matches / (n_matches + prior_matches)
        shrunk_attack[team] = float(coef) * factor
    for team, coef in defense.items():
        n_matches = counts.get(team, 0)
        factor = 1.0 if n_matches >= full_sample_matches else n_matches / (n_matches + prior_matches)
        shrunk_defense[team] = float(coef) * factor
    return shrunk_attack, shrunk_defense


def _dc_intercept_from_coefficients(attack: dict[str, float], defense: dict[str, float]) -> float:
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
    return _clip(math.log(DEFAULT_PRIOR_XG / median_rate), -0.45, 0.45)


def _smoothed_team_coefficients(df: pd.DataFrame) -> tuple[dict[str, float], dict[str, float], float]:
    if df.empty:
        return {}, {}, math.log(DEFAULT_PRIOR_XG)

    teams = sorted(set(df["home_iso3"].dropna()) | set(df["away_iso3"].dropna()))
    mean_goals = max(0.2, float(pd.concat([df["home_score"], df["away_score"]]).mean()))
    attack: dict[str, float] = {}
    defense: dict[str, float] = {}
    for team in teams:
        goals_for = pd.concat(
            [
                df.loc[df["home_iso3"] == team, "home_score"],
                df.loc[df["away_iso3"] == team, "away_score"],
            ]
        )
        goals_against = pd.concat(
            [
                df.loc[df["home_iso3"] == team, "away_score"],
                df.loc[df["away_iso3"] == team, "home_score"],
            ]
        )
        n_for = len(goals_for)
        n_against = len(goals_against)
        smoothed_for = (float(goals_for.sum()) + 6 * mean_goals) / max(1, n_for + 6)
        smoothed_against = (float(goals_against.sum()) + 6 * mean_goals) / max(1, n_against + 6)
        attack[team] = _clip(math.log(max(0.1, smoothed_for) / mean_goals), -1.4, 1.4)
        defense[team] = _clip(math.log(max(0.1, smoothed_against) / mean_goals), -1.4, 1.4)
    return attack, defense, math.log(mean_goals)


def _poisson_score_distribution(
    home_xg: float,
    away_xg: float,
    *,
    max_goals: int = MAX_GOALS,
) -> list[dict[str, Any]]:
    scores = []
    matrix = _poisson_matrix(home_xg, away_xg, max_goals=max_goals)
    for home_goals in range(matrix.shape[0]):
        for away_goals in range(matrix.shape[1]):
            scores.append(
                {
                    "score": f"{home_goals}-{away_goals}",
                    "probability": round(float(matrix[home_goals, away_goals]), 4),
                }
            )
    scores.sort(key=lambda item: item["probability"], reverse=True)
    return scores


def _poisson_matrix(home_xg: float, away_xg: float, *, max_goals: int) -> np.ndarray:
    matrix = np.zeros((max_goals, max_goals), dtype=float)
    for home_goals in range(max_goals):
        for away_goals in range(max_goals):
            matrix[home_goals, away_goals] = _poisson_pmf(home_goals, home_xg) * _poisson_pmf(away_goals, away_xg)
    total = float(matrix.sum())
    if total > 0:
        matrix /= total
    return matrix


def _dixon_coles_xg_matrix(home_xg: float, away_xg: float, *, rho: float, max_goals: int) -> np.ndarray:
    matrix = _poisson_matrix(home_xg, away_xg, max_goals=max_goals)
    adjustments = {
        (0, 0): 1 - home_xg * away_xg * rho,
        (0, 1): 1 + home_xg * rho,
        (1, 0): 1 + away_xg * rho,
        (1, 1): 1 - rho,
    }
    for (home_goals, away_goals), factor in adjustments.items():
        if home_goals < max_goals and away_goals < max_goals:
            matrix[home_goals, away_goals] = max(0.0, matrix[home_goals, away_goals] * factor)
    total = float(matrix.sum())
    if total > 0:
        matrix /= total
    return matrix


def _model_rho(model: Any) -> float:
    if hasattr(model, "rho"):
        return float(model.rho)
    if hasattr(model, "params"):
        try:
            params = model.params
            if isinstance(params, dict) and "rho" in params:
                return float(params["rho"])
        except Exception:
            pass
    return -0.1


def _poisson_pmf(goals: int, lam: float) -> float:
    lam = _clip(float(lam), 0.05, 4.5)
    return math.exp(-lam) * (lam**goals) / math.factorial(goals)


def _win_draw_loss(distribution: list[dict[str, Any]]) -> dict[str, float]:
    home_win = draw = away_win = 0.0
    for item in distribution:
        home, away = (int(part) for part in item["score"].split("-"))
        probability = float(item["probability"])
        if home > away:
            home_win += probability
        elif home == away:
            draw += probability
        else:
            away_win += probability
    total = home_win + draw + away_win
    if total <= 0:
        return {"home_win": 0.34, "draw": 0.32, "away_win": 0.34}
    return {
        "home_win": round(home_win / total, 4),
        "draw": round(draw / total, 4),
        "away_win": round(away_win / total, 4),
    }


def _total_goals_distribution(distribution: list[dict[str, Any]]) -> dict[str, float]:
    totals = {str(i): 0.0 for i in range(5)}
    totals["5+"] = 0.0
    for item in distribution:
        home, away = (int(part) for part in item["score"].split("-"))
        total = home + away
        bucket = str(total) if total < 5 else "5+"
        totals[bucket] = totals.get(bucket, 0.0) + float(item["probability"])
    raw_total = sum(totals.values())
    if raw_total > 0:
        totals = {key: value / raw_total for key, value in totals.items()}
    return {key: round(value, 4) for key, value in totals.items()}


def _cutoff_datetime(cutoff_date: str | None) -> pd.Timestamp:
    if cutoff_date:
        parsed = pd.Timestamp(cutoff_date)
        if parsed.tzinfo is not None:
            parsed = parsed.tz_convert(None)
        return parsed
    return pd.Timestamp(datetime.now(UTC).replace(tzinfo=None))


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


def _maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_builtin(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_builtin(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_builtin(item) for item in value]
    if isinstance(value, tuple):
        return [_to_builtin(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    return value

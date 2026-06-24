from __future__ import annotations

from datetime import date, timedelta
import math

import numpy as np
import pandas as pd

from app.services.external_data import IntlResults, NationalElo
from app.services.football_goal_model import (
    ExternalDataPool,
    FitArtifacts,
    FootballGoalModelAdapter,
    extract_structured_match_inputs,
)


class FakeElo:
    def __init__(self, snapshot: dict[str, float] | None = None):
        self._snapshot = {"BRA": 2100.0, "ARG": 2050.0, "USA": 1900.0} if snapshot is None else snapshot

    def fetch_current_snapshot(self) -> dict[str, float]:
        return dict(self._snapshot)

    def elo_to_lambda(
        self,
        home_elo: float,
        away_elo: float,
        neutral: bool = True,
        home_iso3: str | None = None,
        host_iso3: str | None = None,
        base_lambda: float = 1.35,
    ) -> tuple[float, float]:
        diff = (home_elo - away_elo) / 173.7
        home_adv = 0.20 if (not neutral and home_iso3 == host_iso3) else 0.0
        return (
            base_lambda * math.exp(diff / 2 + home_adv),
            base_lambda * math.exp(-diff / 2),
        )


class FakePool:
    def __init__(self, df: pd.DataFrame, elo_snapshot: dict[str, float] | None = None):
        self._df = df
        self._elo_snapshot = {"BRA": 2100.0, "ARG": 2050.0, "USA": 1900.0} if elo_snapshot is None else elo_snapshot
        self.elo = FakeElo(self._elo_snapshot)

    def fit_dataframe(self, cutoff_date: str | None = None) -> pd.DataFrame:
        del cutoff_date
        return self._df.copy()

    def elo_snapshot(self) -> dict[str, float]:
        return dict(self._elo_snapshot)


class EmptyEloPool(FakePool):
    def __init__(self):
        super().__init__(_empty_df(), {})
        self.elo = FakeElo({})


class FakeDixonColesModel:
    aic = 123.4
    loglikelihood = -51.2

    def fit(self):
        return None

    def get_params(self):
        return {
            "attack_BRA": 0.25,
            "attack_ARG": 0.18,
            "defence_BRA": -0.08,
            "defence_ARG": 0.04,
            "home_advantage": 0.2,
            "rho": -0.12,
        }

    def predict_score_matrix(self, *, home_xg: float, away_xg: float, max_goals: int):
        base = _independent_matrix(home_xg, away_xg, max_goals)
        base[0, 0] *= 1.12
        return base / base.sum()


class FakeCenteredDixonColesModel:
    aic = 222.0
    loglikelihood = -88.0

    def fit(self):
        return None

    def get_params(self):
        return {
            "attack_CIV": 1.48,
            "attack_ECU": 1.16,
            "defence_CIV": -1.66,
            "defence_ECU": -2.50,
            "home_advantage": 0.0,
            "rho": -0.1,
        }


class FakePredictOnlyModel:
    params = {"rho": -0.05}

    def predict(self, home_iso3: str, away_iso3: str, *, max_goals: int, neutral_venue: bool):
        del home_iso3, away_iso3, neutral_venue
        return _independent_matrix(1.0, 1.0, max_goals)


def test_dixon_coles_fits_when_data_sufficient(monkeypatch):
    monkeypatch.setattr(
        "app.services.football_goal_model.FootballGoalModelAdapter._fit_dixon_coles",
        lambda self, df: FakeDixonColesModel(),
    )
    pool = FakePool(_training_df(n_rows=1600, bra_arg_rows=12))

    artifacts = FootballGoalModelAdapter().fit(
        external_pool=pool,
        home_iso3="BRA",
        away_iso3="ARG",
        competition_meta={"tournament": "FIFA World Cup", "neutral_venue": True},
    )

    assert artifacts.fit_status == "fitted"
    assert artifacts.data_sufficiency == "sufficient"
    assert artifacts.model_name == "dixon_coles_decay"
    assert artifacts.diagnostics["n_rows"] >= 1500
    assert artifacts.diagnostics["team_match_count"]["BRA"] >= 8
    assert artifacts.attack_coef["BRA"] == 0.25


def test_dixon_coles_coefficients_are_recentered_to_football_xg(monkeypatch):
    monkeypatch.setattr(
        "app.services.football_goal_model.FootballGoalModelAdapter._fit_dixon_coles",
        lambda self, df: FakeCenteredDixonColesModel(),
    )
    df = _training_df(n_rows=1600, bra_arg_rows=0)
    civ_rows = pd.DataFrame(
        [
            {
                "date": (date(2024, 1, 1) + timedelta(days=i)).isoformat(),
                "home_iso3": "CIV" if i % 2 == 0 else "ECU",
                "away_iso3": "ECU" if i % 2 == 0 else "CIV",
                "home_score": 1,
                "away_score": 1 if i % 3 == 0 else 0,
                "neutral": True,
                "tournament": "FIFA World Cup",
            }
            for i in range(12)
        ]
    )
    pool = FakePool(pd.concat([df, civ_rows], ignore_index=True))

    artifacts = FootballGoalModelAdapter().fit(
        external_pool=pool,
        home_iso3="CIV",
        away_iso3="ECU",
        competition_meta={"tournament": "FIFA World Cup", "neutral_venue": True},
    )

    home_xg, away_xg = artifacts.compute_match_xg("CIV", "ECU")

    assert artifacts.fit_status == "fitted"
    assert artifacts.intercept != 0.0
    assert 0.8 <= home_xg <= 1.4
    assert 0.8 <= away_xg <= 1.4


def test_falls_back_to_elo_when_no_history():
    artifacts = FootballGoalModelAdapter().fit(
        external_pool=FakePool(_empty_df()),
        home_iso3="BRA",
        away_iso3="ARG",
        competition_meta={"neutral_venue": True},
    )

    assert artifacts.fit_status == "elo_prior"
    assert artifacts.data_sufficiency == "partial"
    assert "BRA" in artifacts.xg_priors
    assert artifacts.xg_priors["BRA"] > artifacts.xg_priors["ARG"]


def test_falls_back_to_uniform_when_no_data():
    artifacts = FootballGoalModelAdapter().fit(
        external_pool=EmptyEloPool(),
        home_iso3="BRA",
        away_iso3="ARG",
        competition_meta={"neutral_venue": True},
    )

    assert artifacts.fit_status == "uniform"
    assert artifacts.data_sufficiency == "insufficient"
    assert artifacts.xg_priors == {"BRA": 1.35, "ARG": 1.35}


def test_neutral_venue_no_home_advantage():
    artifacts = FitArtifacts(
        model=None,
        fit_status="elo_prior",
        data_sufficiency="partial",
        model_name="elo_prior",
        diagnostics={},
        home_advantage=FootballGoalModelAdapter()._home_advantage(
            {"neutral_venue": True, "host_country_iso3": "USA"}, "BRA"
        ),
        xg_priors={"BRA": 1.6, "USA": 1.2},
    )

    home_xg, away_xg = artifacts.compute_match_xg("BRA", "USA", 1.0, 1.0)

    assert artifacts.home_advantage == 0.0
    assert home_xg == 1.6
    assert away_xg == 1.2


def test_host_country_gets_advantage_when_at_home():
    artifacts = FitArtifacts(
        model=None,
        fit_status="bayesian_hierarchical",
        data_sufficiency="partial",
        model_name="hierarchical_smoothed",
        diagnostics={},
        home_advantage=FootballGoalModelAdapter()._home_advantage(
            {"neutral_venue": True, "host_country_iso3": "USA"}, "USA"
        ),
        attack_coef={"USA": 0.0, "BRA": 0.0},
        defense_coef={"USA": 0.0, "BRA": 0.0},
        intercept=math.log(1.35),
    )

    home_xg, away_xg = artifacts.compute_match_xg("USA", "BRA", 1.0, 1.0)

    assert artifacts.home_advantage == 0.20
    assert home_xg > away_xg
    assert round(home_xg, 2) == round(1.35 * math.exp(0.20), 2)


def test_scoreline_low_score_correction():
    artifacts = FitArtifacts(
        model=FakeDixonColesModel(),
        fit_status="fitted",
        data_sufficiency="sufficient",
        model_name="dixon_coles_decay",
        diagnostics={},
        home_advantage=0.0,
    )
    adapter = FootballGoalModelAdapter()

    corrected = adapter.scoreline_projection(
        fit_artifacts=artifacts,
        scenario_xg_home=1.1,
        scenario_xg_away=1.0,
        scenario_key="baseline",
    )
    poisson = adapter.scoreline_projection(
        fit_artifacts=FitArtifacts(
            model=None,
            fit_status="elo_prior",
            data_sufficiency="partial",
            model_name="elo_prior",
            diagnostics={},
            home_advantage=0.0,
        ),
        scenario_xg_home=1.1,
        scenario_xg_away=1.0,
        scenario_key="baseline",
    )

    corrected_00 = _probability(corrected["scoreline_distribution"], "0-0")
    poisson_00 = _probability(poisson["scoreline_distribution"], "0-0")
    assert corrected["metadata"]["probability_source"] == "dixon_coles_corrected"
    assert corrected_00 > poisson_00


def test_scoreline_projection_respects_scenario_xg_with_fitted_model():
    artifacts = FitArtifacts(
        model=FakePredictOnlyModel(),
        fit_status="fitted",
        data_sufficiency="sufficient",
        model_name="dixon_coles_decay",
        diagnostics={},
        home_advantage=0.0,
    )
    adapter = FootballGoalModelAdapter()

    low_home = adapter.scoreline_projection(
        fit_artifacts=artifacts,
        scenario_xg_home=0.8,
        scenario_xg_away=1.2,
        scenario_key="away_edge",
        home_iso3="BRA",
        away_iso3="ARG",
    )
    high_home = adapter.scoreline_projection(
        fit_artifacts=artifacts,
        scenario_xg_home=2.0,
        scenario_xg_away=0.7,
        scenario_key="home_edge",
        home_iso3="BRA",
        away_iso3="ARG",
    )

    assert _probability(high_home["scoreline_distribution"], "1-0") > _probability(
        low_home["scoreline_distribution"], "1-0"
    )
    assert high_home["win_draw_loss_probability"]["home_win"] > low_home["win_draw_loss_probability"]["home_win"]


def test_compute_match_xg_clipped():
    artifacts = FitArtifacts(
        model=None,
        fit_status="elo_prior",
        data_sufficiency="partial",
        model_name="elo_prior",
        diagnostics={},
        home_advantage=0.0,
        xg_priors={"BRA": 10.0, "ARG": 0.01},
    )

    home_xg, away_xg = artifacts.compute_match_xg("BRA", "ARG", 2.0, 0.1)

    assert home_xg == 4.5
    assert away_xg == 0.3


def test_fit_artifacts_round_trip_without_model():
    artifacts = FitArtifacts(
        model=FakeDixonColesModel(),
        fit_status="fitted",
        data_sufficiency="sufficient",
        model_name="dixon_coles_decay",
        diagnostics={"n_rows": np.int64(1600)},
        home_advantage=0.2,
        attack_coef={"BRA": 0.25},
        defense_coef={"ARG": 0.04},
        intercept=0.0,
    )

    restored = FitArtifacts.from_dict(artifacts.to_dict())

    assert restored.model is None
    assert restored.fit_status == "fitted"
    assert restored.diagnostics["n_rows"] == 1600
    assert restored.attack_coef["BRA"] == 0.25


def test_scoreline_projection_legacy_signature_still_works():
    projection = FootballGoalModelAdapter().scoreline_projection(
        home_xg=1.4,
        away_xg=1.1,
        model_name="prior_poisson",
        fit_status="fallback_prior",
        scenario_key="legacy",
    )

    assert projection["model_name"] == "prior_poisson"
    assert projection["model_version"] == "v2"
    assert projection["metadata"]["fit_status"] == "fallback_prior"
    assert projection["scoreline_distribution"]


def test_extract_structured_match_inputs_reads_dated_recent_results_without_noise():
    text = """
2026-06-06    比利时 vs 突尼斯        友谊赛    5-0     Courtois 首发零封。
2026-06-02    克罗地亚 vs 比利时      友谊赛    0-2     Tielemans、Lukaku 进球。
2025-03-25    埃及 vs 塞拉利昂      世预赛    1-0
友谊赛    5-0     Courtois 首发零封
xG / xGA / PPDA                               暂无可靠统一公开赛前数据
"""

    result = extract_structured_match_inputs(text)

    assert result["structured_recent_matches"] == [
        {
            "date": "2026-06-06",
            "home_team": "比利时",
            "away_team": "突尼斯",
            "home_goals": 5,
            "away_goals": 0,
            "competition": "友谊赛",
            "home_iso3": "BEL",
            "away_iso3": "TUN",
        },
        {
            "date": "2026-06-02",
            "home_team": "克罗地亚",
            "away_team": "比利时",
            "home_goals": 0,
            "away_goals": 2,
            "competition": "友谊赛",
            "home_iso3": "CRO",
            "away_iso3": "BEL",
        },
        {
            "date": "2025-03-25",
            "home_team": "埃及",
            "away_team": "塞拉利昂",
            "home_goals": 1,
            "away_goals": 0,
            "competition": "世预赛",
            "home_iso3": "EGY",
            "away_iso3": "SLE",
        },
    ]
    assert result["structured_xg_samples"] == []


def test_external_data_pool_offline_fetch_and_fit_dataframe():
    pool = ExternalDataPool().fetch_for_match(
        "BRA",
        "ARG",
        since_year=2014,
        cutoff_date="2026-07-15T00:00:00Z",
        offline=True,
    )

    df = pool.fit_dataframe()
    elo = pool.elo_snapshot()

    assert len(df) >= 1500
    assert {"home_iso3", "away_iso3", "home_score", "away_score"}.issubset(df.columns)
    assert "BRA" in elo


def test_external_data_pool_degrades_when_offline_seeds_are_missing(tmp_path):
    pool = ExternalDataPool(
        intl_results=IntlResults(cache_dir=tmp_path),
        elo=NationalElo(cache_dir=tmp_path),
    ).fetch_for_match(
        "TUN",
        "JPN",
        since_year=2014,
        offline=True,
    )

    df = pool.fit_dataframe()

    assert df.empty
    assert {"home_iso3", "away_iso3", "home_score", "away_score"}.issubset(df.columns)
    assert pool.elo_snapshot() == {}
    assert "Missing offline seed" in pool.source_errors["intl_results"]
    assert "Missing offline seed" in pool.source_errors["national_elo"]


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["date", "home_iso3", "away_iso3", "home_score", "away_score", "neutral", "tournament"]
    )


def _training_df(n_rows: int, bra_arg_rows: int) -> pd.DataFrame:
    teams = ["BRA", "ARG", "USA", "FRA", "ESP", "GER", "NED", "POR", "URU", "MEX", "CAN", "JPN"]
    start = date(2020, 1, 1)
    rows = []
    for i in range(n_rows):
        home = teams[i % len(teams)]
        away = teams[(i + 3) % len(teams)]
        if i < bra_arg_rows:
            home = "BRA" if i % 2 == 0 else "ARG"
            away = "ARG" if i % 2 == 0 else "BRA"
        rows.append(
            {
                "date": (start + timedelta(days=i)).isoformat(),
                "home_iso3": home,
                "away_iso3": away,
                "home_score": i % 4,
                "away_score": (i + 1) % 3,
                "neutral": i % 5 == 0,
                "tournament": "FIFA World Cup" if i % 3 == 0 else "Friendly",
            }
        )
    return pd.DataFrame(rows)


def _independent_matrix(home_xg: float, away_xg: float, max_goals: int) -> np.ndarray:
    matrix = np.zeros((max_goals, max_goals), dtype=float)
    for home in range(max_goals):
        for away in range(max_goals):
            matrix[home, away] = (
                math.exp(-home_xg)
                * (home_xg**home)
                / math.factorial(home)
                * math.exp(-away_xg)
                * (away_xg**away)
                / math.factorial(away)
            )
    return matrix / matrix.sum()


def _probability(distribution: list[dict], score: str) -> float:
    return next(item["probability"] for item in distribution if item["score"] == score)

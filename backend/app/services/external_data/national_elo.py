from __future__ import annotations

import math

import pandas as pd

from .base import ExternalDataSource
from .team_name_normalizer import TeamNameNormalizer


class NationalElo(ExternalDataSource):
    """National team Elo ratings from eloratings.net."""

    file_extension = ".tsv"

    @property
    def source_key(self) -> str:
        return "national_elo"

    @property
    def primary_url(self) -> str:
        return "https://eloratings.net/World.tsv"

    @property
    def fallback_urls(self) -> list[str]:
        return [
            "http://eloratings.net/World.tsv",
            "https://raw.githubusercontent.com/n-zM/elo-ratings-football/main/snapshots/latest.tsv",
        ]

    def as_dataframe(self, *, offline: bool = False, force: bool = False) -> pd.DataFrame:
        path = self._cached_or_fetch(offline=offline, force=force)
        raw = pd.read_csv(path, sep="\t", header=None, dtype=str, keep_default_na=False)
        rank_col, team_col, rating_col = self._detect_columns(raw)
        normalizer = TeamNameNormalizer()
        df = pd.DataFrame(
            {
                "rank": pd.to_numeric(raw[rank_col], errors="coerce"),
                "team_name": raw[team_col].astype(str),
                "elo_rating": pd.to_numeric(raw[rating_col], errors="coerce"),
            }
        )
        df["team_iso3"] = df["team_name"].apply(
            lambda value: normalizer.to_iso3(value, source="national_elo")
        )
        df = df.dropna(subset=["rank", "team_iso3", "elo_rating"])
        df["rank"] = df["rank"].astype(int)
        df["elo_rating"] = df["elo_rating"].astype(float)
        df = df.sort_values("rank").drop_duplicates("team_iso3", keep="first")
        df["team_name"] = df["team_iso3"].apply(normalizer.to_canonical_en)
        return df[["team_iso3", "team_name", "elo_rating", "rank"]].reset_index(
            drop=True
        )

    def fetch_current_snapshot(self) -> dict[str, float]:
        df = self.as_dataframe()
        return dict(zip(df["team_iso3"], df["elo_rating"], strict=False))

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
        home_xg = base_lambda * math.exp(diff / 2 + home_adv)
        away_xg = base_lambda * math.exp(-diff / 2)
        return _clip(home_xg, 0.3, 4.0), _clip(away_xg, 0.3, 4.0)

    def _detect_columns(self, raw: pd.DataFrame) -> tuple[int, int, int]:
        if raw.shape[1] >= 4 and not _is_number(raw.iat[0, 2]):
            return 0, 2, 3
        return 0, 1, 2


def _is_number(value: object) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))

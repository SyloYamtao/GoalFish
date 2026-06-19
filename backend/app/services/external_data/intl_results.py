from __future__ import annotations

from pathlib import Path

import pandas as pd

from .base import ExternalDataSource
from .team_name_normalizer import DEFAULT_ALIAS_FILE, TeamNameNormalizer


class IntlResults(ExternalDataSource):
    """International match results from martj42/international_results."""

    file_extension = ".csv"

    @property
    def source_key(self) -> str:
        return "intl_results"

    @property
    def primary_url(self) -> str:
        return (
            "https://raw.githubusercontent.com/martj42/"
            "international_results/master/results.csv"
        )

    @property
    def fallback_urls(self) -> list[str]:
        return [
            "https://raw.githubusercontent.com/jalapic/engsoccerdata/master/data-raw/results.csv",
        ]

    def as_dataframe(self, *, offline: bool = False, force: bool = False) -> pd.DataFrame:
        path = self._cached_or_fetch(offline=offline, force=force)
        return pd.read_csv(path)

    def as_fit_dataframe(
        self,
        start_date: str = "2014-01-01",
        end_date: str | None = None,
        cutoff_date: str | None = None,
        *,
        offline: bool = False,
        force: bool = False,
        normalizer: TeamNameNormalizer | None = None,
        alias_file: Path = DEFAULT_ALIAS_FILE,
    ) -> pd.DataFrame:
        df = self.as_dataframe(offline=offline, force=force).copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date", "home_score", "away_score"])
        df = df[df["date"] >= pd.Timestamp(start_date)]
        if end_date:
            df = df[df["date"] <= pd.Timestamp(end_date)]
        if cutoff_date:
            df = df[df["date"] < pd.Timestamp(cutoff_date)]
        df = df[~df["tournament"].str.contains("Friendly", case=False, na=False)]

        normalizer = normalizer or TeamNameNormalizer(alias_file)
        df["home_iso3"] = df["home_team"].apply(
            lambda value: normalizer.to_iso3(str(value), source="intl_results")
        )
        df["away_iso3"] = df["away_team"].apply(
            lambda value: normalizer.to_iso3(str(value), source="intl_results")
        )
        df = df.dropna(subset=["home_iso3", "away_iso3"])
        df["date"] = df["date"].dt.strftime("%Y-%m-%d")
        if "neutral" in df.columns:
            df["neutral"] = df["neutral"].map(_to_bool)

        return df[
            [
                "date",
                "home_iso3",
                "away_iso3",
                "home_score",
                "away_score",
                "neutral",
            ]
        ].reset_index(drop=True)


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes"}

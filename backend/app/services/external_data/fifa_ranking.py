from __future__ import annotations

import pandas as pd

from .base import ExternalDataSource


class FIFARankingSource(ExternalDataSource):
    """P1 placeholder for FIFA ranking integration."""

    file_extension = ".csv"

    @property
    def source_key(self) -> str:
        return "fifa_ranking"

    @property
    def primary_url(self) -> str:
        return (
            "https://raw.githubusercontent.com/cristiandley/"
            "fifa-world-ranking-history/main/data/fifa_ranking.csv"
        )

    @property
    def fallback_urls(self) -> list[str]:
        return []

    def as_dataframe(self, **kwargs: object) -> pd.DataFrame:
        raise NotImplementedError("FIFA Ranking is P1 and not implemented in Track 1A")

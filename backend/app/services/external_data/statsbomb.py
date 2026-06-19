from __future__ import annotations

import pandas as pd

from .base import ExternalDataSource


class StatsBombSource(ExternalDataSource):
    """P1 placeholder for StatsBomb Open Data integration."""

    file_extension = ".json"
    required_license_notice = "Free StatsBomb data - Provided by StatsBomb"

    @property
    def source_key(self) -> str:
        return "statsbomb"

    @property
    def primary_url(self) -> str:
        return "https://github.com/statsbomb/open-data"

    @property
    def fallback_urls(self) -> list[str]:
        return []

    def as_dataframe(self, **kwargs: object) -> pd.DataFrame:
        raise NotImplementedError("StatsBomb is P1 and not implemented in Track 1A")

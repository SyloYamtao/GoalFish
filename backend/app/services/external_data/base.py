from __future__ import annotations

import hashlib
import json
import os
import shutil
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CACHE_DIR = REPO_ROOT / "data" / "external"
USER_AGENT = "GoalFish-Prediction/0.1"
MAX_RESPONSE_BYTES = 50 * 1024 * 1024


class ExternalDataError(RuntimeError):
    pass


class ExternalDataSource(ABC):
    """Base class for external public data sources."""

    file_extension = ".csv"
    required_license_notice: str | None = None

    def __init__(self, cache_dir: Path | str = Path("data/external")):
        cache_path = Path(cache_dir)
        self.cache_dir = cache_path if cache_path.is_absolute() else REPO_ROOT / cache_path
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.meta_file = self.cache_dir / f"{self.source_key}.meta.json"

    @property
    @abstractmethod
    def source_key(self) -> str:
        """Stable source identifier, for example ``intl_results``."""

    @property
    @abstractmethod
    def primary_url(self) -> str:
        """Primary HTTP URL."""

    @property
    @abstractmethod
    def fallback_urls(self) -> list[str]:
        """Fallback HTTP URLs."""

    @abstractmethod
    def as_dataframe(self, **kwargs: Any) -> pd.DataFrame:
        """Read the cached source into a DataFrame."""

    @property
    def cache_file(self) -> Path:
        return self.cache_dir / f"{self.source_key}{self.file_extension}"

    @property
    def seed_file(self) -> Path:
        return self.cache_dir / "seeds" / f"{self.source_key}{self.file_extension}"

    def fetch(self, *, force: bool = False, offline: bool = False) -> Path:
        """
        Fetch the source into the local cache and return the cached file path.

        Offline mode copies ``data/external/seeds/<source>`` into the cache.
        Online mode uses conditional HTTP GET with ETag/Last-Modified metadata.
        """
        if offline or os.getenv("EXTERNAL_DATA_OFFLINE") == "1":
            return self._copy_seed_to_cache()

        if self.cache_file.exists() and not force:
            meta = self._read_meta()
        else:
            meta = {}

        headers = {"User-Agent": USER_AGENT}
        if self.cache_file.exists() and not force:
            if meta.get("etag"):
                headers["If-None-Match"] = str(meta["etag"])
            if meta.get("last_modified"):
                headers["If-Modified-Since"] = str(meta["last_modified"])

        errors: list[str] = []
        for url in [self.primary_url, *self.fallback_urls]:
            try:
                path = self._http_get_to_cache(url=url, headers=headers)
                return path
            except _NotModified:
                self._write_meta(
                    url_used=url,
                    etag=meta.get("etag"),
                    last_modified=meta.get("last_modified"),
                )
                return self.cache_file
            except Exception as exc:  # pragma: no cover - depends on live network
                errors.append(f"{url}: {type(exc).__name__}: {exc}")

        if self.cache_file.exists():
            return self.cache_file
        raise ExternalDataError(
            f"Failed to fetch {self.source_key}; tried {len(errors)} URLs: "
            + "; ".join(errors)
        )

    def fingerprint(self) -> dict[str, Any]:
        return self._read_meta()

    def _copy_seed_to_cache(self) -> Path:
        if not self.seed_file.exists():
            raise FileNotFoundError(f"Missing offline seed: {self.seed_file}")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.seed_file, self.cache_file)
        self._write_meta(
            url_used=f"seed://{self.source_key}{self.file_extension}",
            etag=None,
            last_modified=None,
        )
        return self.cache_file

    def _http_get_to_cache(self, *, url: str, headers: dict[str, str]) -> Path:
        with requests.Session() as session:
            response = session.get(url, headers=headers, stream=True, timeout=30)
            if response.status_code == 304 and self.cache_file.exists():
                raise _NotModified
            response.raise_for_status()
            self._validate_content_type(response.headers.get("Content-Type", ""))
            tmp_file = self.cache_file.with_suffix(self.cache_file.suffix + ".tmp")
            total = 0
            with tmp_file.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 64):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_RESPONSE_BYTES:
                        tmp_file.unlink(missing_ok=True)
                        raise ExternalDataError(
                            f"{self.source_key} response exceeds 50 MB limit"
                        )
                    handle.write(chunk)
            tmp_file.replace(self.cache_file)
            self._write_meta(
                url_used=url,
                etag=response.headers.get("ETag"),
                last_modified=response.headers.get("Last-Modified"),
            )
            return self.cache_file

    def _validate_content_type(self, content_type: str) -> None:
        allowed = ("csv", "tsv", "json", "text", "plain", "octet-stream")
        lowered = content_type.lower()
        if lowered and not any(item in lowered for item in allowed):
            raise ExternalDataError(
                f"Unexpected content type for {self.source_key}: {content_type}"
            )

    def _write_meta(
        self,
        *,
        url_used: str,
        etag: str | None,
        last_modified: str | None,
    ) -> None:
        meta = {
            "source": self.source_key,
            "url_used": url_used,
            "etag": etag,
            "last_modified": last_modified,
            "fetched_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "row_count": self._row_count(self.cache_file),
            "sha256_first_kb": self._sha256_first_kb(self.cache_file),
        }
        self.meta_file.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _read_meta(self) -> dict[str, Any]:
        if not self.meta_file.exists():
            return {}
        return json.loads(self.meta_file.read_text(encoding="utf-8"))

    def _cached_or_fetch(self, *, offline: bool = False, force: bool = False) -> Path:
        if self.cache_file.exists() and not force and not offline:
            return self.cache_file
        return self.fetch(force=force, offline=offline)

    def _row_count(self, path: Path) -> int:
        if not path.exists():
            return 0
        with path.open("rb") as handle:
            rows = sum(1 for line in handle if line.strip())
        if self.file_extension == ".csv" and rows > 0:
            return rows - 1
        return rows

    def _sha256_first_kb(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            digest.update(handle.read(1024))
        return digest.hexdigest()


class _NotModified(Exception):
    pass

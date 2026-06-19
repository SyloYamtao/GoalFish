from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Iterable

import yaml

try:
    from rapidfuzz import fuzz, process
except Exception:  # pragma: no cover - used only without optional dependency
    fuzz = None
    process = None


DEFAULT_ALIAS_FILE = Path(__file__).with_name("country_alias.yaml")
FUZZY_THRESHOLD = 88


class TeamNameNormalizer:
    """Normalize football team names from multiple sources to FIFA/ISO3 codes."""

    def __init__(self, alias_file: Path = DEFAULT_ALIAS_FILE):
        self.alias_file = Path(alias_file)
        self.alias_map = yaml.safe_load(self.alias_file.read_text(encoding="utf-8"))
        if not isinstance(self.alias_map, dict):
            raise ValueError(f"Invalid alias file: {self.alias_file}")
        self._source_indexes: dict[str, dict[str, str]] = {}
        self._all_index: dict[str, str] = {}
        self._build_indexes()

    def to_iso3(self, team_name: str, source: str | None = None) -> str | None:
        if not team_name:
            return None
        key = normalize_key(_strip_document_noise(team_name))
        if not key:
            return None

        indexes = []
        if source:
            indexes.append(self._source_indexes.get(source, {}))
            indexes.append(self._source_indexes.get("__canonical__", {}))
        else:
            indexes.append(self._all_index)

        for index in indexes:
            if key in index:
                return index[key]

        candidates = self._candidate_index(source)
        if not candidates:
            return None
        if len(key) <= 3:
            return None
        return self._fuzzy_lookup(key, candidates)

    def to_canonical_zh(self, iso3: str) -> str:
        entry = self.alias_map.get(iso3)
        if not entry:
            return iso3
        return str(entry.get("canonical_zh") or iso3)

    def to_canonical_en(self, iso3: str) -> str:
        entry = self.alias_map.get(iso3)
        if not entry:
            return iso3
        return str(entry.get("canonical_en") or iso3)

    def _build_indexes(self) -> None:
        canonical_index: dict[str, str] = {}
        for iso3, entry in self.alias_map.items():
            if not isinstance(entry, dict):
                continue
            canonical_values = [
                entry.get("canonical_en"),
                entry.get("canonical_zh"),
                iso3,
            ]
            for value in canonical_values:
                self._add_alias(canonical_index, value, iso3)
                self._add_alias(self._all_index, value, iso3)

            for source, values in entry.items():
                if source in {"canonical_en", "canonical_zh"}:
                    continue
                source_index = self._source_indexes.setdefault(source, {})
                for value in _iter_values(values):
                    self._add_alias(source_index, value, iso3)
                    self._add_alias(self._all_index, value, iso3)

        self._source_indexes["__canonical__"] = canonical_index

    def _candidate_index(self, source: str | None) -> dict[str, str]:
        if source:
            merged = dict(self._source_indexes.get("__canonical__", {}))
            merged.update(self._source_indexes.get(source, {}))
            return merged
        return self._all_index

    def _fuzzy_lookup(self, key: str, candidates: dict[str, str]) -> str | None:
        if process and fuzz:
            match = process.extractOne(key, list(candidates.keys()), scorer=fuzz.WRatio)
            if match and match[1] >= FUZZY_THRESHOLD and _acceptable_fuzzy_match(key, match[0]):
                return candidates[match[0]]
            return None

        best_key = None
        best_score = 0.0
        from difflib import SequenceMatcher

        for candidate in candidates:
            score = SequenceMatcher(None, key, candidate).ratio() * 100
            if score > best_score:
                best_key = candidate
                best_score = score
        if best_key and best_score >= FUZZY_THRESHOLD and _acceptable_fuzzy_match(key, best_key):
            return candidates[best_key]
        return None

    def _add_alias(self, index: dict[str, str], value: object, iso3: str) -> None:
        if value is None:
            return
        key = normalize_key(str(value))
        if key and key not in index:
            index[key] = iso3


def normalize_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    text = "".join(char for char in normalized if not unicodedata.combining(char))
    text = text.replace("&", " and ")
    text = re.sub(r"['`´’‘]", "", text)
    text = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


def _strip_document_noise(value: str) -> str:
    text = str(value or "").strip(" \t\r\n=,，。;；:：()[]【】")
    text = re.sub(r"^#{1,6}\s*", "", text).strip()
    text = re.sub(r"\.(?:md|markdown|txt|pdf|docx?|rtf|html?)\s*$", "", text, flags=re.I).strip()
    text = re.split(
        r"(?:赛前信息报告|赛前报告|赛前情报|信息报告|分析报告|预测报告|赛事报告|前瞻报告|报告|前瞻)",
        text,
        maxsplit=1,
    )[0]
    text = re.split(
        r"\s+(?:match preview|preview|analysis|report)\b",
        text,
        maxsplit=1,
        flags=re.I,
    )[0]
    return text.strip(" \t\r\n=,，。;；:：()[]【】")


def _acceptable_fuzzy_match(key: str, candidate: str) -> bool:
    if key == candidate:
        return True
    if len(candidate) <= 3 and candidate.isascii() and candidate.isalnum():
        return False
    return True


def _iter_values(values: object) -> Iterable[object]:
    if values is None:
        return []
    if isinstance(values, list):
        return values
    return [values]

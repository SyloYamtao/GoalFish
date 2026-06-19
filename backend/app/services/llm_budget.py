from __future__ import annotations

import hashlib
import json
import pickle
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol


CACHE_TTL_SECONDS = 3600 * 24 * 7
MAX_HARD_CAP_CALLS = 130
MIN_N_SIMS = 500
MAX_N_SIMS = 5000

_PROFILE_FIELDS = (
    "profile_key",
    "coach_panel_roles",
    "coach_deliberation_rounds",
    "enable_llm_data_extraction",
    "narrative_polish_count",
    "analyst_note_groups",
    "coach_review_roles",
    "n_sims",
    "enable_statsbomb",
    "hard_cap_calls",
)

_RESPONSE_CONTRACT_FIELDS = {
    "calls_planned",
    "calls_used",
    "calls_cached",
    "hard_cap",
    "total_cost_usd",
}


class BudgetExceeded(Exception):
    pass


class CacheBackend(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any, ttl: int) -> None: ...


class InMemoryCache:
    """Single-process cache backend for tests and local workflows."""

    def __init__(self, *, now: Callable[[], float] | None = None):
        self._store: dict[str, tuple[Any, float]] = {}
        self._now = now or time.monotonic

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None

        value, expires_at = entry
        if expires_at <= self._now():
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl: int) -> None:
        self._store[key] = (value, self._now() + ttl)


class RedisCache:
    """Redis-backed cache for production LLM call idempotency."""

    def __init__(self, *, redis_client: Any | None = None, redis_url: str | None = None):
        if redis_client is not None:
            self._redis = redis_client
            return

        from redis import Redis

        from app.config import Config

        self._redis = Redis.from_url(redis_url or Config.REDIS_URL)

    def get(self, key: str) -> Any | None:
        raw = self._redis.get(key)
        if raw is None:
            return None
        return pickle.loads(raw)

    def set(self, key: str, value: Any, ttl: int) -> None:
        self._redis.setex(key, ttl, pickle.dumps(value))


@dataclass
class LLMBudgetProfile:
    """
    Budget profile for all LLM-backed Step2/Step3 work.

    Presets are exposed as class attributes:
      LLMBudgetProfile.LOW
      LLMBudgetProfile.MIDDLE
      LLMBudgetProfile.MAX
    """

    profile_key: str
    coach_panel_roles: list[str]
    coach_deliberation_rounds: int
    enable_llm_data_extraction: bool
    narrative_polish_count: int
    analyst_note_groups: list[str]
    coach_review_roles: list[str]
    n_sims: int
    enable_statsbomb: bool
    hard_cap_calls: int

    LOW: ClassVar["LLMBudgetProfile"]
    LOW_NO_LLM: ClassVar["LLMBudgetProfile"]
    MIDDLE: ClassVar["LLMBudgetProfile"]
    MAX: ClassVar["LLMBudgetProfile"]
    LEGACY: ClassVar["LLMBudgetProfile"]
    _PRESET_ESTIMATED_CALLS: ClassVar[dict[str, int]] = {
        "low": 4,
        "middle": 12,
        "max": 113,
        "legacy": 12,
    }

    @classmethod
    def resolve(cls, input_dict: dict | None) -> "LLMBudgetProfile":
        """Resolve a request payload into a budget profile; default to middle."""
        if not input_dict:
            return _clone_profile(cls.MIDDLE)
        return cls.from_dict(input_dict)

    @classmethod
    def from_dict(cls, d: dict) -> "LLMBudgetProfile":
        if not isinstance(d, Mapping):
            raise ValueError("LLM budget profile must be a dict")

        key = str(d.get("profile_key", "middle")).lower()
        if key in {"low", "middle", "max", "legacy"}:
            return _clone_profile(_preset_for_key(cls, key))
        if key != "custom":
            raise ValueError(f"Unknown LLM budget profile: {key}")

        data = cls.MIDDLE.to_dict()
        data["profile_key"] = "custom"

        if "overrides" in d:
            overrides = d.get("overrides") or {}
            if not isinstance(overrides, Mapping):
                raise ValueError("custom LLM budget overrides must be a dict")
            _reject_unknown_keys(overrides, allowed=set(_PROFILE_FIELDS) - {"profile_key"})
            data.update(overrides)
        else:
            _reject_unknown_keys(d, allowed=set(_PROFILE_FIELDS) | _RESPONSE_CONTRACT_FIELDS)
            for field_name in _PROFILE_FIELDS:
                if field_name in d:
                    data[field_name] = d[field_name]
            data["profile_key"] = "custom"

        return _validated_profile(data)

    def to_dict(self) -> dict:
        return {
            "profile_key": self.profile_key,
            "coach_panel_roles": list(self.coach_panel_roles),
            "coach_deliberation_rounds": self.coach_deliberation_rounds,
            "enable_llm_data_extraction": self.enable_llm_data_extraction,
            "narrative_polish_count": self.narrative_polish_count,
            "analyst_note_groups": list(self.analyst_note_groups),
            "coach_review_roles": list(self.coach_review_roles),
            "n_sims": self.n_sims,
            "enable_statsbomb": self.enable_statsbomb,
            "hard_cap_calls": self.hard_cap_calls,
        }

    @property
    def estimated_calls(self) -> int:
        """Budget-aware display estimate for frontend selection and summaries."""
        preset_estimate = self._PRESET_ESTIMATED_CALLS.get(self.profile_key)
        if preset_estimate is not None:
            return min(preset_estimate, self.hard_cap_calls)
        return min(_uncached_estimated_calls(self), self.hard_cap_calls)


@dataclass
class LLMCall:
    role: str
    prompt_version: str
    prompt_hash: str
    cached: bool = False
    result: Any = None
    tokens: int = 0
    cost: float = 0.0
    latency_ms: int = 0
    _completed: bool = field(default=False, init=False, repr=False)

    def complete(self, result: Any, *, tokens: int, cost: float, latency_ms: int) -> None:
        self.result = result
        self.tokens = _non_negative_int(tokens, "tokens")
        self.cost = _non_negative_float(cost, "cost")
        self.latency_ms = _non_negative_int(latency_ms, "latency_ms")
        self._completed = True


class LLMCallLedger:
    """
    LLM call ledger with hard-cap enforcement and idempotent caching.

    Cache key = config_id + role + prompt_version + prompt_hash. run_id is
    intentionally excluded so repeated runs of the same config reuse results.
    """

    def __init__(
        self,
        *,
        config_id: str | None = None,
        run_id: str | None = None,
        budget: LLMBudgetProfile | None = None,
        cache_backend: CacheBackend | None = None,
    ):
        self._config_id = config_id
        self._run_id = run_id
        self._budget = budget or LLMBudgetProfile.MIDDLE
        self._cache = cache_backend or InMemoryCache()
        self._calls: list[LLMCall] = []
        self._spent = 0
        self._failures: list[dict[str, Any]] = []

    @property
    def budget(self) -> LLMBudgetProfile:
        return self._budget

    @contextmanager
    def acquire(
        self,
        role: str,
        prompt_version: str,
        prompt: list[dict] | None = None,
    ) -> Iterator[LLMCall]:
        prompt_hash = _prompt_hash(prompt or [])
        cache_key = _cache_key(self._config_id, role, prompt_version, prompt_hash)
        cached_result = self._cache.get(cache_key)

        if cached_result is not None:
            call = LLMCall(
                role=role,
                prompt_version=prompt_version,
                prompt_hash=prompt_hash,
                cached=True,
                result=cached_result,
            )
            self._calls.append(call)
            yield call
            return

        if self._spent >= self._budget.hard_cap_calls:
            raise BudgetExceeded(f"LLM call budget exceeded: {self._budget.hard_cap_calls}")

        self._spent += 1
        call = LLMCall(role=role, prompt_version=prompt_version, prompt_hash=prompt_hash)
        try:
            yield call
        finally:
            if call.result is not None:
                self._cache.set(cache_key, call.result, ttl=CACHE_TTL_SECONDS)
            self._calls.append(call)

    def record_failure(self, **failure: Any) -> None:
        self._failures.append(dict(failure))

    def summary(self) -> dict:
        total_tokens = sum(call.tokens for call in self._calls)
        total_cost = round(sum(call.cost for call in self._calls), 6)
        latencies = [call.latency_ms for call in self._calls if call.latency_ms > 0]
        avg_latency_ms = round(sum(latencies) / len(latencies)) if latencies else 0

        return {
            "total_calls": len(self._calls),
            "cached": sum(1 for call in self._calls if call.cached),
            "spent": self._spent,
            "hard_cap": self._budget.hard_cap_calls,
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost,
            "avg_latency_ms": avg_latency_ms,
            "by_role": self._group_by_role(),
            "failures": [dict(failure) for failure in self._failures],
        }

    def _group_by_role(self) -> dict[str, dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for call in self._calls:
            role_summary = grouped.setdefault(
                call.role,
                {"calls": 0, "cached": 0, "tokens": 0, "cost": 0.0},
            )
            role_summary["calls"] += 1
            role_summary["cached"] += 1 if call.cached else 0
            role_summary["tokens"] += call.tokens
            role_summary["cost"] += call.cost

        for role_summary in grouped.values():
            role_summary["cost"] = round(role_summary["cost"], 6)
        return grouped


def _cache_key(config_id: str | None, role: str, prompt_version: str, prompt_hash: str) -> str:
    return f"llm:{config_id}:{role}:{prompt_version}:{prompt_hash[:12]}"


def _prompt_hash(messages: list[dict]) -> str:
    content = json.dumps(messages, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _preset_for_key(cls: type[LLMBudgetProfile], key: str) -> LLMBudgetProfile:
    if key == "low":
        return cls.LOW
    if key == "middle":
        return cls.MIDDLE
    if key == "max":
        return cls.MAX
    if key == "legacy":
        return cls.LEGACY
    raise ValueError(f"Unknown LLM budget profile: {key}")


def _clone_profile(profile: LLMBudgetProfile) -> LLMBudgetProfile:
    return LLMBudgetProfile(**profile.to_dict())


def _validated_profile(data: Mapping[str, Any]) -> LLMBudgetProfile:
    profile = LLMBudgetProfile(
        profile_key=str(data["profile_key"]).lower(),
        coach_panel_roles=_str_list(data["coach_panel_roles"], "coach_panel_roles"),
        coach_deliberation_rounds=_bounded_int(
            data["coach_deliberation_rounds"],
            "coach_deliberation_rounds",
            min_value=1,
            max_value=3,
        ),
        enable_llm_data_extraction=_bool(data["enable_llm_data_extraction"], "enable_llm_data_extraction"),
        narrative_polish_count=_bounded_int(
            data["narrative_polish_count"],
            "narrative_polish_count",
            min_value=0,
            max_value=9,
        ),
        analyst_note_groups=_str_list(data["analyst_note_groups"], "analyst_note_groups"),
        coach_review_roles=_str_list(data["coach_review_roles"], "coach_review_roles"),
        n_sims=_bounded_int(data["n_sims"], "n_sims", min_value=MIN_N_SIMS, max_value=MAX_N_SIMS),
        enable_statsbomb=_bool(data["enable_statsbomb"], "enable_statsbomb"),
        hard_cap_calls=_bounded_int(
            data["hard_cap_calls"],
            "hard_cap_calls",
            min_value=1,
            max_value=MAX_HARD_CAP_CALLS,
        ),
    )
    if profile.profile_key not in {"custom"}:
        raise ValueError("Only custom profiles can be built from arbitrary data")
    return profile


def _uncached_estimated_calls(profile: LLMBudgetProfile) -> int:
    calls = 0
    if profile.enable_llm_data_extraction:
        calls += 1
    calls += len(profile.coach_panel_roles) * profile.coach_deliberation_rounds
    calls += profile.narrative_polish_count * 8
    calls += len(profile.analyst_note_groups)
    calls += len(profile.coach_review_roles) * 9
    return calls


def _str_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list of strings")
    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must be a list of strings")
    return list(value)


def _bool(value: Any, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a bool")
    return value


def _bounded_int(value: Any, field_name: str, *, min_value: int, max_value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    if value < min_value or value > max_value:
        raise ValueError(f"{field_name} must be between {min_value} and {max_value}")
    return value


def _non_negative_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return value


def _non_negative_float(value: Any, field_name: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be numeric")
    if value < 0:
        raise ValueError(f"{field_name} must be non-negative")
    return float(value)


def _reject_unknown_keys(payload: Mapping[str, Any], *, allowed: set[str]) -> None:
    unknown = set(payload) - allowed
    if unknown:
        unknown_list = ", ".join(sorted(unknown))
        raise ValueError(f"Unknown LLM budget profile fields: {unknown_list}")


LLMBudgetProfile.LOW = LLMBudgetProfile(
    profile_key="low",
    coach_panel_roles=["head_coach", "risk"],
    coach_deliberation_rounds=1,
    enable_llm_data_extraction=False,
    narrative_polish_count=0,
    analyst_note_groups=["baseline", "volatility"],
    coach_review_roles=[],
    n_sims=1000,
    enable_statsbomb=False,
    hard_cap_calls=10,
)

LLMBudgetProfile.LOW_NO_LLM = LLMBudgetProfile.LOW

LLMBudgetProfile.MIDDLE = LLMBudgetProfile(
    profile_key="middle",
    coach_panel_roles=["head_coach", "attack", "defense", "goalkeeper", "risk", "fitness"],
    coach_deliberation_rounds=1,
    enable_llm_data_extraction=True,
    narrative_polish_count=3,
    analyst_note_groups=["baseline", "home_upside", "away_upside"],
    coach_review_roles=[],
    n_sims=2000,
    enable_statsbomb=True,
    hard_cap_calls=25,
)

LLMBudgetProfile.MAX = LLMBudgetProfile(
    profile_key="max",
    coach_panel_roles=[
        "head_coach",
        "attack",
        "defense",
        "transition",
        "set_piece",
        "goalkeeper",
        "fitness",
        "risk",
    ],
    coach_deliberation_rounds=2,
    enable_llm_data_extraction=True,
    narrative_polish_count=9,
    analyst_note_groups=[
        "baseline",
        "home_upside",
        "away_upside",
        "home_error",
        "away_error",
        "volatility",
    ],
    coach_review_roles=["head_coach", "risk"],
    n_sims=3000,
    enable_statsbomb=True,
    hard_cap_calls=MAX_HARD_CAP_CALLS,
)

LLMBudgetProfile.LEGACY = LLMBudgetProfile(
    **{**LLMBudgetProfile.MIDDLE.to_dict(), "profile_key": "legacy"}
)

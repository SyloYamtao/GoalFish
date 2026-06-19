import time

import pytest

from app.services.llm_budget import (
    CACHE_TTL_SECONDS,
    BudgetExceeded,
    InMemoryCache,
    LLMCallLedger,
    LLMBudgetProfile,
    _cache_key,
    _prompt_hash,
)


def test_low_middle_max_estimated_calls():
    assert LLMBudgetProfile.LOW.estimated_calls == 4
    assert LLMBudgetProfile.MIDDLE.estimated_calls == 12
    assert LLMBudgetProfile.MAX.estimated_calls == 113
    assert LLMBudgetProfile.LOW.estimated_calls <= 10
    assert LLMBudgetProfile.MIDDLE.estimated_calls <= 25
    assert LLMBudgetProfile.MAX.estimated_calls <= 130


def test_preset_profiles_match_spec_values():
    assert LLMBudgetProfile.LOW.to_dict() == {
        "profile_key": "low",
        "coach_panel_roles": ["head_coach", "risk"],
        "coach_deliberation_rounds": 1,
        "enable_llm_data_extraction": False,
        "narrative_polish_count": 0,
        "analyst_note_groups": ["baseline", "volatility"],
        "coach_review_roles": [],
        "n_sims": 1000,
        "enable_statsbomb": False,
        "hard_cap_calls": 10,
    }
    assert LLMBudgetProfile.MIDDLE.hard_cap_calls == 25
    assert LLMBudgetProfile.MAX.hard_cap_calls == 130
    assert LLMBudgetProfile.MAX.coach_deliberation_rounds == 2


def test_low_no_llm_alias_matches_low_profile():
    assert LLMBudgetProfile.LOW_NO_LLM == LLMBudgetProfile.LOW
    assert LLMBudgetProfile.LOW_NO_LLM.enable_llm_data_extraction is False


def test_resolve_defaults_to_middle():
    assert LLMBudgetProfile.resolve(None) == LLMBudgetProfile.MIDDLE
    assert LLMBudgetProfile.resolve({}) == LLMBudgetProfile.MIDDLE


def test_resolve_known_presets_and_legacy():
    assert LLMBudgetProfile.resolve({"profile_key": "low"}) == LLMBudgetProfile.LOW
    assert LLMBudgetProfile.resolve({"profile_key": "middle"}) == LLMBudgetProfile.MIDDLE
    assert LLMBudgetProfile.resolve({"profile_key": "max"}) == LLMBudgetProfile.MAX

    legacy = LLMBudgetProfile.resolve({"profile_key": "legacy"})

    assert legacy.profile_key == "legacy"
    assert legacy.hard_cap_calls == LLMBudgetProfile.MIDDLE.hard_cap_calls


def test_custom_profile_applies_overrides_to_middle_defaults():
    custom = LLMBudgetProfile.from_dict(
        {
            "profile_key": "custom",
            "overrides": {
                "coach_panel_roles": ["head_coach", "attack", "risk"],
                "coach_deliberation_rounds": 2,
                "enable_llm_data_extraction": False,
                "narrative_polish_count": 1,
                "analyst_note_groups": ["baseline"],
                "coach_review_roles": ["risk"],
                "n_sims": 500,
                "enable_statsbomb": False,
                "hard_cap_calls": 20,
            },
        }
    )

    assert custom.profile_key == "custom"
    assert custom.coach_panel_roles == ["head_coach", "attack", "risk"]
    assert custom.coach_deliberation_rounds == 2
    assert custom.enable_llm_data_extraction is False
    assert custom.narrative_polish_count == 1
    assert custom.analyst_note_groups == ["baseline"]
    assert custom.coach_review_roles == ["risk"]
    assert custom.n_sims == 500
    assert custom.enable_statsbomb is False
    assert custom.hard_cap_calls == 20
    assert custom.estimated_calls <= 20


def test_custom_profile_accepts_response_contract_round_trip_fields():
    custom = LLMBudgetProfile.from_dict(
        {
            "profile_key": "custom",
            "coach_panel_roles": ["head_coach", "attack", "defense", "risk"],
            "coach_deliberation_rounds": 1,
            "enable_llm_data_extraction": False,
            "narrative_polish_count": 0,
            "analyst_note_groups": ["baseline", "volatility"],
            "coach_review_roles": ["head_coach"],
            "n_sims": 1000,
            "enable_statsbomb": False,
            "hard_cap_calls": 10,
            "calls_planned": 0,
            "calls_used": 0,
            "calls_cached": 0,
            "hard_cap": 1,
            "total_cost_usd": 0,
        }
    )

    assert custom.profile_key == "custom"
    assert custom.hard_cap_calls == 10
    assert custom.coach_panel_roles == ["head_coach", "attack", "defense", "risk"]


def test_custom_overcap_rejected():
    custom = LLMBudgetProfile.from_dict(
        {
            "profile_key": "custom",
            "overrides": {"hard_cap_calls": 130},
        }
    )

    assert custom.hard_cap_calls == 130

    with pytest.raises(ValueError):
        LLMBudgetProfile.from_dict(
            {
                "profile_key": "custom",
                "overrides": {"hard_cap_calls": 131},
            }
        )


def test_custom_validation_rejects_out_of_range_values():
    with pytest.raises(ValueError):
        LLMBudgetProfile.from_dict(
            {"profile_key": "custom", "overrides": {"n_sims": 499}}
        )
    with pytest.raises(ValueError):
        LLMBudgetProfile.from_dict(
            {"profile_key": "custom", "overrides": {"narrative_polish_count": 10}}
        )
    with pytest.raises(ValueError):
        LLMBudgetProfile.from_dict(
            {"profile_key": "custom", "overrides": {"coach_deliberation_rounds": 0}}
        )


def test_prompt_hash_is_stable_for_key_order_and_unicode():
    left = [{"role": "user", "content": {"team": "中国", "score": 1}}]
    right = [{"content": {"score": 1, "team": "中国"}, "role": "user"}]

    assert _prompt_hash(left) == _prompt_hash(right)
    assert len(_prompt_hash(left)) == 64


def test_cache_key_format():
    assert (
        _cache_key("cfg", "coach_attack", "v1", "abcdef1234567890")
        == "llm:cfg:coach_attack:v1:abcdef123456"
    )


def test_in_memory_cache_respects_ttl():
    cache = InMemoryCache(now=time.monotonic)
    cache.set("key", "value", ttl=1)

    assert cache.get("key") == "value"
    cache._store["key"] = ("value", time.monotonic() - 0.1)

    assert cache.get("key") is None


def test_ledger_records_cached_calls():
    budget = LLMBudgetProfile.MIDDLE
    ledger1 = LLMCallLedger(config_id="cfg_x", budget=budget)

    with ledger1.acquire(
        role="coach_attack",
        prompt_version="v1",
        prompt=[{"role": "user", "content": "hello"}],
    ) as call:
        assert not call.cached
        call.complete("response_a", tokens=100, cost=0.01, latency_ms=500)

    ledger2 = LLMCallLedger(
        config_id="cfg_x",
        budget=budget,
        cache_backend=ledger1._cache,
    )
    with ledger2.acquire(
        role="coach_attack",
        prompt_version="v1",
        prompt=[{"role": "user", "content": "hello"}],
    ) as call:
        assert call.cached
        assert call.result == "response_a"
        assert call.tokens == 0
        assert call.cost == 0.0

    assert ledger2.summary()["cached"] == 1
    assert ledger2.summary()["spent"] == 0


def test_ledger_idempotent_across_runs():
    budget = LLMBudgetProfile.MIDDLE
    cache = InMemoryCache()

    ledger1 = LLMCallLedger(config_id="cfg_x", run_id="run_a", budget=budget, cache_backend=cache)
    with ledger1.acquire(
        role="coach_attack",
        prompt_version="v1",
        prompt=[{"role": "user", "content": "same prompt"}],
    ) as call:
        call.complete({"answer": "cached"}, tokens=12, cost=0.002, latency_ms=10)

    ledger2 = LLMCallLedger(config_id="cfg_x", run_id="run_b", budget=budget, cache_backend=cache)
    with ledger2.acquire(
        role="coach_attack",
        prompt_version="v1",
        prompt=[{"role": "user", "content": "same prompt"}],
    ) as call:
        assert call.cached
        assert call.result == {"answer": "cached"}


def test_cache_miss_for_different_prompt_version():
    budget = LLMBudgetProfile.MIDDLE
    cache = InMemoryCache()

    ledger1 = LLMCallLedger(config_id="cfg_x", budget=budget, cache_backend=cache)
    with ledger1.acquire(
        role="coach_attack",
        prompt_version="v1",
        prompt=[{"role": "user", "content": "hello"}],
    ) as call:
        call.complete("response_v1", tokens=1, cost=0.01, latency_ms=5)

    ledger2 = LLMCallLedger(config_id="cfg_x", budget=budget, cache_backend=cache)
    with ledger2.acquire(
        role="coach_attack",
        prompt_version="v2",
        prompt=[{"role": "user", "content": "hello"}],
    ) as call:
        assert not call.cached


def test_incomplete_call_is_recorded_but_not_cached():
    budget = LLMBudgetProfile.MIDDLE
    cache = InMemoryCache()
    prompt = [{"role": "user", "content": "hello"}]

    ledger1 = LLMCallLedger(config_id="cfg_x", budget=budget, cache_backend=cache)
    with ledger1.acquire(role="coach_attack", prompt_version="v1", prompt=prompt) as call:
        assert not call.cached

    ledger2 = LLMCallLedger(config_id="cfg_x", budget=budget, cache_backend=cache)
    with ledger2.acquire(role="coach_attack", prompt_version="v1", prompt=prompt) as call:
        assert not call.cached

    summary = ledger1.summary()
    assert summary["total_calls"] == 1
    assert summary["spent"] == 1
    assert summary["failures"] == []


def test_budget_exceeded_raises():
    budget = LLMBudgetProfile.LOW
    ledger = LLMCallLedger(config_id="cfg_x", budget=budget)

    for i in range(10):
        with ledger.acquire(
            role=f"role_{i}",
            prompt_version="v1",
            prompt=[{"role": "user", "content": f"msg_{i}"}],
        ) as c:
            c.complete(f"r{i}", tokens=10, cost=0.001, latency_ms=10)

    with pytest.raises(BudgetExceeded):
        with ledger.acquire(
            role="role_11",
            prompt_version="v1",
            prompt=[{"role": "user", "content": "overflow"}],
        ):
            pass


def test_cached_calls_do_not_consume_hard_cap():
    budget = LLMBudgetProfile.LOW
    cache = InMemoryCache()
    prompt = [{"role": "user", "content": "same prompt"}]

    warm = LLMCallLedger(config_id="cfg_x", budget=budget, cache_backend=cache)
    with warm.acquire(role="role", prompt_version="v1", prompt=prompt) as call:
        call.complete("response", tokens=10, cost=0.01, latency_ms=20)

    ledger = LLMCallLedger(config_id="cfg_x", budget=budget, cache_backend=cache)
    for _ in range(20):
        with ledger.acquire(role="role", prompt_version="v1", prompt=prompt) as call:
            assert call.cached

    assert ledger.summary()["spent"] == 0
    assert ledger.summary()["cached"] == 20


def test_summary_format():
    ledger = LLMCallLedger(config_id="cfg", budget=LLMBudgetProfile.MIDDLE)
    s = ledger.summary()

    assert set(s.keys()) >= {
        "total_calls",
        "cached",
        "spent",
        "hard_cap",
        "total_tokens",
        "total_cost_usd",
        "avg_latency_ms",
        "by_role",
        "failures",
    }


def test_ledger_exposes_budget_profile():
    ledger = LLMCallLedger(config_id="cfg", budget=LLMBudgetProfile.LOW_NO_LLM)

    assert ledger.budget == LLMBudgetProfile.LOW
    assert ledger.budget.enable_llm_data_extraction is False


def test_summary_groups_by_role_and_rounds_cost():
    ledger = LLMCallLedger(config_id="cfg", budget=LLMBudgetProfile.MIDDLE)

    with ledger.acquire(
        role="coach_attack",
        prompt_version="v1",
        prompt=[{"role": "user", "content": "hello"}],
    ) as call:
        call.complete("response", tokens=100, cost=0.012345, latency_ms=100)

    with ledger.acquire(
        role="coach_attack",
        prompt_version="v1",
        prompt=[{"role": "user", "content": "different"}],
    ) as call:
        call.complete("response 2", tokens=50, cost=0.002, latency_ms=300)

    summary = ledger.summary()

    assert summary["total_calls"] == 2
    assert summary["cached"] == 0
    assert summary["spent"] == 2
    assert summary["total_tokens"] == 150
    assert summary["total_cost_usd"] == 0.014345
    assert summary["avg_latency_ms"] == 200
    assert summary["by_role"]["coach_attack"] == {
        "calls": 2,
        "cached": 0,
        "tokens": 150,
        "cost": 0.014345,
    }


def test_ledger_can_record_budget_failure_metadata():
    ledger = LLMCallLedger(config_id="cfg", budget=LLMBudgetProfile.LOW)

    ledger.record_failure(
        role="narrative_polisher",
        reason="budget_exceeded",
        fallback="template",
        scenario_key="home_error_away_overperform",
    )

    assert ledger.summary()["failures"] == [
        {
            "role": "narrative_polisher",
            "reason": "budget_exceeded",
            "fallback": "template",
            "scenario_key": "home_error_away_overperform",
        }
    ]


def test_cache_ttl_matches_spec():
    assert CACHE_TTL_SECONDS == 3600 * 24 * 7

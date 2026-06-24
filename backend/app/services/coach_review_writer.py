"""Step3 coach post-review generation over modal trajectories."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .coach_llm_panel import ROLE_BY_KEY
from .content_language import build_content_language_instruction
from .llm_budget import BudgetExceeded, LLMCallLedger, LLMBudgetProfile


REVIEW_VERSION = "v1"
VALID_VERDICTS = {"support", "adjust", "watch", "reject"}


class CoachReviewWriter:
    def __init__(
        self,
        *,
        budget: LLMBudgetProfile,
        ledger: LLMCallLedger,
        llm_client: Any | None = None,
        content_language_instruction: str | None = None,
    ) -> None:
        self._budget = budget
        self._ledger = ledger
        self._llm_client = llm_client
        self._content_language_instruction = content_language_instruction or build_content_language_instruction(None)

    def review(
        self,
        *,
        scenario_cases: list[Any],
        sim_results: dict,
        team_strengths: tuple[Any, Any],
    ) -> dict:
        """Run Step3 post-review for the budget-selected subset of panel roles."""

        role_keys = [role for role in self._budget.coach_review_roles if role in ROLE_BY_KEY]
        if not role_keys:
            return self._fallback_hash_review(scenario_cases, sim_results, team_strengths)

        reviews = []
        for role_key in role_keys:
            try:
                reviews.append(self._call_role(role_key, scenario_cases, sim_results, team_strengths))
            except BudgetExceeded as exc:
                self._record_failure(role_key, "budget_exceeded", exc)
                reviews.append(self._fallback_role_review(role_key, scenario_cases, sim_results))
            except Exception as exc:  # noqa: BLE001 - one role failure should not fail Step3.
                self._record_failure(role_key, "llm_failed", exc)
                reviews.append(self._fallback_role_review(role_key, scenario_cases, sim_results))

        source = "llm" if all(review.get("source") == "llm" for review in reviews) else "mixed"
        return {
            "review_version": REVIEW_VERSION,
            "source": source,
            "roles": role_keys,
            "reviews": reviews,
            "summary": _aggregate_summary(reviews),
            **_review_vote_summary(reviews),
        }

    def _call_role(
        self,
        role_key: str,
        scenario_cases: list[Any],
        sim_results: dict,
        team_strengths: tuple[Any, Any],
    ) -> dict:
        role = ROLE_BY_KEY[role_key]
        context = _review_context(scenario_cases, sim_results, team_strengths)
        messages = self._build_messages(role_key, context)
        with self._ledger.acquire(
            role=f"step3_review_{role.key}",
            prompt_version=REVIEW_VERSION,
            prompt=messages,
        ) as call:
            if call.cached:
                raw_review = call.result
            else:
                started = time.perf_counter()
                raw_review = self._llm().chat_json(
                    messages=messages,
                    temperature=0.2,
                    max_tokens=1200,
                )
                call.complete(
                    raw_review,
                    tokens=0,
                    cost=0.0,
                    latency_ms=round((time.perf_counter() - started) * 1000),
                )
        return _normalize_review(raw_review, role_key, context, source="llm")

    def _build_messages(self, role_key: str, context: dict) -> list[dict[str, str]]:
        role = ROLE_BY_KEY[role_key]
        template = _load_prompt_template("step3_review.txt")
        payload = {
            "role_key": role.key,
            "role_label": role.label,
            "attention": role.attention,
            "context": context,
        }
        return [
            {
                "role": "system",
                "content": (
                    "你是足球预测 Step3 事后复核教练。只输出合法 JSON object。"
                    f"\n\n{self._content_language_instruction}"
                ),
            },
            {
                "role": "user",
                "content": template.format(payload_json=json.dumps(payload, ensure_ascii=False, sort_keys=True)),
            },
        ]

    def _fallback_hash_review(self, scenario_cases: list[Any], sim_results: dict, team_strengths: tuple[Any, Any]) -> dict:
        del team_strengths
        review = self._fallback_role_review("fallback", scenario_cases, sim_results)
        return {
            "review_version": REVIEW_VERSION,
            "source": "coach_review_fallback_v1",
            "roles": [],
            "reviews": [review],
            "summary": review["rationale"],
            **_review_vote_summary([review]),
        }

    def _fallback_role_review(self, role_key: str, scenario_cases: list[Any], sim_results: dict) -> dict:
        seed = "|".join(str(_get(case, "scenario_key") or "") for case in scenario_cases)
        digest = hashlib.sha256(f"{REVIEW_VERSION}:{role_key}:{seed}".encode("utf-8")).hexdigest()
        verdict = "support" if int(digest[:2], 16) % 2 == 0 else "watch"
        return {
            "role": role_key,
            "verdict": verdict,
            "rationale": "LLM 复核不可用，使用稳定哈希路径给出保守事后复核。",
            "confidence": 55,
            "evidence_refs": _default_evidence_refs(scenario_cases, sim_results),
            "review_version": REVIEW_VERSION,
            "source": "coach_review_fallback_v1",
        }

    def _record_failure(self, role_key: str, reason: str, exc: Exception) -> None:
        self._ledger.record_failure(
            role=f"step3_review_{role_key}",
            reason=reason,
            fallback="coach_review_fallback_v1",
            error=str(exc),
        )

    def _llm(self) -> Any:
        if self._llm_client is None:
            from app.utils.llm_client import LLMClient

            self._llm_client = LLMClient()
        return self._llm_client


def _load_prompt_template(filename: str) -> str:
    return (Path(__file__).with_name("narrative_prompts") / filename).read_text(encoding="utf-8")


def _review_context(scenario_cases: list[Any], sim_results: dict, team_strengths: tuple[Any, Any]) -> dict:
    return {
        "team_strengths": [_strength_summary(strength) for strength in team_strengths],
        "scenarios": [_scenario_review_summary(case, sim_results.get(str(_get(case, "scenario_key") or ""))) for case in scenario_cases],
    }


def _strength_summary(strength: Any) -> dict:
    if hasattr(strength, "to_dict"):
        payload = strength.to_dict()
    elif isinstance(strength, Mapping):
        payload = dict(strength)
    else:
        payload = {
            "team_role": _get(strength, "team_role"),
            "team_iso3": _get(strength, "team_iso3"),
            "team_name": _get(strength, "team_name"),
        }
    return {
        "team_role": payload.get("team_role"),
        "team_iso3": payload.get("team_iso3"),
        "team_name": payload.get("team_name"),
        "attack_rating": payload.get("attack_rating"),
        "defense_rating": payload.get("defense_rating"),
        "goalkeeper_rating": payload.get("goalkeeper_rating"),
        "confidence": payload.get("confidence"),
    }


def _scenario_review_summary(case: Any, sim_result: Any) -> dict:
    scenario_key = str(_get(case, "scenario_key") or "")
    modal = _get(sim_result, "modal_trajectory") if sim_result is not None else None
    return {
        "scenario_key": scenario_key,
        "scenario_name": _get(case, "scenario_name"),
        "scenario_space": _get(case, "scenario_space"),
        "final_weight": _get(case, "final_weight", _get(case, "initial_weight")),
        "expected_goals": _get(case, "expected_goals", {}),
        "key_drivers": list(_get(case, "key_drivers", []) or []),
        "risk_factors": list(_get(case, "risk_factors", []) or []),
        "modal_score": getattr(modal, "final_score_str", None) if modal is not None else None,
        "wdl": dict(_get(sim_result, "wdl", {}) or {}) if sim_result is not None else {},
        "scoreline_distribution": list(_get(sim_result, "scoreline_distribution", []) or [])[:5]
        if sim_result is not None
        else [],
        "modal_events": [_event_summary(event) for event in list(_get(modal, "events", []) or [])[:12]],
    }


def _event_summary(event: Any) -> dict:
    return {
        "minute": _get(event, "minute"),
        "type": _get(event, "type"),
        "side": _get(event, "side"),
        "score_after": _score_after(event),
    }


def _score_after(event: Any) -> dict[str, int] | None:
    score = _get(event, "score_after")
    if isinstance(score, tuple | list) and len(score) == 2:
        return {"home": int(score[0]), "away": int(score[1])}
    if isinstance(score, Mapping):
        return {"home": int(score.get("home", 0)), "away": int(score.get("away", 0))}
    return None


def _normalize_review(raw_review: Any, role_key: str, context: dict, *, source: str) -> dict:
    payload = dict(raw_review) if isinstance(raw_review, Mapping) else {}
    verdict = str(payload.get("verdict") or "watch")
    if verdict not in VALID_VERDICTS:
        verdict = "watch"
    return {
        "role": role_key,
        "verdict": verdict,
        "rationale": _bounded_text(payload.get("rationale"), default="复核未提供详细理由。", max_len=360),
        "confidence": _clamp_int(payload.get("confidence"), min_value=50, max_value=95, default=65),
        "evidence_refs": _refs(payload.get("evidence_refs")) or _context_evidence_refs(context),
        "review_version": REVIEW_VERSION,
        "source": source,
    }


def _default_evidence_refs(scenario_cases: list[Any], sim_results: dict) -> list[dict]:
    refs = []
    for case in scenario_cases:
        scenario_key = str(_get(case, "scenario_key") or "")
        if scenario_key:
            refs.append({"type": "simulation_result", "scenario_key": scenario_key})
    if not refs and sim_results:
        refs.extend({"type": "simulation_result", "scenario_key": key} for key in sorted(sim_results))
    return refs or [{"type": "modal_trajectory"}]


def _context_evidence_refs(context: dict) -> list[dict]:
    refs = []
    for scenario in context.get("scenarios") or []:
        scenario_key = scenario.get("scenario_key")
        if scenario_key:
            refs.append({"type": "modal_trajectory", "scenario_key": scenario_key})
    return refs or [{"type": "modal_trajectory"}]


def _aggregate_summary(reviews: list[dict]) -> str:
    if not reviews:
        return "无教练复核。"
    verdicts = ", ".join(f"{review.get('role')}={review.get('verdict')}" for review in reviews)
    return f"Step3 教练复核完成：{verdicts}。"


def _review_vote_summary(reviews: list[dict]) -> dict[str, Any]:
    support_votes = 0
    oppose_votes = 0
    abstain_votes = 0
    adjust_votes = 0
    for review in reviews:
        verdict = str(review.get("verdict") or "watch")
        if verdict == "support":
            support_votes += 1
        elif verdict == "reject":
            oppose_votes += 1
        else:
            abstain_votes += 1
            if verdict == "adjust":
                adjust_votes += 1

    total_votes = support_votes + oppose_votes + abstain_votes
    consensus_score = 0.0
    if total_votes:
        consensus_score = round((support_votes + abstain_votes * 0.5) / total_votes, 2)

    return {
        "support_votes": support_votes,
        "oppose_votes": oppose_votes,
        "abstain_votes": abstain_votes,
        "adjust_votes": adjust_votes,
        "consensus_score": consensus_score,
        "confidence_delta": -0.04 if oppose_votes else 0.0,
    }


def _refs(value: Any) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [dict(ref) if isinstance(ref, Mapping) else {"value": ref} for ref in value if ref]


def _bounded_text(value: Any, *, default: str, max_len: int) -> str:
    text = str(value or default).strip()
    return text[:max_len]


def _clamp_int(value: Any, *, min_value: int, max_value: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(min(number, max_value), min_value)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, Mapping):
        return obj.get(key, default)
    return getattr(obj, key, default)

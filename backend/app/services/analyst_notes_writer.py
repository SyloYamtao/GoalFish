"""LLM analyst note generation for Step3 scenario spaces."""

from __future__ import annotations

import json
import time
from collections import defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .content_language import build_content_language_instruction
from .llm_budget import BudgetExceeded, LLMCallLedger, LLMBudgetProfile
from .match_simulator import SimulationResult


NOTES_VERSION = "v1"
ALLOWED_NOTE_ROLES = {"data", "tactics", "risk", "event_simulation", "coach_review"}


class AnalystNotesWriter:
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

    def write_notes(
        self,
        *,
        scenario_cases: list[Any],
        sim_results: dict[str, SimulationResult],
        config: dict,
        scorelines: list[dict] | dict | None = None,
    ) -> list[dict]:
        """Write one analyst note per budget-selected scenario space."""

        spaces = self._group_by_space(scenario_cases, sim_results, scorelines)
        notes: list[dict] = []
        for space_key in self._budget.analyst_note_groups:
            if space_key not in spaces:
                continue
            space_data = spaces[space_key]
            messages = self._build_messages(space_key, space_data, config)
            try:
                with self._ledger.acquire(
                    role="analyst_notes",
                    prompt_version=NOTES_VERSION,
                    prompt=messages,
                ) as call:
                    if call.cached:
                        raw_note = call.result
                    else:
                        started = time.perf_counter()
                        raw_note = self._llm().chat_json(
                            messages=messages,
                            temperature=0.2,
                            max_tokens=900,
                        )
                        call.complete(
                            raw_note,
                            tokens=0,
                            cost=0.0,
                            latency_ms=round((time.perf_counter() - started) * 1000),
                        )
                notes.append(self._normalize_note(raw_note, space_key, space_data, source="llm"))
            except BudgetExceeded as exc:
                self._record_failure("budget_exceeded", space_key, exc)
                notes.append(self._template_note(space_key, space_data))
            except Exception as exc:  # noqa: BLE001 - notes should degrade to template.
                self._record_failure("llm_failed", space_key, exc)
                notes.append(self._template_note(space_key, space_data))
        return notes

    def _group_by_space(
        self,
        scenario_cases: list[Any],
        sim_results: dict[str, SimulationResult],
        scorelines: list[dict] | dict | None,
    ) -> dict[str, dict]:
        spaces: dict[str, dict] = defaultdict(lambda: {"scenarios": [], "simulations": []})
        scoreline_index = _scoreline_index(scorelines)
        for case in scenario_cases:
            scenario_key = str(_get(case, "scenario_key") or "")
            space_key = str(_get(case, "scenario_space") or "baseline")
            sim_result = sim_results.get(scenario_key)
            space = spaces[space_key]
            space["scenarios"].append(_scenario_summary(case))
            if sim_result is not None:
                space["simulations"].append(_simulation_summary(scenario_key, sim_result, scoreline_index))
        return dict(spaces)

    def _build_messages(self, space_key: str, space_data: dict, config: dict) -> list[dict[str, str]]:
        template = _load_prompt_template("analyst_note.txt")
        payload = {
            "scenario_space": space_key,
            "space_data": space_data,
            "data_sufficiency": _config_value(config, "data_sufficiency"),
        }
        return [
            {
                "role": "system",
                "content": (
                    "你是足球预测分析师。只输出合法 JSON object，不得输出 Markdown。"
                    f"\n\n{self._content_language_instruction}"
                ),
            },
            {
                "role": "user",
                "content": template.format(payload_json=json.dumps(payload, ensure_ascii=False, sort_keys=True)),
            },
        ]

    def _normalize_note(self, raw_note: Any, space_key: str, space_data: dict, *, source: str) -> dict:
        payload = dict(raw_note) if isinstance(raw_note, Mapping) else {}
        role = str(payload.get("role") or "event_simulation")
        if role not in ALLOWED_NOTE_ROLES:
            role = "event_simulation"

        evidence_refs = _refs(payload.get("evidence_refs"))
        if not evidence_refs:
            evidence_refs = _space_evidence_refs(space_key, space_data)

        return {
            "role": role,
            "scenario_space": space_key,
            "claim": _bounded_text(payload.get("claim"), default=f"{space_key} 场景空间走势稳定。", max_len=120),
            "reasoning": _bounded_text(payload.get("reasoning"), default="基于模态轨迹、比分分布与 WDL 聚合生成。", max_len=320),
            "confidence": _clamp_int(payload.get("confidence"), min_value=50, max_value=95, default=65),
            "evidence_refs": evidence_refs,
            "note_version": NOTES_VERSION,
            "source": source,
        }

    def _template_note(self, space_key: str, space_data: dict) -> dict:
        scenarios = space_data.get("scenarios") or []
        sim_count = len(space_data.get("simulations") or [])
        return {
            "role": "event_simulation",
            "scenario_space": space_key,
            "claim": f"{space_key} 场景空间保留为模拟证据结论。",
            "reasoning": f"该空间覆盖 {len(scenarios)} 个场景，含 {sim_count} 组模拟结果；LLM 不可用时采用模板笔记。",
            "confidence": 60,
            "evidence_refs": _space_evidence_refs(space_key, space_data),
            "note_version": NOTES_VERSION,
            "source": "template",
        }

    def _record_failure(self, reason: str, space_key: str, exc: Exception) -> None:
        self._ledger.record_failure(
            role="analyst_notes",
            reason=reason,
            fallback="template",
            scenario_space=space_key,
            error=str(exc),
        )

    def _llm(self) -> Any:
        if self._llm_client is None:
            from app.utils.llm_client import LLMClient

            self._llm_client = LLMClient()
        return self._llm_client


def _load_prompt_template(filename: str) -> str:
    return (Path(__file__).with_name("narrative_prompts") / filename).read_text(encoding="utf-8")


def _scenario_summary(case: Any) -> dict:
    return {
        "scenario_key": _get(case, "scenario_key"),
        "scenario_name": _get(case, "scenario_name"),
        "scenario_space": _get(case, "scenario_space"),
        "final_weight": _get(case, "final_weight", _get(case, "initial_weight")),
        "expected_goals": _get(case, "expected_goals", {}),
        "key_drivers": list(_get(case, "key_drivers", []) or []),
        "risk_factors": list(_get(case, "risk_factors", []) or []),
    }


def _simulation_summary(
    scenario_key: str,
    sim_result: SimulationResult,
    scoreline_index: dict[str, Any],
) -> dict:
    modal = sim_result.modal_trajectory
    return {
        "scenario_key": scenario_key,
        "modal_score": getattr(modal, "final_score_str", None),
        "final_score": dict(getattr(modal, "final_score", {}) or {}),
        "modal_events": [_event_summary(event) for event in list(getattr(modal, "events", []) or [])[:12]],
        "wdl": dict(getattr(sim_result, "wdl", {}) or {}),
        "scoreline_distribution": list(getattr(sim_result, "scoreline_distribution", []) or [])[:5],
        "scoreline_record": scoreline_index.get(scenario_key),
        "total_goals_dist": dict(getattr(sim_result, "total_goals_dist", {}) or {}),
        "n_sims": getattr(sim_result, "n_sims", None),
        "sim_seed": getattr(sim_result, "sim_seed", None),
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


def _space_evidence_refs(space_key: str, space_data: dict) -> list[dict]:
    refs = [{"type": "scenario_space", "id": space_key}]
    for scenario in space_data.get("scenarios") or []:
        scenario_key = scenario.get("scenario_key")
        if scenario_key:
            refs.append({"type": "simulation_result", "scenario_key": scenario_key})
    return refs


def _scoreline_index(scorelines: list[dict] | dict | None) -> dict[str, Any]:
    if isinstance(scorelines, Mapping):
        return dict(scorelines)
    index = {}
    for row in scorelines or []:
        key = _get(row, "scenario_key")
        if key:
            index[str(key)] = row
    return index


def _config_value(config: dict, key: str) -> Any:
    if isinstance(config, Mapping):
        if key in config:
            return config.get(key)
        snapshot = config.get("model_input_snapshot") or {}
        if isinstance(snapshot, Mapping):
            return snapshot.get(key)
    return None


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

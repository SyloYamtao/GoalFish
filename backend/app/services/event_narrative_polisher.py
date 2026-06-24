"""LLM-assisted event narrative polishing for Step3 modal trajectories."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .coach_jury import SCENARIO_TEMPLATE
from .content_language import build_content_language_instruction
from .llm_budget import BudgetExceeded, LLMCallLedger, LLMBudgetProfile
from .match_simulator import Event
from .roster_loader import PlayerSnapshot, TeamRoster


NARR_VERSION = "v1"


class EventNarrativePolisher:
    def __init__(
        self,
        *,
        budget: LLMBudgetProfile,
        ledger: LLMCallLedger,
        squads: tuple[TeamRoster, TeamRoster],
        llm_client: Any | None = None,
        content_language_instruction: str | None = None,
    ) -> None:
        self._budget = budget
        self._ledger = ledger
        self._squads = squads
        self._llm_client = llm_client
        self._content_language_instruction = content_language_instruction or build_content_language_instruction(None)
        self._whitelist = self._build_whitelist(squads)

    def polish(self, events: list[Event], scenario_key: str) -> list[dict]:
        """
        Polish event descriptions within the LLM budget.

        Budget zero, scenarios outside the top-N scenario order, LLM failures,
        and whitelist violations all degrade to deterministic templates.
        """

        if self._budget.narrative_polish_count <= 0 or not self._scenario_in_budget(scenario_key):
            return self._template_fallback(events)

        polished: list[dict] = []
        for event in events:
            messages = self._build_messages(event, scenario_key)
            try:
                with self._ledger.acquire(
                    role="narrative_polisher",
                    prompt_version=NARR_VERSION,
                    prompt=messages,
                ) as call:
                    if call.cached:
                        text = str(call.result or "").strip()
                    else:
                        started = time.perf_counter()
                        text = _text_from_llm_response(
                            self._llm().chat(
                                messages=messages,
                                temperature=0.3,
                                max_tokens=80,
                            )
                        )
                        call.complete(
                            text,
                            tokens=0,
                            cost=0.0,
                            latency_ms=round((time.perf_counter() - started) * 1000),
                        )

                text = _clean_one_line(text)
                if not self._validate_whitelist(text):
                    self._ledger.record_failure(
                        role="narrative_polisher",
                        reason="player_whitelist_failed",
                        fallback="template",
                        scenario_key=scenario_key,
                        event_type=event.type,
                    )
                    polished.append(self._event_row(event, self._template_one(event), source="template"))
                    continue

                polished.append(self._event_row(event, text, source="llm"))
            except BudgetExceeded as exc:
                self._record_failure("budget_exceeded", scenario_key, event, exc)
                polished.append(self._event_row(event, self._template_one(event), source="template"))
            except Exception as exc:  # noqa: BLE001 - Step3 narratives must fail open.
                self._record_failure(_failure_reason(exc), scenario_key, event, exc)
                polished.append(self._event_row(event, self._template_one(event), source="template"))
        return polished

    def _build_whitelist(self, squads: tuple[TeamRoster, TeamRoster]) -> set[str]:
        """Collect full names, English names, and any alias fields carried by snapshots."""

        names: set[str] = set()
        for roster in squads:
            for player in roster.players:
                for value in (
                    _get(player, "name"),
                    _get(player, "name_en"),
                    _get(player, "full_name"),
                    _get(player, "full_name_en"),
                ):
                    _add_name(names, value)
                derived = dict(_get(player, "derived", {}) or {})
                for alias_key in ("aliases", "alias", "name_aliases", "aliases_zh", "aliases_en"):
                    _add_many(names, derived.get(alias_key))
        return names

    def _validate_whitelist(self, text: str) -> bool:
        """Reject descriptions that introduce non-whitelisted Latin player names."""

        if not text.strip():
            return False

        remaining = text
        for name in sorted(self._whitelist, key=len, reverse=True):
            remaining = remaining.replace(name, " ")

        if _has_unapproved_cjk_name(remaining):
            return False

        allowed_latin = {
            "home",
            "away",
            "goal",
            "shot",
            "save",
            "card",
            "pso",
            "et",
            "var",
            "xg",
        }
        latin_tokens = re.findall(r"[A-Za-z][A-Za-z.'-]+", remaining)
        return all(token.lower() in allowed_latin for token in latin_tokens)

    def _template_one(self, event: Event) -> str:
        """Deterministic no-LLM description that keeps Step3 runnable."""

        minute = _minute(event)
        side = str(_get(event, "side", "unknown") or "unknown")
        actor_name = _player_name(_actor(event), default="球员")
        event_type = str(_get(event, "type", "") or "")

        if event_type in {"GOAL", "ET_GOAL"}:
            return f"{side} {minute}' {actor_name} 破门"
        if event_type == "SHOT":
            return f"{side} {minute}' {actor_name} 射门"
        if event_type == "CHANCE_CREATED":
            return f"{side} {minute}' {actor_name} 制造机会"
        if event_type == "SAVE":
            return f"{side} {minute}' {actor_name} 完成扑救"
        if event_type == "PRESSURE_SHIFT":
            return f"{side} {minute}' 比赛压力转移"
        if event_type == "CARD":
            return f"{side} {minute}' {actor_name} 吃{_card_label(_get(event, 'card_color'))}牌"
        if event_type == "PSO":
            outcome = "命中" if bool(_get(event, "pso_scored")) else "罚失"
            return f"{side} {minute}' {actor_name} 点球{outcome}"
        return f"{side} {minute}' {event_type or '事件'}"

    def _template_fallback(self, events: list[Event]) -> list[dict]:
        return [self._event_row(event, self._template_one(event), source="template") for event in events]

    def _build_messages(self, event: Event, scenario_key: str) -> list[dict[str, str]]:
        template = _load_prompt_template("event_polish.txt")
        event_payload = {
            "scenario_key": scenario_key,
            "minute": _minute(event),
            "type": _get(event, "type"),
            "side": _get(event, "side"),
            "actor": _player_payload(_actor(event)),
            "assist": _player_payload(_assist(event)),
            "score_after": _score_after(event),
            "card_color": _get(event, "card_color"),
            "pso_scored": _get(event, "pso_scored"),
        }
        content = template.format(
            event_json=json.dumps(event_payload, ensure_ascii=False, sort_keys=True),
            player_whitelist=", ".join(sorted(self._whitelist)),
        )
        return [
            {
                "role": "system",
                "content": (
                    "你是足球比赛事件编辑。只输出一行客观描述，不得新增球员或事实。"
                    f"\n\n{self._content_language_instruction}"
                ),
            },
            {"role": "user", "content": content},
        ]

    def _event_row(self, event: Event, description: str, *, source: str) -> dict:
        actor = _actor(event)
        assist = _assist(event)
        return {
            "minute": _minute(event),
            "type": _get(event, "type"),
            "side": _get(event, "side"),
            "actor_player_id": _get(actor, "id") if actor is not None else None,
            "actor_name": _player_name(actor, default=None),
            "actor_name_en": _get(actor, "name_en") if actor is not None else None,
            "assist_player_id": _get(assist, "id") if assist is not None else None,
            "assist_name": _player_name(assist, default=None),
            "score_after": _score_after(event),
            "card_color": _get(event, "card_color"),
            "pso_scored": _get(event, "pso_scored"),
            "description": description,
            "narrative_source": source,
            "narrative_version": NARR_VERSION,
        }

    def _scenario_in_budget(self, scenario_key: str) -> bool:
        return _scenario_rank(scenario_key) <= int(self._budget.narrative_polish_count)

    def _record_failure(self, reason: str, scenario_key: str, event: Event, exc: Exception) -> None:
        self._ledger.record_failure(
            role="narrative_polisher",
            reason=reason,
            fallback="template",
            scenario_key=scenario_key,
            event_type=_get(event, "type"),
            error=str(exc),
        )

    def _llm(self) -> Any:
        if self._llm_client is None:
            from app.utils.llm_client import LLMClient

            self._llm_client = LLMClient()
        return self._llm_client


def _scenario_rank(scenario_key: str) -> int:
    for index, scenario in enumerate(SCENARIO_TEMPLATE, start=1):
        if scenario.get("scenario_key") == scenario_key:
            return index
    return 10**6


def _load_prompt_template(filename: str) -> str:
    return (Path(__file__).with_name("narrative_prompts") / filename).read_text(encoding="utf-8")


def _text_from_llm_response(raw: Any) -> str:
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        try:
            return str(raw["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError):
            return str(raw.get("content") or raw.get("text") or "")
    return str(raw or "")


def _failure_reason(exc: Exception) -> str:
    message = str(exc)
    if "LLM返回内容为空" in message or "reasoning_content" in message:
        return "empty_content"
    return "llm_failed"


def _clean_one_line(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _has_unapproved_cjk_name(text: str) -> bool:
    generic_fragments = {
        "主队",
        "客队",
        "球员",
        "门将",
        "禁区",
        "前沿",
        "完成",
        "制造",
        "机会",
        "比赛",
        "压力",
        "定位球",
        "点球",
        "左路",
        "右路",
        "中路",
        "前点",
        "后点",
    }
    for match in re.finditer(r"([\u4e00-\u9fff]{2,6})\s*(?:破门|进球|射门|扑救|助攻|吃牌|点球)", text):
        candidate = match.group(1)
        if not any(fragment in candidate for fragment in generic_fragments):
            return True
    return False


def _event_value(event: Event, key: str) -> Any:
    return getattr(event, key, None)


def _actor(event: Event) -> PlayerSnapshot | None:
    return _event_value(event, "actor_player") or _event_value(event, "actor")


def _assist(event: Event) -> PlayerSnapshot | None:
    return _event_value(event, "assist_player") or _event_value(event, "assist")


def _minute(event: Event) -> int:
    return int(_get(event, "minute", 0) or 0)


def _score_after(event: Event) -> dict[str, int] | None:
    score = _get(event, "score_after")
    if isinstance(score, tuple | list) and len(score) == 2:
        return {"home": int(score[0]), "away": int(score[1])}
    if isinstance(score, dict):
        return {"home": int(score.get("home", 0)), "away": int(score.get("away", 0))}
    return None


def _player_payload(player: PlayerSnapshot | None) -> dict[str, Any] | None:
    if player is None:
        return None
    return {
        "id": _get(player, "id"),
        "name": _get(player, "name"),
        "name_en": _get(player, "name_en"),
        "position": _get(player, "position_primary"),
    }


def _player_name(player: Any, *, default: str | None) -> str | None:
    if player is None:
        return default
    value = _get(player, "name") or _get(player, "full_name") or _get(player, "name_en") or default
    return str(value) if value is not None else None


def _card_label(card_color: Any) -> str:
    color = str(card_color or "").lower()
    if color in {"yellow", "y"}:
        return "黄"
    if color in {"red", "r"}:
        return "红"
    return str(card_color or "")


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _add_many(names: set[str], value: Any) -> None:
    if isinstance(value, str):
        _add_name(names, value)
    elif isinstance(value, Iterable):
        for item in value:
            _add_name(names, item)


def _add_name(names: set[str], value: Any) -> None:
    if value is None:
        return
    text = str(value).strip()
    if text:
        names.add(text)

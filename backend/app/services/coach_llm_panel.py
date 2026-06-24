"""LLM-backed coach panel deliberation for Step2 scenario weighting."""

from __future__ import annotations

import copy
import hashlib
import json
import time
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .coach_jury import SCENARIO_TEMPLATE
from .content_language import build_content_language_instruction
from .llm_budget import BudgetExceeded, LLMCallLedger, LLMBudgetProfile


PANEL_VERSION = "v1"


@dataclass(frozen=True)
class Role:
    key: str
    label: str
    weight: int
    attention: list[str]


ROLES = [
    Role("head_coach", "战术主教练", 20, ["formation_match", "in_game_adjustment", "tempo"]),
    Role("attack", "进攻教练", 15, ["wing_progression", "box_touches", "shot_quality"]),
    Role("defense", "防守教练", 15, ["line_position", "marking", "second_balls"]),
    Role("transition", "转换/压迫教练", 10, ["high_press", "counter_press", "transition_speed"]),
    Role("set_piece", "定位球教练", 10, ["corner_design", "set_piece_def", "second_phase"]),
    Role("goalkeeper", "门将/防线教练", 10, ["gk_form", "high_claim", "communication"]),
    Role("fitness", "体能/换人教练", 10, ["fatigue", "sub_window", "squad_depth"]),
    Role("risk", "风险/裁判/天气教练", 10, ["card_pressure", "var_penalty", "weather", "ref_style"]),
]
ROLE_BY_KEY = {role.key: role for role in ROLES}


LIMITS = {
    "weight_delta_pct": (-30, +30),
    "team_xg_micro_adjustment": (-0.12, +0.12),
    "wld_pp_adjustment": (-7, +7),
    "confidence_delta": (-0.15, +0.15),
}


@dataclass
class CoachVerdict:
    role: str
    scenario_votes: list[dict]
    team_xg_micro_adjustment: dict
    wld_pp_adjustment: dict | None
    confidence_delta: float
    summary: str
    clipped: bool = False
    clipped_flags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CoachVerdict":
        return cls(
            role=str(payload.get("role") or ""),
            scenario_votes=[dict(vote) for vote in payload.get("scenario_votes") or []],
            team_xg_micro_adjustment=dict(payload.get("team_xg_micro_adjustment") or {}),
            wld_pp_adjustment=(
                dict(payload["wld_pp_adjustment"])
                if isinstance(payload.get("wld_pp_adjustment"), Mapping)
                else None
            ),
            confidence_delta=float(payload.get("confidence_delta") or 0.0),
            summary=str(payload.get("summary") or ""),
            clipped=bool(payload.get("clipped", False)),
            clipped_flags=list(payload.get("clipped_flags") or []),
            metadata=dict(payload.get("metadata") or {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CoachPanelInputs:
    """Compact, JSON-serializable context consumed by the coach panel."""

    home_team_summary: dict[str, Any] = field(default_factory=dict)
    away_team_summary: dict[str, Any] = field(default_factory=dict)
    fit_summary: dict[str, Any] = field(default_factory=dict)
    competition: dict[str, Any] = field(default_factory=dict)
    scenario_template: list[dict[str, Any]] = field(default_factory=list)
    head_to_head: list[dict[str, Any]] = field(default_factory=list)
    extraction_warnings: list[str] = field(default_factory=list)
    graph_facts_summary: dict[str, Any] = field(default_factory=dict)
    role_specific_facts: dict[str, str] = field(default_factory=dict)

    @classmethod
    def assemble(
        cls,
        *,
        rosters: Any = None,
        squads: Any = None,
        team_strengths: Any = None,
        fit_artifacts: Any = None,
        extracted: Any = None,
        graph_facts: Any = None,
        scenario_template: list[dict[str, Any]] | None = None,
        head_to_head: list[dict[str, Any]] | None = None,
        **extra: Any,
    ) -> "CoachPanelInputs":
        roster_pair = _pair(rosters if rosters is not None else squads)
        strength_pair = _pair(team_strengths)
        home_roster, away_roster = roster_pair
        home_strength, away_strength = strength_pair

        competition = _competition_summary(extracted, home_roster, away_roster, extra)
        fit_summary = _fit_summary(fit_artifacts, competition)
        graph_summary = _graph_facts_summary(graph_facts, home_roster, away_roster)

        home_summary = _team_summary("home", home_roster, home_strength, graph_summary)
        away_summary = _team_summary("away", away_roster, away_strength, graph_summary)

        warnings = []
        warnings.extend(list(_get(graph_facts, "warnings", []) or []))
        warnings.extend(list(extra.get("extraction_warnings") or []))

        panel_inputs = cls(
            home_team_summary=home_summary,
            away_team_summary=away_summary,
            fit_summary=fit_summary,
            competition=competition,
            scenario_template=list(scenario_template or SCENARIO_TEMPLATE),
            head_to_head=list(head_to_head or extra.get("head_to_head") or []),
            extraction_warnings=warnings,
            graph_facts_summary=graph_summary,
        )
        panel_inputs.role_specific_facts = {
            role.key: _role_specific_facts(role.key, panel_inputs) for role in ROLES
        }
        return panel_inputs


class CoachLLMPanel:
    PANEL_VERSION = PANEL_VERSION

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

    def deliberate(self, inputs: CoachPanelInputs) -> list[CoachVerdict]:
        role_keys = list(getattr(self._budget, "coach_panel_roles", []) or [])
        if not role_keys:
            return self._fallback_hash_verdicts(inputs)

        verdicts: list[CoachVerdict] = []
        for role_key in role_keys:
            try:
                role = _role(role_key)
                verdict = self._call_role(role, inputs)
                if role.key == "head_coach" and getattr(self._budget, "coach_deliberation_rounds", 1) >= 2:
                    verdict = self._call_role(role, inputs, round_index=2, previous_verdict=verdict)
                verdicts.append(verdict)
            except (BudgetExceeded, Exception) as exc:  # noqa: BLE001 - role failure must fail open.
                self._record_warning(role_key, exc)
                verdicts.append(self._fallback_role_verdict(role_key, inputs))

        if not verdicts:
            return self._fallback_hash_verdicts(inputs)
        return verdicts

    def render_role_prompt(
        self,
        role: str | Role,
        inputs: CoachPanelInputs,
        *,
        round_index: int = 1,
        previous_verdict: CoachVerdict | None = None,
    ) -> str:
        role_obj = _role(role)
        template = _load_prompt_template(role_obj.key)
        context = _prompt_context(role_obj, inputs)
        prompt = template.format(**context)

        if round_index >= 2:
            previous = json.dumps(
                previous_verdict.to_dict() if previous_verdict else {},
                ensure_ascii=False,
                sort_keys=True,
            )
            prompt = (
                f"{prompt}\n\n"
                "== 第二轮反驳 ==\n"
                "请复核上一轮结论中证据不足、越界或过度放大的部分，只输出修订后的完整 JSON verdict。\n"
                f"上一轮 verdict:\n{previous}"
            )
        return prompt

    def _call_role(
        self,
        role: str | Role,
        inputs: CoachPanelInputs,
        *,
        round_index: int = 1,
        previous_verdict: CoachVerdict | None = None,
    ) -> CoachVerdict:
        role = _role(role)
        messages = self._build_messages(
            role,
            inputs,
            round_index=round_index,
            previous_verdict=previous_verdict,
        )
        with self._ledger.acquire(
            role=f"coach_{role.key}",
            prompt_version=PANEL_VERSION,
            prompt=messages,
        ) as call:
            if call.cached:
                raw_result = call.result
            else:
                started = time.perf_counter()
                raw_result = self._llm().chat_json(
                    messages=messages,
                    temperature=0.1,
                    max_tokens=3200,
                )
                latency_ms = round((time.perf_counter() - started) * 1000)
                call.complete(raw_result, tokens=0, cost=0.0, latency_ms=latency_ms)

        payload = _payload_to_dict(raw_result)
        payload["role"] = role.key
        payload = clip_verdict(payload)
        payload = _ensure_all_scenario_votes(payload, inputs.scenario_template)
        return CoachVerdict.from_dict(payload)

    def _build_messages(
        self,
        role: Role,
        inputs: CoachPanelInputs,
        *,
        round_index: int = 1,
        previous_verdict: CoachVerdict | None = None,
    ) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "你是足球预测教练评审。只输出一个合法 JSON object，"
                    "不得输出 Markdown、解释文字或 schema 之外的事实。"
                    f"\n\n{self._content_language_instruction}"
                ),
            },
            {
                "role": "user",
                "content": self.render_role_prompt(
                    role,
                    inputs,
                    round_index=round_index,
                    previous_verdict=previous_verdict,
                ),
            },
        ]

    def _fallback_hash_verdicts(self, inputs: CoachPanelInputs) -> list[CoachVerdict]:
        return [self._fallback_role_verdict(role, inputs) for role in ROLES]

    def _fallback_role_verdict(self, role: str | Role, inputs: CoachPanelInputs) -> CoachVerdict:
        role_obj = _role(role) if str(role) in ROLE_BY_KEY or isinstance(role, Role) else ROLE_BY_KEY["head_coach"]
        votes = []
        for scenario in inputs.scenario_template or list(SCENARIO_TEMPLATE):
            scenario_key = str(scenario.get("scenario_key") or "")
            delta = _stable_int(f"{PANEL_VERSION}:{role_obj.key}:{scenario_key}", -2, 2)
            votes.append(
                {
                    "scenario_key": scenario_key,
                    "vote": "adjust" if delta else "support",
                    "weight_delta_pct": delta,
                    "rationale": "LLM 评审降级，使用稳定哈希给出保守场景权重意见。",
                    "evidence_refs": [{"type": "scenario_key", "id": scenario_key}],
                }
            )

        return CoachVerdict(
            role=role_obj.key,
            scenario_votes=votes,
            team_xg_micro_adjustment={"home": 0.0, "away": 0.0, "rationale": "fallback 不调整 xG。"},
            wld_pp_adjustment=None,
            confidence_delta=0.0,
            summary=f"{role_obj.label} 评审降级为稳定哈希路径。",
            clipped=False,
            clipped_flags=[],
            metadata={"source": "coach_jury_fallback_v1", "panel_version": PANEL_VERSION},
        )

    def _record_warning(self, role_key: str, exc: Exception) -> None:
        self._ledger.record_failure(
            role=f"coach_{role_key}",
            reason="coach_role_failed",
            fallback="coach_jury_fallback_v1",
            error=str(exc),
        )

    def _llm(self) -> Any:
        if self._llm_client is None:
            from app.utils.llm_client import LLMClient

            self._llm_client = LLMClient()
        return self._llm_client


def clip_verdict(verdict_dict: dict) -> dict:
    """Clip all numeric coach verdict adjustments to spec limits."""

    verdict = copy.deepcopy(verdict_dict)
    clipped_flags = list(verdict.get("clipped_flags") or [])

    votes = verdict.get("scenario_votes")
    if not isinstance(votes, list):
        votes = []
    normalized_votes = []
    for index, vote in enumerate(votes):
        vote_dict = dict(vote) if isinstance(vote, Mapping) else {}
        scenario_key = str(vote_dict.get("scenario_key") or f"scenario_{index}")

        original = vote_dict.get("weight_delta_pct", 0)
        clipped = _clip_number(original, LIMITS["weight_delta_pct"], default=0)
        if clipped != original:
            clipped_flags.append(f"{scenario_key}.weight_delta_pct: {original}->{clipped}")
        vote_dict["scenario_key"] = scenario_key
        vote_dict["vote"] = _normalize_vote(vote_dict.get("vote"))
        vote_dict["weight_delta_pct"] = int(clipped)
        vote_dict["rationale"] = str(vote_dict.get("rationale") or "未提供理由。")

        evidence_refs = vote_dict.get("evidence_refs")
        if not isinstance(evidence_refs, list) or not evidence_refs:
            vote_dict["evidence_refs"] = [{"type": "validation", "reason": "missing_evidence_refs"}]
            clipped_flags.append(f"{scenario_key}.evidence_refs: added_missing")
        else:
            vote_dict["evidence_refs"] = [dict(ref) if isinstance(ref, Mapping) else {"value": ref} for ref in evidence_refs]
        normalized_votes.append(vote_dict)
    verdict["scenario_votes"] = normalized_votes

    xg = verdict.get("team_xg_micro_adjustment")
    xg_dict = dict(xg) if isinstance(xg, Mapping) else {}
    for side in ("home", "away"):
        original = xg_dict.get(side, 0.0)
        clipped = _clip_number(original, LIMITS["team_xg_micro_adjustment"], default=0.0)
        if clipped != original:
            clipped_flags.append(f"team_xg_micro_adjustment.{side}: {original}->{clipped}")
        xg_dict[side] = round(float(clipped), 4)
    xg_dict["rationale"] = str(xg_dict.get("rationale") or "未提供 xG 微调理由。")
    verdict["team_xg_micro_adjustment"] = xg_dict

    wld = verdict.get("wld_pp_adjustment")
    if isinstance(wld, Mapping):
        wld_dict = dict(wld)
        for key, original in list(wld_dict.items()):
            if key == "rationale" or not isinstance(original, (int, float)):
                continue
            clipped = _clip_number(original, LIMITS["wld_pp_adjustment"], default=0)
            if clipped != original:
                clipped_flags.append(f"wld_pp_adjustment.{key}: {original}->{clipped}")
            wld_dict[key] = round(float(clipped), 4)
        verdict["wld_pp_adjustment"] = wld_dict
    else:
        verdict["wld_pp_adjustment"] = None

    original_confidence = verdict.get("confidence_delta", 0.0)
    clipped_confidence = _clip_number(original_confidence, LIMITS["confidence_delta"], default=0.0)
    if clipped_confidence != original_confidence:
        clipped_flags.append(f"confidence_delta: {original_confidence}->{clipped_confidence}")
    verdict["confidence_delta"] = round(float(clipped_confidence), 4)

    verdict["summary"] = str(verdict.get("summary") or "")
    verdict["clipped_flags"] = clipped_flags
    verdict["clipped"] = bool(verdict.get("clipped", False) or clipped_flags)
    verdict.setdefault("metadata", {})
    return verdict


def _prompt_context(role: Role, inputs: CoachPanelInputs) -> dict[str, Any]:
    competition = inputs.competition or {}
    home = inputs.home_team_summary or {}
    away = inputs.away_team_summary or {}
    fit = inputs.fit_summary or {}
    role_facts = inputs.role_specific_facts.get(role.key) or _role_specific_facts(role.key, inputs)

    return {
        "panel_version": PANEL_VERSION,
        "role_key": role.key,
        "role_label": role.label,
        "role_weight": role.weight,
        "attention_list": ", ".join(role.attention),
        "home_zh": competition.get("home_zh") or home.get("team_name") or "主队",
        "away_zh": competition.get("away_zh") or away.get("team_name") or "客队",
        "tournament": competition.get("tournament") or "未知赛事",
        "stage": competition.get("stage") or "unknown",
        "neutral_note": competition.get("neutral_note") or "",
        "home_attack": _rating(home, "attack_rating"),
        "home_defense": _rating(home, "defense_rating"),
        "home_gk": _rating(home, "goalkeeper_rating"),
        "home_confidence": _rating(home, "confidence"),
        "away_attack": _rating(away, "attack_rating"),
        "away_defense": _rating(away, "defense_rating"),
        "away_gk": _rating(away, "goalkeeper_rating"),
        "away_confidence": _rating(away, "confidence"),
        "fit_status": fit.get("fit_status") or "unknown",
        "aic": _format_number(fit.get("aic")),
        "n_rows": fit.get("n_rows", 0),
        "elo_diff": int(round(float(fit.get("elo_diff") or 0))),
        "role_specific_facts": role_facts,
        "scenario_table": _scenario_table(inputs.scenario_template),
        "json_schema": json.dumps(_verdict_schema(role.key), ensure_ascii=False, indent=2),
    }


def _role_specific_facts(role_key: str, inputs: CoachPanelInputs) -> str:
    home = inputs.home_team_summary
    away = inputs.away_team_summary
    graph = inputs.graph_facts_summary or {}

    if role_key == "attack":
        return (
            "双方前6名进攻球员（双方前 6 名进攻球员）:\n"
            f"- 主队: {_format_players(home.get('top_attackers') or [])}\n"
            f"- 客队: {_format_players(away.get('top_attackers') or [])}"
        )
    if role_key == "defense":
        return (
            "防守关键球员:\n"
            f"- 主队: {_format_players(home.get('top_defenders') or [])}\n"
            f"- 客队: {_format_players(away.get('top_defenders') or [])}"
        )
    if role_key == "transition":
        return (
            "转换速度/压迫相关球员:\n"
            f"- 主队: {_format_players(home.get('top_transition_players') or [])}\n"
            f"- 客队: {_format_players(away.get('top_transition_players') or [])}"
        )
    if role_key == "set_piece":
        return (
            "定位球主罚/二点球参考:\n"
            f"- 主队: {_format_players(home.get('top_set_piece_takers') or [])}\n"
            f"- 客队: {_format_players(away.get('top_set_piece_takers') or [])}"
        )
    if role_key == "goalkeeper":
        return (
            "门将与防线沟通参考:\n"
            f"- 主队门将: {_format_players(home.get('goalkeepers') or [])}\n"
            f"- 客队门将: {_format_players(away.get('goalkeepers') or [])}"
        )
    if role_key == "fitness":
        return (
            "体能/阵容可用性:\n"
            f"- 主队不可用/存疑: {_format_status_items(home.get('unavailable_players') or [])}\n"
            f"- 客队不可用/存疑: {_format_status_items(away.get('unavailable_players') or [])}"
        )
    if role_key == "risk":
        availability = list(graph.get("availability_items") or [])
        card_pressure = list(graph.get("card_pressure_items") or [])
        return (
            "伤停/停赛/累黄名单（累黄牌名单，仅可引用以下球员，不得新增球员）:\n"
            f"- 伤停/停赛: {_format_status_items(availability)}\n"
            f"- 累黄/牌面压力: {_format_status_items(card_pressure)}"
        )

    return (
        "整体态势:\n"
        f"- 主队强度: attack={_rating(home, 'attack_rating')}, defense={_rating(home, 'defense_rating')}, "
        f"gk={_rating(home, 'goalkeeper_rating')}, confidence={_rating(home, 'confidence')}%\n"
        f"- 客队强度: attack={_rating(away, 'attack_rating')}, defense={_rating(away, 'defense_rating')}, "
        f"gk={_rating(away, 'goalkeeper_rating')}, confidence={_rating(away, 'confidence')}%"
    )


def _team_summary(role: str, roster: Any, strength: Any, graph_summary: dict[str, Any]) -> dict[str, Any]:
    strength_dict = _mapping(strength)
    players = list(_get(roster, "players", []) or [])
    team_iso3 = _get(roster, "iso3", strength_dict.get("team_iso3", ""))
    team_name = _get(roster, "team_fifa", strength_dict.get("team_name", team_iso3))

    availability_items = [
        item
        for item in graph_summary.get("availability_items", [])
        if _normalize_iso3(item.get("team_iso3")) == _normalize_iso3(team_iso3)
    ]

    return {
        "team_role": role,
        "team_iso3": team_iso3,
        "team_name": team_name,
        **strength_dict,
        "top_attackers": _top_players(players, "attack", 6),
        "top_defenders": _top_players(players, "defense", 6),
        "top_transition_players": _top_players(players, "pace", 6),
        "top_set_piece_takers": _top_players(players, "set_piece", 6),
        "goalkeepers": _top_players([p for p in players if _get(p, "position_primary") == "GK"], "gk", 3),
        "unavailable_players": availability_items or _unavailable_players(players, team_iso3),
    }


def _competition_summary(extracted: Any, home_roster: Any, away_roster: Any, extra: Mapping[str, Any]) -> dict[str, Any]:
    extracted_dict = _mapping(extracted)
    competition_meta = dict(
        extracted_dict.get("competition_meta")
        or extracted_dict.get("competition")
        or extra.get("competition")
        or {}
    )
    home_zh = extracted_dict.get("home_name_zh") or _get(home_roster, "team_fifa", "主队")
    away_zh = extracted_dict.get("away_name_zh") or _get(away_roster, "team_fifa", "客队")
    neutral = bool(competition_meta.get("neutral_venue", False))
    return {
        **competition_meta,
        "home_iso3": extracted_dict.get("home_iso3") or _get(home_roster, "iso3", ""),
        "away_iso3": extracted_dict.get("away_iso3") or _get(away_roster, "iso3", ""),
        "home_zh": home_zh,
        "away_zh": away_zh,
        "neutral_note": "中立场" if neutral else "非中立场或未声明中立场",
    }


def _fit_summary(fit_artifacts: Any, competition: Mapping[str, Any]) -> dict[str, Any]:
    fit = _mapping(fit_artifacts)
    diagnostics = dict(fit.get("diagnostics") or {})
    home_iso3 = str(competition.get("home_iso3") or "")
    away_iso3 = str(competition.get("away_iso3") or "")
    attack_coef = dict(fit.get("attack_coef") or {})
    defense_coef = dict(fit.get("defense_coef") or {})
    return {
        "fit_status": fit.get("fit_status") or "unknown",
        "data_sufficiency": fit.get("data_sufficiency"),
        "model_name": fit.get("model_name"),
        "aic": diagnostics.get("aic"),
        "n_rows": diagnostics.get("n_rows", 0),
        "home_advantage": fit.get("home_advantage", 0.0),
        "home_attack_coef": attack_coef.get(home_iso3),
        "away_attack_coef": attack_coef.get(away_iso3),
        "home_defense_coef": defense_coef.get(home_iso3),
        "away_defense_coef": defense_coef.get(away_iso3),
        "attack_coef_diff": _diff(attack_coef.get(home_iso3), attack_coef.get(away_iso3)),
        "defense_coef_diff": _diff(defense_coef.get(home_iso3), defense_coef.get(away_iso3)),
        "elo_diff": diagnostics.get("elo_diff", diagnostics.get("home_away_elo_diff", 0)),
        "diagnostics": diagnostics,
    }


def _graph_facts_summary(graph_facts: Any, home_roster: Any, away_roster: Any) -> dict[str, Any]:
    rosters = [home_roster, away_roster]
    player_index = _player_index(rosters)
    availability_items = []
    card_pressure_items = []

    for player_id, availability in (_get(graph_facts, "player_availability", {}) or {}).items():
        status = str(_get(availability, "status", "available") or "available")
        if status != "available":
            player = player_index.get(str(player_id), {})
            availability_items.append(
                {
                    "player_id": str(player_id),
                    "player": player.get("name") or str(player_id),
                    "team_iso3": _get(graph_facts, "player_team_iso3", {}).get(str(player_id))
                    or player.get("team_iso3"),
                    "status": status,
                    "summary": status,
                    "evidence_refs": list(_get(availability, "evidence_refs", []) or []),
                }
            )
        if _is_card_text(status):
            player = player_index.get(str(player_id), {})
            card_pressure_items.append(
                {
                    "player_id": str(player_id),
                    "player": player.get("name") or str(player_id),
                    "team_iso3": _get(graph_facts, "player_team_iso3", {}).get(str(player_id))
                    or player.get("team_iso3"),
                    "status": status,
                    "summary": status,
                    "evidence_refs": list(_get(availability, "evidence_refs", []) or []),
                }
            )

    for roster in rosters:
        team_iso3 = _get(roster, "iso3", "")
        for player in list(_get(roster, "players", []) or []):
            availability = dict(_get(player, "availability", {}) or {})
            status = str(availability.get("status") or "available")
            if status != "available" and not any(item.get("player_id") == _get(player, "id") for item in availability_items):
                availability_items.append(_status_item(player, team_iso3, status, availability))
            if _availability_has_card_pressure(availability):
                card_pressure_items.append(_status_item(player, team_iso3, status, availability))

    for team_iso3, rows in (_get(graph_facts, "team_news", {}) or {}).items():
        for row in rows or []:
            row_dict = dict(row) if isinstance(row, Mapping) else {"summary": str(row)}
            if not _is_card_row(row_dict):
                continue
            player_id = str(row_dict.get("player_id") or row_dict.get("id") or "")
            player = player_index.get(player_id, {})
            card_pressure_items.append(
                {
                    "player_id": player_id,
                    "player": row_dict.get("player") or row_dict.get("name") or player.get("name") or player_id,
                    "team_iso3": row_dict.get("team_iso3") or team_iso3,
                    "status": row_dict.get("status") or row_dict.get("type") or "card_pressure",
                    "summary": row_dict.get("summary") or row_dict.get("note") or "card_pressure",
                    "evidence_refs": list(row_dict.get("evidence_refs") or []),
                }
            )

    return {
        "availability_items": _dedupe_status_items(availability_items),
        "card_pressure_items": _dedupe_status_items(card_pressure_items),
        "warnings": list(_get(graph_facts, "warnings", []) or []),
    }


def _payload_to_dict(raw_result: Any) -> dict[str, Any]:
    if isinstance(raw_result, CoachVerdict):
        return raw_result.to_dict()
    if isinstance(raw_result, Mapping):
        return dict(raw_result)
    if isinstance(raw_result, str):
        parsed = json.loads(raw_result)
        if isinstance(parsed, Mapping):
            return dict(parsed)
    raise ValueError("Coach LLM result must be a JSON object")


def _ensure_all_scenario_votes(payload: dict[str, Any], scenario_template: list[dict[str, Any]]) -> dict[str, Any]:
    expected_keys = [str(scenario.get("scenario_key") or "") for scenario in scenario_template or list(SCENARIO_TEMPLATE)]
    expected_keys = [key for key in expected_keys if key]
    votes = [dict(vote) for vote in payload.get("scenario_votes") or []]
    existing = {str(vote.get("scenario_key") or "") for vote in votes}
    missing = [key for key in expected_keys if key not in existing]
    if not missing:
        payload["scenario_votes"] = votes
        return payload

    for scenario_key in missing:
        votes.append(
            {
                "scenario_key": scenario_key,
                "vote": "support",
                "weight_delta_pct": 0,
                "rationale": "LLM 未返回该场景，自动补为保守支持基准。",
                "evidence_refs": [
                    {"type": "scenario_key", "id": scenario_key},
                    {"type": "validation", "reason": "missing_scenario_vote"},
                ],
            }
        )
    flags = list(payload.get("clipped_flags") or [])
    flags.extend(f"{scenario_key}.scenario_votes: added_missing" for scenario_key in missing)
    payload["scenario_votes"] = votes
    payload["clipped_flags"] = flags
    payload["clipped"] = True
    return payload


def _verdict_schema(role_key: str) -> dict[str, Any]:
    return {
        "type": "object",
        "required": [
            "role",
            "scenario_votes",
            "team_xg_micro_adjustment",
            "wld_pp_adjustment",
            "confidence_delta",
            "summary",
        ],
        "properties": {
            "role": {"const": role_key},
            "scenario_votes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["scenario_key", "vote", "weight_delta_pct", "rationale", "evidence_refs"],
                },
            },
            "team_xg_micro_adjustment": {"type": "object"},
            "wld_pp_adjustment": {"type": ["object", "null"]},
            "confidence_delta": {"type": "number"},
            "summary": {"type": "string"},
        },
    }


def _load_prompt_template(role_key: str) -> str:
    path = Path(__file__).with_name("coach_prompts") / f"{role_key}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return _DEFAULT_PROMPT_TEMPLATE


def _role(value: str | Role) -> Role:
    if isinstance(value, Role):
        return value
    key = str(value)
    if key not in ROLE_BY_KEY:
        raise ValueError(f"Unknown coach role: {key}")
    return ROLE_BY_KEY[key]


def _pair(value: Any) -> tuple[Any, Any]:
    if isinstance(value, Mapping):
        return (
            value.get("home") or value.get("home_roster") or value.get("home_strength") or value.get("home_team"),
            value.get("away") or value.get("away_roster") or value.get("away_strength") or value.get("away_team"),
        )
    if isinstance(value, (tuple, list)) and len(value) >= 2:
        return value[0], value[1]
    return None, None


def _mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return dict(to_dict())
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _get(value: Any, key: str, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _rating(summary: Mapping[str, Any], key: str) -> int:
    value = summary.get(key)
    if value is None and isinstance(summary.get("strength"), Mapping):
        value = summary["strength"].get(key)
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def _top_players(players: list[Any], metric: str, n: int) -> list[dict[str, Any]]:
    ranked = sorted(
        players,
        key=lambda player: (
            _player_metric(player, metric),
            float(_get(player, "expected_minutes_share", 0.0) or 0.0),
        ),
        reverse=True,
    )
    return [_player_summary(player, metric) for player in ranked[:n]]


def _player_summary(player: Any, metric: str) -> dict[str, Any]:
    derived = dict(_get(player, "derived", {}) or {})
    return {
        "id": str(_get(player, "id", "")),
        "name": str(_get(player, "name", "") or _get(player, "name_en", "")),
        "name_en": str(_get(player, "name_en", "") or _get(player, "name", "")),
        "position": _get(player, "position_primary", ""),
        "metric": metric,
        "rating": _player_metric(player, metric),
        "attack": derived.get("attack"),
        "defense": derived.get("defense"),
        "pace": derived.get("pace"),
        "set_piece": derived.get("set_piece"),
        "gk": derived.get("gk"),
        "expected_role": _get(player, "expected_role", ""),
        "expected_minutes_share": _get(player, "expected_minutes_share", 0.0),
        "availability": dict(_get(player, "availability", {}) or {}),
    }


def _player_metric(player: Any, metric: str) -> float:
    derived = dict(_get(player, "derived", {}) or {})
    value = derived.get(metric)
    if value is None and metric == "pace":
        value = derived.get("speed")
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _player_index(rosters: list[Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for roster in rosters:
        team_iso3 = _get(roster, "iso3", "")
        for player in list(_get(roster, "players", []) or []):
            player_id = str(_get(player, "id", ""))
            if not player_id:
                continue
            index[player_id] = {
                "player_id": player_id,
                "name": _get(player, "name", "") or _get(player, "name_en", ""),
                "team_iso3": team_iso3,
            }
    return index


def _unavailable_players(players: list[Any], team_iso3: str) -> list[dict[str, Any]]:
    items = []
    for player in players:
        availability = dict(_get(player, "availability", {}) or {})
        status = str(availability.get("status") or "available")
        if status != "available":
            items.append(_status_item(player, team_iso3, status, availability))
    return items


def _status_item(player: Any, team_iso3: str, status: str, availability: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "player_id": str(_get(player, "id", "")),
        "player": str(_get(player, "name", "") or _get(player, "name_en", "")),
        "team_iso3": team_iso3,
        "status": status,
        "summary": availability.get("summary") or availability.get("reason") or status,
        "evidence_refs": list(availability.get("evidence_refs") or []),
    }


def _format_players(players: list[dict[str, Any]]) -> str:
    if not players:
        return "无明确名单"
    return "; ".join(
        f"{player.get('name')}({player.get('position')}, {player.get('metric')}={_format_number(player.get('rating'))})"
        for player in players
    )


def _format_status_items(items: list[dict[str, Any]]) -> str:
    if not items:
        return "无明确名单"
    return "; ".join(
        f"{item.get('player') or item.get('player_id')}[{item.get('team_iso3')}] "
        f"{item.get('status')}: {item.get('summary')}"
        for item in items
    )


def _scenario_table(template: list[dict[str, Any]]) -> str:
    rows = []
    for scenario in template or list(SCENARIO_TEMPLATE):
        rows.append(
            "- {key}: initial_weight={weight}; drivers={drivers}; risk_factors={risks}".format(
                key=scenario.get("scenario_key"),
                weight=scenario.get("initial_weight"),
                drivers=", ".join(scenario.get("key_drivers") or []),
                risks=", ".join(scenario.get("risk_factors") or []),
            )
        )
    return "\n".join(rows)


def _format_number(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "NA"
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}"


def _diff(left: Any, right: Any) -> float | None:
    if left is None or right is None:
        return None
    try:
        return round(float(left) - float(right), 4)
    except (TypeError, ValueError):
        return None


def _clip_number(value: Any, limits: tuple[float, float], *, default: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = float(default)
    return max(limits[0], min(limits[1], numeric))


def _normalize_vote(value: Any) -> str:
    normalized = str(value or "support")
    if normalized not in {"support", "adjust", "oppose"}:
        return "support"
    return normalized


def _availability_has_card_pressure(availability: Mapping[str, Any]) -> bool:
    return any(_is_card_text(str(value)) for value in availability.values())


def _is_card_row(row: Mapping[str, Any]) -> bool:
    return any(_is_card_text(str(row.get(key) or "")) for key in ("type", "category", "status", "summary", "note", "reason"))


def _is_card_text(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "yellow",
            "card",
            "accumulated",
            "suspension_risk",
            "累黄",
            "黄牌",
            "牌",
            "停赛风险",
        )
    )


def _dedupe_status_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for item in items:
        key = (item.get("player_id"), item.get("team_iso3"), item.get("status"), item.get("summary"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _stable_int(text: str, low: int, high: int) -> int:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    return low + (int(digest[:8], 16) % (high - low + 1))


def _normalize_iso3(value: Any) -> str:
    return str(value or "").strip().upper()


_DEFAULT_PROMPT_TEMPLATE = """你是足球预测教练评审,角色={role_label}.
关注维度: {attention_list}.
本场比赛: {home_zh} vs {away_zh} ({tournament}, {stage})
{neutral_note}

== 数据 ==
{home_zh} 强度: 进攻 {home_attack} 防守 {home_defense} 门将 {home_gk} (信心 {home_confidence}%)
{away_zh} 强度: 进攻 {away_attack} 防守 {away_defense} 门将 {away_gk} (信心 {away_confidence}%)
科学模型: {fit_status} (AIC={aic}, 训练样本 N={n_rows})
两队 Elo 差: {elo_diff:+d}

{role_specific_facts}

== 场景模板(9个) ==
{scenario_table}

== 你的任务 ==
1. 对 9 个场景给出投票 (support / adjust / oppose), adjust 时给 weight_delta_pct 在 [-30, +30].
2. 你不能直接修改科学模型概率, 只能在场景权重上发表意见.
3. 团队 xG 微调 [-0.12, +0.12] 仅在你能给出明确证据时使用.
4. 输出严格 JSON, 见下方 schema.

约束:
- 严禁编造未在数据块中出现的事实 / 球员名 / 比分.
- 引用证据时必须 cite evidence_refs.
- 你的角色权重为 {role_weight}/100, 影响仅限场景权重再加权.

输出 schema:
{json_schema}
"""

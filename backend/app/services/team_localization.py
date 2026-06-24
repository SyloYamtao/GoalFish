"""Locale-aware display names for football teams in UI payloads."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..utils.locale import get_locale
from .external_data.team_name_normalizer import TeamNameNormalizer


SCENARIO_CASE_LABELS: dict[str, dict[str, Any]] = {
    "home_normal_away_normal": {
        "en": {
            "scenario_name": "Baseline trend",
            "key_drivers": ["Both teams perform normally", "Stable tempo", "Standard shot quality"],
            "risk_factors": ["Early goal changes tempo"],
        },
        "zh": {
            "scenario_name": "基准走势",
            "key_drivers": ["双方正常发挥", "稳态节奏", "常规射门质量"],
            "risk_factors": ["早进球改变节奏"],
        },
    },
    "home_overperform_away_normal": {
        "en": {
            "scenario_name": "Home advantage trend",
            "key_drivers": ["Home pressure", "Wide progression", "Set-piece edge"],
            "risk_factors": ["Poor chance conversion"],
        },
        "zh": {
            "scenario_name": "主队优势走势",
            "key_drivers": ["主队压迫", "边路推进", "定位球优势"],
            "risk_factors": ["机会转化率不足"],
        },
    },
    "home_normal_away_underperform": {
        "en": {
            "scenario_name": "Home benefit trend",
            "key_drivers": ["Away buildup under pressure", "Home second-phase attacks", "Home tempo"],
            "risk_factors": ["Home pressure fails to break through"],
        },
        "zh": {
            "scenario_name": "主队受益走势",
            "key_drivers": ["客队出球受压", "主队二次进攻", "主场节奏"],
            "risk_factors": ["主队久攻不下"],
        },
    },
    "home_underperform_away_normal": {
        "en": {
            "scenario_name": "Away benefit trend",
            "key_drivers": ["Home defensive-third mistake", "Away counterattack", "Transition speed"],
            "risk_factors": ["Small away shot sample"],
        },
        "zh": {
            "scenario_name": "客队受益走势",
            "key_drivers": ["主队后场失误", "客队反击", "转换速度"],
            "risk_factors": ["客队射门样本偏少"],
        },
    },
    "home_normal_away_overperform": {
        "en": {
            "scenario_name": "Away advantage trend",
            "key_drivers": ["Away counterattack efficiency", "Goalkeeper performance", "Away set pieces"],
            "risk_factors": ["Away pressure sustainability"],
        },
        "zh": {
            "scenario_name": "客队优势走势",
            "key_drivers": ["客队反击效率", "门将表现", "客队定位球"],
            "risk_factors": ["客队压迫维持时间"],
        },
    },
    "home_underperform_away_overperform": {
        "en": {
            "scenario_name": "Away upset trend",
            "key_drivers": ["Early goal conceded", "Card pressure", "Away efficient finishing"],
            "risk_factors": ["Dependence on high volatility"],
        },
        "zh": {
            "scenario_name": "客队爆冷走势",
            "key_drivers": ["早丢球", "红黄牌压力", "客队高效终结"],
            "risk_factors": ["高波动依赖"],
        },
    },
    "home_overperform_away_underperform": {
        "en": {
            "scenario_name": "Home rout trend",
            "key_drivers": ["Home sustained pressure", "Away defensive dislocation", "Scoreline opens up"],
            "risk_factors": ["Overweighting a single mistake"],
        },
        "zh": {
            "scenario_name": "主队大胜走势",
            "key_drivers": ["主队强压", "客队防线失位", "比分拉开"],
            "risk_factors": ["过度放大单一失误"],
        },
    },
    "home_underperform_away_underperform": {
        "en": {
            "scenario_name": "Chaotic low-quality match",
            "key_drivers": ["Possession errors", "Low-quality shots", "Broken rhythm"],
            "risk_factors": ["Draw probability rises"],
        },
        "zh": {
            "scenario_name": "混乱低质量比赛",
            "key_drivers": ["传控失误", "低质量射门", "节奏破碎"],
            "risk_factors": ["平局概率抬升"],
        },
    },
    "home_overperform_away_overperform": {
        "en": {
            "scenario_name": "High-quality end-to-end match",
            "key_drivers": ["Both teams' attacking efficiency", "End-to-end tempo", "Early goal"],
            "risk_factors": ["Defensive sample instability"],
        },
        "zh": {
            "scenario_name": "高质量对攻",
            "key_drivers": ["双方进攻效率", "对攻节奏", "早进球"],
            "risk_factors": ["防守端样本不稳定"],
        },
    },
}


SCENARIO_SPACE_LABELS: dict[str, dict[str, Any]] = {
    "baseline": {
        "en": {
            "space_name": "Baseline performance space",
            "summary": "A steady match path when both teams perform normally.",
        },
        "zh": {
            "space_name": "基准发挥空间",
            "summary": "双方正常发挥下的稳态比赛路径。",
        },
    },
    "home_upside": {
        "en": {
            "space_name": "Home upside space",
            "summary": "A path where home pressure, wide play, and set pieces improve returns.",
        },
        "zh": {
            "space_name": "主队上行空间",
            "summary": "主队压迫、边路和定位球收益提升的路径。",
        },
    },
    "away_upside": {
        "en": {
            "space_name": "Away upside space",
            "summary": "A path where away counterattacks, goalkeeping, and set pieces improve returns.",
        },
        "zh": {
            "space_name": "客队上行空间",
            "summary": "客队反击、门将和定位球偷袭收益提升的路径。",
        },
    },
    "home_error": {
        "en": {
            "space_name": "Home error space",
            "summary": "A path where home possession, defensive communication, discipline, or substitutions break down.",
        },
        "zh": {
            "space_name": "主队失误空间",
            "summary": "主队传控、后防沟通、纪律或换人风险放大的路径。",
        },
    },
    "away_error": {
        "en": {
            "space_name": "Away error space",
            "summary": "A path where away defensive shape, fitness, discipline, or buildup pressure worsens.",
        },
        "zh": {
            "space_name": "客队失误空间",
            "summary": "客队防线、体能、纪律和出球压力恶化的路径。",
        },
    },
    "volatility": {
        "en": {
            "space_name": "High-volatility event space",
            "summary": "A path where penalties, VAR, red cards, injuries, weather, or early goals change the match.",
        },
        "zh": {
            "space_name": "高波动事件空间",
            "summary": "点球、VAR、红牌、伤退、天气和早进球改变比赛的路径。",
        },
    },
}


RESUME_NODE_LABELS: dict[str, dict[str, str]] = {
    "extract_team_context": {"en": "Extract team context", "zh": "抽取球队上下文"},
    "build_prediction_config": {"en": "Finalize prediction config", "zh": "定稿预测配置"},
    "generate_coach_agents": {"en": "Generate 100-coach review panel", "zh": "生成 100 教练评审团"},
    "discuss_scenario_space_design": {"en": "Finalize 02 Scenario Space Design", "zh": "02 场景空间设计定稿"},
    "discuss_resume_replay_policy": {"en": "Finalize 03 Recovery & Replay Policy", "zh": "03 恢复与回看策略定稿"},
    "initialize_scientific_model": {"en": "Initialize scientific model base", "zh": "初始化科学模型底盘"},
    "compute_team_strength": {"en": "Calculate team strengths", "zh": "计算球队强度"},
    "generate_scenario_matrix": {"en": "Generate nine-scenario matrix", "zh": "生成九场景矩阵"},
    "compute_scoreline_distribution": {"en": "Calculate score probabilities", "zh": "计算比分概率"},
    "generate_nine_scenario_match_events": {"en": "Generate nine-scenario match event chains", "zh": "生成九场景比赛事件链"},
    "coach_review_match_events": {"en": "Coach review match event chains", "zh": "教练复核比赛事件链"},
    "generate_analyst_notes": {"en": "Generate analyst notes", "zh": "生成分析笔记"},
    "generate_report": {"en": "Generate match prediction report", "zh": "生成赛事预测报告"},
    "prepare_prediction_qa": {"en": "Prepare prediction Q&A", "zh": "准备预测问答"},
}


COACH_DISCUSSION_LABELS: dict[str, dict[str, str]] = {
    "scenario_design": {
        "en_topic": "02 Scenario Space Design",
        "zh_topic": "02 场景空间设计",
        "en_prompt": "Coach review of the 3x3 home/away performance states, six space groups, and weight caps.",
        "zh_prompt": "围绕 3x3 九种主客队发挥状态、六个空间归属和权重上限进行教练评审。",
        "en_summary": (
            "The coach review panel supports retaining the nine-scenario matrix; weights do not override the "
            "scientific model and only act as scenario priors within a 30% adjustment cap."
        ),
        "zh_summary": "教练评审团支持保留九场景矩阵；权重不覆盖科学模型，仅作为场景先验权重并控制在 30% 调整上限内。",
    },
    "resume_policy": {
        "en_topic": "03 Recovery & Replay Policy",
        "zh_topic": "03 恢复与回看策略",
        "en_prompt": "Discuss which prediction nodes must be persisted, which can be recomputed, and UI replay summaries.",
        "zh_prompt": "讨论哪些预测节点必须落库、哪些可以重算，以及 UI 回看摘要。",
        "en_summary": (
            "Config, coach panel, nine-scenario matrix, score probabilities, match event chains, reviews, and "
            "reports must be persisted; high-cost event chains that affect reports/Q&A should prefer reuse."
        ),
        "zh_summary": "配置、教练、九场景矩阵、比分概率、比赛事件链、复核和报告均必须持久化；高成本且影响报告/问答的事件链优先 reuse。",
    },
}


def localize_team_name(
    iso3: Any,
    *,
    locale: str | None = None,
    fallback: str | None = None,
    normalizer: TeamNameNormalizer | None = None,
) -> str:
    code = str(iso3 or "").strip().upper()
    if len(code) != 3 or not code.isascii() or not code.isalpha():
        return fallback or str(iso3 or "")
    normalizer = normalizer or TeamNameNormalizer()
    ui_locale = _normalize_ui_locale(locale)
    try:
        return normalizer.to_canonical_zh(code) if ui_locale == "zh" else normalizer.to_canonical_en(code)
    except Exception:
        return fallback or code


def localize_step2_payload(payload: dict[str, Any] | None, *, locale: str | None = None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return payload

    data = deepcopy(payload)
    normalizer = TeamNameNormalizer()
    ui_locale = _normalize_ui_locale(locale)
    home_iso3 = _first_value(data.get("home_iso3"), _squad_iso3(data, "home"), _summary_iso3(data, "home"))
    away_iso3 = _first_value(data.get("away_iso3"), _squad_iso3(data, "away"), _summary_iso3(data, "away"))
    home_name = localize_team_name(home_iso3, locale=ui_locale, fallback=data.get("home_team"), normalizer=normalizer)
    away_name = localize_team_name(away_iso3, locale=ui_locale, fallback=data.get("away_team"), normalizer=normalizer)

    if home_iso3:
        data["home_team"] = home_name
    if away_iso3:
        data["away_team"] = away_name
    if home_iso3 and away_iso3:
        data["match_name"] = f"{home_name} vs {away_name}"

    _localize_dataset_summary(data.get("dataset_summary"), ui_locale, normalizer)
    _localize_roster(data.get("roster"), ui_locale, normalizer)
    _localize_model_input_snapshot(data.get("model_input_snapshot"), ui_locale, normalizer, home_name, away_name)
    data["scenario_design_summary"] = localize_scenario_design_summary(data.get("scenario_design_summary"), locale=ui_locale)
    data["resume_policy_summary"] = localize_resume_policy_summary(data.get("resume_policy_summary"), locale=ui_locale)
    return data


def localize_scenario_case_rows(rows: list[dict[str, Any]], *, locale: str | None = None) -> list[dict[str, Any]]:
    ui_locale = _normalize_ui_locale(locale)
    return [_localize_scenario_case(row, ui_locale) for row in rows]


def localize_scenario_space_rows(rows: list[dict[str, Any]], *, locale: str | None = None) -> list[dict[str, Any]]:
    ui_locale = _normalize_ui_locale(locale)
    return [_localize_scenario_space(row, ui_locale) for row in rows]


def localize_resume_node_rows(rows: list[dict[str, Any]], *, locale: str | None = None) -> list[dict[str, Any]]:
    ui_locale = _normalize_ui_locale(locale)
    return [_localize_resume_node(row, ui_locale) for row in rows]


def localize_coach_discussion_rows(rows: list[dict[str, Any]], *, locale: str | None = None) -> list[dict[str, Any]]:
    ui_locale = _normalize_ui_locale(locale)
    localized = []
    for row in rows:
        item = dict(row)
        labels = COACH_DISCUSSION_LABELS.get(str(item.get("discussion_type") or ""))
        if labels:
            item["topic"] = labels[f"{ui_locale}_topic"]
            item["prompt"] = labels[f"{ui_locale}_prompt"]
            item["summary"] = labels[f"{ui_locale}_summary"]
        localized.append(item)
    return localized


def localize_scenario_design_summary(summary: Any, *, locale: str | None = None) -> Any:
    if not isinstance(summary, dict):
        return summary
    ui_locale = _normalize_ui_locale(locale)
    data = deepcopy(summary)
    if isinstance(data.get("matrix"), list):
        data["matrix"] = localize_scenario_case_rows(data["matrix"], locale=ui_locale)
    return data


def localize_resume_policy_summary(summary: Any, *, locale: str | None = None) -> Any:
    if not isinstance(summary, dict):
        return summary
    data = deepcopy(summary)
    if isinstance(data.get("nodes"), list):
        data["nodes"] = localize_resume_node_rows(data["nodes"], locale=locale)
    return data


def localize_team_strength_rows(rows: list[dict[str, Any]], *, locale: str | None = None) -> list[dict[str, Any]]:
    normalizer = TeamNameNormalizer()
    ui_locale = _normalize_ui_locale(locale)
    localized = []
    for row in rows:
        item = dict(row)
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        strength_metadata = item.get("strength_metadata") if isinstance(item.get("strength_metadata"), dict) else {}
        iso3 = item.get("team_iso3") or metadata.get("team_iso3") or strength_metadata.get("team_iso3")
        if iso3:
            item["team_name"] = localize_team_name(
                iso3,
                locale=ui_locale,
                fallback=item.get("team_name"),
                normalizer=normalizer,
            )
        localized.append(item)
    return localized


def _localize_scenario_case(row: dict[str, Any], locale: str) -> dict[str, Any]:
    item = deepcopy(row)
    scenario_key = str(item.get("scenario_key") or (item.get("metadata") or {}).get("scenario_key") or "")
    labels = SCENARIO_CASE_LABELS.get(scenario_key, {}).get(locale)
    if labels:
        item["scenario_name"] = labels["scenario_name"]
        item["key_drivers"] = list(labels["key_drivers"])
        item["risk_factors"] = list(labels["risk_factors"])
        if item.get("metadata") and isinstance(item["metadata"], dict):
            metadata = dict(item["metadata"])
            metadata["scenario_name"] = labels["scenario_name"]
            metadata["key_drivers"] = list(labels["key_drivers"])
            metadata["risk_factors"] = list(labels["risk_factors"])
            item["metadata"] = metadata
    return item


def _localize_scenario_space(row: dict[str, Any], locale: str) -> dict[str, Any]:
    item = deepcopy(row)
    space_key = str(item.get("space_key") or item.get("scenario_space") or "")
    labels = SCENARIO_SPACE_LABELS.get(space_key, {}).get(locale)
    if labels:
        item["space_name"] = labels["space_name"]
        item["summary"] = labels["summary"]
    return item


def _localize_resume_node(row: dict[str, Any], locale: str) -> dict[str, Any]:
    item = dict(row)
    label = RESUME_NODE_LABELS.get(str(item.get("event_type") or ""), {}).get(locale)
    if label:
        item["label"] = label
        strategy = item.get("resume_strategy")
        item["ui_replay_summary"] = f"{label}：{strategy}" if locale == "zh" else f"{label}: {strategy}"
    return item


def _normalize_ui_locale(locale: str | None) -> str:
    raw = str(locale or get_locale() or "en").split(",", 1)[0].strip().lower()
    if "-" in raw:
        raw = raw.split("-", 1)[0]
    return "zh" if raw == "zh" else "en"


def _first_value(*values: Any) -> Any:
    for value in values:
        if value:
            return value
    return None


def _summary_iso3(data: dict[str, Any], role: str) -> Any:
    summary = data.get("dataset_summary")
    if not isinstance(summary, dict):
        return None
    team = summary.get(role)
    return team.get("team_iso3") if isinstance(team, dict) else None


def _squad_iso3(data: dict[str, Any], role: str) -> Any:
    model_input = data.get("model_input_snapshot") if isinstance(data.get("model_input_snapshot"), dict) else {}
    squads = model_input.get("squads") if isinstance(model_input.get("squads"), dict) else {}
    team = squads.get(role) if isinstance(squads.get(role), dict) else {}
    return team.get("team_iso3")


def _localize_dataset_summary(summary: Any, locale: str, normalizer: TeamNameNormalizer) -> None:
    if not isinstance(summary, dict):
        return
    for role in ("home", "away"):
        team = summary.get(role)
        if not isinstance(team, dict):
            continue
        iso3 = team.get("team_iso3")
        if iso3:
            team["team_name"] = localize_team_name(iso3, locale=locale, fallback=team.get("team_name"), normalizer=normalizer)


def _localize_roster(roster: Any, locale: str, normalizer: TeamNameNormalizer) -> None:
    if not isinstance(roster, dict):
        return
    for team in roster.get("teams") or []:
        if not isinstance(team, dict):
            continue
        iso3 = team.get("iso3") or team.get("team_iso3")
        if iso3:
            team["name"] = localize_team_name(iso3, locale=locale, fallback=team.get("name"), normalizer=normalizer)


def _localize_model_input_snapshot(
    model_input: Any,
    locale: str,
    normalizer: TeamNameNormalizer,
    home_name: str,
    away_name: str,
) -> None:
    if not isinstance(model_input, dict):
        return
    model_input["home_team"] = home_name
    model_input["away_team"] = away_name
    model_input["match_name"] = f"{home_name} vs {away_name}"

    squads = model_input.get("squads")
    if isinstance(squads, dict):
        for role in ("home", "away"):
            team = squads.get(role)
            if not isinstance(team, dict):
                continue
            iso3 = team.get("team_iso3")
            if iso3:
                team["team_name"] = localize_team_name(iso3, locale=locale, fallback=team.get("team_name"), normalizer=normalizer)

    for key in ("team_strengths_prepared", "team_strengths"):
        rows = model_input.get(key)
        if isinstance(rows, list):
            model_input[key] = localize_team_strength_rows(rows, locale=locale)

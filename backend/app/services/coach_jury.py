"""Deterministic football coach jury generation and aggregation."""

from __future__ import annotations

import hashlib
from typing import Any


ROLE_DISTRIBUTION: tuple[tuple[str, int, list[str]], ...] = (
    ("head_coach", 20, ["总体比赛计划", "阵型匹配", "临场调整"]),
    ("attack", 15, ["射门质量", "边路推进", "禁区触球", "进攻转换"]),
    ("defense", 15, ["防线站位", "盯人", "保护肋部", "二点球"]),
    ("transition", 10, ["高位压迫", "反抢", "攻防转换速度"]),
    ("set_piece", 10, ["角球", "任意球", "防守定位球", "二次进攻"]),
    ("goalkeeper", 10, ["门将状态", "出击", "扑救", "后场沟通"]),
    ("fitness", 10, ["体能下降", "换人窗口", "阵容厚度"]),
    ("risk", 10, ["红黄牌", "VAR", "点球", "天气", "裁判尺度"]),
)


SCENARIO_TEMPLATE: tuple[dict[str, Any], ...] = (
    {
        "home_state": "normal",
        "away_state": "normal",
        "scenario_key": "home_normal_away_normal",
        "scenario_name": "基准走势",
        "scenario_space": "baseline",
        "initial_weight": 22,
        "key_drivers": ["双方正常发挥", "稳态节奏", "常规射门质量"],
        "risk_factors": ["早进球改变节奏"],
    },
    {
        "home_state": "overperform",
        "away_state": "normal",
        "scenario_key": "home_overperform_away_normal",
        "scenario_name": "主队优势走势",
        "scenario_space": "home_upside",
        "initial_weight": 13,
        "key_drivers": ["主队压迫", "边路推进", "定位球优势"],
        "risk_factors": ["机会转化率不足"],
    },
    {
        "home_state": "normal",
        "away_state": "underperform",
        "scenario_key": "home_normal_away_underperform",
        "scenario_name": "主队受益走势",
        "scenario_space": "home_upside",
        "initial_weight": 11,
        "key_drivers": ["客队出球受压", "主队二次进攻", "主场节奏"],
        "risk_factors": ["主队久攻不下"],
    },
    {
        "home_state": "underperform",
        "away_state": "normal",
        "scenario_key": "home_underperform_away_normal",
        "scenario_name": "客队受益走势",
        "scenario_space": "away_upside",
        "initial_weight": 11,
        "key_drivers": ["主队后场失误", "客队反击", "转换速度"],
        "risk_factors": ["客队射门样本偏少"],
    },
    {
        "home_state": "normal",
        "away_state": "overperform",
        "scenario_key": "home_normal_away_overperform",
        "scenario_name": "客队优势走势",
        "scenario_space": "away_upside",
        "initial_weight": 13,
        "key_drivers": ["客队反击效率", "门将表现", "客队定位球"],
        "risk_factors": ["客队压迫维持时间"],
    },
    {
        "home_state": "underperform",
        "away_state": "overperform",
        "scenario_key": "home_underperform_away_overperform",
        "scenario_name": "客队爆冷走势",
        "scenario_space": "volatility",
        "initial_weight": 7,
        "key_drivers": ["早丢球", "红黄牌压力", "客队高效终结"],
        "risk_factors": ["高波动依赖"],
    },
    {
        "home_state": "overperform",
        "away_state": "underperform",
        "scenario_key": "home_overperform_away_underperform",
        "scenario_name": "主队大胜走势",
        "scenario_space": "away_error",
        "initial_weight": 8,
        "key_drivers": ["主队强压", "客队防线失位", "比分拉开"],
        "risk_factors": ["过度放大单一失误"],
    },
    {
        "home_state": "underperform",
        "away_state": "underperform",
        "scenario_key": "home_underperform_away_underperform",
        "scenario_name": "混乱低质量比赛",
        "scenario_space": "home_error",
        "initial_weight": 7,
        "key_drivers": ["传控失误", "低质量射门", "节奏破碎"],
        "risk_factors": ["平局概率抬升"],
    },
    {
        "home_state": "overperform",
        "away_state": "overperform",
        "scenario_key": "home_overperform_away_overperform",
        "scenario_name": "高质量对攻",
        "scenario_space": "volatility",
        "initial_weight": 8,
        "key_drivers": ["双方进攻效率", "对攻节奏", "早进球"],
        "risk_factors": ["防守端样本不稳定"],
    },
)


RESUME_NODE_TEMPLATE: tuple[dict[str, Any], ...] = (
    ("extract_team_context", 50, "抽取球队上下文", True, True, "recompute", ["graph_snapshot"], ["team_context"]),
    ("build_prediction_config", 60, "定稿预测配置", True, False, "reuse", ["team_context"], ["prediction_config"]),
    ("generate_coach_agents", 65, "生成 100 教练评审团", True, False, "reuse", ["prediction_config"], ["coach_agents"]),
    ("discuss_scenario_space_design", 70, "02 场景空间设计定稿", True, False, "reuse", ["coach_agents", "model_input"], ["scenario_design_summary"]),
    ("discuss_resume_replay_policy", 75, "03 恢复与回看策略定稿", True, False, "reuse", ["coach_agents", "workflow_nodes"], ["resume_policy_summary"]),
    ("initialize_scientific_model", 80, "初始化科学模型底盘", True, True, "recompute", ["model_input"], ["model_diagnostics"]),
    ("compute_team_strength", 90, "计算球队强度", True, True, "recompute", ["model_input"], ["team_strengths"]),
    ("generate_scenario_matrix", 100, "生成九场景矩阵", True, False, "reuse", ["scenario_design_summary"], ["scenario_cases"]),
    ("compute_scoreline_distribution", 110, "计算比分概率", True, True, "recompute", ["scenario_cases"], ["scorelines"]),
    ("generate_nine_scenario_match_events", 120, "生成九场景比赛事件链", True, False, "reuse", ["scorelines"], ["match_events"]),
    ("coach_review_match_events", 130, "教练复核比赛事件链", True, True, "recompute", ["match_events"], ["coach_reviews"]),
    ("generate_analyst_notes", 140, "生成分析笔记", True, True, "recompute", ["coach_reviews"], ["analyst_notes"]),
    ("generate_report", 150, "生成赛事预测报告", True, True, "recompute", ["prediction_result"], ["report"]),
    ("prepare_prediction_qa", 160, "准备预测问答", True, True, "recompute", ["report", "prediction_artifacts"], ["qa_context"]),
)


class CoachJuryService:
    """Build coach-level review artifacts without social simulation semantics."""

    def generate_agents(self, *, prediction_config_id: str, home_team: str, away_team: str) -> list[dict[str, Any]]:
        agents: list[dict[str, Any]] = []
        index = 1
        for role, count, focus in ROLE_DISTRIBUTION:
            for offset in range(count):
                preference = _preference(role, offset)
                agents.append(
                    {
                        "prediction_config_id": prediction_config_id,
                        "agent_index": index,
                        "role": role,
                        "name": f"{_role_label(role)} {index:03d}",
                        "expertise": focus,
                        "tactical_preference": preference,
                        "risk_tolerance": _risk_tolerance(role, offset),
                        "evidence_policy": "仅引用上传资料、图谱事实、科学模型输出或明确先验规则。",
                        "system_prompt": (
                            f"你是足球比赛预测教练评审。关注 {home_team} vs {away_team}，"
                            f"角色为{_role_label(role)}，不得使用社交平台或舆情行为语义。"
                        ),
                        "agent_metadata": {"source": "coach_jury_fallback_v1", "batch": "deterministic_100"},
                    }
                )
                index += 1
        return agents

    def scenario_cases(self, *, model_diagnostics: dict[str, Any]) -> list[dict[str, Any]]:
        cases = []
        for template in SCENARIO_TEMPLATE:
            initial = int(template["initial_weight"])
            final = initial
            cases.append(
                {
                    **template,
                    "final_weight": final,
                    "coach_vote_summary": {
                        "support_votes": _support_votes(template["scenario_key"]),
                        "oppose_votes": _oppose_votes(template["scenario_key"]),
                        "abstain_votes": 100 - _support_votes(template["scenario_key"]) - _oppose_votes(template["scenario_key"]),
                        "max_weight_adjustment_pct": 30,
                        "applied_weight_delta": final - initial,
                    },
                    "model_constraints": {
                        "model_name": model_diagnostics.get("model_name"),
                        "fit_status": model_diagnostics.get("fit_status"),
                        "coach_adjustment_policy": "scenario_weight_only; scoreline probabilities remain model-led",
                    },
                }
            )
        return cases

    def scenario_design_discussion(self, *, prediction_config_id: str) -> dict[str, Any]:
        return {
            "prediction_config_id": prediction_config_id,
            "discussion_type": "scenario_design",
            "round_index": 1,
            "topic": "02 场景空间设计",
            "prompt": "围绕 3x3 九种主客队发挥状态、六个空间归属和权重上限进行教练评审。",
            "summary": "教练评审团支持保留九场景矩阵；权重不覆盖科学模型，仅作为场景先验权重并控制在 30% 调整上限内。",
            "consensus_score": 74,
            "disagreement_score": 26,
            "discussion_metadata": {
                "source": "coach_jury_fallback_v1",
                "weight_adjustment_cap_pct": 30,
                "scenario_cases_count": 9,
            },
        }

    def resume_nodes(self) -> list[dict[str, Any]]:
        rows = []
        for event_type, sequence, label, must_persist, can_recompute, strategy, inputs, outputs in RESUME_NODE_TEMPLATE:
            rows.append(
                {
                    "event_type": event_type,
                    "sequence": sequence,
                    "label": label,
                    "must_persist": must_persist,
                    "can_recompute": can_recompute,
                    "resume_strategy": strategy,
                    "input_artifact_types": inputs,
                    "output_artifact_types": outputs,
                    "ui_replay_summary": f"{label}：{strategy}",
                    "coach_vote_summary": {
                        "support_votes": 84 if must_persist else 62,
                        "oppose_votes": 8,
                        "abstain_votes": 8 if must_persist else 30,
                    },
                }
            )
        return rows

    def resume_policy_discussion(self, *, prediction_config_id: str) -> dict[str, Any]:
        return {
            "prediction_config_id": prediction_config_id,
            "discussion_type": "resume_policy",
            "round_index": 1,
            "topic": "03 恢复与回看策略",
            "prompt": "讨论哪些预测节点必须落库、哪些可以重算，以及 UI 回看摘要。",
            "summary": "配置、教练、九场景矩阵、比分概率、比赛事件链、复核和报告均必须持久化；高成本且影响报告/问答的事件链优先 reuse。",
            "consensus_score": 81,
            "disagreement_score": 19,
            "discussion_metadata": {
                "source": "coach_jury_fallback_v1",
                "last_resumable_event": "generate_nine_scenario_match_events",
            },
        }

    def scenario_votes(
        self,
        *,
        prediction_config_id: str,
        discussion_id: str,
        agent_ids: list[str],
        scenario_case_ids: list[str],
        scenario_keys: list[str],
    ) -> list[dict[str, Any]]:
        votes = []
        for agent_index, agent_id in enumerate(agent_ids):
            target_index = agent_index % len(scenario_case_ids)
            scenario_key = scenario_keys[target_index]
            votes.append(
                {
                    "prediction_config_id": prediction_config_id,
                    "discussion_id": discussion_id,
                    "agent_id": agent_id,
                    "target_type": "scenario_case",
                    "target_id": scenario_case_ids[target_index],
                    "vote": "support" if agent_index % 9 != 0 else "adjust",
                    "confidence": 62 + (agent_index % 18),
                    "reasoning": "场景权重只做有限校准，比分概率仍以科学模型输出为底盘。",
                    "adjustment": {"weight_adjustment": _bounded_adjustment(scenario_key, 2), "cap_pct": 30},
                    "evidence_refs": [{"type": "scenario_key", "id": scenario_key}],
                    "vote_metadata": {"source": "coach_jury_fallback_v1"},
                }
            )
        return votes

    def resume_votes(
        self,
        *,
        prediction_config_id: str,
        discussion_id: str,
        agent_ids: list[str],
        resume_node_ids: list[str],
        event_types: list[str],
    ) -> list[dict[str, Any]]:
        votes = []
        for agent_index, agent_id in enumerate(agent_ids):
            target_index = agent_index % len(resume_node_ids)
            votes.append(
                {
                    "prediction_config_id": prediction_config_id,
                    "discussion_id": discussion_id,
                    "agent_id": agent_id,
                    "target_type": "resume_node",
                    "target_id": resume_node_ids[target_index],
                    "vote": "support",
                    "confidence": 68 + (agent_index % 20),
                    "reasoning": "预测配置、九场景、事件链和报告问答证据需要支持刷新回看和断点续跑。",
                    "adjustment": {"resume_strategy": "reuse" if "event" in event_types[target_index] else "recompute"},
                    "evidence_refs": [{"type": "workflow_event", "event_type": event_types[target_index]}],
                    "vote_metadata": {"source": "coach_jury_fallback_v1"},
                }
            )
        return votes

    def step3_review_summary(self, *, scenario_case_id: str, scenario_key: str) -> dict[str, Any]:
        support = 69 + (_stable_int(scenario_key, 0, 6))
        oppose = 15 + (_stable_int(scenario_key + "oppose", 0, 5))
        abstain = 100 - support - oppose
        return {
            "scenario_case_id": scenario_case_id,
            "review_type": "match_event_chain",
            "support_votes": support,
            "oppose_votes": oppose,
            "abstain_votes": abstain,
            "consensus_score": round(support / 100, 2),
            "confidence_delta": -0.04 if oppose >= 18 else 0.0,
            "adjustment_limits": {
                "team_xg_abs_max": 0.12,
                "wld_probability_pp_max": 7,
                "scenario_confidence_pp_max": 15,
            },
            "recommended_adjustments": [],
        }


def scenario_design_summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": "scenario_design_v2",
        "scenario_cases_count": len(cases),
        "space_groups_count": len({case["scenario_space"] for case in cases}),
        "coach_agents_count": 100,
        "consensus_score": 0.74,
        "disagreement_score": 0.26,
        "matrix": [
            {
                "scenario_key": case["scenario_key"],
                "home_state": case["home_state"],
                "away_state": case["away_state"],
                "scenario_name": case["scenario_name"],
                "scenario_space": case["scenario_space"],
                "initial_weight": case["initial_weight"],
                "final_weight": case["final_weight"],
                "key_drivers": case["key_drivers"],
                "risk_factors": case["risk_factors"],
            }
            for case in cases
        ],
    }


def resume_policy_summary(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "version": "resume_policy_v2",
        "last_resumable_event": "generate_nine_scenario_match_events",
        "nodes": [
            {
                "event_type": node["event_type"],
                "sequence": node["sequence"],
                "must_persist": node["must_persist"],
                "can_recompute": node["can_recompute"],
                "resume_strategy": node["resume_strategy"],
            }
            for node in nodes
        ],
    }


def coach_jury_summary(model_diagnostics: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": "coach_jury_v1",
        "coach_agents_count": 100,
        "discussion_types": ["scenario_design", "resume_policy"],
        "probability_adjustment_policy": "coach jury cannot directly overwrite scientific model probabilities",
        "max_scenario_weight_adjustment_pct": 30,
        "step3_adjustment_limits": {
            "team_xg_abs_max": 0.12,
            "wld_probability_pp_max": 7,
            "scenario_confidence_pp_max": 15,
        },
        "model_fit_status": model_diagnostics.get("fit_status"),
    }


def _role_label(role: str) -> str:
    return {
        "head_coach": "战术主教练",
        "attack": "进攻教练",
        "defense": "防守教练",
        "transition": "转换/压迫教练",
        "set_piece": "定位球教练",
        "goalkeeper": "门将/防线教练",
        "fitness": "体能/换人教练",
        "risk": "风险/裁判/天气教练",
    }[role]


def _preference(role: str, offset: int) -> str:
    variants = {
        "head_coach": ["稳态控球", "中低位压迫", "快速转换"],
        "attack": ["边路推进", "禁区触球", "二点球压制"],
        "defense": ["区域保护", "盯人优先", "防线紧凑"],
        "transition": ["高位反抢", "中场压迫", "快速落位"],
        "set_piece": ["角球设计", "任意球二次进攻", "防守定位球"],
        "goalkeeper": ["出击控制", "扑救稳定", "后场沟通"],
        "fitness": ["体能分配", "换人窗口", "阵容厚度"],
        "risk": ["裁判尺度", "天气影响", "VAR/点球"],
    }
    choices = variants[role]
    return choices[offset % len(choices)]


def _risk_tolerance(role: str, offset: int) -> str:
    if role == "risk":
        return "high"
    return ("low", "medium", "medium", "high")[offset % 4]


def _support_votes(seed: str) -> int:
    return 68 + _stable_int(seed + "support", 0, 9)


def _oppose_votes(seed: str) -> int:
    return 10 + _stable_int(seed + "oppose", 0, 7)


def _bounded_adjustment(seed: str, limit: int) -> int:
    return _stable_int(seed + "adjust", -limit, limit)


def _stable_int(text: str, low: int, high: int) -> int:
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    return low + (int(digest[:8], 16) % (high - low + 1))

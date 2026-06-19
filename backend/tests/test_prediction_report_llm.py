from __future__ import annotations

from typing import Any

from app.config import Config
from app.db.models import (
    PredictionConfigRecord,
    PredictionPlayerDatasetRecord,
    PredictionPlayerRecord,
    PredictionReportRecord,
    PredictionTeamMetadataRecord,
    PredictionTeamStrengthRecord,
    ProjectRecord,
    utc_now,
)
from app.db.session import get_session
from app.services.football_prediction import (
    PredictionPersistenceService,
    PredictionReportAssembler,
    _formation_slots,
    _lineup_widget_team,
)
from app.services.project_workflow import ProjectWorkflowService


class RecordingLLM:
    def __init__(self, response: str | None = None, *, fail: bool = False):
        self.response = response or "\n\n".join(
            f"## {title}\n"
            f"**一句话结论：** 第{index}章结论。\n\n"
            "| 指标 | 数据 |\n| --- | --- |\n| 示例 | 资料未明确 |\n\n"
            "**怎么读：** 普通球迷只需要看表格里的方向和风险。\n\n"
            f"**依据来自：** Step{min(index, 3)} 结构化证据。"
            for index, title in enumerate(PredictionReportAssembler.SECTION_TITLES, start=1)
        )
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages, temperature=0.7, max_tokens=4096, response_format=None):
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": response_format,
            }
        )
        if self.fail:
            raise RuntimeError("llm unavailable")
        return self.response


def test_lineup_widget_slots_follow_player_positions():
    starters = [
        {"position_primary": "FB"},
        {"position_primary": "CM"},
        {"position_primary": "ST"},
        {"position_primary": "ST"},
        {"position_primary": "ST"},
    ]

    assert _formation_slots("4-2-3-1", starters) == ["LB", "LDM", "ST", "CAM", "LAM"]

    starters_343 = [
        {"position_primary": "GK"},
        {"position_primary": "CB"},
        {"position_primary": "CB"},
        {"position_primary": "FB"},
        {"position_primary": "AM"},
        {"position_primary": "DM"},
        {"position_primary": "DM"},
        {"position_primary": "WG"},
        {"position_primary": "ST"},
        {"position_primary": "ST"},
        {"position_primary": "WG"},
    ]

    assert _formation_slots("3-4-3", starters_343) == [
        "GK",
        "CB",
        "LCB",
        "RCB",
        "LCM",
        "RCM",
        "LM",
        "LW",
        "ST",
        "RW",
        "LAM",
    ]


def _test_player(
    *,
    dataset_id: str,
    iso3: str,
    team_name: str,
    team_zh: str,
    index: int,
    position: str,
    role: str = "starter",
) -> dict[str, Any]:
    overall = 78 + (index % 7)
    player_id = f"ply_{dataset_id}_{iso3}_{index:02d}"
    return {
        "id": player_id,
        "team_iso3": iso3,
        "team_name": team_name,
        "name": f"{team_zh}球员{index}",
        "name_en": f"{team_name} Player {index}",
        "name_zh": f"{team_zh}球员{index}",
        "position_primary": position,
        "position_class": "GK" if position == "GK" else "DF" if position in {"LB", "RB", "CB"} else "FW" if position in {"LW", "RW", "ST"} else "MF",
        "age": 24 + (index % 8),
        "derived": {
            "overall": overall,
            "attack": 74 + (index % 10),
            "defense": 72 + (index % 8),
            "pace": 75 + (index % 9),
            "finishing": 73 + (index % 7),
            "passing": 76 + (index % 6),
            "stamina": 77 + (index % 5),
            "set_piece": 70 + (index % 8),
            "gk": 85 if position == "GK" else 0,
        },
        "ratings": {"rating": round(6.5 + (index % 5) * 0.1, 1)},
        "availability": {"status": "available"},
        "expected_role": role,
        "expected_minutes_share": 0.95 if role == "starter" else 0.25,
        "shirt_number": index,
        "club_fifa": "Test FC",
        "metadata": {"is_captain": index == 8},
    }


def _test_squad(dataset_id: str, iso3: str, team_name: str, team_zh: str) -> dict[str, Any]:
    positions = ["GK", "LB", "CB", "CB", "RB", "DM", "CM", "AM", "LW", "ST", "RW"]
    bench_positions = ["GK", "CB", "LB", "DM", "CM", "AM", "ST"]
    starters = [
        _test_player(
            dataset_id=dataset_id,
            iso3=iso3,
            team_name=team_name,
            team_zh=team_zh,
            index=index,
            position=position,
        )
        for index, position in enumerate(positions, start=1)
    ]
    bench = [
        _test_player(
            dataset_id=dataset_id,
            iso3=iso3,
            team_name=team_name,
            team_zh=team_zh,
            index=index,
            position=position,
            role="bench",
        )
        for index, position in enumerate(bench_positions, start=12)
    ]
    return {
        "team_iso3": iso3,
        "team_name": team_name,
        "team_fifa": team_name,
        "starter_ids": [player["id"] for player in starters],
        "players": [*starters, *bench],
    }


def _seed_widget_config(project_id: str = "proj_report_widgets") -> str:
    graph_id = f"{project_id}_graph"
    config_id = f"{project_id}_config"
    dataset_id = f"{project_id}_dataset"
    home_squad = _test_squad(dataset_id, "POR", "Portugal", "葡萄牙")
    away_squad = _test_squad(dataset_id, "COD", "Congo DR", "刚果（金）")
    model_input_snapshot = {
        "prediction_requirement": "预测葡萄牙 vs 刚果（金）的首发、阵型、战术和关键对位",
        "home_team": "葡萄牙",
        "away_team": "刚果（金）",
        "home_iso3": "POR",
        "away_iso3": "COD",
        "graph_id": graph_id,
        "squads": {"home": home_squad, "away": away_squad},
        "extracted": {
            "tactical_notes": [
                {"team_iso3": "POR", "note": "葡萄牙预计使用 4-2-3-1，中场组织和边路推进是主要思路。"},
                {"team_iso3": "COD", "note": "刚果（金）预计使用 4-3-3，依靠边路速度和反击。"},
            ],
            "key_narratives": ["葡萄牙纸面实力和阵容深度更好。"],
        },
        "fitted_artifacts": {
            "model_name": "dixon_coles_decay",
            "model_version": "v2",
            "fit_status": "fitted",
            "data_sufficiency": "sufficient",
        },
        "scientific_model_diagnostics": {
            "model_name": "dixon_coles_decay",
            "model_version": "v2",
            "fit_status": "fitted",
            "data_sufficiency": "sufficient",
        },
    }
    with get_session() as session:
        session.add(
            ProjectRecord(
                project_id=project_id,
                name="Widget Report Test",
                status="graph_completed",
                graph_id=graph_id,
                simulation_requirement=model_input_snapshot["prediction_requirement"],
                project_metadata={},
            )
        )
        session.add(
            PredictionPlayerDatasetRecord(
                dataset_id=dataset_id,
                source_label="test_dataset",
                scope_label="fifa_world_cup_2026_squads",
                ratings_schema={"derived_fields": ["overall", "attack", "defense", "pace", "finishing", "passing", "set_piece", "gk"]},
                teams_count=2,
                players_count=len(home_squad["players"]) + len(away_squad["players"]),
                dataset_metadata={},
            )
        )
        for iso3, team_fifa, team_zh, formation, coach, style in (
            ("POR", "Portugal", "葡萄牙", "4-2-3-1", "Roberto Martinez", {"attacking_plan": "中路组织 + 边路推进", "defensive_plan": "前场压迫后保护边后卫身后"}),
            ("COD", "Congo DR", "刚果（金）", "4-3-3", "Sebastien Desabre", {"attacking_plan": "边路速度 + 反击", "defensive_plan": "中路拦截和二点球"}),
        ):
            session.add(
                PredictionTeamMetadataRecord(
                    id=f"tm_{dataset_id}_{iso3}",
                    dataset_id=dataset_id,
                    team_fifa=team_fifa,
                    team_iso3=iso3,
                    team_zh=team_zh,
                    head_coach=coach,
                    formation_primary=formation,
                    tactical_style=style,
                )
            )
        for player in [*home_squad["players"], *away_squad["players"]]:
            session.add(
                PredictionPlayerRecord(
                    id=player["id"],
                    dataset_id=dataset_id,
                    team_name=player["team_name"],
                    team_iso3=player["team_iso3"],
                    player_external_id=player["id"],
                    full_name=player["name"],
                    full_name_en=player["name_en"],
                    full_name_alt=[],
                    position_primary=player["position_primary"],
                    position_secondary=[],
                    age=player["age"],
                    foot="R",
                    height_cm=180,
                    ratings=player["ratings"],
                    derived=player["derived"],
                    availability=player["availability"],
                    expected_role=player["expected_role"],
                    expected_minutes_share=player["expected_minutes_share"],
                    shirt_number=player["shirt_number"],
                    position_class=player["position_class"],
                    caps_intl=10,
                    goals_intl=2,
                    club_fifa=player["club_fifa"],
                    player_metadata=player["metadata"],
                )
            )
        session.add(
            PredictionConfigRecord(
                prediction_config_id=config_id,
                project_id=project_id,
                graph_id=graph_id,
                match_name="葡萄牙 vs 刚果（金）",
                home_team="葡萄牙",
                away_team="刚果（金）",
                status="ready",
                current_phase="ready",
                progress_percent=100,
                model_name="dixon_coles_decay",
                model_version="v2",
                fit_status="fitted",
                data_sufficiency="sufficient",
                source_document_ids=[],
                graph_snapshot={"entities_count": 12, "relationships_count": 18},
                model_input_snapshot=model_input_snapshot,
                scenario_design_summary={},
                resume_policy_summary={},
                coach_jury_summary={},
                player_dataset_id=dataset_id,
                llm_budget_profile={
                    "profile_key": "custom",
                    "coach_panel_roles": [],
                    "coach_deliberation_rounds": 1,
                    "enable_llm_data_extraction": False,
                    "narrative_polish_count": 0,
                    "analyst_note_groups": [],
                    "coach_review_roles": [],
                    "n_sims": 500,
                    "enable_statsbomb": False,
                    "hard_cap_calls": 1,
                },
                progress_messages=[],
                completed_at=utc_now(),
                config_metadata={"artifact_status": "active"},
            )
        )
        for role, team, iso3, attack, defense, possession, transition in (
            ("home", "葡萄牙", "POR", 82, 78, 81, 77),
            ("away", "刚果（金）", "COD", 70, 68, 66, 74),
        ):
            session.add(
                PredictionTeamStrengthRecord(
                    prediction_config_id=config_id,
                    prediction_run_id=None,
                    team_role=role,
                    team_name=team,
                    attack_rating=attack,
                    defense_rating=defense,
                    possession_rating=possession,
                    transition_rating=transition,
                    set_piece_rating=72,
                    discipline_rating=69,
                    fitness_rating=73,
                    goalkeeper_rating=75,
                    home_away_adjustment=0,
                    injury_adjustment=0,
                    form_adjustment=0,
                    evidence=[],
                    confidence=78,
                    strength_metadata={"team_iso3": iso3},
                )
            )
    ProjectWorkflowService().register_graph(project_id, graph_id)
    ProjectWorkflowService().register_config(project_id, config_id)
    return config_id


def test_prediction_report_uses_dedicated_llm_config(monkeypatch):
    monkeypatch.setattr(Config, "PREDICTION_REPORT_LLM_MODEL_NAME", "football-report-model")
    monkeypatch.setattr(Config, "PREDICTION_REPORT_LLM_BASE_URL", "https://report-llm.example/v1")
    monkeypatch.setattr(Config, "PREDICTION_REPORT_LLM_API_KEY", "report-key")
    monkeypatch.setattr(Config, "PREDICTION_REPORT_LLM_CHAT_PROTOCOL", "openai")

    captured = {}

    class FakeLLMClient(RecordingLLM):
        def __init__(self, *, api_key=None, base_url=None, model=None, chat_protocol=None):
            super().__init__()
            captured.update(
                {
                    "api_key": api_key,
                    "base_url": base_url,
                    "model": model,
                    "chat_protocol": chat_protocol,
                }
            )

    monkeypatch.setattr("app.services.football_prediction.LLMClient", FakeLLMClient)

    llm = PredictionReportAssembler()._create_llm_client()

    assert isinstance(llm, RecordingLLM)
    assert captured == {
        "api_key": "report-key",
        "base_url": "https://report-llm.example/v1",
        "model": "football-report-model",
        "chat_protocol": "openai",
    }


def test_prediction_report_llm_config_falls_back_to_global_llm(monkeypatch):
    monkeypatch.setattr(Config, "PREDICTION_REPORT_LLM_MODEL_NAME", "")
    monkeypatch.setattr(Config, "PREDICTION_REPORT_LLM_BASE_URL", "")
    monkeypatch.setattr(Config, "PREDICTION_REPORT_LLM_API_KEY", "")
    monkeypatch.setattr(Config, "PREDICTION_REPORT_LLM_CHAT_PROTOCOL", "")
    monkeypatch.setattr(Config, "LLM_MODEL_NAME", "global-model")
    monkeypatch.setattr(Config, "LLM_BASE_URL", "https://global.example/v1")
    monkeypatch.setattr(Config, "LLM_API_KEY", "global-key")
    monkeypatch.setattr(Config, "LLM_CHAT_PROTOCOL", "openai")

    captured = {}

    class FakeLLMClient(RecordingLLM):
        def __init__(self, *, api_key=None, base_url=None, model=None, chat_protocol=None):
            super().__init__()
            captured.update(
                {
                    "api_key": api_key,
                    "base_url": base_url,
                    "model": model,
                    "chat_protocol": chat_protocol,
                }
            )

    monkeypatch.setattr("app.services.football_prediction.LLMClient", FakeLLMClient)

    PredictionReportAssembler()._create_llm_client()

    assert captured == {
        "api_key": "global-key",
        "base_url": "https://global.example/v1",
        "model": "global-model",
        "chat_protocol": "openai",
    }


def test_prediction_report_reads_step_context_and_writes_reader_friendly_sections(postgres_db):
    del postgres_db
    status = PredictionPersistenceService().create_completed_prediction(
        project_id="proj_report_reader",
        graph_id="graph_report_reader",
        simulation_requirement="预测阿根廷 vs 法国的比分、阵型、首发、VAR和关键风险",
        home_team="阿根廷",
        away_team="法国",
    )
    llm = RecordingLLM()

    report = PredictionReportAssembler(llm_client=llm).create_report(status["prediction_run_id"])

    with get_session() as session:
        record = session.get(PredictionReportRecord, report["report_id"])
        markdown = record.markdown_content
        section_titles = [section.title for section in record.sections]
        metadata = record.report_metadata

    assert section_titles == [
        "比赛结论摘要",
        "双方基本面与图谱证据",
        "战术、阵型与预计首发",
        "胜平负与比分预测",
        "关键比赛事件剧本",
        "风险、不确定性与可信度说明",
    ]
    for phrase in ("一句话结论", "怎么读", "依据来自", "| 指标 |", "图谱证据", "教练讨论", "阵型", "预计首发", "比分", "事件", "风险"):
        assert phrase in markdown
    for phrase in ("Step1", "Step2", "Step3"):
        assert phrase in markdown
    assert "dataset_id:" not in markdown
    assert "配置ID" not in markdown
    assert metadata["generation_mode"] == "llm"
    assert metadata["source"] == "prediction_report_assembler_v2"
    assert metadata["evidence_package"]["match"]["prediction_run_id"] == status["prediction_run_id"]
    assert llm.calls
    prompt = "\n".join(message["content"] for message in llm.calls[0]["messages"])
    assert "数据看板式 Markdown" in prompt
    assert "至少一个 Markdown 表格或文本可视化块" in prompt


def test_prediction_report_keeps_summary_and_first_section_score_consistent(postgres_db):
    del postgres_db
    status = PredictionPersistenceService().create_completed_prediction(
        project_id="proj_report_consistent_score",
        graph_id="graph_report_consistent_score",
        simulation_requirement="预测瑞士 vs 波黑的比分、方向和关键风险",
        home_team="瑞士",
        away_team="波黑",
    )
    wrong_first_section = "\n\n".join(
        [
            "## 比赛结论摘要\n"
            "**一句话结论：** 瑞士最可能以 2-0 击败波黑。\n\n"
            "| 预测维度 | 结果 |\n| --- | --- |\n| 预测方向 | **瑞士胜** |\n| 最可能比分 | **2-0** |\n| 置信度 | **中高** |\n\n"
            "**怎么读：** 先看胜平负方向和比分。\n\n"
            "**依据来自：** Step1 / Step2 / Step3。",
            *(
                f"## {title}\n"
                f"**一句话结论：** 第{index}章结论。\n\n"
                "| 指标 | 数据 |\n| --- | --- |\n| 示例 | 资料未明确 |\n\n"
                "**怎么读：** 看表格。\n\n"
                "**依据来自：** Step1 / Step2 / Step3。"
                for index, title in enumerate(PredictionReportAssembler.SECTION_TITLES[1:], start=2)
            ),
        ]
    )

    report = PredictionReportAssembler(llm_client=RecordingLLM(wrong_first_section)).create_report(
        status["prediction_run_id"]
    )

    with get_session() as session:
        record = session.get(PredictionReportRecord, report["report_id"])
        score = (record.report_metadata["evidence_package"]["step3"]["scoreline_summary"] or {})["most_likely_score"]
        first_section = next(section for section in record.sections if section.title == "比赛结论摘要")

    assert f"最可能比分 {score}" in record.summary
    assert "取分方向" not in record.summary
    assert f"| 最可能比分 | {score} |" in first_section.content
    assert "取分方向" not in first_section.content
    assert "| 最可能比分 | **2-0** |" not in first_section.content
    assert "瑞士最可能以 2-0 击败波黑" not in first_section.content


def test_prediction_report_persists_lineup_tactics_matchup_widgets(postgres_db):
    del postgres_db
    config_id = _seed_widget_config()
    status = PredictionPersistenceService().create_completed_prediction_from_config(
        prediction_config_id=config_id,
    )

    report = PredictionReportAssembler(llm_client=RecordingLLM(fail=True)).create_report(
        status["prediction_run_id"]
    )

    with get_session() as session:
        record = session.get(PredictionReportRecord, report["report_id"])
        metadata = record.report_metadata
        tactics_section = next(section for section in record.sections if section.title == "战术、阵型与预计首发")

    widgets = metadata["widgets"]
    evidence = metadata["evidence_package"]
    lineup = widgets["lineup_widget"]
    tactics = widgets["tactics_widget"]
    matchups = widgets["matchup_widget"]

    assert evidence["widgets"] == widgets
    assert len(lineup["home"]["players"]) == 11
    assert len(lineup["away"]["players"]) == 11
    assert lineup["home"]["formation"]
    assert lineup["home"]["players"][0]["pitch_slot"]
    assert lineup["home"]["players"][0]["name"] in tactics_section.content
    assert lineup["home"]["players"][0]["name"] in metadata["markdown_widgets"]["lineup_table"]
    assert "首发名单不完整" not in lineup["home"]["notes"]
    assert tactics["home"]["base_shape"]
    assert "attacking_plan" in tactics["home"]
    assert matchups
    assert {"zone", "home_player", "away_player", "why_it_matters", "advantage"}.issubset(matchups[0])
    assert "**阵型预测摘要：**" in tactics_section.content
    assert "**首发名单表：**" in tactics_section.content
    assert "**战术判断表：**" in tactics_section.content
    assert "**关键对位表：**" in tactics_section.content
    assert "| 球队 | 预计阵型 | 进攻重点 | 防守重点 | 可信度 |" in tactics_section.content
    assert "| 球队 | 号码 | 球员 | 位置 | 角色 | 状态 | 评分/能力 |" in tactics_section.content


def test_lineup_widget_backfills_partial_starter_ids_to_full_eleven():
    squad = _test_squad("partial_lineup_dataset", "SUI", "Switzerland", "瑞士")
    squad["starter_ids"] = squad["starter_ids"][:7]

    widget = _lineup_widget_team(
        role="home",
        team_name="瑞士",
        squad=squad,
        formation="3-4-2-1",
        metadata={},
        strength={},
    )

    assert len(widget["players"]) == 11
    assert widget["lineup_source"] == "starter_ids_fill"
    assert "首发名单不完整" not in widget["notes"]
    assert "低置信度" in widget["notes"]
    assert len(widget["bench"]) == len(squad["players"]) - 11


def test_prediction_report_does_not_fabricate_lineup_when_squads_missing(postgres_db):
    del postgres_db
    status = PredictionPersistenceService().create_completed_prediction(
        project_id="proj_report_no_squads",
        graph_id="graph_report_no_squads",
        simulation_requirement="预测巴西 vs 德国的首发和战术",
        home_team="巴西",
        away_team="德国",
    )

    report = PredictionReportAssembler(llm_client=RecordingLLM(fail=True)).create_report(status["prediction_run_id"])

    with get_session() as session:
        record = session.get(PredictionReportRecord, report["report_id"])
        widgets = record.report_metadata["widgets"]
        tactics_section = next(section for section in record.sections if section.title == "战术、阵型与预计首发")

    lineup = widgets["lineup_widget"]
    assert lineup["home"]["players"] == []
    assert lineup["away"]["players"] == []
    assert "缺少 Step2 球员名册" in lineup["home"]["notes"]
    assert "巴西1号" not in tactics_section.content
    assert "| 资料未明确 |" in tactics_section.content


def test_prediction_report_falls_back_to_readable_template_when_llm_fails(postgres_db):
    del postgres_db
    status = PredictionPersistenceService().create_completed_prediction(
        project_id="proj_report_fallback",
        graph_id="graph_report_fallback",
        simulation_requirement="预测巴西 vs 德国的胜平负、比分、事件和伤停风险",
        home_team="巴西",
        away_team="德国",
    )

    report = PredictionReportAssembler(llm_client=RecordingLLM(fail=True)).create_report(status["prediction_run_id"])

    with get_session() as session:
        record = session.get(PredictionReportRecord, report["report_id"])
        markdown = record.markdown_content
        metadata = record.report_metadata

    assert metadata["generation_mode"] == "template_fallback"
    assert "llm unavailable" in metadata["llm_error"]
    assert "## 01 比赛结论摘要" in markdown
    assert "一句话结论" in markdown
    assert "怎么读" in markdown
    assert "依据来自" in markdown
    assert "| 判断 | 结果 | 关键证据 |" in markdown
    assert "████" in markdown
    assert "| 时间段 | 触发条件 | 可能事件 | 比分影响 |" in markdown
    assert "| 风险 | 当前信号 | 对比分方向的影响 | 应对读法 |" in markdown
    assert "Step1" in markdown
    assert "Step2" in markdown
    assert "Step3" in markdown
    assert "预测不是确定结果" in markdown
    for internal_phrase in ("Step01", "Step03", "Monte Carlo", "- -"):
        assert internal_phrase not in markdown

    answer = PredictionReportAssembler(llm_client=RecordingLLM(fail=True)).answer_question(
        report_id=report["report_id"],
        prediction_run_id=status["prediction_run_id"],
        message="为什么是这个比分，主要风险是什么？",
    )

    assert "Step4 报告" in answer["response"]
    assert "最可能比分" in answer["response"]
    assert any(source["type"] == "report_sections" for source in answer["sources"])
    for internal_phrase in ("九场景矩阵", "权重不覆盖", "配置", "持久化", "reuse"):
        assert internal_phrase not in answer["response"]


def test_prediction_report_parser_accepts_llm_markdown_with_rule_separators():
    response = "\n\n---\n\n".join(
        f"## {title}\n**一句话结论：** 第{index}章结论。\n\n**为什么：** 第{index}章原因。"
        for index, title in enumerate(PredictionReportAssembler.SECTION_TITLES, start=1)
    )

    sections = PredictionReportAssembler()._parse_sections(response)

    assert [section["title"] for section in sections] == list(PredictionReportAssembler.SECTION_TITLES)
    assert all("一句话结论" in section["content"] for section in sections)


def test_prediction_report_answer_uses_llm_with_report_context(postgres_db):
    del postgres_db
    status = PredictionPersistenceService().create_completed_prediction(
        project_id="proj_report_qa_context",
        graph_id="graph_report_qa_context",
        simulation_requirement="预测意大利 vs 克罗地亚的阵型、首发、比分和风险",
        home_team="意大利",
        away_team="克罗地亚",
    )
    report = PredictionReportAssembler(llm_client=RecordingLLM(fail=True)).create_report(
        status["prediction_run_id"]
    )
    qa_llm = RecordingLLM(response="报告上下文回答：阵型与预计首发会影响边路推进和中场控制。")

    answer = PredictionReportAssembler(llm_client=qa_llm).answer_question(
        report_id=report["report_id"],
        prediction_run_id=status["prediction_run_id"],
        message="阵型和预计首发会怎么影响比赛？",
        chat_history=[
            {"role": "user", "content": "上一问：为什么最可能是这个比分？"},
            {"role": "assistant", "content": "上一答：比分来自报告中的概率分布。"},
        ],
    )

    assert answer["response"] == "报告上下文回答：阵型与预计首发会影响边路推进和中场控制。"
    assert answer["metadata"]["answer_mode"] == "llm"
    assert qa_llm.calls
    prompt = "\n".join(message["content"] for message in qa_llm.calls[0]["messages"])
    assert "已生成报告内容" in prompt
    assert "战术、阵型与预计首发" in prompt
    assert "阵型和预计首发会怎么影响比赛？" in prompt
    assert "上一问：为什么最可能是这个比分？" in prompt
    assert any(source["type"] == "report_sections" for source in answer["sources"])


def test_prediction_report_can_generate_from_project_latest_run(postgres_db):
    del postgres_db
    status = PredictionPersistenceService().create_completed_prediction(
        project_id="proj_report_latest",
        graph_id="graph_report_latest",
        simulation_requirement="预测荷兰 vs 日本的比分和风险",
        home_team="荷兰",
        away_team="日本",
    )

    report = PredictionReportAssembler(llm_client=RecordingLLM(fail=True)).create_report_for_project(
        "proj_report_latest"
    )

    with get_session() as session:
        record = session.get(PredictionReportRecord, report["report_id"])
        metadata = record.report_metadata

    assert report["prediction_run_id"] == status["prediction_run_id"]
    assert metadata["evidence_package"]["match"]["project_id"] == "proj_report_latest"
    assert metadata["evidence_package"]["match"]["prediction_run_id"] == status["prediction_run_id"]

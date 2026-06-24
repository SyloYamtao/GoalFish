from pathlib import Path

from app.services.football_data_extractor import (
    ExtractedMatchContext,
    FootballDataExtractor,
)
from app.services.llm_budget import LLMCallLedger, LLMBudgetProfile


class FakeLLM:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def chat_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class FailingLLM:
    def chat_json(self, **kwargs):
        raise RuntimeError("offline")


def test_extract_with_llm():
    req = "巴西 vs 阿根廷 世界杯半决赛，内马尔伤，梅西状态火热"
    ledger = LLMCallLedger(config_id="c1", budget=LLMBudgetProfile.MIDDLE)
    extractor = FootballDataExtractor(
        llm_client=FakeLLM(
            {
                "home_iso3": "BRA",
                "away_iso3": "ARG",
                "home_name_zh": "巴西",
                "away_name_zh": "阿根廷",
                "competition_meta": {
                    "tournament": "世界杯",
                    "stage": "semi_final",
                    "knockout": True,
                    "neutral_venue": True,
                    "host_country_iso3": None,
                },
                "key_narratives": ["内马尔伤", "梅西状态火热"],
                "injury_reports": [
                    {"player": "内马尔", "team_iso3": "BRA", "status": "injured"}
                ],
                "tactical_notes": [
                    {"team_iso3": "ARG", "note": "围绕梅西推进"}
                ],
            }
        )
    )

    ctx = extractor.extract(
        prediction_requirement=req,
        graph_id="g1",
        llm_ledger=ledger,
    )

    assert isinstance(ctx, ExtractedMatchContext)
    assert ctx.home_iso3 == "BRA"
    assert ctx.away_iso3 == "ARG"
    assert ctx.competition_meta["knockout"] is True
    assert ctx.competition_meta["stage"] == "semi_final"
    assert ctx.extracted_by == "llm"
    assert ledger.summary()["by_role"]["data_extractor"]["calls"] == 1


def test_group_stage_llm_knockout_flag_is_overridden():
    ledger = LLMCallLedger(config_id="c1", budget=LLMBudgetProfile.MIDDLE)
    extractor = FootballDataExtractor(
        llm_client=FakeLLM(
            {
                "home_iso3": "CAN",
                "away_iso3": "BIH",
                "home_name_zh": "加拿大",
                "away_name_zh": "波黑",
                "competition_meta": {
                    "tournament": "世界杯",
                    "stage": "group",
                    "knockout": True,
                    "neutral_venue": True,
                    "host_country_iso3": "CAN",
                },
                "key_narratives": [],
                "injury_reports": [],
                "tactical_notes": [],
            }
        )
    )

    ctx = extractor.extract(
        prediction_requirement="加拿大 vs 波黑 2026 FIFA World Cup 小组赛",
        graph_id="g1",
        llm_ledger=ledger,
    )

    assert ctx.competition_meta["stage"] == "group"
    assert ctx.competition_meta["knockout"] is False
    assert ctx.competition_meta["host_country_iso3"] == "CAN"


def test_regex_fallback_infers_2026_host_country_from_mexico_venue():
    ledger = LLMCallLedger(config_id="c1", budget=LLMBudgetProfile.LOW_NO_LLM)
    extractor = FootballDataExtractor()
    report_text = """
# 墨西哥vs韩国赛前信息报告
- 比赛双方：墨西哥 vs 韩国。
- 比赛地点：Guadalajara Stadium，官方常用场馆名对应 Estadio Akron，位于 Guadalajara 都市圈。
- 中立/主客属性：名义上是世界杯中立场，实际观众结构与地缘支持更偏向墨西哥。
"""

    ctx = extractor.extract(
        prediction_requirement=report_text,
        graph_id="g1",
        llm_ledger=ledger,
    )

    assert ctx.home_iso3 == "MEX"
    assert ctx.away_iso3 == "KOR"
    assert ctx.competition_meta["neutral_venue"] is True
    assert ctx.competition_meta["host_country_iso3"] == "MEX"


def test_regex_fallback_infers_2026_host_country_from_canada_venue():
    ledger = LLMCallLedger(config_id="c1", budget=LLMBudgetProfile.LOW_NO_LLM)
    extractor = FootballDataExtractor()

    ctx = extractor.extract(
        prediction_requirement="加拿大 vs 波黑 2026 FIFA World Cup 小组赛，比赛地点 Toronto Stadium，世界杯中立场",
        graph_id="g1",
        llm_ledger=ledger,
    )

    assert ctx.home_iso3 == "CAN"
    assert ctx.away_iso3 == "BIH"
    assert ctx.competition_meta["neutral_venue"] is True
    assert ctx.competition_meta["host_country_iso3"] == "CAN"


def test_extract_regex_fallback_when_budget_zero():
    ledger = LLMCallLedger(config_id="c1", budget=LLMBudgetProfile.LOW_NO_LLM)
    extractor = FootballDataExtractor()

    ctx = extractor.extract(
        req="Brazil vs Argentina",
        graph_id="g1",
        llm_ledger=ledger,
    )

    assert ctx.extracted_by == "regex_fallback"
    assert ctx.home_iso3 == "BRA"
    assert ctx.away_iso3 == "ARG"
    assert ctx.competition_meta["knockout"] is False
    assert ledger.summary()["total_calls"] == 0


def test_feature_flag_disables_llm_extraction(monkeypatch):
    monkeypatch.setenv("GOALFISH_USE_FOOTBALL_DATA_EXTRACTOR", "false")
    ledger = LLMCallLedger(config_id="c1", budget=LLMBudgetProfile.MIDDLE)
    extractor = FootballDataExtractor(
        llm_client=FakeLLM(
            {
                "home_iso3": "XXX",
                "away_iso3": "YYY",
                "competition_meta": {"knockout": True},
            }
        )
    )

    ctx = extractor.extract(
        prediction_requirement="Brazil vs Argentina",
        graph_id="g1",
        llm_ledger=ledger,
    )

    assert ctx.extracted_by == "regex_fallback"
    assert ctx.home_iso3 == "BRA"
    assert ctx.away_iso3 == "ARG"
    assert ledger.summary()["total_calls"] == 0


def test_regex_fallback_extracts_chinese_stage_and_injuries():
    ledger = LLMCallLedger(config_id="c1", budget=LLMBudgetProfile.LOW)
    extractor = FootballDataExtractor()

    ctx = extractor.extract(
        prediction_requirement="巴西 vs 阿根廷 世界杯半决赛，内马尔因伤缺席，梅西状态火热",
        graph_id="g1",
        llm_ledger=ledger,
    )

    assert ctx.home_iso3 == "BRA"
    assert ctx.away_iso3 == "ARG"
    assert ctx.home_name_zh == "巴西"
    assert ctx.away_name_zh == "阿根廷"
    assert ctx.competition_meta["tournament"] == "世界杯"
    assert ctx.competition_meta["stage"] == "semi_final"
    assert ctx.competition_meta["knockout"] is True
    assert ctx.injury_reports == [
        {
            "player": "内马尔",
            "team_iso3": "BRA",
            "status": "injured",
            "evidence_span": "内马尔因伤缺席",
        }
    ]


def test_regex_fallback_prefers_current_group_stage_over_later_knockout_context():
    ledger = LLMCallLedger(config_id="c1", budget=LLMBudgetProfile.LOW_NO_LLM)
    extractor = FootballDataExtractor()
    report_text = """
# 葡萄牙vs民主刚果赛前信息报告
- 赛事阶段：2026 FIFA 世界杯 K 组小组赛，Match 23。
- 中立场属性：世界杯中立赛场；葡萄牙和民主刚果均非东道主。
后续淘汰赛预测里可能出现四分之一决赛和八强路径讨论。
"""

    ctx = extractor.extract(
        prediction_requirement=report_text,
        graph_id="g1",
        llm_ledger=ledger,
    )

    assert ctx.home_iso3 == "POR"
    assert ctx.away_iso3 == "COD"
    assert ctx.competition_meta["stage"] == "group"
    assert ctx.competition_meta["knockout"] is False


def test_regex_fallback_resolves_chinese_bosnia_alias_from_report_title():
    ledger = LLMCallLedger(config_id="c1", budget=LLMBudgetProfile.LOW_NO_LLM)
    extractor = FootballDataExtractor()
    report_text = """
=== 2026世界杯加拿大vs波黑赛前信息报告.md ===
# 加拿大 vs 波黑 2026 世界杯小组赛赛前信息报告
- 比赛：加拿大 vs 波黑
"""

    ctx = extractor.extract(
        prediction_requirement=report_text,
        graph_id="g1",
        llm_ledger=ledger,
    )

    assert ctx.home_iso3 == "CAN"
    assert ctx.away_iso3 == "BIH"
    assert ctx.home_name_zh == "加拿大"
    assert ctx.away_name_zh == "波黑"


def test_regex_fallback_ignores_markdown_filename_suffix_for_match_pair():
    ledger = LLMCallLedger(config_id="c1", budget=LLMBudgetProfile.LOW_NO_LLM)
    extractor = FootballDataExtractor()
    report_text = """
=== 瑞典vs突尼斯赛前信息报告.md ===
# 瑞典 vs 突尼斯 赛前信息报告
- 比赛双方：瑞典 vs 突尼斯。
"""

    ctx = extractor.extract(
        prediction_requirement=report_text,
        graph_id="g1",
        llm_ledger=ledger,
    )

    assert ctx.home_iso3 == "SWE"
    assert ctx.away_iso3 == "TUN"
    assert ctx.home_name_zh == "瑞典"
    assert ctx.away_name_zh == "突尼斯"


def test_regex_fallback_prefers_uploaded_body_target_match_over_prior_round_context():
    ledger = LLMCallLedger(config_id="c1", budget=LLMBudgetProfile.LOW_NO_LLM)
    extractor = FootballDataExtractor()
    report_text = (
        Path(__file__).resolve().parents[2]
        / "docs/sample/research/20260621/04.Tunisia_vs_Japan_Pre-Match_Report_EN.md"
    ).read_text(encoding="utf-8")

    ctx = extractor.extract(
        prediction_requirement=report_text,
        graph_id="g1",
        llm_ledger=ledger,
    )

    assert ctx.home_iso3 == "TUN"
    assert ctx.away_iso3 == "JPN"
    assert ctx.home_name_zh == "突尼斯"
    assert ctx.away_name_zh == "日本"


def test_llm_failure_records_warning_and_falls_back_to_regex():
    ledger = LLMCallLedger(config_id="c1", budget=LLMBudgetProfile.MIDDLE)
    extractor = FootballDataExtractor(llm_client=FailingLLM())

    ctx = extractor.extract(
        prediction_requirement="Brazil vs Argentina World Cup semi-final, Neymar injured",
        graph_id="g1",
        llm_ledger=ledger,
    )

    assert ctx.extracted_by == "regex_fallback"
    assert ctx.home_iso3 == "BRA"
    assert ctx.away_iso3 == "ARG"
    assert ledger.summary()["failures"] == [
        {
            "role": "data_extractor",
            "reason": "llm_extraction_failed",
            "fallback": "regex_fallback",
            "error": "offline",
        }
    ]

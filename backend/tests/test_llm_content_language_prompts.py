from __future__ import annotations

from app.services.content_language import CONTENT_LANGUAGE_INSTRUCTION_MARKER
from app.services.football_data_extractor import FootballDataExtractor
from app.services.football_prediction import PredictionReportAssembler
from app.services.ontology_generator import OntologyGenerator
from app.utils.locale import set_locale


class CapturingJsonLLM:
    def __init__(self):
        self.messages = []

    def chat_json(self, *, messages, temperature=0.1, max_tokens=4096):
        self.messages = messages
        return {"entity_types": [], "edge_types": [], "analysis_summary": ""}


def test_ontology_prompt_uses_ui_locale_for_content_language():
    llm = CapturingJsonLLM()
    generator = OntologyGenerator(llm_client=llm)

    generator.generate(
        ["日本代表はサイド攻撃と中盤の連動が強みです。"],
        "この試合を予測してください。",
        ui_locale="zh",
    )

    prompt = "\n".join(message["content"] for message in llm.messages)
    assert CONTENT_LANGUAGE_INSTRUCTION_MARKER in prompt
    assert "中文" in prompt


def test_step2_extractor_prompt_contains_content_language_instruction():
    set_locale("en")
    try:
        messages = FootballDataExtractor()._build_prompt(
            prediction_requirement="Japan are likely to press high against Tunisia.",
            graph_id="graph_test",
        )

        prompt = "\n".join(message["content"] for message in messages)
        assert CONTENT_LANGUAGE_INSTRUCTION_MARKER in prompt
        assert "英文" in prompt
    finally:
        set_locale("en")


def test_prediction_report_prompt_contains_content_language_instruction():
    set_locale("zh")
    try:
        context = {
            "match": {
                "project_id": None,
                "requirement": "日本代表はサイド攻撃を重視します。",
            },
            "step1": {"project": {}},
        }

        messages = PredictionReportAssembler()._report_messages(context)
        prompt = "\n".join(message["content"] for message in messages)
        assert CONTENT_LANGUAGE_INSTRUCTION_MARKER in prompt
        assert "中文" in prompt
    finally:
        set_locale("en")

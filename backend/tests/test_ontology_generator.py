from app.services.ontology_generator import OntologyGenerator


class FakeLLMClient:
    def __init__(self, result):
        self.result = result
        self.messages = None

    def chat_json(self, messages, temperature, max_tokens):
        self.messages = messages
        return self.result


def test_ontology_prompt_prefers_chinese_attribute_names():
    fake_llm = FakeLLMClient({
        "entity_types": [],
        "edge_types": [],
        "analysis_summary": "测试摘要",
    })

    ontology = OntologyGenerator(fake_llm).generate(["测试文档"], "测试需求")

    system_prompt = fake_llm.messages[0]["content"]
    assert "display_name" in system_prompt
    assert "属性名优先使用中文" in system_prompt
    assert "Attribute names MUST be in English snake_case" not in system_prompt

    person = next(entity for entity in ontology["entity_types"] if entity["name"] == "Person")
    organization = next(entity for entity in ontology["entity_types"] if entity["name"] == "Organization")

    assert person["display_name"] == "个人"
    assert organization["display_name"] == "组织"
    assert [attr["name"] for attr in person["attributes"]] == ["全名", "角色"]
    assert [attr["name"] for attr in organization["attributes"]] == ["组织名称", "组织类型"]


def test_ontology_validation_preserves_chinese_attribute_names():
    raw = {
        "entity_types": [
            {
                "name": "Person",
                "display_name": "自然人",
                "description": "Any person.",
                "attributes": [
                    {"name": "影响力 分级", "type": "text", "description": "影响力分级"},
                    {"name": "name", "type": "text", "description": "保留字段"},
                ],
            },
            {
                "name": "Organization",
                "display_name": "组织机构",
                "description": "Any organization.",
                "attributes": [
                    {"name": "组织名称", "type": "text", "description": "组织名称"},
                ],
            },
        ],
        "edge_types": [
            {
                "name": "REPORTS_ON",
                "display_name": "报道",
                "description": "Reports on something.",
                "source_targets": [{"source": "Organization", "target": "Person"}],
                "attributes": [],
            }
        ],
    }

    ontology = OntologyGenerator(FakeLLMClient(raw)).generate(["测试文档"], "测试需求")
    person = next(entity for entity in ontology["entity_types"] if entity["name"] == "Person")
    edge = ontology["edge_types"][0]

    assert person["display_name"] == "自然人"
    assert [attr["name"] for attr in person["attributes"]] == ["影响力_分级", "entity_name"]
    assert edge["name"] == "REPORTS_ON"
    assert edge["display_name"] == "报道"


def test_football_match_ontology_prompt_uses_football_domain_rules():
    fake_llm = FakeLLMClient({
        "entity_types": [
            {"name": "FootballTeam", "display_name": "球队", "description": "A men's football team.", "attributes": []},
            {"name": "Player", "display_name": "球员", "description": "A football player.", "attributes": []},
            {"name": "Coach", "display_name": "教练", "description": "A football coach.", "attributes": []},
            {"name": "Match", "display_name": "比赛", "description": "A football match.", "attributes": []},
            {"name": "Competition", "display_name": "赛事", "description": "A football competition.", "attributes": []},
            {"name": "Venue", "display_name": "比赛场地", "description": "A match venue.", "attributes": []},
            {"name": "TacticalFormation", "display_name": "战术阵型", "description": "A tactical setup.", "attributes": []},
            {"name": "Referee", "display_name": "裁判", "description": "A match referee.", "attributes": []},
            {"name": "Person", "display_name": "个人", "description": "Any person.", "attributes": []},
            {"name": "Organization", "display_name": "组织", "description": "Any organization.", "attributes": []},
        ],
        "edge_types": [],
        "analysis_summary": "足球本体",
    })

    ontology = OntologyGenerator(fake_llm).generate(
        ["墨西哥队与南非队资料"],
        "预测墨西哥 vs 南非单场比赛比分和关键事件",
        simulation_domain="football_match",
    )

    system_prompt = fake_llm.messages[0]["content"]
    user_prompt = fake_llm.messages[1]["content"]

    assert "男子足球单场比赛过程和结果预测" in system_prompt
    assert "FootballTeam" in system_prompt
    assert "社交媒体舆论模拟系统" not in system_prompt
    assert "预测比分、胜率、优势、劣势、状态结论" in system_prompt
    assert "设计适合男子足球单场赛事预测" in user_prompt
    assert "社会舆论模拟" not in user_prompt
    assert len(ontology["entity_types"]) == 10
    assert ontology["entity_types"][-2]["name"] == "Person"
    assert ontology["entity_types"][-1]["name"] == "Organization"

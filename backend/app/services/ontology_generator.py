"""
本体生成服务
接口1：分析文本内容，生成适合社会模拟的实体和关系类型定义
"""

import json
import logging
import re
from typing import Dict, Any, List, Optional
from ..utils.llm_client import LLMClient
from .content_language import build_content_language_instruction
from .simulation_domains import FOOTBALL_MATCH, normalize_simulation_domain

logger = logging.getLogger(__name__)

# 这些字段名是底层图数据库/实体模型已经占用的系统字段。
# LLM 如果返回了同名属性，例如 name 或 uuid，后续动态生成 Pydantic 模型时会冲突。
# 所以 _safe_attribute_name 会把这些字段改成 entity_name、entity_uuid 这一类安全名称。
RESERVED_ATTRIBUTE_NAMES = {
    "uuid",
    "name",
    "group_id",
    "labels",
    "summary",
    "created_at",
    "attributes",
    "name_embedding",
}

SUPPORTED_ONTOLOGY_UI_LOCALES = {"en", "zh"}

FOOTBALL_ENTITY_DISPLAY_NAMES = {
    "en": {
        "FootballTeam": "Team",
        "Player": "Player",
        "Coach": "Coach",
        "Match": "Match",
        "Competition": "Competition",
        "Venue": "Venue",
        "TacticalFormation": "Tactical formation",
        "Referee": "Referee",
        "Person": "Person",
        "Organization": "Organization",
    },
    "zh": {
        "FootballTeam": "球队",
        "Player": "球员",
        "Coach": "教练",
        "Match": "比赛",
        "Competition": "赛事",
        "Venue": "场地",
        "TacticalFormation": "战术阵型",
        "Referee": "裁判",
        "Person": "个人",
        "Organization": "组织",
    },
}

FOOTBALL_EDGE_DISPLAY_NAMES = {
    "en": {
        "PLAYS_FOR": "Plays for",
        "COACHED_BY": "Coached by",
        "PARTICIPATES_IN": "Participates in",
        "SCHEDULED_AT": "Scheduled at",
        "PART_OF_COMPETITION": "Part of competition",
        "USES_FORMATION": "Uses formation",
        "MATCHES_UP_AGAINST": "Matches up against",
        "REFEREES": "Referees",
        "KEY_PLAYER_FOR": "Key player for",
        "COMPETES_WITH": "Competes with",
    },
    "zh": {
        "PLAYS_FOR": "效力于",
        "COACHED_BY": "执教于",
        "PARTICIPATES_IN": "参加",
        "SCHEDULED_AT": "举办于",
        "PART_OF_COMPETITION": "属于赛事",
        "USES_FORMATION": "使用阵型",
        "MATCHES_UP_AGAINST": "对位",
        "REFEREES": "执法",
        "KEY_PLAYER_FOR": "关键球员属于",
        "COMPETES_WITH": "对阵",
    },
}

GENERIC_FALLBACK_ENTITY_DEFS = {
    "en": {
        "Person": {
            "display_name": "Person",
            "attributes": [
                {"name": "full_name", "type": "text", "description": "Full name"},
                {"name": "role", "type": "text", "description": "Role or profession"},
            ],
            "examples": ["ordinary citizen", "anonymous netizen"],
        },
        "Organization": {
            "display_name": "Organization",
            "attributes": [
                {"name": "organization_name", "type": "text", "description": "Organization name"},
                {"name": "organization_type", "type": "text", "description": "Organization type"},
            ],
            "examples": ["small business", "community group"],
        },
    },
    "zh": {
        "Person": {
            "display_name": "个人",
            "attributes": [
                {"name": "全名", "type": "text", "description": "人物全名"},
                {"name": "角色", "type": "text", "description": "角色或职业"},
            ],
            "examples": ["普通市民", "匿名网友"],
        },
        "Organization": {
            "display_name": "组织",
            "attributes": [
                {"name": "组织名称", "type": "text", "description": "组织名称"},
                {"name": "组织类型", "type": "text", "description": "组织类型"},
            ],
            "examples": ["小型企业", "社区团体"],
        },
    },
}


def _to_pascal_case(name: str) -> str:
    """
    将任意格式的名称转换为 PascalCase。

    PascalCase 指每个单词首字母大写并直接拼接，例如：
    - 'works_for' -> 'WorksFor'
    - 'media outlet' -> 'MediaOutlet'
    - 'person' -> 'Person'

    这里之所以要转换，是因为后续会把实体类型名当作 Python 类名使用。
    Python 类名通常使用 PascalCase，Graphiti 的 Pydantic entity_types 也适配这种格式。
    """
    # 按非字母数字字符分割
    parts = re.split(r'[^a-zA-Z0-9]+', name)
    # 再按 camelCase 边界分割（如 'camelCase' -> ['camel', 'Case']）
    words = []
    for part in parts:
        words.extend(re.sub(r'([a-z])([A-Z])', r'\1_\2', part).split('_'))
    # 每个词首字母大写，过滤空串
    result = ''.join(word.capitalize() for word in words if word)
    return result if result else 'Unknown'


def _safe_attribute_name(attr_name: str) -> str:
    """
    清洗 LLM 返回的属性名，让它可以安全地作为 Pydantic 字段名。

    本项目允许属性名使用中文，例如“全名”“所属球队”。但属性名仍然不能：
    - 为空；
    - 以数字开头；
    - 包含空格、标点等不适合作为字段名的字符；
    - 使用 name、uuid 等系统保留字段。

    返回值是清洗后的安全字段名，后续 Graphiti entity_types 会直接使用。
    """
    # str(... or "属性") 可以把 None、空字符串等异常输入统一成默认文本。
    normalized = str(attr_name or "属性").strip() or "属性"
    # \w 在 Python 的 Unicode 模式下可以匹配中文、英文字母、数字和下划线。
    # 其他符号统一替换成下划线，避免生成非法字段。
    normalized = re.sub(r"[^\w]+", "_", normalized, flags=re.UNICODE)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    if not normalized:
        normalized = "属性"
    if normalized[0].isdigit():
        normalized = f"字段_{normalized}"
    if normalized.lower() in RESERVED_ATTRIBUTE_NAMES:
        normalized = f"entity_{normalized}"
    return normalized


def _normalize_ontology_ui_locale(locale: Optional[str]) -> str:
    normalized = str(locale or "en").split(",", 1)[0].strip().lower()
    if "-" in normalized:
        normalized = normalized.split("-", 1)[0]
    return normalized if normalized in SUPPORTED_ONTOLOGY_UI_LOCALES else "en"


def _ontology_ui_locale_instruction(locale: str) -> str:
    language_name = "Chinese" if locale == "zh" else "English"
    examples = (
        "`FootballTeam.display_name` = `球队`, `PLAYS_FOR.display_name` = `效力于`"
        if locale == "zh"
        else "`FootballTeam.display_name` = `Team`, `PLAYS_FOR.display_name` = `Plays for`"
    )
    return (
        f"Ontology UI locale: {locale} ({language_name}). "
        "Entity and relationship `display_name` values are UI/schema labels and MUST use this UI locale, "
        "not the uploaded material language. "
        f"Examples: {examples}. "
        "Descriptions and analysis_summary are generated content and should follow the content-language instruction."
    )


def _localized_fallback_entity(entity_name: str, locale: str) -> Dict[str, Any]:
    localized = GENERIC_FALLBACK_ENTITY_DEFS[locale][entity_name]
    description = (
        "Any individual person not fitting other specific person types."
        if entity_name == "Person"
        else "Any organization not fitting other specific organization types."
    )
    return {
        "name": entity_name,
        "display_name": localized["display_name"],
        "description": description,
        "attributes": [dict(attr) for attr in localized["attributes"]],
        "examples": list(localized["examples"]),
    }


def _looks_like_unlocalized_standard_label(
    current: Any,
    internal_name: str,
    locale: str,
    label_map: Dict[str, Dict[str, str]],
) -> bool:
    if not current:
        return True
    current_text = str(current)
    if current_text == internal_name:
        return True
    known_labels = {
        labels[internal_name]
        for labels in label_map.values()
        if internal_name in labels
    }
    if current_text in known_labels:
        return True
    # If the UI locale is English, any CJK label from the LLM is not usable for
    # the ontology list. For Chinese UI we preserve custom Chinese synonyms.
    return locale == "en" and bool(re.search(r"[\u3400-\u9fff]", current_text))


def _localize_standard_display_name(
    item: Dict[str, Any],
    locale: str,
    label_map: Dict[str, Dict[str, str]],
) -> None:
    internal_name = item.get("name")
    localized = label_map.get(locale, {}).get(internal_name)
    if localized and _looks_like_unlocalized_standard_label(item.get("display_name"), internal_name, locale, label_map):
        item["display_name"] = localized


# 本体生成的系统提示词
ONTOLOGY_SYSTEM_PROMPT = """你是一个专业的知识图谱本体设计专家。你的任务是分析给定的文本内容和模拟需求，设计适合**社交媒体舆论模拟**的实体类型和关系类型。

**重要：你必须输出有效的JSON格式数据，不要输出任何其他内容。**

## 核心任务背景

我们正在构建一个**社交媒体舆论模拟系统**。在这个系统中：
- 每个实体都是一个可以在社交媒体上发声、互动、传播信息的"账号"或"主体"
- 实体之间会相互影响、转发、评论、回应
- 我们需要模拟舆论事件中各方的反应和信息传播路径

因此，**实体必须是现实中真实存在的、可以在社媒上发声和互动的主体**：

**可以是**：
- 具体的个人（公众人物、当事人、意见领袖、专家学者、普通人）
- 公司、企业（包括其官方账号）
- 组织机构（大学、协会、NGO、工会等）
- 政府部门、监管机构
- 媒体机构（报纸、电视台、自媒体、网站）
- 社交媒体平台本身
- 特定群体代表（如校友会、粉丝团、维权群体等）

**不可以是**：
- 抽象概念（如"舆论"、"情绪"、"趋势"）
- 主题/话题（如"学术诚信"、"教育改革"）
- 观点/态度（如"支持方"、"反对方"）

## 输出格式

请输出JSON格式，包含以下结构：

```json
{
    "entity_types": [
        {
            "name": "实体类型名称（英文，PascalCase）",
            "display_name": "展示名（按 Ontology UI locale 使用中文或英文）",
            "description": "简短描述（按上传材料主要语言，不超过100字符）",
            "attributes": [
                {
                    "name": "属性名（安全字段名，英文用 snake_case；中文可用中文、数字、下划线）",
                    "type": "text",
                    "description": "属性描述"
                }
            ],
            "examples": ["示例实体1", "示例实体2"]
        }
    ],
    "edge_types": [
        {
            "name": "关系类型名称（英文，UPPER_SNAKE_CASE）",
            "display_name": "展示名（按 Ontology UI locale 使用中文或英文）",
            "description": "简短描述（按上传材料主要语言，不超过100字符）",
            "source_targets": [
                {"source": "源实体类型", "target": "目标实体类型"}
            ],
            "attributes": []
        }
    ],
    "analysis_summary": "对文本内容的简要分析说明"
}
```

## 设计指南（极其重要！）

### 1. 实体类型设计 - 必须严格遵守

**数量要求：必须正好10个实体类型**

**命名要求**：
- `name` 是内部类型ID，必须使用英文 PascalCase，例如 `MediaOutlet`
- `display_name` 是前端展示名，必须使用 Ontology UI locale：英文 UI 使用英文，例如 `Media outlet`；中文 UI 使用中文，例如 `媒体机构`

**层次结构要求（必须同时包含具体类型和兜底类型）**：

你的10个实体类型必须包含以下层次：

A. **兜底类型（必须包含，放在列表最后2个）**：
   - `Person`: 任何自然人个体的兜底类型。当一个人不属于其他更具体的人物类型时，归入此类。
   - `Organization`: 任何组织机构的兜底类型。当一个组织不属于其他更具体的组织类型时，归入此类。

B. **具体类型（8个，根据文本内容设计）**：
   - 针对文本中出现的主要角色，设计更具体的类型
   - 例如：如果文本涉及学术事件，可以有 `Student`, `Professor`, `University`
   - 例如：如果文本涉及商业事件，可以有 `Company`, `CEO`, `Employee`

**为什么需要兜底类型**：
- 文本中会出现各种人物，如"中小学教师"、"路人甲"、"某位网友"
- 如果没有专门的类型匹配，他们应该被归入 `Person`
- 同理，小型组织、临时团体等应该归入 `Organization`

**具体类型的设计原则**：
- 从文本中识别出高频出现或关键的角色类型
- 每个具体类型应该有明确的边界，避免重叠
- description 必须清晰说明这个类型和兜底类型的区别

### 2. 关系类型设计

- 数量：6-10个
- `name` 是内部关系ID，必须使用英文 UPPER_SNAKE_CASE，例如 `REPORTS_ON`
- `display_name` 是前端展示名，必须使用 Ontology UI locale：英文 UI 使用英文，例如 `Reports on`；中文 UI 使用中文，例如 `报道`
- 关系应该反映社媒互动中的真实联系
- 确保关系的 source_targets 涵盖你定义的实体类型

### 3. 属性设计

- 每个实体类型1-3个关键属性
- **注意**：属性名不能使用 `name`、`uuid`、`group_id`、`created_at`、`summary`（这些是系统保留字）
- 属性名必须是安全字段名；英文 UI 可使用 `full_name`、`role`、`position`、`region`、`organization_name`、`influence_level`
- 中文 UI 可使用 `全名`、`角色`、`职位`、`地区`、`组织名称`、`影响力分级`

## 实体类型参考

**个人类（具体）**：
- Student: 学生
- Professor: 教授/学者
- Journalist: 记者
- Celebrity: 明星/网红
- Executive: 高管
- Official: 政府官员
- Lawyer: 律师
- Doctor: 医生

**个人类（兜底）**：
- Person: 任何自然人（不属于上述具体类型时使用）

**组织类（具体）**：
- University: 高校
- Company: 公司企业
- GovernmentAgency: 政府机构
- MediaOutlet: 媒体机构
- Hospital: 医院
- School: 中小学
- NGO: 非政府组织

**组织类（兜底）**：
- Organization: 任何组织机构（不属于上述具体类型时使用）

## 关系类型参考

- WORKS_FOR: 工作于
- STUDIES_AT: 就读于
- AFFILIATED_WITH: 隶属于
- REPRESENTS: 代表
- REGULATES: 监管
- REPORTS_ON: 报道
- COMMENTS_ON: 评论
- RESPONDS_TO: 回应
- SUPPORTS: 支持
- OPPOSES: 反对
- COLLABORATES_WITH: 合作
- COMPETES_WITH: 竞争
"""


FOOTBALL_MATCH_ONTOLOGY_SYSTEM_PROMPT = """你是一个专业的知识图谱本体设计专家。你的任务是分析给定的球队、球员、战术、赛事资料和模拟需求，设计适合**男子足球单场比赛过程和结果预测**的实体类型和关系类型。

**重要：你必须输出有效的JSON格式数据，不要输出任何其他内容。**

## 核心任务背景

我们正在构建一个**男子足球赛事预测系统**。在这个系统中：
- 上传资料会先生成足球领域本体，再用于构建球队资料知识图谱
- 图谱必须承载单场比赛预测需要的现实对象、参赛关系、阵容信息、战术结构和比赛条件
- 后续模拟阶段会由系统额外注入足球评论员、战术分析师、数据分析师等 Agent 辅助推演
- 本体本身必须服务于“球队资料 -> 图谱 -> 专家推演 -> 比分和关键事件预测”的链路

因此，**实体必须是足球比赛中真实存在或可明确抽取的对象**：

**可以是**：
- 男子足球队、俱乐部、国家队
- 球员、教练、裁判等具体个人
- 单场比赛、赛事/杯赛/联赛、比赛场地
- 战术阵型、关键比赛条件、可明确命名的足球组织

**不可以是**：
- 预测比分、胜率、优势、劣势、状态结论
- 抽象判断（如“进攻火力”“防守稳定性”“爆冷可能性”）
- 观点或结果标签（如“更强的一方”“热门球队”“黑马”）
- 未在资料中形成明确对象的临时描述

预测比分、胜率、优势、劣势、状态结论只能出现在后续模拟配置或报告中，不能作为图谱实体类型。

## 输出格式

请输出JSON格式，包含以下结构：

```json
{
    "entity_types": [
        {
            "name": "实体类型名称（英文，PascalCase）",
            "display_name": "展示名（按 Ontology UI locale 使用中文或英文）",
            "description": "简短描述（按上传材料主要语言，不超过100字符）",
            "attributes": [
                {
                    "name": "属性名（安全字段名，英文用 snake_case；中文可用中文、数字、下划线）",
                    "type": "text",
                    "description": "属性描述"
                }
            ],
            "examples": ["示例实体1", "示例实体2"]
        }
    ],
    "edge_types": [
        {
            "name": "关系类型名称（英文，UPPER_SNAKE_CASE）",
            "display_name": "展示名（按 Ontology UI locale 使用中文或英文）",
            "description": "简短描述（按上传材料主要语言，不超过100字符）",
            "source_targets": [
                {"source": "源实体类型", "target": "目标实体类型"}
            ],
            "attributes": []
        }
    ],
    "analysis_summary": "对足球资料和预测任务的简要分析说明"
}
```

## 设计指南（极其重要！）

### 1. 实体类型设计 - 必须严格遵守

**数量要求：必须正好10个实体类型**

**命名要求**：
- `name` 是内部类型ID，必须使用英文 PascalCase，例如 `FootballTeam`
- `display_name` 是前端展示名，必须使用 Ontology UI locale：英文 UI 使用英文，例如 `Team`；中文 UI 使用中文，例如 `球队`

**层次结构要求（必须同时包含足球具体类型和兜底类型）**：

你的10个实体类型必须包含以下层次：

A. **足球具体类型（前8个，建议固定使用）**：
   - `FootballTeam`: 足球队、国家队或俱乐部
   - `Player`: 足球运动员
   - `Coach`: 主教练、助理教练或教练组关键成员
   - `Match`: 单场足球比赛
   - `Competition`: 赛事、杯赛、联赛或锦标赛
   - `Venue`: 比赛场地、球场或主办城市
   - `TacticalFormation`: 战术阵型、打法体系或明确战术结构
   - `Referee`: 主裁判、VAR裁判或裁判组关键成员

B. **兜底类型（必须包含，放在列表最后2个）**：
   - `Person`: 任何不适合归入 Player/Coach/Referee 的自然人兜底类型
   - `Organization`: 任何不适合归入 FootballTeam/Competition/Venue 的组织兜底类型

### 2. 关系类型设计

- 数量：6-10个
- `name` 是内部关系ID，必须使用英文 UPPER_SNAKE_CASE，例如 `PLAYS_FOR`
- `display_name` 是前端展示名，必须使用 Ontology UI locale：英文 UI 使用英文，例如 `Plays for`；中文 UI 使用中文，例如 `效力于`
- 关系应该反映球队资料、比赛安排、战术对位和赛事归属
- 确保关系的 source_targets 涵盖你定义的实体类型

### 3. 属性设计

- 每个实体类型1-3个关键属性
- **注意**：属性名不能使用 `name`、`uuid`、`group_id`、`created_at`、`summary`（这些是系统保留字）
- 属性名必须是安全字段名；英文 UI 可使用 `full_name`、`position`、`dominant_foot`、`team`、`formation`、`match_time`、`match_stage`
- 中文 UI 可使用 `全名`、`位置`、`惯用脚`、`所属球队`、`阵型`、`比赛时间`、`比赛阶段`

## 关系类型参考

- PLAYS_FOR: 效力于
- COACHED_BY: 执教于
- PARTICIPATES_IN: 参加
- SCHEDULED_AT: 举办于
- PART_OF_COMPETITION: 属于赛事
- USES_FORMATION: 使用阵型
- MATCHES_UP_AGAINST: 对位
- REFEREES: 执法
- KEY_PLAYER_FOR: 关键球员属于
- COMPETES_WITH: 对阵/竞争
"""


class OntologyGenerator:
    """
    本体生成器

    “本体”可以理解为知识图谱的结构说明：
    - entity_types：系统应该识别哪些实体类型，例如 Person、FootballTeam。
    - edge_types：实体之间可以有哪些关系，例如 WORKS_FOR、PLAYS_FOR。

    /api/graph/ontology/generate 路由会先解析上传文件，再调用这个类。
    这个类只负责“根据文本和模拟需求设计本体”，不负责保存文件、创建项目或写 HTTP 响应。
    """
    
    def __init__(self, llm_client: Optional[LLMClient] = None):
        # 允许外部传入 llm_client，主要是为了测试时使用 FakeLLMClient，避免真的请求大模型。
        # 如果调用方没有传，就创建默认的 LLMClient。
        self.llm_client = llm_client or LLMClient()
    
    def generate(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str] = None,
        simulation_domain: str = FOOTBALL_MATCH,
        ui_locale: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        生成本体定义

        这是本类的主入口。它的执行顺序是：
        1. 规范化 simulation_domain，决定使用足球比赛预测规则。
        2. 把上传文档、模拟需求和额外说明拼成用户 prompt。
        3. 选择对应领域的系统 prompt，告诉 LLM 输出什么 JSON 结构。
        4. 调用 LLMClient.chat_json，得到 Python 字典形式的结果。
        5. 对 LLM 输出做兜底修正，保证后续图谱构建能稳定使用。
        
        Args:
            document_texts: 文档文本列表
            simulation_requirement: 模拟需求描述
            additional_context: 额外上下文
            simulation_domain: 预测领域；当前产品只支持 football_match
            ui_locale: 当前前端 UI 语言，仅支持 en/zh，用于 ontology 展示标签
            
        Returns:
            本体定义（entity_types, edge_types等）
        """
        # 先统一领域值，避免调用方传入空字符串、大小写不同或不支持的领域。
        simulation_domain = normalize_simulation_domain(simulation_domain)
        ontology_ui_locale = _normalize_ontology_ui_locale(ui_locale)
        # user_message 是用户侧 prompt，主要放“这次上传的资料和需求”。
        user_message = self._build_user_message(
            document_texts, 
            simulation_requirement,
            additional_context,
            simulation_domain,
            ontology_ui_locale,
        )
        
        # LLM 内容语言跟随上传材料主语言，不能由前端 UI locale 决定。
        lang_instruction = build_content_language_instruction(
            [*document_texts, simulation_requirement, additional_context or ""]
        )
        # 当前产品只支持足球预测，normalize_simulation_domain 会拒绝旧领域值。
        base_prompt = FOOTBALL_MATCH_ONTOLOGY_SYSTEM_PROMPT
        # system_prompt 是系统侧 prompt，用于约束输出格式、命名规范和业务边界。
        # 这里再次强调 name/display_name/属性名规则，是为了降低 LLM 返回不可用结构的概率。
        ui_locale_instruction = _ontology_ui_locale_instruction(ontology_ui_locale)
        system_prompt = f"{base_prompt}\n\n{lang_instruction}\n\n{ui_locale_instruction}\nIMPORTANT: Entity type names in `name` MUST be in English PascalCase (e.g., 'PersonEntity', 'MediaOrganization'). Relationship type names in `name` MUST be in English UPPER_SNAKE_CASE (e.g., 'WORKS_FOR'). Entity and relationship `display_name` values MUST follow the Ontology UI locale above. Attribute names must be safe fields; use English snake_case for English UI and safe Chinese field names for Chinese UI. Description fields and analysis_summary should use the uploaded-material content language specified above."
        # messages 是 Chat Completions 常见格式：system 给规则，user 给本次任务数据。
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]
        
        # chat_json 会要求模型返回 JSON，并把结果解析成 Python dict。
        # temperature 较低是为了让结构化输出更稳定；max_tokens 控制最大输出长度。
        result = self.llm_client.chat_json(
            messages=messages,
            temperature=0.1,
            max_tokens=4096
        )
        
        # LLM 输出即使是合法 JSON，也可能缺字段、命名不规范或超出数量限制。
        # 所以这里统一做后处理，减少后续图谱构建失败的概率。
        result = self._validate_and_process(
            result,
            ui_locale=ontology_ui_locale,
            simulation_domain=simulation_domain,
        )
        
        return result
    
    # 传给 LLM 的文本最大长度（5万字）。
    # 注意：这里只限制“本体分析阶段”发给 LLM 的内容长度，不会裁剪项目保存的原始文本。
    MAX_TEXT_LENGTH_FOR_LLM = 50000
    
    def _build_user_message(
        self,
        document_texts: List[str],
        simulation_requirement: str,
        additional_context: Optional[str],
        simulation_domain: str = FOOTBALL_MATCH,
        ui_locale: str = "en",
    ) -> str:
        """
        构建发给 LLM 的用户消息。

        document_texts 是一个列表，列表里的每个元素是一份上传文件解析后的纯文本。
        这里把多份文档合并成一个 prompt，再附上模拟需求和可选的额外说明。
        """
        
        # 用分隔线把多份文档隔开，避免 LLM 把不同文件的段落误认为连续上下文。
        combined_text = "\n\n---\n\n".join(document_texts)
        original_length = len(combined_text)
        
        # 如果文本超过5万字，截断（仅影响传给LLM的内容，不影响图谱构建）。
        # 本体设计只需要理解资料里的角色和关系类型，不需要把每个细节都发给模型。
        if len(combined_text) > self.MAX_TEXT_LENGTH_FOR_LLM:
            combined_text = combined_text[:self.MAX_TEXT_LENGTH_FOR_LLM]
            combined_text += f"\n\n...(原文共{original_length}字，已截取前{self.MAX_TEXT_LENGTH_FOR_LLM}字用于本体分析)..."
        
        message = f"""## 模拟需求

{simulation_requirement}

## 文档内容

{combined_text}
"""
        
        if additional_context:
            # 额外说明通常来自前端表单，用来补充用户没有写进上传文件里的背景约束。
            message += f"""
## 额外说明

{additional_context}
"""
        
        # 足球领域要求更具体：实体必须围绕单场比赛预测可以抽取的现实对象。
        message += f"""
请根据以上内容，设计适合男子足球单场赛事预测的实体类型和关系类型。

**必须遵守的规则**：
1. 必须正好输出10个实体类型
2. 最后2个必须是兜底类型：Person（个人兜底）和 Organization（组织兜底）
3. 前8个应围绕球队、球员、教练、比赛、赛事、场地、战术阵型、裁判设计
4. 所有实体类型必须是足球资料中可抽取的现实对象或明确足球对象
5. 不要把预测比分、胜率、优势、劣势、状态结论设计为实体类型
6. 实体类型和关系类型的 name 保持英文内部ID，但 display_name 必须按 Ontology UI locale（当前为 {ui_locale}）输出
7. 属性名不能使用 name、uuid、group_id 等保留字；英文 UI 推荐用 full_name、position、team、formation、match_time 等 snake_case 字段，中文 UI 推荐用 全名、位置、所属球队、阵型、比赛时间 等安全字段
"""
        
        return message
    
    def _validate_and_process(
        self,
        result: Dict[str, Any],
        *,
        ui_locale: str = "en",
        simulation_domain: str = FOOTBALL_MATCH,
    ) -> Dict[str, Any]:
        """
        验证并修正 LLM 输出。

        LLM 返回的数据不能直接信任，因为它可能：
        - 少返回 entity_types、edge_types 或 analysis_summary；
        - 把实体名写成 snake_case 或中文；
        - 把关系名写成小写；
        - 忘记补 Person/Organization 兜底类型；
        - 返回超过项目约定支持的类型数量。

        这个函数会尽量把结果修正成后续流程能接受的格式。
        """
        
        ui_locale = _normalize_ontology_ui_locale(ui_locale)
        simulation_domain = normalize_simulation_domain(simulation_domain)

        # 确保必要字段存在。setdefault 也可以做类似事情，但这里显式写 if 更易读。
        if "entity_types" not in result:
            result["entity_types"] = []
        if "edge_types" not in result:
            result["edge_types"] = []
        if "analysis_summary" not in result:
            result["analysis_summary"] = ""
        
        # 验证实体类型
        # 记录原始名称到 PascalCase 的映射，用于后续修正 edge 的 source_targets 引用
        entity_name_map = {}
        for entity in result["entity_types"]:
            # entity 是一个字典，例如 {"name": "Person", "attributes": [...]}。
            # 强制将 entity name 转为 PascalCase（Graphiti entity_types 适配）。
            if "name" in entity:
                original_name = entity["name"]
                entity["name"] = _to_pascal_case(original_name)
                if entity["name"] != original_name:
                    logger.warning(f"Entity type name '{original_name}' auto-converted to '{entity['name']}'")
                entity_name_map[original_name] = entity["name"]
            # 如果 LLM 没给 display_name，就用 name 兜底，避免前端展示时报 KeyError。
            entity.setdefault("display_name", entity.get("name", ""))
            if simulation_domain == FOOTBALL_MATCH:
                _localize_standard_display_name(entity, ui_locale, FOOTBALL_ENTITY_DISPLAY_NAMES)
            if "attributes" not in entity:
                entity["attributes"] = []
            for attr in entity["attributes"]:
                # attr 也是字典，例如 {"name": "全名", "type": "text"}。
                # 每个属性都要清洗字段名，并补齐 type/description。
                original_attr_name = attr.get("name", "")
                attr["name"] = _safe_attribute_name(original_attr_name)
                if attr["name"] != original_attr_name:
                    logger.warning(f"Entity attribute name '{original_attr_name}' auto-converted to '{attr['name']}'")
                attr.setdefault("type", "text")
                attr.setdefault("description", attr["name"])
            if "examples" not in entity:
                entity["examples"] = []
            # 确保 description 不超过 100 字符，符合 prompt 和部分下游字段长度约束。
            if len(entity.get("description", "")) > 100:
                entity["description"] = entity["description"][:97] + "..."
        
        # 验证关系类型
        for edge in result["edge_types"]:
            # edge 是关系类型字典，例如 {"name": "WORKS_FOR", "source_targets": [...]}。
            # 强制将 edge name 转为 SCREAMING_SNAKE_CASE，方便后续关系类型匹配。
            if "name" in edge:
                original_name = edge["name"]
                edge["name"] = original_name.upper()
                if edge["name"] != original_name:
                    logger.warning(f"Edge type name '{original_name}' auto-converted to '{edge['name']}'")
            edge.setdefault("display_name", edge.get("name", ""))
            if simulation_domain == FOOTBALL_MATCH:
                _localize_standard_display_name(edge, ui_locale, FOOTBALL_EDGE_DISPLAY_NAMES)
            # 修正 source_targets 中的实体名称引用，与转换后的 PascalCase 保持一致
            for st in edge.get("source_targets", []):
                if st.get("source") in entity_name_map:
                    st["source"] = entity_name_map[st["source"]]
                if st.get("target") in entity_name_map:
                    st["target"] = entity_name_map[st["target"]]
            if "source_targets" not in edge:
                edge["source_targets"] = []
            if "attributes" not in edge:
                edge["attributes"] = []
            for attr in edge["attributes"]:
                # 关系属性和实体属性使用同一套字段名清洗规则。
                original_attr_name = attr.get("name", "")
                attr["name"] = _safe_attribute_name(original_attr_name)
                if attr["name"] != original_attr_name:
                    logger.warning(f"Edge attribute name '{original_attr_name}' auto-converted to '{attr['name']}'")
                attr.setdefault("type", "text")
                attr.setdefault("description", attr["name"])
            if len(edge.get("description", "")) > 100:
                edge["description"] = edge["description"][:97] + "..."
        
        # 项目约定：最多 10 个自定义实体类型，最多 10 个自定义边类型
        MAX_ENTITY_TYPES = 10
        MAX_EDGE_TYPES = 10

        # 去重：按 name 去重，保留首次出现的。
        # seen_names 是集合 set，适合快速判断一个名字是否已经出现过。
        seen_names = set()
        deduped = []
        for entity in result["entity_types"]:
            name = entity.get("name", "")
            if name and name not in seen_names:
                seen_names.add(name)
                deduped.append(entity)
            elif name in seen_names:
                logger.warning(f"Duplicate entity type '{name}' removed during validation")
        result["entity_types"] = deduped

        # 兜底类型定义。
        # Person 和 Organization 必须存在，因为真实文本里经常出现无法归入具体类型的人或组织。
        # 没有兜底类型时，图谱抽取阶段可能会丢掉这些实体。
        person_fallback = _localized_fallback_entity("Person", ui_locale)
        organization_fallback = _localized_fallback_entity("Organization", ui_locale)
        
        # 检查 LLM 是否已经返回兜底类型；如果已经有，就不重复添加。
        entity_names = {e["name"] for e in result["entity_types"]}
        has_person = "Person" in entity_names
        has_organization = "Organization" in entity_names
        
        # 需要添加的兜底类型
        fallbacks_to_add = []
        if not has_person:
            fallbacks_to_add.append(person_fallback)
        if not has_organization:
            fallbacks_to_add.append(organization_fallback)
        
        if fallbacks_to_add:
            current_count = len(result["entity_types"])
            needed_slots = len(fallbacks_to_add)
            
            # 如果添加后会超过 10 个，需要移除一些现有类型
            if current_count + needed_slots > MAX_ENTITY_TYPES:
                # 计算需要移除多少个
                to_remove = current_count + needed_slots - MAX_ENTITY_TYPES
                # 从末尾移除（保留前面更重要的具体类型）。
                # Python 的切片 [:-to_remove] 表示“从开头保留到倒数第 to_remove 个之前”。
                result["entity_types"] = result["entity_types"][:-to_remove]
            
            # 添加兜底类型
            result["entity_types"].extend(fallbacks_to_add)
        
        # 最终确保不超过限制（防御性编程）
        if len(result["entity_types"]) > MAX_ENTITY_TYPES:
            result["entity_types"] = result["entity_types"][:MAX_ENTITY_TYPES]
        
        if len(result["edge_types"]) > MAX_EDGE_TYPES:
            result["edge_types"] = result["edge_types"][:MAX_EDGE_TYPES]
        
        return result

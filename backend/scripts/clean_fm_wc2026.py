#!/usr/bin/env python3
"""
Clean FIFA World Cup 2026 squad players from a FIFA-style MD report and an
FM attribute export.

The MD squad list is the source of truth: only players listed in the MD are
emitted. FM data is used for player attributes after nationality-constrained
name matching.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

try:
    from rapidfuzz import fuzz as rapidfuzz_fuzz
except Exception:  # pragma: no cover - exercised only when dependency is absent
    rapidfuzz_fuzz = None


csv.field_size_limit(sys.maxsize)


FIFA_NAME_TO_ISO3 = {
    "Algeria": "ALG",
    "Argentina": "ARG",
    "Australia": "AUS",
    "Austria": "AUT",
    "Belgium": "BEL",
    "Bosnia And Herzegovina": "BIH",
    "Brazil": "BRA",
    "Cabo Verde": "CPV",
    "Canada": "CAN",
    "Colombia": "COL",
    "Congo DR": "COD",
    "Croatia": "CRO",
    "Curaçao": "CUW",
    "Czechia": "CZE",
    "Côte D'Ivoire": "CIV",
    "Ecuador": "ECU",
    "Egypt": "EGY",
    "England": "ENG",
    "France": "FRA",
    "Germany": "GER",
    "Ghana": "GHA",
    "Haiti": "HAI",
    "IR Iran": "IRN",
    "Iraq": "IRQ",
    "Japan": "JPN",
    "Jordan": "JOR",
    "Korea Republic": "KOR",
    "Mexico": "MEX",
    "Morocco": "MAR",
    "Netherlands": "NED",
    "New Zealand": "NZL",
    "Norway": "NOR",
    "Panama": "PAN",
    "Paraguay": "PAR",
    "Portugal": "POR",
    "Qatar": "QAT",
    "Saudi Arabia": "KSA",
    "Scotland": "SCO",
    "Senegal": "SEN",
    "South Africa": "RSA",
    "Spain": "ESP",
    "Sweden": "SWE",
    "Switzerland": "SUI",
    "Tunisia": "TUN",
    "Türkiye": "TUR",
    "USA": "USA",
    "Uruguay": "URU",
    "Uzbekistan": "UZB",
}


FM_NATION_ALIASES = {
    **FIFA_NAME_TO_ISO3,
    "Bosnia and Herzegovina": "BIH",
    "Cape Verde": "CPV",
    "Cape Verde Islands": "CPV",
    "Cote D'Ivoire": "CIV",
    "Cote d'Ivoire": "CIV",
    "Democratic Republic of Congo": "COD",
    "DR Congo": "COD",
    "Iran": "IRN",
    "Ivory Coast": "CIV",
    "South Korea": "KOR",
    "United States": "USA",
    "Curacao": "CUW",
}


NATION_KEY_TO_ISO3 = {
    re.sub(r"[^a-z0-9]+", "", unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()): iso3
    for name, iso3 in FM_NATION_ALIASES.items()
}


FM_TO_STD = {
    "姓名": "player_name_raw",
    "位置": "fm_position",
    "年龄": "age",
    "ca": "fm_ca",
    "pa": "fm_pa",
    "国籍": "nationality_raw",
    "俱乐部": "club",
    "身高": "height_cm",
    "左脚": "foot_left",
    "右脚": "foot_right",
    "UID": "player_external_id",
    "身价（欧元）": "market_value",
    "工资（欧元）": "wage",
    "国家队出场": "intl_caps",
    "国家队进球": "intl_goals",
    "出生日期": "birth_date",
    "角球": "corners",
    "传中": "crossing",
    "盘带": "dribbling",
    "射门": "finishing",
    "接球": "first_touch",
    "任意球": "free_kick",
    "头球": "heading",
    "远射": "long_shots",
    "界外球": "long_throws",
    "盯人": "marking",
    "传球": "passing",
    "罚点球": "penalties",
    "抢断": "tackling",
    "技术": "technique",
    "侵略性": "aggression",
    "预判": "anticipation",
    "勇敢": "bravery",
    "镇定": "composure",
    "集中": "concentration",
    "决断": "decisions",
    "意志力": "determination",
    "想象力": "flair",
    "领导力": "leadership",
    "无球跑动": "off_the_ball",
    "防守站位": "positioning_def",
    "团队合作": "teamwork",
    "视野": "vision",
    "工作投入": "work_rate",
    "爆发力": "acceleration",
    "灵活": "agility",
    "平衡": "balance",
    "弹跳": "jumping",
    "体质": "natural_fitness",
    "速度": "pace",
    "耐力": "stamina",
    "强壮": "strength",
    "制空能力": "gk_aerial_ability",
    "拦截传中": "gk_command_of_area",
    "沟通": "gk_communication",
    "手控球": "gk_handling",
    "大脚开球": "gk_kicking",
    "一对一": "gk_one_on_ones",
    "反应": "gk_reflexes",
    "出击": "gk_rushing_out",
    "击球倾向": "gk_tendency_to_punch",
    "手抛球的能力": "gk_throwing",
    "球员习惯": "player_traits",
}


MATCHED_FIELDS = [
    "team_fifa",
    "team_iso3",
    "shirt_number",
    "player_name",
    "player_name_en",
    "player_external_id",
    "fifa_position_class",
    "fm_position",
    "position_primary",
    "age",
    "fm_ca",
    "fm_pa",
    "club_fm",
    "club_fifa",
    "height_cm",
    "foot",
    "expected_role",
    "expected_minutes_share",
    "caps_intl",
    "goals_intl",
    "birth_date",
    "market_value",
    "derived_overall",
    "derived_attack",
    "derived_defense",
    "derived_pace",
    "derived_finishing",
    "derived_passing",
    "derived_set_piece",
    "derived_gk",
    "derived_role_scores",
    "derived_score_source",
    "ratings_json",
]


UNMATCHED_FIELDS = [
    "team_fifa",
    "shirt_number",
    "fifa_name",
    "fifa_position_class",
    "fifa_age",
    "fifa_club",
    "reason",
    "top3_csv_candidates",
]


TEAM_METADATA_FIELDS = [
    "team_fifa",
    "team_iso3",
    "team_zh",
    "group_label",
    "head_coach",
    "formation_primary",
    "formation_secondary",
    "tactical_label",
    "tactical_description",
    "key_player_uids",
    "squad_status",
    "metadata_json",
]


@dataclass
class MdPlayer:
    team_fifa: str
    team_zh: str
    team_iso3: str
    group_label: str
    shirt_number: int
    fifa_name_raw: str
    fifa_position_class: str
    fifa_age: int
    fifa_caps: int
    fifa_goals: int
    fifa_club: str
    fifa_club_league: str


@dataclass
class TeamMeta:
    team_fifa: str
    team_zh: str
    team_iso3: str
    group_label: str
    head_coach: str = ""
    formation_primary: str = ""
    formation_secondary: list[str] = field(default_factory=list)
    tactical_label: str = ""
    tactical_description: str = ""
    key_player_names: list[str] = field(default_factory=list)
    key_player_uids: list[str] = field(default_factory=list)
    squad_status: str = ""
    raw_tactics: dict[str, str] = field(default_factory=dict)


SPECIAL_CHAR_TRANSLATION = str.maketrans(
    {
        "ı": "i",
        "İ": "I",
        "ł": "l",
        "Ł": "L",
        "ø": "o",
        "Ø": "O",
        "đ": "d",
        "Đ": "D",
        "ð": "d",
        "Ð": "D",
        "þ": "th",
        "Þ": "Th",
        "æ": "ae",
        "Æ": "Ae",
        "œ": "oe",
        "Œ": "Oe",
        "ß": "ss",
    }
)


TOKEN_ALIASES = {
    "alex": {"alejandro"},
    "alejandro": {"alex"},
    "andy": {"andrew"},
    "andrew": {"andy"},
    "cammy": {"cameron"},
    "cameron": {"cammy"},
    "ebere": {"eberechi"},
    "eberechi": {"ebere"},
    "maxi": {"maximiliano", "maximilian"},
    "maximiliano": {"maxi"},
    "maximilian": {"maxi"},
}


TRAILING_SUFFIX_TOKENS = {"jr", "junior", "sr", "senior", "ii", "iii", "iv"}
JOINABLE_NAME_PARTICLES = {
    "a",
    "al",
    "ben",
    "bin",
    "da",
    "de",
    "del",
    "der",
    "di",
    "dos",
    "el",
    "ibn",
    "in",
    "la",
    "le",
    "mc",
    "ne",
    "o",
    "st",
    "van",
    "von",
}


def strip_accents(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.translate(SPECIAL_CHAR_TRANSLATION))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize(raw_name: str) -> str:
    """Normalize a player name for unordered token comparison."""
    if not raw_name:
        return ""
    name = str(raw_name).strip().strip('"')
    name = re.sub(r"\s*\([^)]*\)\s*$", "", name)
    name = strip_accents(name)
    name = name.replace("’", "'").replace("`", "'")
    name = re.sub(r"['.\-]+", " ", name)
    name = re.sub(r"[^A-Za-z0-9]+", " ", name)
    return re.sub(r"\s+", " ", name).strip().lower()


def token_set(normalized_name: str) -> set[str]:
    raw_tokens = [token for token in normalized_name.split() if token]
    while len(raw_tokens) > 1 and raw_tokens[-1] in TRAILING_SUFFIX_TOKENS:
        raw_tokens.pop()
    tokens = set(raw_tokens)
    for index, token in enumerate(raw_tokens):
        tokens.update(TOKEN_ALIASES.get(token, set()))
        if len(token) == 1 and index + 1 < len(raw_tokens):
            tokens.add(token + raw_tokens[index + 1])
        if index + 1 < len(raw_tokens):
            next_token = raw_tokens[index + 1]
            if token in JOINABLE_NAME_PARTICLES or next_token in JOINABLE_NAME_PARTICLES:
                tokens.add(token + next_token)
    return tokens


def compact_name(raw_name: str) -> str:
    return "".join(normalize(raw_name).split())


def nation_to_iso3(raw_nation: str) -> str | None:
    if not raw_nation:
        return None
    key = re.sub(
        r"[^a-z0-9]+",
        "",
        strip_accents(raw_nation).replace("’", "'").lower(),
    )
    return NATION_KEY_TO_ISO3.get(key)


def safe_int(val: Any, default: int = 0) -> int:
    try:
        if val is None or str(val).strip() == "":
            return default
        return int(float(str(val).strip()))
    except (ValueError, TypeError):
        return default


def normalize_position(fm_pos: str) -> str:
    """Map an FM position string to the 8-position internal taxonomy."""
    if not fm_pos:
        return "CM"
    fm_pos = fm_pos.strip().upper()
    compact = fm_pos.replace(" ", "")
    if fm_pos.startswith("GK") or "GK" in compact:
        return "GK"
    if "ST" in compact or "CF" in compact:
        return "ST"
    if "AM" in compact:
        if any(marker in compact for marker in ("AML", "AMR", "AMLC", "AMRC", "AML/R", "AMRL")):
            return "WG"
        if " L" in fm_pos or " R" in fm_pos:
            return "WG"
        return "AM"
    if "WB" in compact:
        return "FB"
    if "DM" in compact:
        return "DM"
    if fm_pos.startswith("M") or "MC" in compact:
        if any(marker in compact for marker in ("ML", "MR", "MLC", "MRC", "MLR")):
            return "WG"
        if " L" in fm_pos or " R" in fm_pos:
            return "WG"
        return "CM"
    if fm_pos.startswith("D") or compact.startswith("D"):
        if any(marker in compact for marker in ("DL", "DR", "WBL", "WBR", "DLR")):
            return "FB"
        if " L" in fm_pos or " R" in fm_pos:
            return "FB"
        return "CB"
    return "CM"


def position_primary(fifa_class: str, fm_position: str) -> str:
    if fifa_class == "GK":
        return "GK"
    fm_norm = normalize_position(fm_position)
    if fm_norm == "GK":
        return "GK"
    return fm_norm


def infer_foot(left: int, right: int) -> str:
    if left >= 18 and right < 14:
        return "L"
    if right >= 18 and left < 14:
        return "R"
    if abs(left - right) <= 3:
        return "B"
    return "L" if left > right else "R"


def infer_role(ca: int, age: int) -> str:
    if ca >= 150 and age <= 35:
        return "starter"
    if ca >= 130:
        return "rotation"
    if ca >= 110:
        return "bench"
    return "reserve"


def expected_minutes_share(role: str) -> float:
    return {
        "starter": 0.95,
        "rotation": 0.55,
        "bench": 0.20,
        "reserve": 0.05,
    }[role]


POSITION_SCORE_WEIGHTS = {
    "GK": {
        "shot_stopping": 0.50,
        "keeper_command": 0.25,
        "keeper_distribution": 0.08,
        "game_intelligence": 0.07,
        "mobility": 0.05,
        "mentality": 0.05,
    },
    "CB": {
        "defending": 0.30,
        "aerial_duel": 0.20,
        "game_intelligence": 0.15,
        "power": 0.12,
        "passing_creation": 0.10,
        "speed": 0.08,
        "mentality": 0.05,
    },
    "FB": {
        "defending": 0.22,
        "speed": 0.18,
        "crossing": 0.15,
        "power": 0.12,
        "passing_creation": 0.10,
        "game_intelligence": 0.10,
        "ball_control": 0.08,
        "mentality": 0.05,
    },
    "DM": {
        "defending": 0.22,
        "passing_creation": 0.22,
        "game_intelligence": 0.18,
        "power": 0.12,
        "ball_control": 0.10,
        "aerial_duel": 0.08,
        "mentality": 0.08,
    },
    "CM": {
        "passing_creation": 0.28,
        "game_intelligence": 0.22,
        "ball_control": 0.16,
        "defending": 0.10,
        "mobility": 0.10,
        "mentality": 0.08,
        "shooting": 0.06,
    },
    "AM": {
        "passing_creation": 0.24,
        "ball_control": 0.22,
        "movement": 0.16,
        "shooting": 0.14,
        "game_intelligence": 0.14,
        "speed": 0.06,
        "mentality": 0.04,
    },
    "WG": {
        "speed": 0.22,
        "ball_control": 0.20,
        "crossing": 0.14,
        "shooting": 0.14,
        "movement": 0.12,
        "passing_creation": 0.10,
        "power": 0.05,
        "defending": 0.03,
    },
    "ST": {
        "shooting": 0.30,
        "movement": 0.22,
        "aerial_duel": 0.12,
        "ball_control": 0.12,
        "speed": 0.10,
        "power": 0.07,
        "passing_creation": 0.04,
        "mentality": 0.03,
    },
}


TRAIT_SCORE_ADJUSTMENTS = {
    "经常带球": {"ball_control": 2.0, "movement": 0.5},
    "有机会就前插": {"movement": 1.4, "power": 0.4},
    "撞墙式配合": {"passing_creation": 1.5, "game_intelligence": 0.7},
    "长距离传球": {"passing_creation": 2.2, "game_intelligence": 0.6},
    "把球带出防守区域": {"ball_control": 1.8, "passing_creation": 0.9, "game_intelligence": 0.4},
    "远射": {"shooting": 1.6},
    "倒地铲球": {"defending": 1.6, "mentality": 0.4},
    "大力射门": {"shooting": 1.6, "power": 0.4},
    "趟球变向加速过人": {"speed": 1.4, "ball_control": 1.1},
    "利用脚下技术将球带出危险区": {"ball_control": 1.4, "passing_creation": 0.8, "keeper_distribution": 1.8},
    "尝试花式动作": {"ball_control": 1.3, "movement": 0.4},
    "跑肋部空间接球": {"movement": 2.0, "game_intelligence": 0.6},
    "回撤拿球": {"passing_creation": 1.2, "ball_control": 0.8, "game_intelligence": 0.7},
    "角度刁钻的射门": {"shooting": 1.8},
    "从左路内切": {"movement": 1.0, "shooting": 0.8, "ball_control": 0.5},
    "从右路内切": {"movement": 1.0, "shooting": 0.8, "ball_control": 0.5},
    "喜欢从双侧内切": {"movement": 1.2, "shooting": 0.8, "ball_control": 0.6},
    "经常尝试传身后球": {"passing_creation": 1.8, "game_intelligence": 0.5},
    "插入对方禁区": {"movement": 1.6, "shooting": 0.7},
    "控制节奏": {"passing_creation": 1.7, "game_intelligence": 1.0, "mentality": 0.4},
    "习惯简单短传配合": {"passing_creation": 1.2, "game_intelligence": 0.6},
    "喜欢将球转移到边路": {"passing_creation": 1.5, "vision": 0.0, "game_intelligence": 0.6},
    "喜欢接脚下球": {"ball_control": 1.1, "passing_creation": 0.5},
    "第一时间射门": {"shooting": 1.7, "movement": 0.4},
    "乐于反越位": {"movement": 2.2, "game_intelligence": 0.5},
    "弧线球射门": {"shooting": 1.5, "set_piece": 0.5},
    "用外脚背": {"ball_control": 1.0, "passing_creation": 0.5, "shooting": 0.4},
    "中路带球突进": {"ball_control": 1.4, "movement": 0.8, "speed": 0.6},
    "沿右路带球突进": {"ball_control": 1.2, "crossing": 0.8, "speed": 0.5},
    "沿左路带球突进": {"ball_control": 1.2, "crossing": 0.8, "speed": 0.5},
    "背身拿球": {"ball_control": 1.3, "power": 1.0, "passing_creation": 0.4},
    "喜欢通过长距离手抛球发起防守反击": {"keeper_distribution": 2.2},
    "拉边": {"movement": 1.0, "crossing": 0.9},
    "后排插上进攻": {"movement": 1.4, "shooting": 0.6},
    "尝试倒勾球": {"shooting": 0.8, "movement": 0.4},
    "主罚远距离任意球": {"set_piece": 2.0, "shooting": 0.5},
    "喜欢掷长距离界外球": {"set_piece": 0.8, "power": 0.5},
    "乐意把球传给位置更好的队友": {"passing_creation": 1.0, "game_intelligence": 1.0, "mentality": 0.5},
    "尽早传中": {"crossing": 1.4, "passing_creation": 0.4},
    "喜欢盘过门将后射门": {"shooting": 1.0, "ball_control": 0.8, "composure": 0.0},
    "喜欢过顶球吊射": {"shooting": 1.1, "technique": 0.0},
    "任意球大力攻门": {"set_piece": 1.3, "shooting": 0.8, "power": 0.5},
    "停球观察": {"ball_control": 0.8, "game_intelligence": 0.8},
    "用脚触球": {"keeper_distribution": 1.5, "ball_control": 0.5},
    "禁区杀手": {"shooting": 2.2, "movement": 1.0, "game_intelligence": 0.5},
    "禁区杀手（隐藏习惯）": {"shooting": 2.2, "movement": 1.0, "game_intelligence": 0.5},
    "避免使用弱势脚": {"ball_control": -0.6, "passing_creation": -0.4},
    "不喜欢倒地铲球": {"defending": -0.8},
    "尽量不带球": {"ball_control": -0.7, "movement": -0.3},
    "不喜欢传身后球": {"passing_creation": -0.8},
    "从不前插": {"movement": -0.9},
    "与裁判争论": {"mentality": -1.0, "game_intelligence": -0.5},
    "激怒对手": {"mentality": -0.8, "game_intelligence": -0.3},
    "鼓动观众情绪": {"mentality": 0.4},
    "倾向于尽可能长地延续自己的职业生涯（隐藏习惯）": {"mentality": 0.3},
}

TRAIT_RELEVANCE_BY_POS = {
    "GK": {
        "shot_stopping",
        "keeper_command",
        "keeper_distribution",
        "game_intelligence",
        "mobility",
        "mentality",
        "ball_control",
    },
    "CB": {
        "defending",
        "aerial_duel",
        "game_intelligence",
        "power",
        "passing_creation",
        "speed",
        "mentality",
        "ball_control",
    },
    "FB": {
        "defending",
        "speed",
        "crossing",
        "power",
        "passing_creation",
        "game_intelligence",
        "ball_control",
        "movement",
        "mentality",
        "set_piece",
    },
    "DM": {
        "defending",
        "passing_creation",
        "game_intelligence",
        "power",
        "ball_control",
        "aerial_duel",
        "shooting",
        "movement",
        "mentality",
    },
    "CM": {
        "passing_creation",
        "game_intelligence",
        "ball_control",
        "defending",
        "mobility",
        "mentality",
        "shooting",
        "movement",
        "set_piece",
    },
    "AM": {
        "passing_creation",
        "ball_control",
        "movement",
        "shooting",
        "game_intelligence",
        "speed",
        "mentality",
        "set_piece",
    },
    "WG": {
        "speed",
        "ball_control",
        "crossing",
        "shooting",
        "movement",
        "passing_creation",
        "power",
        "defending",
        "mentality",
        "set_piece",
    },
    "ST": {
        "shooting",
        "movement",
        "aerial_duel",
        "ball_control",
        "speed",
        "power",
        "passing_creation",
        "mentality",
        "set_piece",
    },
}

TRAIT_OVERALL_CAP = 4.0
TRAIT_OVERALL_FLOOR = -3.0


HEIGHT_CONTEXT_BY_POS = {
    "GK": {
        "reference": 190.0,
        "scale": 8.0,
        "cap": 1.5,
        "groups": {
            "keeper_command": 2.2,
            "shot_stopping": 0.6,
            "mobility": -0.5,
        },
    },
    "CB": {
        "reference": 186.0,
        "scale": 7.0,
        "cap": 1.4,
        "groups": {
            "aerial_duel": 2.2,
            "power": 0.9,
            "defending": 0.3,
            "speed": -0.35,
        },
    },
    "FB": {
        "reference": 181.0,
        "scale": 8.0,
        "cap": 1.2,
        "groups": {
            "aerial_duel": 0.8,
            "power": 0.5,
            "mobility": -0.5,
            "speed": -0.2,
        },
    },
    "DM": {
        "reference": 182.0,
        "scale": 8.0,
        "cap": 1.2,
        "groups": {
            "aerial_duel": 1.2,
            "power": 0.7,
            "defending": 0.25,
            "mobility": -0.2,
        },
    },
    "CM": {
        "reference": 181.0,
        "scale": 8.0,
        "cap": 1.0,
        "groups": {
            "aerial_duel": 0.6,
            "power": 0.3,
            "mobility": -0.15,
        },
    },
    "AM": {
        "reference": 180.0,
        "scale": 8.0,
        "cap": 1.0,
        "groups": {
            "aerial_duel": 0.4,
            "power": 0.2,
            "mobility": -0.15,
        },
    },
    "WG": {
        "reference": 178.0,
        "scale": 8.0,
        "cap": 1.1,
        "groups": {
            "aerial_duel": 0.4,
            "power": 0.3,
            "mobility": -0.5,
            "speed": -0.2,
        },
    },
    "ST": {
        "reference": 184.0,
        "scale": 8.0,
        "cap": 1.3,
        "groups": {
            "aerial_duel": 1.5,
            "power": 0.8,
            "mobility": -0.25,
            "speed": -0.15,
        },
    },
}


AGE_CONTEXT_BY_POS = {
    "GK": {
        "young_maturity": 1.0,
        "prime": 0.35,
        "experience": 0.8,
        "decline_start": 36,
        "speed_decline": 0.15,
        "mobility_decline": 0.35,
        "power_decline": 0.10,
    },
    "CB": {
        "young_maturity": 1.0,
        "prime": 0.45,
        "experience": 0.6,
        "decline_start": 33,
        "speed_decline": 0.35,
        "mobility_decline": 0.20,
        "power_decline": 0.20,
    },
    "FB": {
        "young_maturity": 1.0,
        "prime": 0.35,
        "experience": 0.25,
        "decline_start": 31,
        "speed_decline": 0.85,
        "mobility_decline": 0.65,
        "power_decline": 0.30,
    },
    "DM": {
        "young_maturity": 1.0,
        "prime": 0.45,
        "experience": 0.55,
        "decline_start": 32,
        "speed_decline": 0.45,
        "mobility_decline": 0.35,
        "power_decline": 0.25,
    },
    "CM": {
        "young_maturity": 1.0,
        "prime": 0.45,
        "experience": 0.45,
        "decline_start": 32,
        "speed_decline": 0.35,
        "mobility_decline": 0.35,
        "power_decline": 0.20,
    },
    "AM": {
        "young_maturity": 1.0,
        "prime": 0.40,
        "experience": 0.35,
        "decline_start": 31,
        "speed_decline": 0.45,
        "mobility_decline": 0.45,
        "power_decline": 0.20,
    },
    "WG": {
        "young_maturity": 0.9,
        "prime": 0.30,
        "experience": 0.20,
        "decline_start": 30,
        "speed_decline": 1.00,
        "mobility_decline": 0.85,
        "power_decline": 0.35,
    },
    "ST": {
        "young_maturity": 0.9,
        "prime": 0.35,
        "experience": 0.35,
        "decline_start": 31,
        "speed_decline": 0.60,
        "mobility_decline": 0.45,
        "power_decline": 0.25,
    },
}


def _attr_score(raw: dict[str, Any], key: str) -> float | None:
    if raw.get(key) in (None, ""):
        return None
    value = safe_int(raw.get(key))
    if value <= 0:
        return None
    return max(0.0, min(100.0, float(value) * 5.0))


def _weighted_score(raw: dict[str, Any], weights: dict[str, float], fallback: float = 50.0) -> float:
    total_w = 0.0
    total_v = 0.0
    for key, weight in weights.items():
        value = _attr_score(raw, key)
        if value is None:
            continue
        total_w += weight
        total_v += weight * value
    return total_v / total_w if total_w > 0 else fallback


def _score_from_groups(groups: dict[str, float], weights: dict[str, float], fallback: float = 50.0) -> float:
    total_w = 0.0
    total_v = 0.0
    for key, weight in weights.items():
        value = groups.get(key)
        if value is None:
            continue
        total_w += weight
        total_v += weight * value
    return total_v / total_w if total_w > 0 else fallback


def _clip_float(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _set_piece_score(raw: dict[str, Any]) -> float:
    values = [
        _attr_score(raw, "free_kick"),
        _attr_score(raw, "corners"),
        _attr_score(raw, "penalties"),
    ]
    numeric = [value for value in values if value is not None]
    return max(numeric) if numeric else 50.0


def _player_traits(raw: dict[str, Any]) -> list[str]:
    value = raw.get("player_traits") or raw.get("球员习惯") or ""
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = re.split(r"[\r\n]+", str(value))
    return [str(item).strip() for item in raw_items if str(item).strip()]


def _trait_adjustments(raw: dict[str, Any], position: str, groups: dict[str, float]) -> dict[str, Any]:
    traits = _player_traits(raw)
    if not traits:
        return {
            "group_adjustments": {},
            "overall_adjustment": 0.0,
            "applied": [],
            "trait_count": 0,
        }

    relevant = TRAIT_RELEVANCE_BY_POS.get(position, TRAIT_RELEVANCE_BY_POS["CM"])
    group_adjustments: dict[str, float] = defaultdict(float)
    applied: list[dict[str, Any]] = []
    for trait in traits:
        adjustments = TRAIT_SCORE_ADJUSTMENTS.get(trait)
        if adjustments is None and "（隐藏习惯）" in trait:
            adjustments = TRAIT_SCORE_ADJUSTMENTS.get(trait.replace("（隐藏习惯）", "").strip())
        if not adjustments:
            continue
        applied_groups = {}
        for group, delta in adjustments.items():
            if group not in relevant or group not in groups:
                continue
            group_adjustments[group] += float(delta)
            applied_groups[group] = float(delta)
        if applied_groups:
            applied.append({"trait": trait, "groups": applied_groups})

    clipped_adjustments = {
        group: _clip_float(value, -3.0, 3.0)
        for group, value in group_adjustments.items()
    }
    weights = POSITION_SCORE_WEIGHTS.get(position, POSITION_SCORE_WEIGHTS["CM"])
    weighted_delta = sum(clipped_adjustments.get(group, 0.0) * weight for group, weight in weights.items())
    overall_adjustment = _clip_float(weighted_delta, TRAIT_OVERALL_FLOOR, TRAIT_OVERALL_CAP)
    return {
        "group_adjustments": clipped_adjustments,
        "overall_adjustment": overall_adjustment,
        "applied": applied,
        "trait_count": len(traits),
    }


def _apply_trait_adjustments(groups: dict[str, float], adjustment: dict[str, Any]) -> dict[str, float]:
    adjusted = dict(groups)
    for group, delta in (adjustment.get("group_adjustments") or {}).items():
        if group not in adjusted:
            continue
        adjusted[group] = _clip_float(float(adjusted[group]) + float(delta), 0.0, 100.0)
    return adjusted


def _bounded_int(raw: dict[str, Any], key: str, lower: int, upper: int) -> int | None:
    value = safe_int(raw.get(key), default=0)
    if lower <= value <= upper:
        return value
    return None


def _weighted_context_delta(group_adjustments: dict[str, float], position: str) -> float:
    weights = POSITION_SCORE_WEIGHTS.get(position, POSITION_SCORE_WEIGHTS["CM"])
    return sum(group_adjustments.get(group, 0.0) * weight for group, weight in weights.items())


def _height_adjustments(raw: dict[str, Any], position: str, groups: dict[str, float]) -> dict[str, Any]:
    height_cm = _bounded_int(raw, "height_cm", 145, 220)
    if height_cm is None:
        return {"group_adjustments": {}, "overall_adjustment": 0.0, "height_cm": None}

    profile = HEIGHT_CONTEXT_BY_POS.get(position, HEIGHT_CONTEXT_BY_POS["CM"])
    height_index = _clip_float(
        (float(height_cm) - float(profile["reference"])) / float(profile["scale"]),
        -float(profile["cap"]),
        float(profile["cap"]),
    )
    group_adjustments = {
        group: _clip_float(height_index * float(multiplier), -3.0, 3.0)
        for group, multiplier in profile["groups"].items()
        if group in groups
    }
    return {
        "group_adjustments": group_adjustments,
        "overall_adjustment": _weighted_context_delta(group_adjustments, position),
        "height_cm": height_cm,
    }


def _age_adjustments(raw: dict[str, Any], position: str, groups: dict[str, float]) -> dict[str, Any]:
    age = _bounded_int(raw, "age", 15, 48)
    if age is None:
        return {"group_adjustments": {}, "overall_adjustment": 0.0, "age": None}

    profile = AGE_CONTEXT_BY_POS.get(position, AGE_CONTEXT_BY_POS["CM"])
    group_adjustments: dict[str, float] = defaultdict(float)

    if age <= 21:
        youth_penalty = _clip_float((22.0 - float(age)) * 0.55 * float(profile["young_maturity"]), 0.0, 2.5)
        group_adjustments["game_intelligence"] -= youth_penalty
        group_adjustments["mentality"] -= youth_penalty * 0.65
        if position == "GK":
            group_adjustments["keeper_command"] -= youth_penalty * 0.50
        elif position in {"CB", "DM"}:
            group_adjustments["defending"] -= youth_penalty * 0.25
    elif 24 <= age <= 30:
        prime_bonus = float(profile["prime"])
        group_adjustments["game_intelligence"] += prime_bonus
        group_adjustments["mentality"] += prime_bonus * 0.50
        if position in {"FB", "WG", "ST"}:
            group_adjustments["speed"] += 0.15
            group_adjustments["mobility"] += 0.15
        if position == "GK":
            group_adjustments["keeper_command"] += prime_bonus * 0.35
        elif position in {"CB", "DM"}:
            group_adjustments["defending"] += prime_bonus * 0.20
    elif age >= 31:
        experience_bonus = min((float(age) - 30.0) * 0.15 * float(profile["experience"]), 0.8)
        group_adjustments["game_intelligence"] += experience_bonus
        group_adjustments["mentality"] += experience_bonus * 0.80
        if position == "GK":
            group_adjustments["keeper_command"] += experience_bonus * 0.50
        elif position in {"CB", "DM"}:
            group_adjustments["defending"] += experience_bonus * 0.25

        decline_years = max(0.0, float(age) - float(profile["decline_start"]))
        physical_decline = _clip_float(decline_years * 0.45, 0.0, 3.0)
        group_adjustments["speed"] -= physical_decline * float(profile["speed_decline"])
        group_adjustments["mobility"] -= physical_decline * float(profile["mobility_decline"])
        group_adjustments["power"] -= physical_decline * float(profile["power_decline"])

    clipped_adjustments = {
        group: _clip_float(delta, -3.0, 3.0)
        for group, delta in group_adjustments.items()
        if group in groups
    }
    return {
        "group_adjustments": clipped_adjustments,
        "overall_adjustment": _weighted_context_delta(clipped_adjustments, position),
        "age": age,
    }


def _apply_group_adjustments(groups: dict[str, float], adjustment: dict[str, Any]) -> dict[str, float]:
    adjusted = dict(groups)
    for group, delta in (adjustment.get("group_adjustments") or {}).items():
        if group not in adjusted:
            continue
        adjusted[group] = _clip_float(float(adjusted[group]) + float(delta), 0.0, 100.0)
    return adjusted


def _role_scores(raw: dict[str, Any]) -> dict[str, float]:
    shot_stopping = _weighted_score(
        raw,
        {
            "gk_reflexes": 0.40,
            "gk_one_on_ones": 0.26,
            "gk_handling": 0.22,
            "gk_aerial_ability": 0.12,
        },
    )
    keeper_command = _weighted_score(
        raw,
        {
            "gk_aerial_ability": 0.25,
            "gk_command_of_area": 0.25,
            "gk_communication": 0.20,
            "gk_handling": 0.15,
            "gk_rushing_out": 0.15,
        },
    )
    keeper_distribution = _weighted_score(
        raw,
        {
            "gk_kicking": 0.35,
            "gk_throwing": 0.25,
            "passing": 0.20,
            "technique": 0.10,
            "decisions": 0.10,
        },
    )
    passing_creation = _weighted_score(
        raw,
        {
            "passing": 0.34,
            "vision": 0.24,
            "technique": 0.20,
            "decisions": 0.14,
            "first_touch": 0.08,
        },
    )
    ball_control = _weighted_score(
        raw,
        {
            "first_touch": 0.30,
            "technique": 0.28,
            "dribbling": 0.24,
            "agility": 0.10,
            "balance": 0.08,
        },
    )
    shooting = _weighted_score(
        raw,
        {
            "finishing": 0.36,
            "composure": 0.22,
            "off_the_ball": 0.16,
            "anticipation": 0.12,
            "technique": 0.08,
            "long_shots": 0.06,
        },
    )
    movement = _weighted_score(
        raw,
        {
            "off_the_ball": 0.30,
            "anticipation": 0.24,
            "acceleration": 0.14,
            "decisions": 0.12,
            "agility": 0.10,
            "flair": 0.05,
            "work_rate": 0.05,
        },
    )
    crossing = _weighted_score(
        raw,
        {
            "crossing": 0.38,
            "dribbling": 0.18,
            "technique": 0.14,
            "passing": 0.12,
            "vision": 0.08,
            "pace": 0.05,
            "acceleration": 0.05,
        },
    )
    defending = _weighted_score(
        raw,
        {
            "tackling": 0.28,
            "marking": 0.22,
            "positioning_def": 0.20,
            "anticipation": 0.14,
            "concentration": 0.10,
            "heading": 0.06,
        },
    )
    aerial_duel = _weighted_score(
        raw,
        {
            "heading": 0.30,
            "jumping": 0.24,
            "strength": 0.20,
            "bravery": 0.16,
            "balance": 0.10,
        },
    )
    speed = _weighted_score(raw, {"pace": 0.55, "acceleration": 0.45})
    mobility = _weighted_score(
        raw,
        {
            "agility": 0.34,
            "balance": 0.26,
            "acceleration": 0.20,
            "natural_fitness": 0.10,
            "pace": 0.10,
        },
    )
    power = _weighted_score(
        raw,
        {
            "strength": 0.36,
            "stamina": 0.24,
            "natural_fitness": 0.18,
            "jumping": 0.12,
            "work_rate": 0.10,
        },
    )
    game_intelligence = _weighted_score(
        raw,
        {
            "decisions": 0.25,
            "anticipation": 0.22,
            "concentration": 0.18,
            "teamwork": 0.14,
            "composure": 0.12,
            "vision": 0.09,
        },
    )
    mentality = _weighted_score(
        raw,
        {
            "work_rate": 0.24,
            "determination": 0.20,
            "bravery": 0.18,
            "teamwork": 0.16,
            "concentration": 0.12,
            "aggression": 0.10,
        },
    )
    return {
        "shot_stopping": shot_stopping,
        "keeper_command": keeper_command,
        "keeper_distribution": keeper_distribution,
        "passing_creation": passing_creation,
        "ball_control": ball_control,
        "shooting": shooting,
        "movement": movement,
        "crossing": crossing,
        "defending": defending,
        "aerial_duel": aerial_duel,
        "speed": speed,
        "mobility": mobility,
        "power": power,
        "game_intelligence": game_intelligence,
        "mentality": mentality,
        "set_piece": _set_piece_score(raw),
    }


def _position_score(raw: dict[str, Any], position: str) -> tuple[float, dict[str, float]]:
    groups = _role_scores(raw)
    height_adjustment = _height_adjustments(raw, position, groups)
    groups = _apply_group_adjustments(groups, height_adjustment)
    age_adjustment = _age_adjustments(raw, position, groups)
    groups = _apply_group_adjustments(groups, age_adjustment)
    trait_adjustment = _trait_adjustments(raw, position, groups)
    groups = _apply_trait_adjustments(groups, trait_adjustment)
    weights = POSITION_SCORE_WEIGHTS.get(position, POSITION_SCORE_WEIGHTS["CM"])
    context_adjustment = float(trait_adjustment["overall_adjustment"])
    score = _clip_float(_score_from_groups(groups, weights) + context_adjustment, 0.0, 100.0)
    groups["positional_overall"] = score
    groups["height_adjustment"] = float(height_adjustment["overall_adjustment"])
    groups["height_cm"] = height_adjustment["height_cm"]
    groups["age_adjustment"] = float(age_adjustment["overall_adjustment"])
    groups["age_years"] = age_adjustment["age"]
    groups["trait_adjustment"] = float(trait_adjustment["overall_adjustment"])
    groups["trait_count"] = int(trait_adjustment["trait_count"])
    groups["trait_applied"] = trait_adjustment["applied"]
    return score, groups


def compute_derived(raw: dict[str, Any], position: str) -> dict[str, Any]:
    overall, groups = _position_score(raw, position)
    attack = _score_from_groups(
        groups,
        {
            "shooting": 0.34,
            "movement": 0.22,
            "ball_control": 0.18,
            "passing_creation": 0.14,
            "speed": 0.08,
            "mentality": 0.04,
        },
    )
    defense = _score_from_groups(
        groups,
        {
            "defending": 0.58,
            "aerial_duel": 0.20,
            "game_intelligence": 0.14,
            "power": 0.08,
        },
    )
    pace = groups["speed"]
    finishing = groups["shooting"]
    passing = groups["passing_creation"]
    set_piece = groups["set_piece"]
    if position == "GK":
        gk = _score_from_groups(
            groups,
            {
                "shot_stopping": 0.68,
                "keeper_command": 0.27,
                "keeper_distribution": 0.05,
            },
        )
    else:
        gk = 0.0
    return {
        "overall": round(overall, 1),
        "attack": round(attack, 1),
        "defense": round(defense, 1),
        "pace": round(pace, 1),
        "finishing": round(finishing, 1),
        "passing": round(passing, 1),
        "set_piece": round(set_piece, 1),
        "gk": round(gk, 1),
        "role_scores": {
            key: round(value, 1) if isinstance(value, int | float) else value
            for key, value in groups.items()
        },
        "score_source": "attribute_role_trait_bio_weight_v3",
    }


def extract_player_name(raw_name: str) -> str:
    if not raw_name:
        return ""
    return re.sub(r"\s*\([^)]*\)\s*$", "", str(raw_name).strip().strip('"')).strip()


def row_value(row: dict[str, Any], *keys: str, default: str = "") -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return default


def row_name(row: dict[str, Any]) -> str:
    return extract_player_name(str(row_value(row, "name", "player_name", "姓名", "full_name", default="")))


def row_uid(row: dict[str, Any]) -> str:
    return str(row_value(row, "uid", "UID", "player_external_id", default="")).strip()


def row_club(row: dict[str, Any]) -> str:
    return str(row_value(row, "club", "俱乐部", "club_fm", default="")).strip()


def row_age(row: dict[str, Any]) -> int:
    return safe_int(row_value(row, "age", "年龄", default=0))


def row_ca(row: dict[str, Any]) -> int:
    return safe_int(row_value(row, "ca", "fm_ca", default=0))


def row_position(row: dict[str, Any]) -> str:
    return str(row_value(row, "position", "位置", "fm_position", default="")).strip()


def row_nationality(row: dict[str, Any]) -> str:
    return str(row_value(row, "nationality", "国籍", "nationality_raw", default="")).strip()


def normalize_club(raw_club: str) -> str:
    if not raw_club:
        return ""
    club = normalize(raw_club)
    noise = {
        "ac",
        "afc",
        "cf",
        "club",
        "de",
        "fc",
        "fk",
        "if",
        "rc",
        "sc",
        "sk",
        "the",
    }
    return " ".join(token for token in club.split() if token not in noise)


def meaningful_club(raw_club: str) -> bool:
    club = normalize_club(raw_club)
    return club not in {"", "unknown", "none", "na", "n", "a", "free agent"}


def token_sort_ratio(left: str, right: str) -> float:
    left_norm = normalize(left)
    right_norm = normalize(right)
    if not left_norm or not right_norm:
        return 0.0
    if rapidfuzz_fuzz is not None:
        return float(rapidfuzz_fuzz.token_sort_ratio(left_norm, right_norm))
    left_sorted = " ".join(sorted(left_norm.split()))
    right_sorted = " ".join(sorted(right_norm.split()))
    return SequenceMatcher(None, left_sorted, right_sorted).ratio() * 100


def _is_subset_match(md_tokens: set[str], csv_tokens: set[str]) -> bool:
    if min(len(md_tokens), len(csv_tokens)) < 2:
        return False
    return md_tokens.issubset(csv_tokens) or csv_tokens.issubset(md_tokens)


def _is_compound_match(md_name: str, csv_name: str) -> bool:
    md_compact = compact_name(md_name)
    csv_compact = compact_name(csv_name)
    if not md_compact or not csv_compact:
        return False
    return md_compact == csv_compact


def match_with_tiebreaker(md: dict[str, Any], csv_candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not csv_candidates:
        return {"status": "unmatched", "reason": "tier3_below_threshold"}
    if len(csv_candidates) == 1:
        candidate = csv_candidates[0]
        return {
            "status": "matched",
            "uid": row_uid(candidate),
            "row": candidate,
            "tie_breaker_score": 0,
        }

    md_club = str(row_value(md, "club", "fifa_club", default="")).strip()
    md_age = safe_int(row_value(md, "age", "fifa_age", default=0))
    md_position = str(row_value(md, "position", "fifa_position_class", default="")).strip()
    md_norm_club = normalize_club(md_club)
    age_diffs = []
    scored = []

    for candidate in csv_candidates:
        score = 0
        reasons = []
        candidate_club = row_club(candidate)
        candidate_norm_club = normalize_club(candidate_club)
        if meaningful_club(md_club) and meaningful_club(candidate_club):
            if normalize(md_club) == normalize(candidate_club):
                score += 3
                reasons.append("club_exact")
            elif md_norm_club and md_norm_club == candidate_norm_club:
                score += 2
                reasons.append("club_normalized")
        candidate_age = row_age(candidate)
        age_diff = abs(md_age - candidate_age) if md_age and candidate_age else None
        if age_diff is not None:
            age_diffs.append(age_diff)
        if md_position and row_position(candidate):
            if position_primary(md_position, row_position(candidate)) == normalize_position(row_position(candidate)):
                score += 1
                reasons.append("position")
        scored.append(
            {
                "row": candidate,
                "uid": row_uid(candidate),
                "score": score,
                "age_diff": age_diff,
                "ca": row_ca(candidate),
                "reasons": reasons,
            }
        )

    valid_age_diffs = [item["age_diff"] for item in scored if item["age_diff"] is not None]
    if valid_age_diffs:
        min_age_diff = min(valid_age_diffs)
        if min_age_diff <= 2:
            winners = [item for item in scored if item["age_diff"] == min_age_diff]
            if len(winners) == 1:
                winners[0]["score"] += 1
                winners[0]["reasons"].append("age")

    top_score = max(item["score"] for item in scored)
    top = [item for item in scored if item["score"] == top_score]
    if top_score == 0:
        return {
            "status": "ambiguous",
            "candidates": [item["uid"] for item in scored],
            "rows": [item["row"] for item in scored],
            "reason": "ambiguous",
        }
    if len(top) > 1:
        max_ca = max(item["ca"] for item in top)
        ca_top = [item for item in top if item["ca"] == max_ca]
        if len(ca_top) == 1 and max_ca > 0:
            top = ca_top
    if len(top) > 1:
        return {
            "status": "ambiguous",
            "candidates": [item["uid"] for item in top],
            "rows": [item["row"] for item in top],
            "reason": "ambiguous",
        }

    winner = top[0]
    return {
        "status": "matched",
        "uid": winner["uid"],
        "row": winner["row"],
        "tie_breaker_score": winner["score"],
        "tie_breaker_reasons": winner["reasons"],
    }


def three_tier_match(
    md: str | dict[str, Any],
    csv_candidates: list[dict[str, Any]],
    fuzzy_threshold: float = 88,
) -> dict[str, Any]:
    md_info = {"name": md} if isinstance(md, str) else dict(md)
    md_name = str(row_value(md_info, "name", "fifa_name_raw", default="")).strip()
    md_norm = normalize(md_name)
    md_tokens = token_set(md_norm)
    if len(md_tokens) < 1:
        return {"status": "unmatched", "reason": "name_format_anomaly"}

    enriched = []
    for candidate in csv_candidates:
        candidate_name = row_name(candidate)
        candidate_norm = normalize(candidate_name)
        candidate_tokens = token_set(candidate_norm)
        ratio = token_sort_ratio(md_name, candidate_name)
        enriched.append(
            {
                **candidate,
                "_match_name": candidate_name,
                "_match_norm": candidate_norm,
                "_match_tokens": candidate_tokens,
                "_match_ratio": round(ratio, 2),
            }
        )

    tiers = [
        (
            "tier1_exact",
            [
                candidate
                for candidate in enriched
                if candidate["_match_tokens"] == md_tokens or _is_compound_match(md_name, candidate["_match_name"])
            ],
        ),
        (
            "tier2_subset",
            [
                candidate
                for candidate in enriched
                if _is_subset_match(md_tokens, candidate["_match_tokens"])
            ],
        ),
        (
            "tier3_fuzzy",
            [
                candidate
                for candidate in enriched
                if candidate["_match_ratio"] >= fuzzy_threshold
            ],
        ),
    ]

    for tier_name, tier_candidates in tiers:
        if not tier_candidates:
            continue
        result = match_with_tiebreaker(md_info, tier_candidates)
        result["tier"] = tier_name
        result["candidate_count"] = len(tier_candidates)
        if result["status"] == "matched" and len(tier_candidates) > 1:
            result["ambiguous_resolved"] = True
        return result

    top3 = sorted(enriched, key=lambda item: item["_match_ratio"], reverse=True)[:3]
    return {
        "status": "unmatched",
        "reason": "tier3_below_threshold",
        "top3": [
            {
                "name": item["_match_name"],
                "uid": row_uid(item),
                "ratio": item["_match_ratio"],
                "club": row_club(item),
            }
            for item in top3
        ],
    }


def get_candidates_for_md_team(md_team_iso3: str, csv_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for row in csv_rows:
        for nationality in row_nationality(row).split(","):
            if nation_to_iso3(nationality.strip()) == md_team_iso3:
                candidates.append(row)
                break
    return candidates


def make_unique_headers(headers: list[str]) -> list[str]:
    counts: dict[str, int] = defaultdict(int)
    unique = []
    for header in headers:
        clean_header = header.strip()
        counts[clean_header] += 1
        if counts[clean_header] == 1:
            unique.append(clean_header)
        else:
            unique.append(f"{clean_header}__{counts[clean_header]}")
    return unique


def load_fm_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        headers = make_unique_headers(next(reader))
        rows = []
        for row in reader:
            padded = row + [""] * max(0, len(headers) - len(row))
            data = dict(zip(headers, padded[: len(headers)]))
            data["name"] = extract_player_name(data.get("姓名", ""))
            data["uid"] = str(data.get("UID", "")).strip()
            data["nationality"] = data.get("国籍", "")
            data["club"] = data.get("俱乐部", "")
            data["age"] = safe_int(data.get("年龄"))
            data["ca"] = safe_int(data.get("ca"))
            data["position"] = data.get("位置", "")
            rows.append(data)
    return rows


PLAYER_LINE_RE = re.compile(
    r"^- (\d+)号，(.+?)（(GK|DF|MF|FW)；(\d+)岁；国家队(\d+)场/(\d+)球；俱乐部：(.+?)(?: \(([A-Z]+)\))?）\s*$"
)


def parse_md(path: Path) -> tuple[list[MdPlayer], dict[str, TeamMeta], list[str]]:
    players: list[MdPlayer] = []
    metadata: dict[str, TeamMeta] = {}
    warnings: list[str] = []
    current_group = ""
    current_team: TeamMeta | None = None

    for line in path.read_text(encoding="utf-8").splitlines():
        group_match = re.match(r"^## ([A-L])组$", line)
        if group_match:
            current_group = group_match.group(1)
            current_team = None
            continue

        team_match = re.match(r"^### (.+)（([^（）]+)）\s*$", line)
        if team_match and current_group:
            team_zh = team_match.group(1).strip()
            team_fifa = team_match.group(2).strip()
            team_iso3 = FIFA_NAME_TO_ISO3.get(team_fifa)
            if not team_iso3:
                warnings.append(f"team_iso3_missing:{team_fifa}")
                current_team = None
                continue
            current_team = TeamMeta(
                team_fifa=team_fifa,
                team_zh=team_zh,
                team_iso3=team_iso3,
                group_label=current_group,
            )
            metadata[team_fifa] = current_team
            continue

        if current_team is None:
            continue

        if line.startswith("- 主教练："):
            current_team.head_coach = line.split("：", 1)[1].strip()
            continue
        if line.startswith("- 名单状态："):
            status = line.split("：", 1)[1].strip()
            current_team.squad_status = "final_26" if "最终" in status else "provisional"
            current_team.raw_tactics["squad_status_raw"] = status
            continue
        if line.startswith("- 关键球员："):
            raw_names = line.split("：", 1)[1].strip()
            current_team.key_player_names = [name.strip() for name in raw_names.split("、") if name.strip()]
            continue
        if line.startswith("- 执教风格："):
            coaching_style = line.split("：", 1)[1].strip()
            current_team.raw_tactics["coaching_style"] = coaching_style
            if not current_team.tactical_label:
                current_team.tactical_label = re.split(r"[，,。；;]", coaching_style, maxsplit=1)[0].strip()
            continue
        if line.startswith("- 战术重点："):
            current_team.raw_tactics["tactical_focus"] = line.split("：", 1)[1].strip()
            continue
        if line.startswith("- 主要可能使用阵型："):
            formation = line.split("：", 1)[1].strip()
            primary_match = re.search(r"主：(\d(?:-\d){2,3})", formation)
            if primary_match:
                current_team.formation_primary = primary_match.group(1)
            secondary_match = re.search(r"备：(.+)$", formation)
            if secondary_match:
                current_team.formation_secondary = [
                    item.strip()
                    for item in re.split(r"[、,，]", secondary_match.group(1))
                    if item.strip()
                ]
            continue

        quoted_style = re.search(r"「(.+?)」(.+)?", line)
        if quoted_style and "战术" in line:
            current_team.tactical_label = quoted_style.group(1).strip()
            current_team.raw_tactics["quoted_style"] = (quoted_style.group(2) or "").strip()

        player_match = PLAYER_LINE_RE.match(line)
        if player_match:
            players.append(
                MdPlayer(
                    team_fifa=current_team.team_fifa,
                    team_zh=current_team.team_zh,
                    team_iso3=current_team.team_iso3,
                    group_label=current_team.group_label,
                    shirt_number=safe_int(player_match.group(1)),
                    fifa_name_raw=player_match.group(2).strip(),
                    fifa_position_class=player_match.group(3).strip(),
                    fifa_age=safe_int(player_match.group(4)),
                    fifa_caps=safe_int(player_match.group(5)),
                    fifa_goals=safe_int(player_match.group(6)),
                    fifa_club=player_match.group(7).strip(),
                    fifa_club_league=(player_match.group(8) or "").strip(),
                )
            )

    for team_meta in metadata.values():
        pieces = []
        if team_meta.raw_tactics.get("coaching_style"):
            pieces.append(team_meta.raw_tactics["coaching_style"])
        if team_meta.raw_tactics.get("tactical_focus"):
            pieces.append(team_meta.raw_tactics["tactical_focus"])
        if team_meta.raw_tactics.get("quoted_style"):
            pieces.append(team_meta.raw_tactics["quoted_style"])
        team_meta.tactical_description = " ".join(pieces).strip()

    return players, metadata, warnings


def load_manual_overrides(path: Path | None) -> dict[tuple[str, int], dict[str, str]]:
    if not path or not path.exists():
        return {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {
            (row["team_fifa"].strip(), safe_int(row["shirt_number"])): row
            for row in csv.DictReader(handle)
            if row.get("team_fifa") and row.get("shirt_number") and row.get("manual_uid")
        }


def std_row(fm_row: dict[str, Any]) -> dict[str, Any]:
    return {std_key: str(fm_row.get(fm_key, "")).strip() for fm_key, std_key in FM_TO_STD.items()}


def json_scalar(value: Any) -> Any:
    if value is None:
        return ""
    text = str(value).strip()
    if text == "":
        return ""
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    return text


def ratings_json(fm_row: dict[str, Any]) -> str:
    return json.dumps({key: json_scalar(value) for key, value in fm_row.items()}, ensure_ascii=False, sort_keys=True)


def top3_candidates(candidates: list[dict[str, Any]], md_name: str) -> str:
    top = sorted(
        candidates,
        key=lambda item: token_sort_ratio(md_name, row_name(item)),
        reverse=True,
    )[:3]
    return json.dumps(
        [
            {
                "name": row_name(item),
                "uid": row_uid(item),
                "ratio": round(token_sort_ratio(md_name, row_name(item)), 2),
                "club": row_club(item),
            }
            for item in top
        ],
        ensure_ascii=False,
    )


def match_key_player_uids(team_meta: TeamMeta, matched_items: list[dict[str, Any]]) -> list[str]:
    key_uids = []
    for key_name in team_meta.key_player_names:
        best_item = None
        best_score = 0.0
        key_tokens = token_set(normalize(key_name))
        for item in matched_items:
            md_player: MdPlayer = item["md_player"]
            fm_row = item["fm_row"]
            names = [row_name(fm_row), md_player.fifa_name_raw]
            score = max(token_sort_ratio(key_name, candidate_name) for candidate_name in names)
            for candidate_name in names:
                candidate_tokens = token_set(normalize(candidate_name))
                if key_tokens and (
                    key_tokens == candidate_tokens or _is_subset_match(key_tokens, candidate_tokens)
                ):
                    score = max(score, 100.0)
            if score > best_score:
                best_score = score
                best_item = item
        if best_item and best_score >= 88:
            uid = row_uid(best_item["fm_row"])
            if uid and uid not in key_uids:
                key_uids.append(uid)
    return key_uids


def build_cleaned_row(md_player: MdPlayer, fm_row: dict[str, Any], key_player_uid: bool) -> dict[str, Any]:
    std = std_row(fm_row)
    std["age"] = md_player.fifa_age
    fm_position = std.get("fm_position", "")
    primary_position = position_primary(md_player.fifa_position_class, fm_position)
    ca = safe_int(std.get("fm_ca"))
    role = "starter" if key_player_uid else infer_role(ca, md_player.fifa_age)
    derived = compute_derived(std, primary_position)
    player_name = row_name(fm_row)
    return {
        "team_fifa": md_player.team_fifa,
        "team_iso3": md_player.team_iso3,
        "shirt_number": md_player.shirt_number,
        "player_name": player_name,
        "player_name_en": player_name,
        "player_external_id": row_uid(fm_row),
        "fifa_position_class": md_player.fifa_position_class,
        "fm_position": fm_position,
        "position_primary": primary_position,
        "age": md_player.fifa_age,
        "fm_ca": ca,
        "fm_pa": safe_int(std.get("fm_pa")),
        "club_fm": std.get("club", ""),
        "club_fifa": md_player.fifa_club,
        "height_cm": safe_int(std.get("height_cm")),
        "foot": infer_foot(safe_int(std.get("foot_left")), safe_int(std.get("foot_right"))),
        "expected_role": role,
        "expected_minutes_share": expected_minutes_share(role),
        "caps_intl": md_player.fifa_caps,
        "goals_intl": md_player.fifa_goals,
        "birth_date": std.get("birth_date", ""),
        "market_value": std.get("market_value", ""),
        "derived_overall": derived["overall"],
        "derived_attack": derived["attack"],
        "derived_defense": derived["defense"],
        "derived_pace": derived["pace"],
        "derived_finishing": derived["finishing"],
        "derived_passing": derived["passing"],
        "derived_set_piece": derived["set_piece"],
        "derived_gk": derived["gk"],
        "derived_role_scores": json.dumps(derived["role_scores"], ensure_ascii=False, sort_keys=True),
        "derived_score_source": derived["score_source"],
        "ratings_json": ratings_json(fm_row),
    }


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def validate_md_players(players: list[MdPlayer], metadata: dict[str, TeamMeta]) -> list[str]:
    warnings = []
    if len(metadata) != 48:
        raise ValueError(f"Expected 48 teams in MD, parsed {len(metadata)}")
    seen_numbers: set[tuple[str, int]] = set()
    by_team = Counter(player.team_fifa for player in players)
    for player in players:
        key = (player.team_fifa, player.shirt_number)
        if key in seen_numbers:
            raise ValueError(f"Duplicate shirt number in MD: {player.team_fifa} #{player.shirt_number}")
        seen_numbers.add(key)
    for team_fifa in FIFA_NAME_TO_ISO3:
        count = by_team.get(team_fifa, 0)
        if count == 0:
            raise ValueError(f"No players parsed for team {team_fifa}")
        if count != 26:
            warnings.append(f"{team_fifa} has {count} players in MD")
    return warnings


def clean(
    md_path: Path,
    csv_path: Path,
    output_matched: Path,
    output_unmatched: Path,
    output_team_metadata: Path,
    summary_path: Path,
    manual_overrides_path: Path | None = None,
    fuzzy_threshold: float = 88,
) -> dict[str, Any]:
    md_players, team_metadata, warnings = parse_md(md_path)
    warnings.extend(validate_md_players(md_players, team_metadata))

    fm_rows = load_fm_csv(csv_path)
    csv_by_uid = {row_uid(row): row for row in fm_rows if row_uid(row)}
    csv_index = {iso3: get_candidates_for_md_team(iso3, fm_rows) for iso3 in set(FIFA_NAME_TO_ISO3.values())}
    overrides = load_manual_overrides(manual_overrides_path)

    matched_items: list[dict[str, Any]] = []
    unmatched_rows: list[dict[str, Any]] = []
    by_tier: Counter[str] = Counter()
    unmatched_reasons: Counter[str] = Counter()
    ambiguous_resolved = 0
    used_team_uids: set[tuple[str, str]] = set()

    for md_player in md_players:
        override = overrides.get((md_player.team_fifa, md_player.shirt_number))
        candidates = csv_index.get(md_player.team_iso3, [])
        if not candidates:
            reason = "nation_not_in_csv"
            unmatched_reasons[reason] += 1
            unmatched_rows.append(
                {
                    "team_fifa": md_player.team_fifa,
                    "shirt_number": md_player.shirt_number,
                    "fifa_name": md_player.fifa_name_raw,
                    "fifa_position_class": md_player.fifa_position_class,
                    "fifa_age": md_player.fifa_age,
                    "fifa_club": md_player.fifa_club,
                    "reason": reason,
                    "top3_csv_candidates": "[]",
                }
            )
            continue

        if override:
            manual_uid = override["manual_uid"].strip()
            fm_row = csv_by_uid.get(manual_uid)
            if not fm_row:
                reason = "manual_uid_not_found"
                unmatched_reasons[reason] += 1
                unmatched_rows.append(
                    {
                        "team_fifa": md_player.team_fifa,
                        "shirt_number": md_player.shirt_number,
                        "fifa_name": md_player.fifa_name_raw,
                        "fifa_position_class": md_player.fifa_position_class,
                        "fifa_age": md_player.fifa_age,
                        "fifa_club": md_player.fifa_club,
                        "reason": reason,
                        "top3_csv_candidates": top3_candidates(candidates, md_player.fifa_name_raw),
                    }
                )
                continue
            match_result = {"status": "matched", "tier": "manual_override", "row": fm_row}
        else:
            match_result = three_tier_match(
                {
                    "name": md_player.fifa_name_raw,
                    "club": md_player.fifa_club,
                    "age": md_player.fifa_age,
                    "position": md_player.fifa_position_class,
                },
                candidates,
                fuzzy_threshold=fuzzy_threshold,
            )

        if match_result["status"] != "matched":
            reason = match_result.get("reason", match_result["status"])
            unmatched_reasons[reason] += 1
            top3 = match_result.get("top3")
            unmatched_rows.append(
                {
                    "team_fifa": md_player.team_fifa,
                    "shirt_number": md_player.shirt_number,
                    "fifa_name": md_player.fifa_name_raw,
                    "fifa_position_class": md_player.fifa_position_class,
                    "fifa_age": md_player.fifa_age,
                    "fifa_club": md_player.fifa_club,
                    "reason": reason,
                    "top3_csv_candidates": json.dumps(top3, ensure_ascii=False)
                    if top3 is not None
                    else top3_candidates(candidates, md_player.fifa_name_raw),
                }
            )
            continue

        fm_row = match_result["row"]
        uid = row_uid(fm_row)
        team_uid_key = (md_player.team_iso3, uid)
        if uid and team_uid_key in used_team_uids:
            reason = "duplicate_uid_match"
            unmatched_reasons[reason] += 1
            unmatched_rows.append(
                {
                    "team_fifa": md_player.team_fifa,
                    "shirt_number": md_player.shirt_number,
                    "fifa_name": md_player.fifa_name_raw,
                    "fifa_position_class": md_player.fifa_position_class,
                    "fifa_age": md_player.fifa_age,
                    "fifa_club": md_player.fifa_club,
                    "reason": reason,
                    "top3_csv_candidates": top3_candidates(candidates, md_player.fifa_name_raw),
                }
            )
            continue
        if uid:
            used_team_uids.add(team_uid_key)
        by_tier[match_result["tier"]] += 1
        if match_result.get("ambiguous_resolved"):
            ambiguous_resolved += 1
        matched_items.append({"md_player": md_player, "fm_row": fm_row, "match": match_result})

    matched_by_team: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in matched_items:
        matched_by_team[item["md_player"].team_fifa].append(item)

    for team_fifa, team_meta in team_metadata.items():
        team_meta.key_player_uids = match_key_player_uids(team_meta, matched_by_team.get(team_fifa, []))

    key_uid_by_team = {
        team_fifa: set(team_meta.key_player_uids)
        for team_fifa, team_meta in team_metadata.items()
    }
    matched_rows = [
        build_cleaned_row(
            item["md_player"],
            item["fm_row"],
            row_uid(item["fm_row"]) in key_uid_by_team.get(item["md_player"].team_fifa, set()),
        )
        for item in matched_items
    ]

    team_meta_rows = []
    for team_meta in team_metadata.values():
        team_meta_rows.append(
            {
                "team_fifa": team_meta.team_fifa,
                "team_iso3": team_meta.team_iso3,
                "team_zh": team_meta.team_zh,
                "group_label": team_meta.group_label,
                "head_coach": team_meta.head_coach,
                "formation_primary": team_meta.formation_primary,
                "formation_secondary": ",".join(team_meta.formation_secondary),
                "tactical_label": team_meta.tactical_label,
                "tactical_description": team_meta.tactical_description,
                "key_player_uids": ",".join(team_meta.key_player_uids),
                "squad_status": team_meta.squad_status or "final_26",
                "metadata_json": json.dumps(
                    {
                        "key_player_names": team_meta.key_player_names,
                        "raw_tactics": team_meta.raw_tactics,
                    },
                    ensure_ascii=False,
                ),
            }
        )

    write_csv(output_matched, MATCHED_FIELDS, matched_rows)
    write_csv(output_unmatched, UNMATCHED_FIELDS, unmatched_rows)
    write_csv(output_team_metadata, TEAM_METADATA_FIELDS, team_meta_rows)

    by_team = {}
    for team_fifa in sorted(team_metadata):
        total = sum(1 for player in md_players if player.team_fifa == team_fifa)
        matched = sum(1 for row in matched_rows if row["team_fifa"] == team_fifa)
        by_team[team_fifa] = {
            "total": total,
            "matched": matched,
            "unmatched": total - matched,
            "match_rate": round(matched / total, 4) if total else 0,
        }

    top5_per_team = {}
    for team_fifa in sorted(team_metadata):
        top5 = sorted(
            [row for row in matched_rows if row["team_fifa"] == team_fifa],
            key=lambda row: safe_int(row["fm_ca"]),
            reverse=True,
        )[:5]
        top5_per_team[team_fifa] = [
            {
                "name": row["player_name"],
                "uid": row["player_external_id"],
                "position": row["position_primary"],
                "ca": row["fm_ca"],
                "club": row["club_fifa"],
            }
            for row in top5
        ]

    gk_warnings = []
    for team_fifa, stats in by_team.items():
        team_rows = [row for row in matched_rows if row["team_fifa"] == team_fifa]
        if sum(1 for row in team_rows if row["fifa_position_class"] == "GK") < 2:
            gk_warnings.append(f"{team_fifa} has fewer than 2 matched GKs")
        if team_rows and max(float(row["derived_overall"]) for row in team_rows) < 65:
            gk_warnings.append(f"{team_fifa} max overall below 65")
    warnings.extend(gk_warnings)

    nations_with_matched_players = len({row["team_fifa"] for row in matched_rows})
    summary = {
        "input": {"md": str(md_path), "csv": str(csv_path)},
        "output": {
            "matched": str(output_matched),
            "unmatched": str(output_unmatched),
            "team_metadata": str(output_team_metadata),
        },
        "totals": {
            "md_players": len(md_players),
            "matched": len(matched_rows),
            "unmatched": len(unmatched_rows),
            "match_rate": round(len(matched_rows) / len(md_players), 4) if md_players else 0,
            "teams_total": len(team_metadata),
            "nations_covered": nations_with_matched_players,
        },
        "nations_covered": nations_with_matched_players,
        "nations_total": len(team_metadata),
        "by_tier": {
            "tier1_exact": by_tier.get("tier1_exact", 0),
            "tier2_subset": by_tier.get("tier2_subset", 0),
            "tier3_fuzzy": by_tier.get("tier3_fuzzy", 0),
            "manual_override": by_tier.get("manual_override", 0),
            "ambiguous_resolved": ambiguous_resolved,
        },
        "by_team": by_team,
        "unmatched_reasons": dict(unmatched_reasons),
        "warnings": warnings,
        "top5_per_team": top5_per_team,
        "llm_review_candidates": {
            "rows": len(unmatched_rows),
            "note": "Use unmatched top3 candidates for optional LLM-assisted manual override review.",
        },
    }

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=== WC2026 FM squad cleaning complete ===")
    print(f"MD players: {len(md_players)}")
    print(f"Matched: {len(matched_rows)}")
    print(f"Unmatched: {len(unmatched_rows)}")
    print(f"Match rate: {summary['totals']['match_rate']:.2%}")
    print(f"Nations covered: {nations_with_matched_players}/{len(team_metadata)}")
    print(f"Team metadata rows: {len(team_meta_rows)}")
    print(f"By tier: {summary['by_tier']}")
    if warnings:
        print(f"Warnings: {len(warnings)}")
        for warning in warnings[:10]:
            print(f"  - {warning}")
    print(f"Matched CSV: {output_matched}")
    print(f"Unmatched CSV: {output_unmatched}")
    print(f"Team metadata CSV: {output_team_metadata}")
    print(f"Summary JSON: {summary_path}")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--md", default="docs/sample/2026世界杯球队球员与战术报告.md")
    parser.add_argument("--csv", "--input", dest="csv_path", default="docs/球员属性.csv")
    parser.add_argument("--output-matched", "--output", dest="output_matched", default="data/wc2026_squads_cleaned.csv")
    parser.add_argument("--output-unmatched", dest="output_unmatched", default="data/wc2026_unmatched.csv")
    parser.add_argument("--output-team-metadata", dest="output_team_metadata", default="data/wc2026_team_metadata.csv")
    parser.add_argument("--summary", default="data/wc2026_cleaning_summary.json")
    parser.add_argument("--manual-overrides", default="data/wc2026_manual_overrides.csv")
    parser.add_argument("--fuzzy-threshold", type=float, default=88)
    args = parser.parse_args()

    manual_overrides = Path(args.manual_overrides) if args.manual_overrides else None
    clean(
        md_path=Path(args.md),
        csv_path=Path(args.csv_path),
        output_matched=Path(args.output_matched),
        output_unmatched=Path(args.output_unmatched),
        output_team_metadata=Path(args.output_team_metadata),
        summary_path=Path(args.summary),
        manual_overrides_path=manual_overrides,
        fuzzy_threshold=args.fuzzy_threshold,
    )


if __name__ == "__main__":
    main()

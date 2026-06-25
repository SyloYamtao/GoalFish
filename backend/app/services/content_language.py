"""LLM output-language instructions.

Model-generated natural language must follow the current UI locale selected by
the user, not the uploaded/project materials language.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select

from ..db.models import ProjectRecord
from ..db.session import get_session
from ..utils.locale import get_locale


CONTENT_LANGUAGE_INSTRUCTION_MARKER = "按当前界面语言输出"

_MAX_DETECTION_CHARS = 120_000

_SCRIPT_PATTERNS = {
    "ja_kana": re.compile(r"[\u3040-\u30ff]"),
    "hangul": re.compile(r"[\uac00-\ud7af]"),
    "han": re.compile(r"[\u4e00-\u9fff]"),
    "cyrillic": re.compile(r"[\u0400-\u04ff]"),
    "arabic": re.compile(r"[\u0600-\u06ff]"),
    "devanagari": re.compile(r"[\u0900-\u097f]"),
    "thai": re.compile(r"[\u0e00-\u0e7f]"),
    "latin": re.compile(r"[A-Za-z]"),
}

_LANGUAGE_NAMES = {
    "zh": ("中文", "Chinese"),
    "ja": ("日文", "Japanese"),
    "en": ("英文", "English"),
    "ko": ("韩文", "Korean"),
    "ru": ("俄文", "Russian"),
    "ar": ("阿拉伯文", "Arabic"),
    "hi": ("印地文", "Hindi"),
    "th": ("泰文", "Thai"),
    "es": ("西班牙文", "Spanish"),
    "fr": ("法文", "French"),
    "de": ("德文", "German"),
    "pt": ("葡萄牙文", "Portuguese"),
    "it": ("意大利文", "Italian"),
}

_LATIN_HINTS = {
    "es": (
        " el ",
        " la ",
        " los ",
        " las ",
        " que ",
        " del ",
        " una ",
        " partido ",
        " selección ",
        "méxico",
    ),
    "fr": (
        " le ",
        " la ",
        " les ",
        " des ",
        " une ",
        " avec ",
        " équipe ",
        " match ",
        "français",
    ),
    "de": (
        " der ",
        " die ",
        " das ",
        " und ",
        " mit ",
        " nicht ",
        " mannschaft ",
        " spiel ",
    ),
    "pt": (
        " o ",
        " a ",
        " os ",
        " as ",
        " que ",
        " uma ",
        " com ",
        " seleção ",
        "jogo",
    ),
    "it": (
        " il ",
        " la ",
        " gli ",
        " una ",
        " con ",
        " squadra ",
        " partita ",
    ),
}


@dataclass(frozen=True)
class ContentLanguage:
    code: str
    display_name_zh: str
    display_name_en: str
    confidence: float


def detect_content_language(materials: str | Iterable[str] | None) -> ContentLanguage:
    """Detect the primary language from uploaded/project materials."""

    text = _combined_materials(materials)
    if not text:
        return _language("en", confidence=0.0)

    kana = _count("ja_kana", text)
    hangul = _count("hangul", text)
    han = _count("han", text)
    cyrillic = _count("cyrillic", text)
    arabic = _count("arabic", text)
    devanagari = _count("devanagari", text)
    thai = _count("thai", text)
    latin = _count("latin", text)

    scores = {
        "ja": kana * 3.0 + han * 0.35,
        "zh": han * (0.95 if kana else 1.0),
        "ko": hangul * 2.0,
        "ru": cyrillic * 1.5,
        "ar": arabic * 1.5,
        "hi": devanagari * 1.5,
        "th": thai * 1.5,
        "en": latin * 0.8,
    }

    latin_lang = _detect_latin_language(text)
    if latin_lang != "en":
        scores[latin_lang] = max(scores.get(latin_lang, 0), latin * 0.9)
        scores["en"] = latin * 0.55

    code, score = max(scores.items(), key=lambda item: item[1])
    total = max(sum(value for value in scores.values() if value > 0), 1.0)
    if score <= 0:
        return _language("en", confidence=0.0)
    return _language(code, confidence=min(1.0, score / total))


def build_content_language_instruction(
    materials: str | Iterable[str] | None,
    *,
    locale: str | None = None,
) -> str:
    del materials
    language = current_content_language(locale)
    return content_language_instruction(language)


def content_language_instruction(language: ContentLanguage | str | None) -> str:
    if isinstance(language, str):
        language = current_content_language(language)
    elif language is not None:
        language = current_content_language(language.code)
    if language is None:
        language = current_content_language()
    return (
        f"内容语言要求（{CONTENT_LANGUAGE_INSTRUCTION_MARKER}）："
        "请严格根据当前用户在系统界面中选择的语言输出，不要根据上传材料、项目材料内容来判断输出语言。"
        f"当前用户选择的输出语言为：{language.display_name_zh}（{language.display_name_en}, {language.code}）。"
        f"所有面向用户的自然语言内容、报告段落、摘要、分析和问答回答应使用{language.display_name_zh}；"
        "即使上传材料本身是其他语言，也必须以该语言输出。"
        "专有名词、球队/球员名称、引用、JSON key、schema 字段和代码标识按原文或格式要求保留。"
    )


def instruction_for_project(project_id: str | None, fallback_materials: str | Iterable[str] | None = None) -> str:
    del project_id, fallback_materials
    return build_content_language_instruction(None)


def instruction_for_prediction_run(
    prediction_run_id: str | None,
    fallback_materials: str | Iterable[str] | None = None,
) -> str:
    del prediction_run_id, fallback_materials
    return build_content_language_instruction(None)


def current_content_language(locale: str | None = None) -> ContentLanguage:
    code = _content_locale_code(locale)
    return _language(code, confidence=1.0)


def project_materials(project_id: str | None) -> str:
    if not project_id:
        return ""
    with get_session() as session:
        project = session.get(ProjectRecord, project_id)
        if not project:
            return ""
        return _combined_materials(
            [
                project.simulation_requirement or "",
                project.extracted_text or "",
                project.analysis_summary or "",
                " ".join(
                    str(item.get("filename") or item.get("name") or "")
                    for item in (project.files or [])
                    if isinstance(item, dict)
                ),
            ]
        )


def project_materials_by_graph_id(graph_id: str | None) -> str:
    if not graph_id:
        return ""
    with get_session() as session:
        project_id = session.execute(
            select(ProjectRecord.project_id).where(ProjectRecord.graph_id == graph_id).limit(1)
        ).scalar_one_or_none()
    return project_materials(project_id)


def _combined_materials(materials: str | Iterable[str] | None) -> str:
    if materials is None:
        return ""
    if isinstance(materials, str):
        return materials[:_MAX_DETECTION_CHARS]
    parts: list[str] = []
    remaining = _MAX_DETECTION_CHARS
    for item in materials:
        if item is None:
            continue
        text = str(item)
        if not text:
            continue
        parts.append(text[:remaining])
        remaining -= len(parts[-1])
        if remaining <= 0:
            break
    return "\n".join(parts)


def _count(script: str, text: str) -> int:
    return len(_SCRIPT_PATTERNS[script].findall(text))


def _detect_latin_language(text: str) -> str:
    padded = f" {text.casefold()} "
    best_code = "en"
    best_score = 0
    for code, hints in _LATIN_HINTS.items():
        score = sum(padded.count(hint) for hint in hints)
        if score > best_score:
            best_code = code
            best_score = score
    return best_code


def _language(code: str, *, confidence: float) -> ContentLanguage:
    zh, en = _LANGUAGE_NAMES.get(code, (f"{code} 语言", code))
    return ContentLanguage(code=code, display_name_zh=zh, display_name_en=en, confidence=confidence)


def _content_locale_code(locale: str | None = None) -> str:
    raw = str(locale or get_locale() or "en").split(",", 1)[0].strip().lower()
    if "-" in raw:
        raw = raw.split("-", 1)[0]
    return "zh" if raw == "zh" else "en"

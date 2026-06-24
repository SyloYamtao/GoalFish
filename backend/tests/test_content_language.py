from __future__ import annotations

from app.services.content_language import (
    CONTENT_LANGUAGE_INSTRUCTION_MARKER,
    build_content_language_instruction,
    detect_content_language,
)


def test_content_language_instruction_detects_chinese_material():
    instruction = build_content_language_instruction(
        "日本队边路推进很强，但突尼斯中场拦截和定位球防守也很关键。"
    )

    assert CONTENT_LANGUAGE_INSTRUCTION_MARKER in instruction
    assert "中文" in instruction
    assert "前端 UI 语言" in instruction


def test_content_language_instruction_detects_japanese_material():
    instruction = build_content_language_instruction(
        "日本代表はサイド攻撃と中盤の連動が強みです。チュニジアは守備ブロックを重視します。"
    )

    assert CONTENT_LANGUAGE_INSTRUCTION_MARKER in instruction
    assert "日文" in instruction


def test_content_language_instruction_detects_english_material():
    instruction = build_content_language_instruction(
        "Japan are likely to press high, while Tunisia may rely on compact defending and set pieces."
    )

    assert CONTENT_LANGUAGE_INSTRUCTION_MARKER in instruction
    assert "英文" in instruction


def test_detect_content_language_prefers_primary_script_across_materials():
    result = detect_content_language(
        [
            "Short English filename: Japan vs Tunisia",
            "日本代表はサイド攻撃と中盤の連動が強みです。チュニジアは守備ブロックを重視します。",
        ]
    )

    assert result.code == "ja"
    assert result.display_name_zh == "日文"

from __future__ import annotations

from flask import Flask

from app.services.content_language import (
    CONTENT_LANGUAGE_INSTRUCTION_MARKER,
    build_content_language_instruction,
    detect_content_language,
)


def test_content_language_instruction_follows_chinese_ui_locale():
    app = Flask(__name__)
    with app.test_request_context("/", headers={"Accept-Language": "zh"}):
        instruction = build_content_language_instruction(
            "Japan are likely to press high, while Tunisia may defend in a compact block."
        )

    assert CONTENT_LANGUAGE_INSTRUCTION_MARKER in instruction
    assert "中文" in instruction
    assert "不要根据上传材料" in instruction


def test_content_language_instruction_follows_english_ui_locale():
    app = Flask(__name__)
    with app.test_request_context("/", headers={"Accept-Language": "en"}):
        instruction = build_content_language_instruction(
            "日本代表はサイド攻撃と中盤の連動が強みです。チュニジアは守備ブロックを重視します。"
        )

    assert CONTENT_LANGUAGE_INSTRUCTION_MARKER in instruction
    assert "英文" in instruction


def test_content_language_instruction_ignores_material_language_for_output_locale():
    app = Flask(__name__)
    with app.test_request_context("/", headers={"Accept-Language": "zh"}):
        instruction = build_content_language_instruction(
            "Japan are likely to press high, while Tunisia may rely on compact defending and set pieces."
        )

    assert CONTENT_LANGUAGE_INSTRUCTION_MARKER in instruction
    assert "中文" in instruction


def test_detect_content_language_prefers_primary_script_across_materials():
    result = detect_content_language(
        [
            "Short English filename: Japan vs Tunisia",
            "日本代表はサイド攻撃と中盤の連動が強みです。チュニジアは守備ブロックを重視します。",
        ]
    )

    assert result.code == "ja"
    assert result.display_name_zh == "日文"

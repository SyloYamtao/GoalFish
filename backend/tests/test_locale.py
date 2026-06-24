from flask import Flask

from app.utils.locale import get_locale


def test_request_locale_defaults_to_english_without_accept_language():
    app = Flask(__name__)

    with app.test_request_context("/"):
        assert get_locale() == "en"


def test_request_locale_only_allows_english_and_chinese():
    app = Flask(__name__)

    with app.test_request_context("/", headers={"Accept-Language": "zh"}):
        assert get_locale() == "zh"

    with app.test_request_context("/", headers={"Accept-Language": "en-US,en;q=0.9"}):
        assert get_locale() == "en"

    with app.test_request_context("/", headers={"Accept-Language": "ja"}):
        assert get_locale() == "en"

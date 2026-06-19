import logging
from datetime import datetime

from app.utils import logger as logger_module
from app.utils.logger import LogbackStyleFormatter


def make_record(name: str, level: int, line_number: int, message: str) -> logging.LogRecord:
    record = logging.LogRecord(
        name=name,
        level=level,
        pathname="/tmp/example.py",
        lineno=line_number,
        msg=message,
        args=(),
        exc_info=None,
    )
    record.created = datetime(2026, 6, 10, 9, 8, 7, 123000).timestamp()
    return record


def test_logback_style_formatter_matches_expected_layout(monkeypatch):
    monkeypatch.setattr(logger_module.os, "getpid", lambda: 4242)
    formatter = LogbackStyleFormatter()
    record = make_record(
        "goalfish.api.graph.generate_ontology",
        logging.INFO,
        123,
        "ontology generated",
    )

    formatted = formatter.format(record)

    assert formatted == (
        "2026-06-10 09:08:07.123  INFO 4242 [MainThread] "
        "[goalfish.api.graph.generate_ontology    :123] : ontology generated"
    )


def test_logback_style_formatter_uses_warn_level_name(monkeypatch):
    monkeypatch.setattr(logger_module.os, "getpid", lambda: 4242)
    formatter = LogbackStyleFormatter()
    record = make_record("goalfish.retry", logging.WARNING, 45, "retrying")

    formatted = formatter.format(record)

    assert " WARN 4242 " in formatted


def test_logback_style_formatter_abbreviates_long_logger_name(monkeypatch):
    monkeypatch.setattr(logger_module.os, "getpid", lambda: 4242)
    formatter = LogbackStyleFormatter()
    record = make_record(
        "goalfish.application.services.graphiti.ontology.generate.workflow",
        logging.ERROR,
        789,
        "failed",
    )

    formatted = formatter.format(record)

    assert (
        "[g.a.s.g.ontology.generate.workflow      :789] : failed"
        in formatted
    )

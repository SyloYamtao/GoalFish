from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.config import Config
from app.db.session import init_db, reset_engine


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


@pytest.fixture()
def postgres_db(monkeypatch) -> Iterator[str]:
    base_url = os.environ.get("TEST_DATABASE_URL") or Config.DATABASE_URL
    if not base_url:
        pytest.fail("Postgres DATABASE_URL 或 TEST_DATABASE_URL 未配置")
    if not base_url.startswith(("postgresql://", "postgresql+psycopg://", "postgresql+psycopg2://")):
        pytest.fail("测试数据库必须使用 Postgres")

    schema_name = f"test_{uuid.uuid4().hex}"
    admin_engine = create_engine(base_url, future=True, pool_pre_ping=True)
    quoted_schema = _quote_identifier(schema_name)

    with admin_engine.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {quoted_schema}"))

    url = make_url(base_url)
    query = dict(url.query)
    query["options"] = f"-csearch_path={schema_name}"
    test_url = url.set(query=query).render_as_string(hide_password=False)

    monkeypatch.setattr(Config, "DATABASE_URL", test_url)
    monkeypatch.setattr(Config, "SQLALCHEMY_ECHO", False)
    reset_engine()
    init_db()

    try:
        yield schema_name
    finally:
        reset_engine()
        with admin_engine.begin() as connection:
            connection.execute(text(f"DROP SCHEMA IF EXISTS {quoted_schema} CASCADE"))
        admin_engine.dispose()

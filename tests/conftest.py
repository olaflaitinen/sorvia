"""Test fixtures.

Unit tests need nothing. Integration tests (marked `integration`) need a
PostgreSQL 16 server with the pgvector and hypopg extensions, reachable through
SORVIA_TEST_ADMIN_DSN (a superuser DSN, e.g. postgresql://postgres:postgres@localhost:5432/postgres).
A fresh database is created for the session and dropped afterwards.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from sorvia.config import Settings

ROOT = Path(__file__).resolve().parents[1]
TEST_DSN = os.environ.get("SORVIA_TEST_ADMIN_DSN")
API_PW = os.environ.get("SORVIA_TEST_API_PASSWORD", "sorvia_api")
NL_PW = os.environ.get("SORVIA_TEST_NL_PASSWORD", "sorvia_nl")
USER_PW = "Test-Password-1"
TODAY = dt.date(2026, 11, 22)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if TEST_DSN:
        return
    skip = pytest.mark.skip(reason="SORVIA_TEST_ADMIN_DSN is not set")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


def _dsn(base: str, **overrides: str) -> str:
    params = conninfo_to_dict(base)
    params.update(overrides)
    return make_conninfo(**params)  # type: ignore[arg-type]


@pytest.fixture(scope="session")
def database() -> Iterator[dict[str, str]]:
    assert TEST_DSN
    name = f"sorvia_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(TEST_DSN, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    admin = _dsn(TEST_DSN, dbname=name)
    dsns = {
        "admin": admin,
        "app": _dsn(TEST_DSN, dbname=name, user="sorvia_api", password=API_PW),
        "reader": _dsn(TEST_DSN, dbname=name, user="sorvia_nl", password=NL_PW),
    }
    try:
        yield dsns
    finally:
        with psycopg.connect(TEST_DSN, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


@pytest.fixture(scope="session")
def settings(database: dict[str, str]) -> Settings:
    return Settings(
        admin_dsn=database["admin"],
        app_dsn=database["app"],
        reader_dsn=database["reader"],
        environment="test",
        llm_provider="static",
        static_sql_path=ROOT / "benchmark" / "data" / "az_text2sql_v1.jsonl",
        jwt_secret="test-secret-test-secret-test-secret-123",  # type: ignore[arg-type]
        fin_key="test-fin-key",  # type: ignore[arg-type]
        statement_timeout_ms=3000,
        pool_min_size=1,
        pool_max_size=4,
        rate_limit_per_minute=10_000,
    )


@pytest.fixture(scope="session")
def prepared(settings: Settings) -> Settings:
    """Migrated, seeded and indexed database with demo users."""
    from sorvia.cli import _create_user
    from sorvia.config import get_settings
    from sorvia.migrate import apply_migrations, bootstrap_roles
    from sorvia.nl2sql.embeddings import HashingEmbedder
    from sorvia.nl2sql.schema_index import rebuild
    from sorvia.seed.generator import SeedConfig, load

    apply_migrations(settings.admin_dsn, settings.migrations_dir)
    bootstrap_roles(settings.admin_dsn, API_PW, NL_PW, settings.statement_timeout_ms)
    with psycopg.connect(settings.admin_dsn, row_factory=psycopg.rows.dict_row) as conn:
        load(conn, SeedConfig(scale=0.1, seed=1, today=TODAY), settings.fin_key.get_secret_value())
        conn.execute("CALL analytics.refresh(true)")
        conn.commit()
        rebuild(conn, HashingEmbedder(settings.embedding_dim))

    # _create_user reads the cached global settings; point them at the test database.
    get_settings.cache_clear()
    os.environ["SORVIA_ADMIN_DSN"] = settings.admin_dsn
    for username, role, branch in (("admin", "admin", None), ("menecer", "manager", None),
                                   ("aysel.bak01", "pharmacist", "BAK01"), ("tural.gnc01", "pharmacist", "GNC01")):
        _create_user(username, USER_PW, username, role, branch)
    get_settings.cache_clear()
    return settings


@pytest.fixture()
def admin_conn(prepared: Settings) -> Iterator[psycopg.Connection[dict[str, object]]]:
    with psycopg.connect(prepared.admin_dsn, row_factory=psycopg.rows.dict_row) as conn:
        yield conn
        conn.rollback()

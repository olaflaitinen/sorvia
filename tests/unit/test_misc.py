from __future__ import annotations

import datetime as dt
from decimal import Decimal
from pathlib import Path

import jwt
import pytest

from sorvia.advisor.index_advisor import Candidate, Recommendation
from sorvia.api.deps import RateLimiter
from sorvia.config import Settings
from sorvia.evaluation import norm, relaxed_match, strict_match
from sorvia.executor import jsonable
from sorvia.migrate import MigrationError, discover
from sorvia.security import Principal, decode_token, hash_password, issue_token, verify_password

ROOT = Path(__file__).resolve().parents[2]


def test_password_hashing() -> None:
    encoded = hash_password("correct horse")
    assert encoded.startswith("scrypt$")
    assert verify_password("correct horse", encoded)
    assert not verify_password("wrong horse", encoded)
    assert not verify_password("x", "garbage")
    with pytest.raises(ValueError):
        hash_password("short")


def test_jwt_round_trip_and_expiry() -> None:
    p = Principal(7, "aysel", "pharmacist", 1)
    token = issue_token(p, "s" * 40, 5)
    assert decode_token(token, "s" * 40) == p
    with pytest.raises(jwt.InvalidSignatureError):
        decode_token(token, "t" * 40)
    expired = issue_token(p, "s" * 40, -1)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(expired, "s" * 40)


def test_principal_scope() -> None:
    assert Principal(1, "a", "admin", None).all_branches
    assert not Principal(1, "a", "manager", 3).all_branches
    assert not Principal(1, "a", "pharmacist", 3).all_branches


def test_production_settings_require_secrets() -> None:
    with pytest.raises(RuntimeError):
        Settings(environment="production").validate_for_production()
    Settings(environment="production", jwt_secret="x" * 40, fin_key="k" * 20).validate_for_production()  # type: ignore[arg-type]


def test_rate_limiter() -> None:
    limiter = RateLimiter(limit=2, window_s=60)
    assert limiter.allow("u") and limiter.allow("u")
    assert not limiter.allow("u")
    assert limiter.allow("other")


def test_norm_and_matching() -> None:
    assert norm(Decimal("1.005")) == norm(1.0049999) or norm(Decimal("1.5")) == "1.50"
    assert norm(dt.date(2026, 1, 2)) == "2026-01-02"
    gold = [["Bakı", Decimal("10.00")], ["Gəncə", Decimal("5")]]
    assert strict_match(gold, [[5.0, "Gəncə"], ["Bakı", 10]], ordered=False)
    assert not strict_match(gold, [["Gəncə", 5], ["Bakı", 10]], ordered=True)
    assert not strict_match(gold, [["Bakı", 10]], ordered=False)
    assert relaxed_match(gold, [["Bakı", "BAK", 10], ["Gəncə", "GNC", 5]], ordered=True)
    assert not relaxed_match(gold, [["Bakı", 11], ["Gəncə", 5]], ordered=False)
    assert relaxed_match([], [], ordered=False)


def test_relaxed_match_keeps_row_alignment() -> None:
    gold = [["a", 1], ["b", 2]]
    swapped = [["a", 2], ["b", 1]]   # same column multisets, wrong pairing
    assert not relaxed_match(gold, swapped, ordered=False)


def test_jsonable() -> None:
    assert jsonable(Decimal("2.50")) == 2.5
    assert jsonable(dt.date(2026, 1, 1)) == "2026-01-01"
    assert jsonable(dt.timedelta(minutes=1)) == 60.0
    assert jsonable([b"\x01", {"k": Decimal(1)}]) == ["01", {"k": 1.0}]


def test_candidate_ddl() -> None:
    c = Candidate("pharma", "prescription", ("doctor_id",))
    assert c.ddl() == ('CREATE INDEX CONCURRENTLY IF NOT EXISTS "sorvia_idx_prescription_doctor_id" '
                       'ON "pharma"."prescription" ("doctor_id")')
    p = Candidate("pharma", "sale", ("employee_id", "sold_at"), partitioned=True)
    assert "CONCURRENTLY" not in p.ddl()
    long = Candidate("pharma", "x" * 60, ("a", "b"))
    assert len(long.index_name) <= 63
    assert Recommendation(c, 10, 100.0, 80.0).improvement_pct == pytest.approx(20.0)


def test_migrations_are_well_formed() -> None:
    migrations = discover(ROOT / "db" / "migrations")
    assert [m.version for m in migrations] == list(range(1, len(migrations) + 1))
    assert all(len(m.checksum) == 64 for m in migrations)


def test_migration_discovery_rejects_unknown_files(tmp_path: Path) -> None:
    (tmp_path / "notes.sql").write_text("SELECT 1")
    with pytest.raises(MigrationError):
        discover(tmp_path)


def test_repository_text_policy() -> None:
    """Project rule: no em dash characters and no emoji anywhere in the repository."""
    banned = {chr(0x2014)}
    offenders = []
    for path in ROOT.rglob("*"):
        skip = {".git", "results", "__pycache__", ".venv", ".mypy_cache", "node_modules", "dist",
                ".ruff_cache", ".pytest_cache"}
        if not path.is_file() or any(part in skip for part in path.parts):
            continue
        if path.suffix.lower() in {".png", ".jpg", ".ico", ".pyc"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for ch in text:
            if ch in banned or 0x1F300 <= ord(ch) <= 0x1FAFF or 0x2600 <= ord(ch) <= 0x27BF:
                offenders.append(f"{path.relative_to(ROOT)}: U+{ord(ch):04X}")
                break
    assert not offenders, offenders


def test_dsns_are_derived_from_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("DATABASE_URL", "DATABASE_URL_UNPOOLED", "POSTGRES_URL", "POSTGRES_URL_NON_POOLING",
                "SORVIA_ADMIN_DSN", "SORVIA_APP_DSN", "SORVIA_READER_DSN"):
        monkeypatch.delenv(var, raising=False)
    s = Settings(
        database_url="postgresql://owner:pw@ep-x-pooler.neon.tech/db?sslmode=require",
        database_url_unpooled="postgresql://owner:pw@ep-x.neon.tech/db?sslmode=require",
        api_db_password="api-secret",  # type: ignore[arg-type]
        nl_db_password="nl-secret",  # type: ignore[arg-type]
    )
    assert "ep-x.neon.tech" in s.admin_dsn and "owner" in s.admin_dsn
    assert "user=sorvia_api" in s.app_dsn and "ep-x-pooler" in s.app_dsn and "api-secret" in s.app_dsn
    assert "user=sorvia_nl" in s.reader_dsn and "sslmode=require" in s.reader_dsn
    explicit = Settings(database_url="postgresql://o:p@h/db", app_dsn="postgresql://x@y/z",
                        api_db_password="a", nl_db_password="b")  # type: ignore[arg-type]
    assert explicit.app_dsn == "postgresql://x@y/z"


def test_secrets_are_derived_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("DATABASE_URL", "DATABASE_URL_UNPOOLED", "POSTGRES_URL", "POSTGRES_URL_NON_POOLING",
                "SORVIA_JWT_SECRET", "SORVIA_FIN_KEY", "SORVIA_API_DB_PASSWORD", "SORVIA_NL_DB_PASSWORD",
                "SORVIA_ADMIN_DSN", "SORVIA_APP_DSN", "SORVIA_READER_DSN"):
        monkeypatch.delenv(var, raising=False)
    a = Settings(database_url="postgresql://owner:secret-1@h/db", environment="production")
    b = Settings(database_url="postgresql://owner:secret-1@h/db", environment="production")
    c = Settings(database_url="postgresql://owner:secret-2@h/db", environment="production")
    a.validate_for_production()
    assert a.jwt_secret.get_secret_value() == b.jwt_secret.get_secret_value()
    assert a.jwt_secret.get_secret_value() != c.jwt_secret.get_secret_value()
    assert a.api_db_password is not None and a.nl_db_password is not None
    assert a.api_db_password.get_secret_value() != a.nl_db_password.get_secret_value()
    assert "user=sorvia_nl" in a.reader_dsn


def test_provider_urls_are_normalised(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("DATABASE_URL", "DATABASE_URL_UNPOOLED", "POSTGRES_URL", "POSTGRES_URL_NON_POOLING",
                "SORVIA_ADMIN_DSN", "SORVIA_APP_DSN", "SORVIA_READER_DSN"):
        monkeypatch.delenv(var, raising=False)
    s = Settings(database_url="postgres://postgres.abcref:pw@aws-0-eu.pooler.supabase.com:6543/postgres"
                              "?sslmode=require&supa=base-pooler.x&pgbouncer=true")
    assert " supa=" not in s.admin_dsn and "pgbouncer" not in s.admin_dsn and "sslmode=require" in s.admin_dsn
    assert "user=sorvia_api.abcref" in s.app_dsn and "user=sorvia_nl.abcref" in s.reader_dsn

"""Forward-only, checksummed SQL migrations.

Files are named VNNN__description.sql and applied in version order, each in its
own transaction. A checksum of every applied file is stored; if an applied file
is later edited the runner stops instead of silently diverging.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql

log = logging.getLogger(__name__)

_FILE_RE = re.compile(r"^V(?P<version>\d{3})__(?P<name>[a-z0-9_]+)\.sql$")
_LOCK_KEY = 0x50_52_56_41  # arbitrary constant for pg_advisory_lock


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()


class MigrationError(RuntimeError):
    pass


def discover(directory: Path) -> list[Migration]:
    migrations: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        match = _FILE_RE.match(path.name)
        if not match:
            raise MigrationError(f"Unexpected file in migrations directory: {path.name}")
        migrations.append(Migration(int(match["version"]), match["name"], path))
    versions = [m.version for m in migrations]
    if len(versions) != len(set(versions)):
        raise MigrationError("Duplicate migration versions")
    return migrations


def apply_migrations(dsn: str, directory: Path) -> list[Migration]:
    """Apply pending migrations. Returns the migrations that were applied."""
    migrations = discover(directory)
    applied_now: list[Migration] = []
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (_LOCK_KEY,))
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS public.sorvia_schema_migrations (
                    version    integer PRIMARY KEY,
                    name       text NOT NULL,
                    checksum   text NOT NULL,
                    applied_at timestamptz NOT NULL DEFAULT now()
                )
                """
            )
            rows = conn.execute("SELECT version, checksum FROM public.sorvia_schema_migrations").fetchall()
            applied = {int(r[0]): str(r[1]) for r in rows}

            for m in migrations:
                if m.version in applied:
                    if applied[m.version] != m.checksum:
                        raise MigrationError(
                            f"Checksum mismatch for applied migration V{m.version:03d} ({m.name}). "
                            "Applied migrations must never be edited; add a new one instead."
                        )
                    continue
                log.info("Applying V%03d %s", m.version, m.name)
                with conn.transaction():
                    conn.execute(m.path.read_text(encoding="utf-8"))
                    conn.execute("RESET search_path")
                    conn.execute(
                        "INSERT INTO public.sorvia_schema_migrations (version, name, checksum) "
                        "VALUES (%s, %s, %s)",
                        (m.version, m.name, m.checksum),
                    )
                applied_now.append(m)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (_LOCK_KEY,))
    return applied_now


def bootstrap_roles(dsn: str, api_password: str, reader_password: str, statement_timeout_ms: int) -> None:
    """Create or update the two login roles. Idempotent."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        for login, group, password in (
            ("sorvia_api", "sorvia_app", api_password),
            ("sorvia_nl", "sorvia_reader", reader_password),
        ):
            exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (login,)).fetchone()
            verb = sql.SQL("ALTER") if exists else sql.SQL("CREATE")
            conn.execute(
                sql.SQL("{} ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD {}").format(
                    verb, sql.Identifier(login), sql.Literal(password)
                )
            )
            conn.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(group), sql.Identifier(login)))
        # Backstop limits for the reader, independent of what the client sets.
        conn.execute(
            sql.SQL("ALTER ROLE sorvia_nl SET statement_timeout = {}").format(
                sql.Literal(f"{statement_timeout_ms * 2}ms")
            )
        )
        conn.execute("ALTER ROLE sorvia_nl SET search_path = pharma, analytics")
        conn.execute("ALTER ROLE sorvia_nl SET idle_in_transaction_session_timeout = '30s'")

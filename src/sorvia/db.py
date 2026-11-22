"""Connection pools for the three database identities."""

from __future__ import annotations

from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from sorvia.config import Settings


@dataclass
class Database:
    """Holds the application pool and the reader pool.

    The admin DSN is intentionally not pooled: it is used only by short-lived
    maintenance tasks (migrations, seeding, applying an index).
    """

    settings: Settings
    app: ConnectionPool
    reader: ConnectionPool

    @classmethod
    def open(cls, settings: Settings) -> Database:
        app = ConnectionPool(
            settings.app_dsn,
            min_size=settings.pool_min_size,
            max_size=settings.pool_max_size,
            # prepare_threshold=None: safe behind transaction-mode poolers (PgBouncer, Neon).
            kwargs={"row_factory": dict_row, "application_name": "sorvia-api", "prepare_threshold": None},
            open=True,
            name="sorvia-app",
        )
        reader = ConnectionPool(
            settings.reader_dsn,
            min_size=settings.pool_min_size,
            max_size=settings.pool_max_size,
            kwargs={"application_name": "sorvia-reader", "prepare_threshold": None},
            open=True,
            name="sorvia-reader",
        )
        return cls(settings=settings, app=app, reader=reader)

    def close(self) -> None:
        self.app.close()
        self.reader.close()

    def admin_connection(self) -> psycopg.Connection[dict[str, object]]:
        return connect_admin(self.settings)


def connect_admin(settings: Settings, autocommit: bool = False) -> psycopg.Connection[dict[str, object]]:
    return psycopg.connect(
        settings.admin_dsn,
        row_factory=dict_row,
        autocommit=autocommit,
        application_name="sorvia-admin",
    )

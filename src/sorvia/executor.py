"""Executes untrusted SQL inside a scoped, read-only, time-limited transaction.

Layer 2 (plan cost) and layer 3 (database enforcement) of the defence in depth.
"""

from __future__ import annotations

import datetime as dt
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

import psycopg
from psycopg import errors

from sorvia.config import Settings
from sorvia.db import Database


@dataclass(frozen=True)
class ExecutionResult:
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    estimated_cost: float | None
    db_ms: int


class ExecutionError(Exception):
    def __init__(self, code: str, message: str, estimated_cost: float | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.estimated_cost = estimated_cost


class CostLimitExceeded(ExecutionError):
    pass


class QueryTimeout(ExecutionError):
    pass


class ExecutionFailed(ExecutionError):
    """The database rejected or failed the query (syntax, missing column, privilege...)."""


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return value.total_seconds()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return bytes(value).hex()
    if isinstance(value, list | tuple):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    return str(value)


class ScopedExecutor:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def issue_ticket(self, user_id: int) -> uuid.UUID:
        with self.db.app.connection() as conn:
            row = conn.execute("SELECT sorvia.issue_scope_ticket(%s) AS ticket", (user_id,)).fetchone()
        assert row is not None
        return cast(uuid.UUID, row["ticket"])  # type: ignore[call-overload]

    def run(
        self,
        user_id: int,
        sql: str,
        params: tuple[Any, ...] | None = None,
        *,
        check_cost: bool = True,
        max_rows: int | None = None,
    ) -> ExecutionResult:
        limit = max_rows or self.settings.max_rows
        ticket = self.issue_ticket(user_id)
        query = sql
        cost: float | None = None
        start = time.perf_counter()
        try:
            with self.db.reader.connection() as conn, conn.transaction():
                conn.execute("SELECT sorvia.redeem_scope_ticket(%s)", (ticket,))
                conn.execute("SET LOCAL transaction_read_only = on")
                conn.execute("SELECT set_config('statement_timeout', %s, true)",
                             (f"{self.settings.statement_timeout_ms}ms",))
                conn.execute("SET LOCAL search_path = pharma, analytics")
                if check_cost:
                    plan_row = conn.execute("EXPLAIN (FORMAT JSON) " + sql, params).fetchone()
                    assert plan_row is not None
                    cost = float(plan_row[0][0]["Plan"]["Total Cost"])
                    if cost > self.settings.max_plan_cost:
                        raise CostLimitExceeded(
                            "cost_limit",
                            f"Estimated plan cost {cost:,.0f} exceeds the limit "
                            f"{self.settings.max_plan_cost:,.0f}. Narrow the question (period, branch, top N).",
                            cost,
                        )
                cur = conn.execute(query, params)
                columns = [d.name for d in cur.description or []]
                fetched = cur.fetchmany(limit + 1)
        except ExecutionError:
            raise
        except errors.QueryCanceled as exc:
            raise QueryTimeout("timeout", "The query exceeded the time limit", cost) from exc
        except errors.InsufficientPrivilege as exc:
            raise ExecutionFailed("insufficient_privilege", _message(exc), cost) from exc
        except psycopg.Error as exc:
            raise ExecutionFailed(exc.sqlstate or "database_error", _message(exc), cost) from exc

        truncated = len(fetched) > limit
        rows = [[jsonable(v) for v in r] for r in fetched[:limit]]
        return ExecutionResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            estimated_cost=cost,
            db_ms=int((time.perf_counter() - start) * 1000),
        )


def _message(exc: psycopg.Error) -> str:
    diag = exc.diag
    text = diag.message_primary or str(exc)
    if diag.message_hint:
        text += f" (hint: {diag.message_hint})"
    return text

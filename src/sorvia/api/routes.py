"""HTTP routes."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any, cast

import psycopg
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool

from sorvia.advisor.index_advisor import IndexAdvisor, apply_recommendation
from sorvia.api.deps import AdminDep, ManagerDep, PrincipalDep, ServicesDep
from sorvia.api.schemas import (
    AskRequest,
    AskResponse,
    FeedbackRequest,
    QueryLogItem,
    RecommendationOut,
    SaleRequest,
    SaleResponse,
    SchemaObject,
    TableResponse,
    TokenRequest,
    TokenResponse,
    TransferRequest,
    UserOut,
)
from sorvia.db import connect_admin
from sorvia.executor import ExecutionError, jsonable
from sorvia.security import DUMMY_HASH, Principal, issue_token, verify_password

router = APIRouter()

# SQLSTATE class SV: business rule violations raised by the database (V003).
BUSINESS_ERRORS = {
    "SV001": "expired_batch",
    "SV002": "prescription_required",
    "SV003": "insufficient_stock",
    "SV004": "invalid_employee",
    "SV005": "immutable_record",
}


def _business_error(exc: psycopg.Error) -> HTTPException:
    code = BUSINESS_ERRORS.get(exc.sqlstate or "")
    message = exc.diag.message_primary or str(exc)
    if code:
        return HTTPException(status.HTTP_409_CONFLICT, {"code": code, "message": message})
    if exc.sqlstate and exc.sqlstate.startswith("23"):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": "constraint_violation", "message": message})
    return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, {"code": "database_error", "message": "Database error"})


def _resolve_branch(principal: Principal, requested: int | None) -> int:
    if principal.branch_id is not None:
        if requested is not None and requested != principal.branch_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only act on your own branch")
        return principal.branch_id
    if requested is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "branch_id is required for your role")
    return requested


# -- health ------------------------------------------------------------------------


@router.get("/healthz", tags=["health"])
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", tags=["health"])
def readyz(svc: ServicesDep) -> dict[str, str]:
    try:
        with svc.db.app.connection() as conn:
            conn.execute("SELECT 1")
        with svc.db.reader.connection() as conn:
            conn.execute("SELECT 1")
    except psycopg.Error as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Database unavailable") from exc
    return {"status": "ready"}


@router.get("/v1/meta", tags=["health"])
def meta(svc: ServicesDep) -> dict[str, Any]:
    from sorvia import __version__

    s = svc.settings
    return {"version": __version__, "llm_provider": s.llm_provider, "llm_model": s.llm_model or None,
            "strategy": s.strategy, "max_rows": s.max_rows}


@router.get("/v1/suggestions", tags=["ask"])
def suggestions(principal: PrincipalDep, svc: ServicesDep, limit: int = Query(default=8, ge=1, le=60)) -> list[str]:
    """Example questions. With the offline provider these are exactly the questions it can answer."""
    path = svc.settings.static_sql_path
    if path is None or not path.exists():
        return []
    items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    picked = [i["question"] for i in items if i.get("difficulty") in ("easy", "medium")][::3][:limit]
    return picked or [i["question"] for i in items][:limit]


@router.get("/v1/suggestions/all", tags=["ask"])
def all_suggestions(principal: PrincipalDep, svc: ServicesDep) -> list[dict[str, str]]:
    path = svc.settings.static_sql_path
    if path is None or not path.exists():
        return []
    items = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [{"question": i["question"], "difficulty": i["difficulty"]} for i in items]


# -- auth --------------------------------------------------------------------------


@router.post("/v1/auth/token", response_model=TokenResponse, tags=["auth"])
def login(body: TokenRequest, svc: ServicesDep) -> TokenResponse:
    with svc.db.app.connection() as conn:
        row = conn.execute(
            "SELECT user_id, username, display_name, role::text AS role, branch_id, password_hash, is_active "
            "FROM sorvia.app_user WHERE username = %s",
            (body.username.lower(),),
        ).fetchone()
    valid = verify_password(body.password, str(row["password_hash"]) if row else DUMMY_HASH)  # type: ignore[call-overload]
    if not row or not valid or not row["is_active"]:  # type: ignore[call-overload]
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")
    user = UserOut(user_id=row["user_id"], username=row["username"], display_name=row["display_name"],  # type: ignore[call-overload]
                   role=row["role"], branch_id=row["branch_id"])  # type: ignore[call-overload]
    principal = Principal(user.user_id, user.username, user.role, user.branch_id)
    token = issue_token(principal, svc.settings.jwt_secret.get_secret_value(), svc.settings.jwt_ttl_minutes)
    return TokenResponse(access_token=token, expires_in=svc.settings.jwt_ttl_minutes * 60, user=user)


@router.get("/v1/me", response_model=UserOut, tags=["auth"])
def me(principal: PrincipalDep, svc: ServicesDep) -> UserOut:
    with svc.db.app.connection() as conn:
        row = conn.execute(
            "SELECT user_id, username, display_name, role::text AS role, branch_id FROM sorvia.app_user "
            "WHERE user_id = %s AND is_active", (principal.user_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User is no longer active")
    return UserOut(**row)  # type: ignore[arg-type]


# -- natural language --------------------------------------------------------------


@router.post("/v1/ask", response_model=AskResponse, tags=["ask"])
async def ask(body: AskRequest, principal: PrincipalDep, svc: ServicesDep) -> AskResponse:
    if not svc.limiter.allow(f"ask:{principal.user_id}"):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many questions; please wait a minute")
    r = await run_in_threadpool(svc.ask.ask, principal, body.question, body.strategy)
    return AskResponse(
        query_id=r.query_id, status=r.status, question=r.question, sql=r.sql,  # type: ignore[arg-type]
        columns=r.columns, rows=r.rows, row_count=r.row_count, truncated=r.truncated,
        reason_code=r.reason_code, message=r.message, relations=r.relations, strategy=r.strategy,
        repair_attempts=r.repair_attempts,
        timings_ms={"llm": r.llm_ms, "db": r.db_ms, "total": r.total_ms},
    )


@router.get("/v1/queries", response_model=list[QueryLogItem], tags=["ask"])
def list_queries(
    principal: PrincipalDep,
    svc: ServicesDep,
    status_filter: str | None = Query(default=None, alias="status", pattern="^(ok|blocked|error|timeout)$"),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[QueryLogItem]:
    own_only = principal.role == "pharmacist"
    with svc.db.app.connection() as conn:
        rows = conn.execute(
            """
            SELECT query_id, user_id, question, executed_sql, status::text AS status, block_reason,
                   error_message, strategy, repair_attempts, row_count, total_ms, created_at
              FROM sorvia.nl_query
             WHERE (%(own)s IS FALSE OR user_id = %(uid)s)
               AND (%(st)s::text IS NULL OR status::text = %(st)s)
             ORDER BY created_at DESC
             LIMIT %(lim)s
            """,
            {"own": own_only, "uid": principal.user_id, "st": status_filter, "lim": limit},
        ).fetchall()
    return [QueryLogItem(**r) for r in rows]  # type: ignore[arg-type]


@router.post("/v1/queries/{query_id}/feedback", status_code=status.HTTP_204_NO_CONTENT, tags=["ask"])
def feedback(query_id: int, body: FeedbackRequest, principal: PrincipalDep, svc: ServicesDep) -> None:
    with svc.db.app.connection() as conn:
        owner = conn.execute("SELECT user_id FROM sorvia.nl_query WHERE query_id = %s", (query_id,)).fetchone()
        if owner is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Query not found")
        if principal.role == "pharmacist" and owner["user_id"] != principal.user_id:  # type: ignore[call-overload]
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only rate your own questions")
        conn.execute(
            """
            INSERT INTO sorvia.query_feedback (query_id, user_id, is_correct, comment)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (query_id, user_id) DO UPDATE
               SET is_correct = EXCLUDED.is_correct, comment = EXCLUDED.comment, created_at = now()
            """,
            (query_id, principal.user_id, body.is_correct, body.comment),
        )


@router.get("/v1/schema", response_model=list[SchemaObject], tags=["ask"])
def schema(principal: PrincipalDep, svc: ServicesDep) -> list[SchemaObject]:
    with svc.db.app.connection() as conn:
        rows = conn.execute(
            "SELECT schema_name || '.' || object_name AS qualified, object_type AS kind, ddl_summary "
            "FROM sorvia.schema_doc ORDER BY schema_name, object_type, object_name"
        ).fetchall()
    return [SchemaObject(**r) for r in rows]  # type: ignore[arg-type]


# -- operations --------------------------------------------------------------------


@router.post("/v1/sales", response_model=SaleResponse, status_code=status.HTTP_201_CREATED, tags=["operations"])
def create_sale(body: SaleRequest, principal: PrincipalDep, svc: ServicesDep) -> SaleResponse:
    branch_id = _resolve_branch(principal, body.branch_id)
    items = json.dumps([i.model_dump() for i in body.items])
    try:
        with svc.db.app.connection() as conn, conn.transaction():
            conn.execute("SELECT set_config('sorvia.app_user', %s, true)", (principal.username,))
            row = conn.execute(
                "SELECT pharma.register_sale(%s::smallint, %s, %s::jsonb, %s, %s) AS sale_id",
                (branch_id, body.employee_id, items, body.customer_id, body.prescription_id),
            ).fetchone()
            sale_id = int(row["sale_id"])  # type: ignore[index, call-overload]
            header = conn.execute(
                "SELECT sold_at, branch_id, gross_amount, discount_amount, net_amount FROM pharma.sale "
                "WHERE sale_id = %s", (sale_id,),
            ).fetchone()
            lines = conn.execute(
                """
                SELECT si.line_no, b.drug_id, d.trade_name, si.batch_id, b.expires_on, si.quantity, si.unit_price
                  FROM pharma.sale_item si
                  JOIN pharma.batch b USING (batch_id) JOIN pharma.drug d USING (drug_id)
                 WHERE si.sale_id = %s ORDER BY si.line_no
                """, (sale_id,),
            ).fetchall()
    except psycopg.Error as exc:
        raise _business_error(exc) from exc
    assert header is not None
    return SaleResponse(
        sale_id=sale_id, sold_at=header["sold_at"], branch_id=header["branch_id"],  # type: ignore[call-overload]
        gross_amount=float(header["gross_amount"]), discount_amount=float(header["discount_amount"]),  # type: ignore[call-overload]
        net_amount=float(header["net_amount"]),  # type: ignore[call-overload]
        lines=[{k: jsonable(v) for k, v in ln.items()} for ln in lines],  # type: ignore[attr-defined]
    )


@router.post("/v1/transfers", status_code=status.HTTP_201_CREATED, tags=["operations"])
def create_transfer(body: TransferRequest, principal: PrincipalDep, svc: ServicesDep) -> dict[str, Any]:
    from_branch = _resolve_branch(principal, body.from_branch_id)
    try:
        with svc.db.app.connection() as conn, conn.transaction():
            conn.execute("SELECT set_config('sorvia.app_user', %s, true)", (principal.username,))
            conn.execute(
                "CALL pharma.transfer_stock(%s::smallint, %s::smallint, %s, %s, %s)",
                (from_branch, body.to_branch_id, body.batch_id, body.quantity, body.employee_id),
            )
    except psycopg.Error as exc:
        raise _business_error(exc) from exc
    return {"status": "ok", "from_branch_id": from_branch, "to_branch_id": body.to_branch_id,
            "batch_id": body.batch_id, "quantity": body.quantity}


def _scoped_table(
    svc: ServicesDep, principal: Principal, query: str, params: tuple[Any, ...] | None = None
) -> TableResponse:
    try:
        r = svc.executor.run(principal.user_id, query, params, check_cost=False)
    except ExecutionError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, {"code": exc.code, "message": exc.message}) from exc
    return TableResponse(columns=r.columns, rows=r.rows, row_count=r.row_count, truncated=r.truncated)


@router.get("/v1/stock/low", response_model=TableResponse, tags=["operations"])
def low_stock(principal: PrincipalDep, svc: ServicesDep) -> TableResponse:
    return _scoped_table(svc, principal,
                         "SELECT branch_name, trade_name, quantity, min_stock FROM pharma.v_low_stock "
                         "ORDER BY quantity::numeric / greatest(min_stock, 1), branch_name")


@router.get("/v1/stock/expiring", response_model=TableResponse, tags=["operations"])
def expiring(principal: PrincipalDep, svc: ServicesDep) -> TableResponse:
    return _scoped_table(svc, principal,
                         "SELECT branch_name, trade_name, lot_number, expires_on, days_left, quantity "
                         "FROM pharma.v_expiring_soon ORDER BY expires_on, branch_name")


@router.get("/v1/batches/{batch_id}/trace", response_model=TableResponse, tags=["operations"])
def trace_batch(batch_id: int, principal: PrincipalDep, svc: ServicesDep,
                at: dt.datetime | None = None) -> TableResponse:
    when = at or dt.datetime.now(dt.UTC)
    return _scoped_table(svc, principal,
                         "SELECT l.branch_id, b.name AS branch_name, l.quantity "
                         "FROM pharma.batch_location_at(%s, %s) l JOIN pharma.branch b USING (branch_id)",
                         (batch_id, when))


@router.post("/v1/analytics/refresh", tags=["operations"])
def refresh_analytics(principal: ManagerDep, svc: ServicesDep, full: bool = False) -> dict[str, Any]:
    with svc.db.app.connection() as conn:
        conn.execute("CALL analytics.refresh(%s)", (full,))
        row = conn.execute("SELECT count(*) AS facts FROM analytics.fact_sales").fetchone()
    return {"status": "ok", "facts": row["facts"] if row else 0}  # type: ignore[call-overload]


# -- monitoring and self-tuning ------------------------------------------------------


@router.get("/v1/stats", tags=["admin"])
def stats(principal: ManagerDep, svc: ServicesDep, days: int = Query(default=30, ge=1, le=365)) -> dict[str, Any]:
    with svc.db.app.connection() as conn:
        by_status = conn.execute(
            """
            SELECT status::text AS status, count(*) AS n,
                   round(avg(total_ms)) AS avg_ms,
                   percentile_disc(0.95) WITHIN GROUP (ORDER BY total_ms) AS p95_ms
              FROM sorvia.nl_query WHERE created_at > now() - make_interval(days => %s)
             GROUP BY status ORDER BY status
            """, (days,),
        ).fetchall()
        reasons = conn.execute(
            """
            SELECT block_reason, count(*) AS n FROM sorvia.nl_query
             WHERE status = 'blocked' AND created_at > now() - make_interval(days => %s)
             GROUP BY block_reason ORDER BY n DESC
            """, (days,),
        ).fetchall()
        accuracy = conn.execute(
            """
            SELECT count(*) AS rated, avg(is_correct::int)::float AS accuracy
              FROM sorvia.query_feedback WHERE created_at > now() - make_interval(days => %s)
            """, (days,),
        ).fetchone()
    return {
        "days": days,
        "by_status": [{k: jsonable(v) for k, v in cast(dict[str, Any], r).items()} for r in by_status],
        "blocked_reasons": [cast(dict[str, Any], r) for r in reasons],
        "feedback": {k: jsonable(v) for k, v in cast(dict[str, Any], accuracy or {}).items()},
    }


@router.get("/v1/advisor/recommendations", response_model=list[RecommendationOut], tags=["admin"])
def list_recommendations(principal: ManagerDep, svc: ServicesDep) -> list[RecommendationOut]:
    with svc.db.app.connection() as conn:
        rows = conn.execute(
            "SELECT recommendation_id, table_name, columns, index_ddl, workload_size, cost_before, cost_after, "
            "improvement_pct, status::text AS status, created_at FROM sorvia.index_recommendation "
            "ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
    return [RecommendationOut(**r) for r in rows]  # type: ignore[arg-type]


@router.post("/v1/advisor/run", response_model=list[RecommendationOut], tags=["admin"])
def run_advisor(principal: AdminDep, svc: ServicesDep) -> list[RecommendationOut]:
    with connect_admin(svc.settings, autocommit=True) as conn:
        workload = IndexAdvisor.workload_from_log(conn)
        recs = IndexAdvisor(conn).recommend(workload)
        IndexAdvisor.save(conn, recs)
    return list_recommendations(principal, svc)


@router.post("/v1/advisor/recommendations/{recommendation_id}/apply", tags=["admin"])
def apply(recommendation_id: int, principal: AdminDep, svc: ServicesDep) -> dict[str, str]:
    try:
        ddl = apply_recommendation(svc.settings.admin_dsn, recommendation_id, principal.user_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return {"status": "applied", "ddl": ddl}


@router.post("/v1/advisor/recommendations/{recommendation_id}/reject", tags=["admin"])
def reject(recommendation_id: int, principal: AdminDep, svc: ServicesDep) -> dict[str, str]:
    with svc.db.app.connection() as conn:
        row = conn.execute(
            "UPDATE sorvia.index_recommendation SET status = 'rejected', decided_at = now(), decided_by = %s "
            "WHERE recommendation_id = %s AND status = 'proposed' RETURNING recommendation_id",
            (principal.user_id, recommendation_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No open recommendation with this id")
    return {"status": "rejected"}

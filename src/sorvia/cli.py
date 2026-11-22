"""Command-line interface: `sorvia <command>`."""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import logging
import os
import sys
from typing import cast

from sorvia.config import get_settings


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )


def cmd_migrate(args: argparse.Namespace) -> int:
    from sorvia.migrate import apply_migrations

    s = get_settings()
    applied = apply_migrations(s.admin_dsn, s.migrations_dir)
    print(f"Applied {len(applied)} migration(s)." if applied else "Database is up to date.")
    return 0


def cmd_bootstrap_roles(args: argparse.Namespace) -> int:
    from sorvia.migrate import bootstrap_roles

    s = get_settings()
    api_pw = os.environ.get("SORVIA_API_DB_PASSWORD") or getpass.getpass("Password for sorvia_api: ")
    nl_pw = os.environ.get("SORVIA_NL_DB_PASSWORD") or getpass.getpass("Password for sorvia_nl: ")
    bootstrap_roles(s.admin_dsn, api_pw, nl_pw, s.statement_timeout_ms)
    print("Login roles sorvia_api and sorvia_nl are ready.")
    return 0


def _create_user(username: str, password: str, display: str, role: str, branch_code: str | None) -> int:
    from sorvia.db import connect_admin
    from sorvia.security import hash_password

    with connect_admin(get_settings()) as conn:
        branch_id = None
        if branch_code:
            row = conn.execute("SELECT branch_id FROM pharma.branch WHERE code = %s", (branch_code,)).fetchone()
            if row is None:
                raise SystemExit(f"Unknown branch code {branch_code}")
            branch_id = row["branch_id"]
        row = conn.execute(
            """
            INSERT INTO sorvia.app_user (username, password_hash, display_name, role, branch_id)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (username) DO UPDATE
               SET password_hash = EXCLUDED.password_hash, display_name = EXCLUDED.display_name,
                   role = EXCLUDED.role, branch_id = EXCLUDED.branch_id, is_active = true
            RETURNING user_id
            """,
            (username.lower(), hash_password(password), display, role, branch_id),
        ).fetchone()
        conn.commit()
    assert row is not None
    return int(cast(int, row["user_id"]))


def cmd_create_user(args: argparse.Namespace) -> int:
    password = os.environ.get("SORVIA_NEW_USER_PASSWORD") or getpass.getpass(f"Password for {args.username}: ")
    uid = _create_user(args.username, password, args.display_name or args.username, args.role, args.branch)
    print(f"User {args.username} saved (id {uid}).")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    from sorvia.db import connect_admin
    from sorvia.seed.generator import SeedConfig, load

    s = get_settings()
    cfg = SeedConfig(scale=args.scale, seed=args.seed,
                     today=dt.date.fromisoformat(args.today) if args.today else dt.date.today())
    with connect_admin(s) as conn:
        existing = conn.execute("SELECT count(*) AS n FROM pharma.branch").fetchone()
        if args.if_empty and existing and existing["n"]:
            print("Domain data already present; skipping seed.")
        else:
            counts = load(conn, cfg, s.fin_key.get_secret_value(), reset=args.reset)
            conn.execute("CALL analytics.refresh(true)")
            conn.commit()
            print(json.dumps(counts, indent=2))
    if args.demo_users:
        password = os.environ.get("SORVIA_DEMO_PASSWORD")
        if not password:
            raise SystemExit("Set SORVIA_DEMO_PASSWORD to create demo users")
        for username, display, role, branch in (
            ("admin", "Sistem administratoru", "admin", None),
            ("menecer", "Regional menecer", "manager", None),
            ("aysel.bak01", "Aysel Məmmədova (BAK01)", "pharmacist", "BAK01"),
            ("tural.gnc01", "Tural Həsənov (GNC01)", "pharmacist", "GNC01"),
        ):
            _create_user(username, password, display, role, branch)
        print("Demo users: admin, menecer, aysel.bak01, tural.gnc01")
    return 0


def cmd_index_schema(args: argparse.Namespace) -> int:
    from sorvia.db import connect_admin
    from sorvia.nl2sql.embeddings import build_embedder
    from sorvia.nl2sql.schema_index import rebuild

    s = get_settings()
    embedder = build_embedder(s.embedding_provider, s.embedding_dim, s.embedding_model, s.embedding_base_url,
                              s.embedding_api_key.get_secret_value() if s.embedding_api_key else None)
    with connect_admin(s) as conn:
        n = rebuild(conn, embedder)
    print(f"Indexed {n} relations with {embedder.model_name}.")
    return 0


def cmd_refresh_analytics(args: argparse.Namespace) -> int:
    from sorvia.db import connect_admin

    with connect_admin(get_settings(), autocommit=True) as conn:
        conn.execute("CALL analytics.refresh(%s)", (args.full,))
    print("Analytics refreshed.")
    return 0


def cmd_advisor(args: argparse.Namespace) -> int:
    from sorvia.advisor.index_advisor import IndexAdvisor
    from sorvia.db import connect_admin

    with connect_admin(get_settings(), autocommit=True) as conn:
        workload = IndexAdvisor.workload_from_log(conn, limit=args.limit)
        advisor = IndexAdvisor(conn, max_indexes=args.max_indexes, min_improvement_pct=args.min_gain)
        recs = advisor.recommend(workload)
        saved = IndexAdvisor.save(conn, recs)
    for r in recs:
        print(f"{r.improvement_pct:6.1f}%  {r.candidate.ddl()}")
    print(f"{len(recs)} recommendation(s), {saved} new, workload of {len(workload)} queries.")
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    from sorvia.api.app import build_services
    from sorvia.security import Principal

    s = get_settings()
    svc = build_services(s)
    try:
        with svc.db.app.connection() as conn:
            row = conn.execute("SELECT user_id, username, role::text AS role, branch_id FROM sorvia.app_user "
                               "WHERE username = %s", (args.user,)).fetchone()
        if row is None:
            raise SystemExit(f"Unknown user {args.user}")
        principal = Principal(row["user_id"], row["username"], row["role"], row["branch_id"])  # type: ignore[call-overload]
        r = svc.ask.ask(principal, args.question, args.strategy)
    finally:
        svc.db.close()
    print(f"status: {r.status}" + (f" ({r.reason_code}: {r.message})" if r.reason_code else ""))
    if r.sql:
        print(f"\n{r.sql}\n")
    if r.columns:
        print(" | ".join(r.columns))
        for row_ in r.rows[: args.max_rows]:
            print(" | ".join(str(v) for v in row_))
    return 0 if r.status == "ok" else 1


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("sorvia.api.app:create_app", factory=True, host=args.host, port=args.port,
                workers=args.workers, proxy_headers=True, log_level="info")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sorvia", description="Sorvia command-line tools")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("migrate", help="apply database migrations").set_defaults(func=cmd_migrate)
    sub.add_parser("bootstrap-roles", help="create the sorvia_api and sorvia_nl login roles").set_defaults(
        func=cmd_bootstrap_roles)

    u = sub.add_parser("create-user", help="create or update a platform user")
    u.add_argument("username")
    u.add_argument("--role", choices=["admin", "manager", "pharmacist"], required=True)
    u.add_argument("--branch", help="branch code, required for pharmacists (e.g. BAK01)")
    u.add_argument("--display-name")
    u.set_defaults(func=cmd_create_user)

    s = sub.add_parser("seed", help="generate synthetic data")
    s.add_argument("--scale", type=float, default=1.0, help="1.0 = 50 000 sales")
    s.add_argument("--seed", type=int, default=42)
    s.add_argument("--today", help="reference date YYYY-MM-DD (default: today)")
    s.add_argument("--reset", action="store_true",
                   help="truncate existing domain data first (also removes platform users and query logs)")
    s.add_argument("--if-empty", action="store_true", help="do nothing if domain data already exists")
    s.add_argument("--demo-users", action="store_true", help="create demo users (SORVIA_DEMO_PASSWORD)")
    s.set_defaults(func=cmd_seed)

    sub.add_parser("index-schema", help="rebuild the semantic layer embeddings").set_defaults(func=cmd_index_schema)

    r = sub.add_parser("refresh-analytics", help="load new sales into the star schema")
    r.add_argument("--full", action="store_true")
    r.set_defaults(func=cmd_refresh_analytics)

    a = sub.add_parser("advisor", help="run the index advisor on the logged workload")
    a.add_argument("--limit", type=int, default=200)
    a.add_argument("--max-indexes", type=int, default=3)
    a.add_argument("--min-gain", type=float, default=5.0)
    a.set_defaults(func=cmd_advisor)

    q = sub.add_parser("ask", help="ask a question from the terminal")
    q.add_argument("question")
    q.add_argument("--user", required=True)
    q.add_argument("--strategy", choices=["full_schema", "retrieval", "retrieval_fewshot"])
    q.add_argument("--max-rows", type=int, default=20)
    q.set_defaults(func=cmd_ask)

    v = sub.add_parser("serve", help="run the HTTP API")
    v.add_argument("--host", default="0.0.0.0")  # noqa: S104 - container default
    v.add_argument("--port", type=int, default=8000)
    v.add_argument("--workers", type=int, default=1)
    v.set_defaults(func=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    sys.exit(main())

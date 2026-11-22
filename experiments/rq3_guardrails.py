"""RQ3: How much protection does each safety layer provide?

For every attack in benchmark/data/adversarial_sql_v1.jsonl the script records
which layer stopped it, under two configurations:

  full stack   guard (AST policy) -> plan-cost check -> scoped read-only execution
  db only      ablation: the guard and the cost check are switched off; the SQL
               goes straight to the scoped read-only transaction

The false-positive rate is measured on the 60 benign gold queries of the
benchmark, which must all pass the full stack.

Optionally (--nl) the natural-language attacks in adversarial_nl_v1.jsonl are
sent through the complete pipeline including the language model.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from common import out_dir, write_csv
from sorvia.api.app import build_services
from sorvia.config import get_settings
from sorvia.executor import CostLimitExceeded, ExecutionFailed, QueryTimeout
from sorvia.guard import SqlRejected, check_sql
from sorvia.security import Principal

DATA = Path(__file__).resolve().parents[1] / "benchmark" / "data"

DB_LAYER = {
    "25006": "db_read_only_transaction",
    "42501": "db_privilege",
    "insufficient_privilege": "db_privilege",
    "42P01": "db_unknown_relation",
    "42883": "db_unknown_function",
    "0A000": "db_not_supported",
    "42601": "db_syntax",
}


def load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def principal_for(svc: Any, username: str) -> Principal:
    with svc.db.app.connection() as conn:
        row = conn.execute("SELECT user_id, username, role::text AS role, branch_id FROM sorvia.app_user "
                           "WHERE username = %s", (username,)).fetchone()
    if row is None:
        raise SystemExit(f"Unknown user {username}; run `sorvia seed --demo-users` first")
    return Principal(row["user_id"], row["username"], row["role"], row["branch_id"])


def execute(svc: Any, principal: Principal, sql: str, check_cost: bool = True) -> tuple[str, int | None]:
    try:
        result = svc.executor.run(principal.user_id, sql, check_cost=check_cost)
        return "executed", result.row_count
    except CostLimitExceeded:
        return "cost_limit", None
    except QueryTimeout:
        return "timeout", None
    except ExecutionFailed as exc:
        return DB_LAYER.get(exc.code, f"db_error_{exc.code}"), None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--user", default="aysel.bak01", help="branch-scoped user that plays the attacker")
    ap.add_argument("--nl", action="store_true", help="also run natural-language attacks through the LLM")
    args = ap.parse_args()

    settings = get_settings()
    if not args.nl:
        # No language model is needed for the SQL-level matrix.
        settings = settings.model_copy(update={"llm_provider": "static",
                                               "static_sql_path": DATA / "az_text2sql_v1.jsonl"})
    svc = build_services(settings)
    attacker = principal_for(svc, args.user)
    admin = principal_for(svc, "admin")
    policy = svc.ask.policy()
    out = out_dir("rq3_guardrails")

    attacks = load(DATA / "adversarial_sql_v1.jsonl")
    rows = []
    stopped_full = stopped_db = stopped_guard = 0
    for a in attacks:
        try:
            guarded = check_sql(a["sql"], policy)
            guard_verdict = "pass"
            full_outcome, full_rows = execute(svc, attacker, guarded.sql)
        except SqlRejected as exc:
            guard_verdict = f"guard_{exc.code}"
            full_outcome, full_rows = guard_verdict, None
        # Ablation: no guard and no plan-cost check, only the database itself.
        db_outcome, db_rows = execute(svc, attacker, a["sql"], check_cost=False)

        if a["expected"] == "scoped":
            # Must execute, and see only the attacker's own branch (one group).
            full_ok = full_outcome == "executed" and (full_rows or 0) <= 1
            db_ok = db_outcome == "executed" and (db_rows or 0) <= 1
        else:
            full_ok = full_outcome != "executed"
            db_ok = db_outcome != "executed"
        stopped_full += full_ok
        stopped_db += db_ok
        stopped_guard += guard_verdict != "pass"
        rows.append([a["id"], a["expected"], guard_verdict, full_outcome, full_rows, full_ok,
                     db_outcome, db_rows, db_ok])
        print(f"{a['id']:28s} guard={guard_verdict:28s} full={full_outcome:26s} db_only={db_outcome}")

    write_csv(out / "attack_matrix.csv",
              ["attack", "expected", "guard", "full_stack_outcome", "full_rows", "full_stack_safe",
               "db_only_outcome", "db_rows", "db_only_safe"], rows)

    benign = load(DATA / "az_text2sql_v1.jsonl")
    false_positive: list[list[Any]] = []
    for b in benign:
        try:
            guarded = check_sql(b["sql"], policy)
            outcome, _ = execute(svc, admin, guarded.sql)
        except SqlRejected as exc:
            outcome = f"guard_{exc.code}"
        if outcome != "executed":
            false_positive.append([b["id"], outcome])
    write_csv(out / "false_positives.csv", ["id", "outcome"], false_positive)

    n = len(attacks)
    summary = {
        "attacks": n,
        "safe_full_stack_pct": round(100 * stopped_full / n, 1),
        "safe_db_only_pct": round(100 * stopped_db / n, 1),
        "stopped_by_guard_pct": round(100 * stopped_guard / n, 1),
        "benign_queries": len(benign),
        "false_positive_pct": round(100 * len(false_positive) / len(benign), 1),
        "full_stack_outcomes": Counter(r[3] for r in rows),
        "db_only_outcomes": Counter(r[6] for r in rows),
    }

    if args.nl:
        nl_rows = []
        nl_attacks = load(DATA / "adversarial_nl_v1.jsonl")
        safe = 0
        for a in nl_attacks:
            r = svc.ask.ask(attacker, a["question"])
            ok = (r.status != "ok") if a["expected"] == "blocked" else (r.status == "ok" and r.row_count <= 1)
            safe += ok
            nl_rows.append([a["id"], a["question"], a["expected"], r.status, r.reason_code, r.row_count, ok, r.sql])
            print(f"{a['id']} {r.status:8s} {r.reason_code or '':22s} safe={ok}")
        write_csv(out / "nl_attacks.csv",
                  ["id", "question", "expected", "status", "reason", "rows", "safe", "sql"], nl_rows)
        summary["nl_attacks"] = len(nl_attacks)
        summary["nl_safe_pct"] = round(100 * safe / len(nl_attacks), 1)

    (out / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"Results: {out}")
    svc.db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

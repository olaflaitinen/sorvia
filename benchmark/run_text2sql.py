"""RQ1 / RQ2: Text-to-SQL accuracy by prompting strategy and language.

Usage
  python benchmark/run_text2sql.py --strategies full_schema retrieval retrieval_fewshot --langs az en

Every question is answered through the production pipeline (retrieval, prompt,
model, guard, scoped execution, repair). Gold answers are executed through the
same scoped executor, as the same user, on the same snapshot.

Outputs (in --out):
  predictions.jsonl  one record per (question, strategy, language)
  summary.csv        accuracy and latency per strategy x language x difficulty
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from sorvia.api.app import build_services
from sorvia.config import get_settings
from sorvia.evaluation import relaxed_match, strict_match
from sorvia.executor import ExecutionError
from sorvia.security import Principal

DEFAULT_DATASET = Path(__file__).parent / "data" / "az_text2sql_v1.jsonl"


def load_dataset(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    ap.add_argument("--strategies", nargs="+", default=["full_schema", "retrieval", "retrieval_fewshot"])
    ap.add_argument("--langs", nargs="+", choices=["az", "en"], default=["az", "en"])
    ap.add_argument("--user", default="admin", help="platform user to run as (all-branch scope)")
    ap.add_argument("--limit", type=int, default=0, help="only the first N questions")
    ap.add_argument("--out", type=Path, default=Path("benchmark/results") / time.strftime("%Y%m%d-%H%M%S"))
    args = ap.parse_args()

    settings = get_settings()
    svc = build_services(settings)
    args.out.mkdir(parents=True, exist_ok=True)
    data = load_dataset(args.dataset)
    if args.limit:
        data = data[: args.limit]

    with svc.db.app.connection() as conn:
        row = conn.execute("SELECT user_id, username, role::text AS role, branch_id FROM sorvia.app_user "
                           "WHERE username = %s", (args.user,)).fetchone()
    if row is None:
        print(f"Unknown user {args.user}", file=sys.stderr)
        return 2
    principal = Principal(row["user_id"], row["username"], row["role"], row["branch_id"])  # type: ignore[call-overload]

    gold_cache: dict[str, Any] = {}
    for item in data:
        try:
            gold_cache[item["id"]] = svc.executor.run(principal.user_id, item["sql"], check_cost=False,
                                                      max_rows=5000)
        except ExecutionError as exc:
            print(f"Gold query {item['id']} failed: {exc.message}", file=sys.stderr)
            return 2

    records: list[dict[str, Any]] = []
    with (args.out / "predictions.jsonl").open("w", encoding="utf-8") as out:
        for strategy in args.strategies:
            for lang in args.langs:
                for item in data:
                    question = item["question"] if lang == "az" else item["question_en"]
                    r = svc.ask.ask(principal, question, strategy)
                    gold = gold_cache[item["id"]]
                    ok = r.status == "ok"
                    rec = {
                        "id": item["id"], "difficulty": item["difficulty"], "strategy": strategy, "lang": lang,
                        "question": question, "status": r.status, "reason": r.reason_code,
                        "pred_sql": r.sql, "gold_sql": item["sql"],
                        "ex_strict": ok and strict_match(gold.rows, r.rows, item["ordered"]),
                        "ex_relaxed": ok and relaxed_match(gold.rows, r.rows, item["ordered"]),
                        "repairs": r.repair_attempts, "llm_ms": r.llm_ms, "db_ms": r.db_ms, "total_ms": r.total_ms,
                        "retrieved": r.retrieved,
                    }
                    records.append(rec)
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    mark = "+" if rec["ex_relaxed"] else "-"
                    print(f"[{strategy:17s} {lang}] {item['id']} {mark} {r.status}", flush=True)

    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        groups[(rec["strategy"], rec["lang"], rec["difficulty"])].append(rec)
        groups[(rec["strategy"], rec["lang"], "all")].append(rec)

    with (args.out / "summary.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["strategy", "lang", "difficulty", "n", "ex_strict", "ex_relaxed", "blocked", "errors",
                    "repairs", "median_total_ms"])
        for (strategy, lang, diff), recs in sorted(groups.items()):
            n = len(recs)
            w.writerow([
                strategy, lang, diff, n,
                round(sum(r["ex_strict"] for r in recs) / n, 4),
                round(sum(r["ex_relaxed"] for r in recs) / n, 4),
                sum(r["status"] == "blocked" for r in recs),
                sum(r["status"] in ("error", "timeout") for r in recs),
                sum(r["repairs"] for r in recs),
                int(statistics.median(r["total_ms"] for r in recs)),
            ])
    print(f"\nResults written to {args.out}")
    print((args.out / "summary.csv").read_text(encoding="utf-8"))
    svc.db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""RQ4: Does the workload-driven index advisor reduce real query latency?

Procedure
  1. Remove indexes created by earlier runs (name prefix sorvia_idx_).
  2. Build the workload: the 60 benchmark gold queries plus operational lookups
     that a pharmacy runs all day (prescriptions of a doctor, sales of an
     employee, a customer by name, the prescriptions that contain a drug).
  3. Baseline: estimated cost and measured latency (EXPLAIN ANALYZE) per query.
  4. Run the advisor (hypothetical indexes, greedy selection) and apply its
     recommendations.
  5. Re-measure and report per-query and total improvement.
  6. Drop the created indexes unless --keep is given.

The gap between estimated (what-if) and measured gains is itself a result: it
shows how far the optimizer's cost model can be trusted for index selection.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

from common import connect, estimated_cost, measure, out_dir, save_environment, try_plot, write_csv
from sorvia.advisor.index_advisor import IndexAdvisor

DATA = Path(__file__).resolve().parents[1] / "benchmark" / "data"


def operational_workload(conn: Any, n: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    doctors = [r[0] for r in conn.execute("SELECT doctor_id FROM pharma.doctor").fetchall()]
    employees = [r[0] for r in conn.execute("SELECT employee_id FROM pharma.employee").fetchall()]
    names = conn.execute("SELECT DISTINCT first_name, last_name FROM pharma.customer LIMIT 500").fetchall()
    drugs = [r[0] for r in conn.execute("SELECT drug_id FROM pharma.drug WHERE requires_prescription").fetchall()]
    queries = []
    for _ in range(n):
        kind = rng.randrange(4)
        if kind == 0:
            queries.append(f"SELECT prescription_id, issued_on, valid_until FROM pharma.prescription "
                           f"WHERE doctor_id = {rng.choice(doctors)} ORDER BY issued_on DESC LIMIT 50")
        elif kind == 1:
            queries.append(f"SELECT sale_id, sold_at, net_amount FROM pharma.sale WHERE employee_id = "
                           f"{rng.choice(employees)} AND sold_at >= now() - interval '30 days'")
        elif kind == 2:
            first, last = rng.choice(names)
            queries.append(f"SELECT customer_id, phone, bonus_points FROM pharma.customer "
                           f"WHERE last_name = '{last}' AND first_name = '{first}'")
        else:
            queries.append(f"SELECT p.prescription_id, p.issued_on FROM pharma.prescription_item pi "
                           f"JOIN pharma.prescription p ON p.prescription_id = pi.prescription_id "
                           f"WHERE pi.drug_id = {rng.choice(drugs)} LIMIT 100")
    return queries


def drop_advisor_indexes(conn: Any) -> list[str]:
    names = [r[0] for r in conn.execute(
        "SELECT schemaname || '.' || indexname FROM pg_indexes WHERE indexname LIKE 'sorvia\\_idx\\_%'"
    ).fetchall()]
    for name in names:
        schema, _, index = name.partition(".")
        conn.execute(f'DROP INDEX IF EXISTS "{schema}"."{index}"')
    return names


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--operational", type=int, default=40, help="number of operational lookups")
    ap.add_argument("--runs", type=int, default=7)
    ap.add_argument("--max-indexes", type=int, default=5)
    ap.add_argument("--min-gain", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--objective", choices=["relative", "total"], default="relative")
    ap.add_argument("--keep", action="store_true", help="keep the created indexes")
    args = ap.parse_args()

    out = out_dir("rq4_index_advisor")
    conn = connect()
    save_environment(out, conn)
    conn.execute("SET search_path = pharma, analytics, public")
    dropped = drop_advisor_indexes(conn)
    if dropped:
        print(f"Dropped indexes from a previous run: {dropped}")
    conn.execute("ANALYZE")

    gold = [json.loads(x)["sql"] for x in (DATA / "az_text2sql_v1.jsonl").read_text(encoding="utf-8").splitlines() if x]
    workload = gold + operational_workload(conn, args.operational, args.seed)
    print(f"Workload: {len(gold)} analytical + {args.operational} operational queries")

    def snapshot(label: str) -> list[dict[str, float]]:
        res = []
        for i, q in enumerate(workload):
            m = measure(conn, q, runs=args.runs, warmup=1)
            res.append({"cost": estimated_cost(conn, q), **m})
            if (i + 1) % 20 == 0:
                print(f"  {label}: {i + 1}/{len(workload)}")
        return res

    before = snapshot("before")
    advisor = IndexAdvisor(conn, max_indexes=args.max_indexes, min_improvement_pct=args.min_gain,
                           objective=args.objective)
    recs = advisor.recommend(workload)
    for r in recs:
        print(f"recommend {r.improvement_pct:5.1f}% (est.)  {r.candidate.ddl()}")
        conn.execute(r.candidate.ddl())
    conn.execute("ANALYZE")
    after = snapshot("after")

    rows = []
    for i, (q, b, a) in enumerate(zip(workload, before, after, strict=True)):
        rows.append([i, "analytical" if i < len(gold) else "operational", round(b["cost"], 1), round(a["cost"], 1),
                     round(b["median_ms"], 3), round(a["median_ms"], 3),
                     round(b["median_ms"] / a["median_ms"], 2) if a["median_ms"] > 0 else None, q])
    write_csv(out / "per_query.csv", ["i", "kind", "cost_before", "cost_after", "ms_before", "ms_after",
                                      "speedup", "sql"], rows)

    def total(xs: list[dict[str, float]], key: str, kind: str | None = None) -> float:
        return sum(x[key] for i, x in enumerate(xs)
                   if kind is None or (kind == "analytical") == (i < len(gold)))

    summary: dict[str, Any] = {
        "workload_size": len(workload),
        "objective": args.objective,
        "recommendations": [
            {"ddl": r.candidate.ddl(), "estimated_gain_pct": round(r.improvement_pct, 2)} for r in recs
        ],
        "estimated_cost_reduction_pct": round(100 * (1 - total(after, "cost") / total(before, "cost")), 2),
        "measured_latency_reduction_pct": round(100 * (1 - total(after, "median_ms") / total(before, "median_ms")), 2),
    }
    for kind in ("analytical", "operational"):
        summary[f"{kind}_latency_ms_before"] = round(total(before, "median_ms", kind), 2)
        summary[f"{kind}_latency_ms_after"] = round(total(after, "median_ms", kind), 2)
        summary[f"{kind}_latency_reduction_pct"] = round(
            100 * (1 - total(after, "median_ms", kind) / total(before, "median_ms", kind)), 2)
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))

    plt = try_plot()
    if plt is not None:
        fig, ax = plt.subplots(figsize=(7, 4))
        labels = ["Analitik", "Əməliyyat"]
        b_vals = [summary["analytical_latency_ms_before"], summary["operational_latency_ms_before"]]
        a_vals = [summary["analytical_latency_ms_after"], summary["operational_latency_ms_after"]]
        x = range(len(labels))
        ax.bar([i - 0.2 for i in x], b_vals, width=0.4, label="İndekssiz", color="#9aa5b1")
        ax.bar([i + 0.2 for i in x], a_vals, width=0.4, label="Tövsiyədən sonra", color="#2f6fde")
        ax.set_xticks(list(x), labels)
        ax.set_ylabel("Ümumi median gecikmə (ms)")
        ax.set_title("RQ4: İndeks məsləhətçisinin təsiri")
        ax.legend(frameon=False)
        fig.tight_layout()
        fig.savefig(out / "rq4_latency.png", dpi=160)

    if not args.keep:
        drop_advisor_indexes(conn)
    print(f"Results: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

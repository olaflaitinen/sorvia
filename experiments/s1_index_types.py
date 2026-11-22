"""S1: B-tree versus BRIN on an append-only, time-ordered ledger.

A synthetic event table (default 2 000 000 rows, physically ordered by time,
like pharma.batch_movement) is created in the `lab` schema. For each index
configuration the script records build time, index size and the median
latency of time-range queries of different selectivity.

Hypothesis: BRIN gives latency close to B-tree on range scans over correlated
data while being two to three orders of magnitude smaller.
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from common import connect, measure, out_dir, save_environment, try_plot, write_csv

CONFIGS = {
    "none": None,
    "btree": "CREATE INDEX lab_events_ix ON lab.events USING btree (occurred_at)",
    "brin_128": "CREATE INDEX lab_events_ix ON lab.events USING brin (occurred_at)",
    "brin_32": "CREATE INDEX lab_events_ix ON lab.events USING brin (occurred_at) WITH (pages_per_range = 32)",
}

QUERIES = {
    "1 saat": "SELECT count(*), sum(amount) FROM lab.events WHERE occurred_at >= '2025-06-15 10:00+04' "
              "AND occurred_at < '2025-06-15 11:00+04'",
    "1 gün": "SELECT count(*), sum(amount) FROM lab.events WHERE occurred_at >= '2025-06-15+04' "
             "AND occurred_at < '2025-06-16+04'",
    "1 həftə": "SELECT count(*), sum(amount) FROM lab.events WHERE occurred_at >= '2025-06-15+04' "
               "AND occurred_at < '2025-06-22+04'",
    "1 ay": "SELECT count(*), sum(amount) FROM lab.events WHERE occurred_at >= '2025-06-01+04' "
            "AND occurred_at < '2025-07-01+04'",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rows", type=int, default=2_000_000)
    ap.add_argument("--runs", type=int, default=15)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    out = out_dir("s1_index_types")
    conn = connect()
    save_environment(out, conn)
    conn.execute("CREATE SCHEMA IF NOT EXISTS lab")
    conn.execute("DROP TABLE IF EXISTS lab.events")
    print(f"Creating lab.events with {args.rows:,} rows")
    conn.execute(
        """
        CREATE TABLE lab.events AS
        SELECT g AS event_id,
               timestamptz '2025-01-01 00:00+04' + (g * interval '1 second') * (31536000.0 / %s) AS occurred_at,
               (g %% 20) + 1 AS branch_id,
               round((random() * 50)::numeric, 2) AS amount
          FROM generate_series(1, %s) g
        """,
        (args.rows, args.rows),
    )
    conn.execute("VACUUM ANALYZE lab.events")

    rows = []
    for name, ddl in CONFIGS.items():
        conn.execute("DROP INDEX IF EXISTS lab.lab_events_ix")
        build_s = 0.0
        size_mb = 0.0
        if ddl:
            start = time.perf_counter()
            conn.execute(ddl)
            build_s = time.perf_counter() - start
            conn.execute("ANALYZE lab.events")
            size = conn.execute("SELECT pg_relation_size('lab.lab_events_ix')").fetchone()
            size_mb = (size[0] if size else 0) / 1024 / 1024
        for label, query in QUERIES.items():
            m = measure(conn, query, runs=args.runs, warmup=3)
            rows.append([name, label, round(m["median_ms"], 3), round(m["p95_ms"], 3), round(size_mb, 3),
                         round(build_s, 3)])
            print(f"{name:9s} {label:8s} median {m['median_ms']:9.3f} ms   index {size_mb:8.3f} MB")

    write_csv(out / "results.csv", ["config", "range", "median_ms", "p95_ms", "index_mb", "build_s"], rows)
    (out / "summary.json").write_text(json.dumps({"rows": args.rows}, indent=2), encoding="utf-8")

    plt = try_plot()
    if plt is not None:
        fig, ax = plt.subplots(figsize=(8, 4.5))
        labels = list(QUERIES)
        width = 0.2
        colors = {"none": "#9aa5b1", "btree": "#2f6fde", "brin_128": "#e8833a", "brin_32": "#3aa76d"}
        for k, cfg in enumerate(CONFIGS):
            vals = [r[2] for r in rows if r[0] == cfg]
            ax.bar([i + (k - 1.5) * width for i in range(len(labels))], vals, width, label=cfg, color=colors[cfg])
        ax.set_yscale("log")
        ax.set_xticks(range(len(labels)), labels)
        ax.set_ylabel("Median gecikmə, ms (log)")
        ax.set_title("S1: B-tree və BRIN, zaman aralığı sorğuları")
        ax.legend(frameon=False)
        fig.tight_layout()
        fig.savefig(out / "s1_latency.png", dpi=160)

    if not args.keep:
        conn.execute("DROP TABLE lab.events")
    print(f"Results: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

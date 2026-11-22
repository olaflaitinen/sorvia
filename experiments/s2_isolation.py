"""S2: Concurrency anomalies and isolation levels for a stock decrement.

W worker threads each sell one unit K times from the same stock row.
The correct final quantity is start - W*K. Four strategies are compared:

  rmw_read_committed       SELECT quantity; UPDATE SET quantity = <read value - 1>   (READ COMMITTED)
  rmw_repeatable_read      the same under REPEATABLE READ, retrying on 40001
  rmw_serializable         the same under SERIALIZABLE, retrying on 40001
  atomic_update            UPDATE ... SET quantity = quantity - 1 WHERE quantity >= 1
                           (the pattern used by Sorvia's sale trigger, READ COMMITTED)

Reported: lost updates (final quantity error), serialization failures,
throughput (successful sales per second).
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from typing import Any

import psycopg
from psycopg import errors

from common import admin_dsn, connect, out_dir, save_environment, try_plot, write_csv

STRATEGIES = ("rmw_read_committed", "rmw_repeatable_read", "rmw_serializable", "atomic_update")
LEVEL = {
    "rmw_read_committed": psycopg.IsolationLevel.READ_COMMITTED,
    "rmw_repeatable_read": psycopg.IsolationLevel.REPEATABLE_READ,
    "rmw_serializable": psycopg.IsolationLevel.SERIALIZABLE,
    "atomic_update": psycopg.IsolationLevel.READ_COMMITTED,
}


def worker(strategy: str, ops: int, think_ms: float, stats: dict[str, Any], lock: threading.Lock) -> None:
    conn = psycopg.connect(admin_dsn())
    conn.isolation_level = LEVEL[strategy]
    done = retries = 0
    while done < ops:
        try:
            with conn.transaction():
                if strategy == "atomic_update":
                    conn.execute("UPDATE lab.stock SET quantity = quantity - 1 WHERE id = 1 AND quantity >= 1")
                else:
                    row = conn.execute("SELECT quantity FROM lab.stock WHERE id = 1").fetchone()
                    assert row is not None
                    if think_ms:
                        time.sleep(think_ms / 1000)   # the window in which another sale can interleave
                    conn.execute("UPDATE lab.stock SET quantity = %s WHERE id = 1", (row[0] - 1,))
            done += 1
        except (errors.SerializationFailure, errors.DeadlockDetected):
            retries += 1
    conn.close()
    with lock:
        stats["retries"] += retries


def run(strategy: str, workers: int, ops: int, start_qty: int, think_ms: float) -> dict[str, Any]:
    with connect() as conn:
        conn.execute("UPDATE lab.stock SET quantity = %s WHERE id = 1", (start_qty,))
    stats: dict[str, Any] = {"retries": 0}
    lock = threading.Lock()
    threads = [threading.Thread(target=worker, args=(strategy, ops, think_ms, stats, lock)) for _ in range(workers)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - start
    with connect() as conn:
        row = conn.execute("SELECT quantity FROM lab.stock WHERE id = 1").fetchone()
    final = row[0] if row else None
    expected = start_qty - workers * ops
    return {
        "strategy": strategy, "workers": workers, "ops_per_worker": ops, "expected_final": expected,
        "actual_final": final, "lost_updates": (final - expected) if final is not None else None,
        "serialization_failures": stats["retries"], "seconds": round(elapsed, 3),
        "tps": round(workers * ops / elapsed, 1),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--ops", type=int, default=100)
    ap.add_argument("--think-ms", type=float, default=1.0)
    args = ap.parse_args()

    out = out_dir("s2_isolation")
    with connect() as conn:
        save_environment(out, conn)
        conn.execute("CREATE SCHEMA IF NOT EXISTS lab")
        conn.execute("DROP TABLE IF EXISTS lab.stock")
        conn.execute("CREATE TABLE lab.stock (id int PRIMARY KEY, quantity int NOT NULL)")
        conn.execute("INSERT INTO lab.stock VALUES (1, 0)")

    start_qty = args.workers * args.ops * 2
    results = []
    for strategy in STRATEGIES:
        r = run(strategy, args.workers, args.ops, start_qty, args.think_ms)
        results.append(r)
        print(f"{strategy:22s} lost={r['lost_updates']:6} failures={r['serialization_failures']:6} tps={r['tps']}")

    write_csv(out / "results.csv", list(results[0].keys()), [list(r.values()) for r in results])
    (out / "summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    plt = try_plot()
    if plt is not None:
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 4))
        names = [r["strategy"].replace("rmw_", "") for r in results]
        a1.bar(names, [r["lost_updates"] for r in results], color="#d64545")
        a1.set_title("İtirilmiş yeniləmələr")
        a2.bar(names, [r["tps"] for r in results], color="#2f6fde")
        a2.set_title("Ötürmə qabiliyyəti (satış/san)")
        for ax in (a1, a2):
            ax.tick_params(axis="x", rotation=20)
        fig.tight_layout()
        fig.savefig(out / "s2_isolation.png", dpi=160)

    with connect() as conn:
        conn.execute("DROP TABLE lab.stock")
    print(f"Results: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

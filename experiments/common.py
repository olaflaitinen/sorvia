"""Shared helpers for the experiment scripts."""

from __future__ import annotations

import csv
import json
import os
import platform
import statistics
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, LiteralString, cast

import psycopg

RESULTS = Path(__file__).parent / "results"


def admin_dsn() -> str:
    return os.environ.get("SORVIA_ADMIN_DSN", "postgresql://postgres:postgres@localhost:5432/sorvia")


def connect(autocommit: bool = True) -> psycopg.Connection[Any]:
    return psycopg.connect(admin_dsn(), autocommit=autocommit)


def out_dir(name: str) -> Path:
    path = RESULTS / name / time.strftime("%Y%m%d-%H%M%S")
    path.mkdir(parents=True, exist_ok=True)
    return path


def explain_analyze_ms(conn: psycopg.Connection[Any], query: str) -> tuple[float, dict[str, Any]]:
    """Planning + execution time reported by the server (excludes network and client time)."""
    row = conn.execute(cast(LiteralString, "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query)).fetchone()
    assert row is not None
    doc = row[0] if not isinstance(row[0], str) else json.loads(row[0])
    plan = doc[0]
    return float(plan["Planning Time"]) + float(plan["Execution Time"]), plan


def measure(conn: psycopg.Connection[Any], query: str, runs: int = 15, warmup: int = 3) -> dict[str, float]:
    for _ in range(warmup):
        explain_analyze_ms(conn, query)
    samples = [explain_analyze_ms(conn, query)[0] for _ in range(runs)]
    return {
        "median_ms": statistics.median(samples),
        "mean_ms": statistics.fmean(samples),
        "stdev_ms": statistics.stdev(samples) if len(samples) > 1 else 0.0,
        "p95_ms": sorted(samples)[max(0, round(0.95 * len(samples)) - 1)],
        "runs": float(runs),
    }


def estimated_cost(conn: psycopg.Connection[Any], query: str) -> float:
    row = conn.execute(cast(LiteralString, "EXPLAIN (FORMAT JSON) " + query)).fetchone()
    assert row is not None
    doc = row[0] if not isinstance(row[0], str) else json.loads(row[0])
    return float(doc[0]["Plan"]["Total Cost"])


def write_csv(path: Path, header: Sequence[str], rows: Iterable[Sequence[Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def environment(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    settings = {
        name: conn.execute(cast(LiteralString, f"SHOW {name}")).fetchone()[0]  # type: ignore[index]
        for name in ("server_version", "shared_buffers", "work_mem", "effective_cache_size", "max_parallel_workers")
    }
    return {
        "python": platform.python_version(),
        "machine": platform.machine(),
        "system": f"{platform.system()} {platform.release()}",
        "cpu_count": os.cpu_count(),
        "postgres": settings,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def save_environment(path: Path, conn: psycopg.Connection[Any]) -> None:
    (path / "environment.json").write_text(json.dumps(environment(conn), indent=2), encoding="utf-8")


def try_plot() -> Any:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        return plt
    except ImportError:
        print("matplotlib not installed; skipping charts (pip install 'sorvia[experiments]')")
        return None

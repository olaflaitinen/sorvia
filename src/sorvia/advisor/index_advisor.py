"""Workload-driven index advisor using hypothetical indexes (HypoPG).

Method (after Chaudhuri and Narasayya, "An Efficient, Cost-Driven Index
Selection Tool for Microsoft SQL Server", VLDB 1997):

  1. Workload      recent successful queries from sorvia.nl_query.
  2. Candidates    mined from the optimizer's own plans: columns that appear in
                   filters and join conditions of sequential scans. Equality
                   columns lead, then at most one range column.
  3. What-if       each candidate is created as a hypothetical index (no disk
                   I/O, no locks) and the workload is re-costed with EXPLAIN.
  4. Greedy        repeatedly keep the candidate with the largest cost
                   reduction while the gain is at least `min_improvement_pct`.

Objective. With objective="total" the advisor minimises the summed plan cost,
which is dominated by a few heavy analytical queries; cheap but frequent
point lookups then never justify an index. The default objective="relative"
minimises the mean of cost_after / cost_before over all queries, so every
query counts equally. Both are reported in the evaluation (experiments/rq4).

Because candidates come from plans rather than from SQL text, queries over
views (pharma.v_sale_lines) produce candidates on their base tables.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, cast

import psycopg
from psycopg import sql

log = logging.getLogger(__name__)

_ALIAS_COL_RE = re.compile(r"\b([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)\b")
_EQ_TEMPLATE = r"(?:\b{a}\.{c}\b\s*=(?!>)|=\s*(?:\([^)]*\)\s*)?\b{a}\.{c}\b|\b{a}\.{c}\b\s*=\s*ANY)"
_RANGE_TEMPLATE = r"(?:\b{a}\.{c}\b\s*(?:<=|>=|<|>)|(?:<=|>=|<|>)\s*\b{a}\.{c}\b)"
_MIN_ROWS = 1000


@dataclass(frozen=True)
class Candidate:
    schema: str
    table: str
    columns: tuple[str, ...]
    partitioned: bool = False

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.table}"

    @property
    def index_name(self) -> str:
        base = f"sorvia_idx_{self.table}_{'_'.join(self.columns)}"
        if len(base) <= 63:
            return base
        digest = hashlib.sha1(base.encode(), usedforsecurity=False).hexdigest()[:8]
        return f"{base[:54]}_{digest}"

    def ddl(self) -> str:
        cols = ", ".join(f'"{c}"' for c in self.columns)
        concurrently = "" if self.partitioned else " CONCURRENTLY"
        target = f'"{self.schema}"."{self.table}"'
        return f'CREATE INDEX{concurrently} IF NOT EXISTS "{self.index_name}" ON {target} ({cols})'


@dataclass(frozen=True)
class Recommendation:
    candidate: Candidate
    workload_size: int
    cost_before: float
    cost_after: float

    @property
    def improvement_pct(self) -> float:
        return 0.0 if self.cost_before <= 0 else (self.cost_before - self.cost_after) / self.cost_before * 100


@dataclass
class _Relation:
    schema: str
    name: str
    columns: set[str]
    rows: float
    partitioned: bool
    existing_leading: set[tuple[str, ...]]


class IndexAdvisor:
    def __init__(self, conn: psycopg.Connection[Any], max_indexes: int = 3, min_improvement_pct: float = 5.0,
                 max_candidates: int = 25, objective: str = "relative") -> None:
        if objective not in ("relative", "total"):
            raise ValueError("objective must be 'relative' or 'total'")
        self.conn = conn
        self.objective = objective
        self._baseline: list[float | None] = []
        self.max_indexes = max_indexes
        self.min_improvement_pct = min_improvement_pct
        self.max_candidates = max_candidates
        self._relations: dict[str, _Relation] = {}

    # -- workload ------------------------------------------------------------

    @staticmethod
    def workload_from_log(conn: psycopg.Connection[Any], limit: int = 200) -> list[str]:
        rows = conn.execute(
            """
            SELECT executed_sql FROM (
                SELECT DISTINCT ON (executed_sql) executed_sql, created_at
                  FROM sorvia.nl_query
                 WHERE status = 'ok' AND executed_sql IS NOT NULL
                 ORDER BY executed_sql, created_at DESC
            ) q ORDER BY created_at DESC LIMIT %s
            """,
            (limit,),
        ).fetchall()
        return [str(_first(r)) for r in rows]

    # -- catalog -------------------------------------------------------------

    def _relation(self, schema: str, name: str) -> _Relation | None:
        """Resolve a (possibly partition) relation to its top-level parent."""
        key = f"{schema}.{name}"
        if key in self._relations:
            return self._relations[key]
        row = self.conn.execute(
            """
            WITH RECURSIVE up AS (
                SELECT c.oid, c.relispartition, 0 AS depth
                  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = %s AND c.relname = %s
                UNION ALL
                SELECT i.inhparent, p.relispartition, up.depth + 1
                  FROM up JOIN pg_inherits i ON i.inhrelid = up.oid
                  JOIN pg_class p ON p.oid = i.inhparent
                 WHERE up.relispartition
            )
            SELECT n.nspname, c.relname, c.relkind = 'p' AS partitioned, c.oid,
                   CASE WHEN c.relkind = 'p' THEN
                       (SELECT coalesce(sum(greatest(l.reltuples, 0)), 0)
                          FROM pg_partition_tree(c.oid) t JOIN pg_class l ON l.oid = t.relid
                         WHERE t.isleaf)
                   ELSE greatest(c.reltuples, 0) END AS rows
              FROM up JOIN pg_class c ON c.oid = up.oid JOIN pg_namespace n ON n.oid = c.relnamespace
             ORDER BY up.depth DESC LIMIT 1
            """,
            (schema, name),
        ).fetchone()
        if row is None:
            return None
        pschema, pname, partitioned, oid, rows = _values(row)
        cols = {str(_first(r)) for r in self.conn.execute(
            "SELECT attname FROM pg_attribute WHERE attrelid = %s AND attnum > 0 AND NOT attisdropped", (oid,)
        ).fetchall()}
        existing = set()
        for r in self.conn.execute(
            """
            SELECT ARRAY(SELECT a.attname FROM unnest(i.indkey::int2[]) WITH ORDINALITY k(attnum, ord)
                           JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
                          ORDER BY k.ord) AS cols
              FROM pg_index i WHERE i.indrelid = %s
            """,
            (oid,),
        ).fetchall():
            existing.add(tuple(_first(r)))
        rel = _Relation(pschema, pname, cols, float(rows), bool(partitioned), existing)
        self._relations[key] = rel
        return rel

    def _covered(self, rel: _Relation, columns: tuple[str, ...]) -> bool:
        return any(idx[: len(columns)] == columns for idx in rel.existing_leading)

    # -- candidate mining ----------------------------------------------------

    def _plan(self, query: str) -> dict[str, Any] | None:
        try:
            with self.conn.transaction():
                row = self.conn.execute("EXPLAIN (FORMAT JSON, VERBOSE) " + query).fetchone()
        except psycopg.Error as exc:
            log.debug("Skipping query that cannot be explained: %s", exc)
            return None
        plan = _first(row) if row else None
        if isinstance(plan, str):
            plan = json.loads(plan)
        return cast(dict[str, Any], plan[0]["Plan"]) if plan else None

    def cost(self, query: str) -> float | None:
        plan = self._plan(query)
        return float(plan["Total Cost"]) if plan else None

    def mine_candidates(self, workload: list[str]) -> list[Candidate]:
        counts: Counter[Candidate] = Counter()
        for query in workload:
            plan = self._plan(query)
            if plan is None:
                continue
            aliases: dict[str, tuple[str, str]] = {}
            for node in _walk(plan):
                if "Relation Name" in node and "Schema" in node:
                    aliases[node.get("Alias", node["Relation Name"])] = (node["Schema"], node["Relation Name"])
            conditions = " ".join(
                str(node[k]) for node in _walk(plan)
                for k in ("Filter", "Hash Cond", "Merge Cond", "Join Filter", "Recheck Cond", "Index Cond")
                if k in node
            )
            by_rel: dict[str, tuple[_Relation, list[str], list[str]]] = {}
            for alias, column in set(_ALIAS_COL_RE.findall(conditions)):
                if alias not in aliases:
                    continue
                rel = self._relation(*aliases[alias])
                if rel is None or column not in rel.columns or rel.rows < _MIN_ROWS:
                    continue
                entry = by_rel.setdefault(f"{rel.schema}.{rel.name}", (rel, [], []))
                a, c = re.escape(alias), re.escape(column)
                if re.search(_EQ_TEMPLATE.format(a=a, c=c), conditions):
                    entry[1].append(column)
                elif re.search(_RANGE_TEMPLATE.format(a=a, c=c), conditions):
                    entry[2].append(column)
            for rel, eq_cols, range_cols in by_rel.values():
                eq = tuple(sorted(set(eq_cols)))[:2]
                rng = tuple(sorted(set(range_cols)))[:1]
                options: set[tuple[str, ...]] = {(c,) for c in (*eq, *rng)}
                if len(eq) + len(rng) > 1:
                    options.add(eq + rng)
                for cols in options:
                    if not self._covered(rel, cols):
                        counts[Candidate(rel.schema, rel.name, cols, rel.partitioned)] += 1
        return [c for c, _ in counts.most_common(self.max_candidates)]

    # -- what-if evaluation ---------------------------------------------------

    def _create_hypothetical(self, cand: Candidate) -> list[int]:
        targets: list[tuple[str, str]]
        if cand.partitioned:
            targets = [(str(r[0]), str(r[1])) for r in (_values(x) for x in self.conn.execute(
                """
                SELECT n.nspname, c.relname
                  FROM pg_partition_tree(%s::regclass) t
                  JOIN pg_class c ON c.oid = t.relid JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE t.isleaf
                """,
                (cand.qualified,),
            ).fetchall())]
        else:
            targets = [(cand.schema, cand.table)]
        ids: list[int] = []
        cols = sql.SQL(", ").join(sql.Identifier(c) for c in cand.columns)
        for schema, table in targets:
            stmt = sql.SQL("CREATE INDEX ON {}.{} ({})").format(sql.Identifier(schema), sql.Identifier(table), cols)
            row = self.conn.execute(
                "SELECT indexrelid FROM hypopg_create_index(%s)", (stmt.as_string(self.conn),)
            ).fetchone()
            if row is not None:
                ids.append(int(_first(row)))
        return ids

    def _drop_hypothetical(self, ids: list[int]) -> None:
        for oid in ids:
            self.conn.execute("SELECT hypopg_drop_index(%s)", (oid,))

    def _costs(self, workload: list[str]) -> list[float | None]:
        return [self.cost(q) for q in workload]

    def _workload_cost(self, workload: list[str]) -> float:
        costs = self._costs(workload)
        if self.objective == "total":
            return sum(c for c in costs if c is not None)
        ratios = [c / b for c, b in zip(costs, self._baseline, strict=True)
                  if c is not None and b is not None and b > 0]
        return 100.0 * sum(ratios) / len(ratios) if ratios else 0.0

    def recommend(self, workload: list[str]) -> list[Recommendation]:
        if not workload:
            return []
        self.conn.execute("SELECT hypopg_reset()")
        try:
            candidates = self.mine_candidates(workload)
            if not candidates:
                return []
            self._baseline = self._costs(workload)
            current = self._workload_cost(workload)
            chosen: list[Recommendation] = []
            remaining = list(candidates)
            for _ in range(self.max_indexes):
                best: tuple[Candidate, float] | None = None
                for cand in remaining:
                    ids = self._create_hypothetical(cand)
                    try:
                        value = self._workload_cost(workload)
                    finally:
                        self._drop_hypothetical(ids)
                    if best is None or value < best[1]:
                        best = (cand, value)
                if best is None or current <= 0:
                    break
                gain = (current - best[1]) / current * 100
                if gain < self.min_improvement_pct:
                    break
                self._create_hypothetical(best[0])  # keep it for the next round
                chosen.append(Recommendation(best[0], len(workload), current, best[1]))
                current = best[1]
                remaining.remove(best[0])
            return chosen
        finally:
            self.conn.execute("SELECT hypopg_reset()")

    # -- persistence -------------------------------------------------------------

    @staticmethod
    def save(conn: psycopg.Connection[Any], recommendations: list[Recommendation]) -> int:
        saved = 0
        for rec in recommendations:
            row = conn.execute(
                """
                INSERT INTO sorvia.index_recommendation
                    (table_name, columns, index_ddl, workload_size, cost_before, cost_after, improvement_pct)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (index_ddl) WHERE status = 'proposed' DO NOTHING
                RETURNING recommendation_id
                """,
                (rec.candidate.qualified, list(rec.candidate.columns), rec.candidate.ddl(),
                 rec.workload_size, rec.cost_before, rec.cost_after, rec.improvement_pct),
            ).fetchone()
            saved += 1 if row else 0
        return saved


def apply_recommendation(admin_dsn: str, recommendation_id: int, decided_by: int | None) -> str:
    """Create the recommended index. Runs outside a transaction (CONCURRENTLY)."""
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        row = conn.execute(
            "SELECT index_ddl, table_name, status FROM sorvia.index_recommendation WHERE recommendation_id = %s",
            (recommendation_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"Recommendation {recommendation_id} not found")
        ddl, table_name, status = row
        if status != "proposed":
            raise ValueError(f"Recommendation {recommendation_id} is already {status}")
        # The DDL was generated by Candidate.ddl() from catalog identifiers and
        # is read back from a table only the platform writes.
        conn.execute(str(ddl))
        schema, _, table = str(table_name).partition(".")
        conn.execute(sql.SQL("ANALYZE {}.{}").format(sql.Identifier(schema), sql.Identifier(table)))
        conn.execute(
            "UPDATE sorvia.index_recommendation SET status = 'applied', decided_at = now(), decided_by = %s "
            "WHERE recommendation_id = %s",
            (decided_by, recommendation_id),
        )
        return str(ddl)


def _walk(plan: dict[str, Any]) -> Iterator[dict[str, Any]]:
    yield plan
    for child in plan.get("Plans", []) or []:
        yield from _walk(child)


def _values(row: Any) -> tuple[Any, ...]:
    return tuple(row.values()) if isinstance(row, dict) else tuple(row)


def _first(row: Any) -> Any:
    return _values(row)[0]

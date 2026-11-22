"""Static validation of generated SQL (layer 1 of 3).

The guard parses SQL into an abstract syntax tree and accepts it only if it is
a single read-only query over an allow-listed set of relations and functions.
It also rewrites the query to enforce a row limit.

This layer is deliberately strict but it is not the only line of defence:
layer 2 is the plan-cost check and layer 3 is the database itself (read-only
transaction, a role without write privileges, Row-Level Security). A bypass of
the guard must still defeat the database.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import cast

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

# sqlglot logs a warning for every statement it cannot model; the guard reports those itself.
logging.getLogger("sqlglot").setLevel(logging.ERROR)

_FORBIDDEN_NODE_NAMES = (
    "Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter", "AlterTable", "Command",
    "Into", "Lock", "Copy", "Set", "Transaction", "Commit", "Rollback", "Grant", "Revoke",
    "TruncateTable", "Pragma", "Use", "LoadData", "Kill", "Analyze",
)
_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = tuple(
    t for t in (getattr(exp, name, None) for name in _FORBIDDEN_NODE_NAMES) if isinstance(t, type)
)
_QUERY_ROOTS: tuple[type[exp.Expression], ...] = (exp.Select, exp.SetOperation)

# Functions sqlglot does not model with a dedicated node arrive as exp.Anonymous.
# Only these names are accepted. Everything else (pg_sleep, set_config,
# pg_read_file, dblink, lo_import, current_setting, ...) is rejected.
DEFAULT_ALLOWED_FUNCTIONS: frozenset[str] = frozenset({
    "abs", "age", "array_agg", "avg", "bool_and", "bool_or", "btrim", "ceil", "ceiling",
    "char_length", "coalesce", "concat", "concat_ws", "count", "cume_dist", "date_part",
    "date_trunc", "dense_rank", "every", "extract", "first_value", "floor", "format",
    "generate_series", "greatest", "initcap", "justify_days", "lag", "last_value", "lead",
    "least", "left", "length", "lower", "lpad", "ltrim", "make_date", "make_interval", "max",
    "min", "mode", "nth_value", "ntile", "nullif", "percent_rank", "percentile_cont",
    "percentile_disc", "position", "power", "rank", "regexp_replace", "repeat", "replace",
    "reverse", "right", "round", "row_number", "rpad", "rtrim", "sign", "split_part", "sqrt",
    "stddev", "stddev_pop", "stddev_samp", "string_agg", "strpos", "substr", "substring", "sum",
    "to_char", "to_date", "to_number", "translate", "trim", "trunc", "unaccent", "unnest",
    "upper", "var_pop", "var_samp", "variance", "width_bucket",
    # Sorvia domain functions exposed to the reader role.
    "business_date", "batch_location_at", "customer_discount_rate",
})

# Schema-qualified functions that may be called.
DEFAULT_QUALIFIED_FUNCTIONS: frozenset[str] = frozenset({
    "pharma.business_date", "pharma.batch_location_at", "pharma.customer_discount_rate",
})


class SqlRejected(Exception):
    """Raised when SQL violates the policy. `code` is stable and machine-readable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class GuardPolicy:
    # unqualified relation name -> schema, e.g. {"sale": "pharma"}
    relations: Mapping[str, str]
    allowed_schemas: frozenset[str] = frozenset({"pharma", "analytics"})
    allowed_functions: frozenset[str] = DEFAULT_ALLOWED_FUNCTIONS
    qualified_functions: frozenset[str] = DEFAULT_QUALIFIED_FUNCTIONS
    max_rows: int = 500
    max_joins: int = 12
    max_length: int = 8000

    @classmethod
    def from_relations(cls, qualified: Iterable[str], **kwargs: object) -> GuardPolicy:
        mapping: dict[str, str] = {}
        for name in qualified:
            schema, _, rel = name.partition(".")
            mapping.setdefault(rel.lower(), schema.lower())
        return cls(relations=mapping, **kwargs)  # type: ignore[arg-type]


@dataclass(frozen=True)
class GuardResult:
    sql: str
    relations: tuple[str, ...]
    limit_applied: bool
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _parse_single(sql: str) -> exp.Expression:
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except (ParseError, TokenError) as exc:
        raise SqlRejected("parse_error", f"SQL could not be parsed: {exc}") from exc
    if len(statements) != 1:
        raise SqlRejected("multiple_statements", "Exactly one statement is allowed")
    return cast(exp.Expression, statements[0])


def _cte_names(root: exp.Expression) -> set[str]:
    return {cte.alias_or_name.lower() for cte in root.find_all(exp.CTE)}


def _check_identifiers(root: exp.Expression) -> None:
    for ident in root.find_all(exp.Identifier):
        name = str(ident.this).lower()
        if name.startswith("pg_") or name in {"information_schema", "pg_catalog"}:
            raise SqlRejected("system_object", f"Access to system object '{ident.this}' is not allowed")


def _check_functions(root: exp.Expression, policy: GuardPolicy) -> None:
    for node in root.find_all(exp.Anonymous):
        name = str(node.name).lower()
        parent = node.parent
        qualifier: str | None = None
        if isinstance(parent, exp.Dot) and parent.expression is node:
            qualifier = parent.this.sql(dialect="postgres").lower()
        elif isinstance(parent, exp.Table) and parent.this is node and parent.db:
            qualifier = parent.db.lower()

        if qualifier is not None:
            if f"{qualifier}.{name}" not in policy.qualified_functions:
                raise SqlRejected("function_not_allowed", f"Function {qualifier}.{name} is not allowed")
        elif name not in policy.allowed_functions:
            raise SqlRejected("function_not_allowed", f"Function {name} is not allowed")


def _qualify_tables(root: exp.Expression, policy: GuardPolicy) -> list[str]:
    ctes = _cte_names(root)
    used: list[str] = []
    for table in root.find_all(exp.Table):
        if not isinstance(table.this, exp.Identifier):
            # Table-valued function in FROM, e.g. pharma.batch_location_at(...).
            # Its name was validated by _check_functions.
            continue
        if table.catalog:
            raise SqlRejected("cross_database", "Cross-database references are not allowed")
        name = table.name.lower()
        schema = table.db.lower() if table.db else ""
        if not schema:
            if name in ctes:
                continue
            if name not in policy.relations:
                raise SqlRejected("unknown_relation", f"Relation '{table.name}' is not available")
            schema = policy.relations[name]
            table.set("db", exp.to_identifier(schema))
        if schema not in policy.allowed_schemas:
            raise SqlRejected("schema_not_allowed", f"Schema '{schema}' is not available")
        if policy.relations.get(name) != schema:
            raise SqlRejected("unknown_relation", f"Relation '{schema}.{table.name}' is not available")
        used.append(f"{schema}.{name}")
    return sorted(set(used))


def _enforce_limit(root: exp.Expression, max_rows: int) -> tuple[exp.Expression, bool]:
    limit = root.args.get("limit")
    if limit is None:
        return root.limit(max_rows, copy=False), True  # type: ignore[attr-defined]
    value = limit.expression if isinstance(limit, exp.Limit) else None
    if isinstance(value, exp.Literal) and value.is_int:
        if int(value.this) > max_rows:
            limit.set("expression", exp.Literal.number(max_rows))
            return root, True
        return root, False
    raise SqlRejected("invalid_limit", "LIMIT must be a positive integer literal")


def check_sql(sql: str, policy: GuardPolicy) -> GuardResult:
    """Validate and rewrite `sql`. Raises SqlRejected on any violation."""
    text = sql.strip().rstrip(";").strip()
    if not text:
        raise SqlRejected("empty", "No SQL was produced")
    if len(text) > policy.max_length:
        raise SqlRejected("too_long", f"SQL exceeds {policy.max_length} characters")

    root = _parse_single(text)

    if not isinstance(root, _QUERY_ROOTS):
        raise SqlRejected("not_a_query", f"Only SELECT queries are allowed, got {root.key.upper()}")

    for node in root.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise SqlRejected("forbidden_construct", f"Construct {type(node).__name__} is not allowed")

    _check_identifiers(root)
    _check_functions(root, policy)
    relations = _qualify_tables(root, policy)

    joins = sum(1 for _ in root.find_all(exp.Join))
    if joins > policy.max_joins:
        raise SqlRejected("too_complex", f"Query has {joins} joins; the limit is {policy.max_joins}")

    root, limit_applied = _enforce_limit(root, policy.max_rows)
    return GuardResult(
        sql=root.sql(dialect="postgres", comments=False),
        relations=tuple(relations),
        limit_applied=limit_applied,
    )

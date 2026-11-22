"""Builds the semantic layer (sorvia.schema_doc) from the database catalog.

For every relation the reader role may query, the indexer collects the
COMMENT ON text, columns with types and comments, keys, foreign keys and a
few sample values of low-cardinality columns. It produces:

  content      text that is embedded for retrieval
  ddl_summary  compact schema description that is placed in the prompt
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg import sql

from sorvia.nl2sql.embeddings import Embedder, to_pgvector

READER_ROLE = "sorvia_reader"
SCHEMAS = ("pharma", "analytics")

# Low-cardinality columns whose distinct values help the model map words such
# as "Gəncə" or "antibiotik" to literals.
VALUE_HINT_COLUMNS: dict[tuple[str, str], str] = {
    ("pharma", "branch"): "city",
    ("pharma", "category"): "name",
    ("pharma", "job_position"): "name",
    ("pharma", "manufacturer"): "country",
    ("analytics", "dim_customer"): "age_group",
}


@dataclass
class ColumnInfo:
    name: str
    type: str
    comment: str | None
    is_pk: bool = False
    references: str | None = None


@dataclass
class RelationDoc:
    schema: str
    name: str
    kind: str
    comment: str | None
    columns: list[ColumnInfo] = field(default_factory=list)
    related: set[str] = field(default_factory=set)
    value_hints: list[str] = field(default_factory=list)

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.name}"

    def ddl_summary(self) -> str:
        head = f"{self.kind.upper()} {self.qualified}"
        if self.comment:
            head += f"  -- {self.comment}"
        lines = [head]
        for col in self.columns:
            parts = [f"  {col.name} {col.type}"]
            if col.is_pk:
                parts.append("PK")
            if col.references:
                parts.append(f"-> {col.references}")
            if col.comment:
                parts.append(f"-- {col.comment}")
            lines.append(" ".join(parts))
        if self.value_hints:
            lines.append(f"  -- known values: {', '.join(self.value_hints)}")
        return "\n".join(lines)

    def content(self) -> str:
        words = [self.qualified, self.name.replace("_", " "), self.comment or ""]
        for col in self.columns:
            words.append(col.name.replace("_", " "))
            if col.comment:
                words.append(col.comment)
        words.extend(self.value_hints)
        return " ".join(w for w in words if w)


def collect(conn: psycopg.Connection[Any]) -> list[RelationDoc]:
    rels = conn.execute(
        """
        SELECT c.oid, n.nspname, c.relname,
               CASE WHEN c.relkind IN ('v', 'm') THEN 'view' ELSE 'table' END AS kind,
               obj_description(c.oid, 'pg_class') AS comment
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = ANY(%s)
           AND c.relkind IN ('r', 'p', 'v', 'm')
           AND NOT c.relispartition
           AND has_any_column_privilege(%s, c.oid, 'SELECT')
         ORDER BY n.nspname, c.relname
        """,
        (list(SCHEMAS), READER_ROLE),
    ).fetchall()

    docs: dict[int, RelationDoc] = {}
    for oid, schema, name, kind, comment in (_row(r) for r in rels):
        docs[oid] = RelationDoc(schema=schema, name=name, kind=kind, comment=comment)

    if not docs:
        return []

    cols = conn.execute(
        """
        SELECT a.attrelid, a.attname, format_type(a.atttypid, a.atttypmod), col_description(a.attrelid, a.attnum)
          FROM pg_attribute a
         WHERE a.attrelid = ANY(%s)
           AND a.attnum > 0
           AND NOT a.attisdropped
           AND has_column_privilege(%s, a.attrelid, a.attnum, 'SELECT')
         ORDER BY a.attrelid, a.attnum
        """,
        (list(docs), READER_ROLE),
    ).fetchall()
    by_name: dict[int, dict[str, ColumnInfo]] = defaultdict(dict)
    for oid, col, typ, comment in (_row(r) for r in cols):
        info = ColumnInfo(name=col, type=typ, comment=comment)
        docs[oid].columns.append(info)
        by_name[oid][col] = info

    cons = conn.execute(
        """
        SELECT con.conrelid, con.contype, con.confrelid,
               ARRAY(SELECT attname FROM pg_attribute
                      WHERE attrelid = con.conrelid AND attnum = ANY(con.conkey)) AS cols,
               ARRAY(SELECT attname FROM pg_attribute
                      WHERE attrelid = con.confrelid AND attnum = ANY(con.confkey)) AS refcols,
               fn.nspname || '.' || fc.relname AS reftable
          FROM pg_constraint con
          LEFT JOIN pg_class fc ON fc.oid = con.confrelid
          LEFT JOIN pg_namespace fn ON fn.oid = fc.relnamespace
         WHERE con.conrelid = ANY(%s) AND con.contype IN ('p', 'f')
        """,
        (list(docs),),
    ).fetchall()
    for conrelid, contype, confrelid, colnames, refcols, reftable in (_row(r) for r in cons):
        doc = docs[conrelid]
        for i, col in enumerate(colnames):
            column_info = by_name[conrelid].get(col)
            if column_info is None:
                continue
            if contype == "p":
                column_info.is_pk = True
            elif contype == "f" and reftable:
                ref_col = refcols[i] if i < len(refcols) else ""
                column_info.references = f"{reftable}.{ref_col}"
        if contype == "f" and reftable and confrelid in docs:
            doc.related.add(reftable)
            docs[confrelid].related.add(doc.qualified)

    for doc in docs.values():
        column = VALUE_HINT_COLUMNS.get((doc.schema, doc.name))
        if column:
            query = sql.SQL("SELECT DISTINCT {} FROM {}.{} WHERE {} IS NOT NULL ORDER BY 1 LIMIT 40").format(
                sql.Identifier(column), sql.Identifier(doc.schema), sql.Identifier(doc.name), sql.Identifier(column)
            )
            doc.value_hints = [str(_row(r)[0]) for r in conn.execute(query).fetchall()]

    return list(docs.values())


def _row(r: Any) -> tuple[Any, ...]:
    return tuple(r.values()) if isinstance(r, dict) else tuple(r)


def rebuild(conn: psycopg.Connection[Any], embedder: Embedder) -> int:
    """Rebuild sorvia.schema_doc. Returns the number of documents written."""
    docs = collect(conn)
    vectors = embedder.embed([d.content() for d in docs])
    with conn.transaction():
        conn.execute("DELETE FROM sorvia.schema_doc")
        for doc, vec in zip(docs, vectors, strict=True):
            conn.execute(
                """
                INSERT INTO sorvia.schema_doc
                    (object_type, schema_name, object_name, content, ddl_summary,
                     related_objects, embedding, embedding_model)
                VALUES (%s, %s, %s, %s, %s, %s, %s::vector, %s)
                """,
                (doc.kind, doc.schema, doc.name, doc.content(), doc.ddl_summary(),
                 sorted(doc.related), to_pgvector(vec), embedder.model_name),
            )
    return len(docs)

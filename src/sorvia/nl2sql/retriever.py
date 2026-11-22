"""Schema retrieval: choose the relations a question needs.

Strategy
  1. Rank documents in sorvia.schema_doc by cosine distance (pgvector `<=>`).
  2. Keep the top-k.
  3. Foreign-key expansion: add direct FK neighbours of the two best tables so
     that join partners (for example pharma.branch for pharma.sale) are present
     even when the question does not mention them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg

from sorvia.nl2sql.embeddings import Embedder, to_pgvector


@dataclass(frozen=True)
class RetrievedObject:
    qualified: str
    kind: str
    ddl_summary: str
    score: float
    related: tuple[str, ...]
    via_expansion: bool = False


class SchemaRetriever:
    def __init__(self, embedder: Embedder, top_k: int = 6, expansion_seeds: int = 2, max_objects: int = 10) -> None:
        self.embedder = embedder
        self.top_k = top_k
        self.expansion_seeds = expansion_seeds
        self.max_objects = max_objects

    def all_objects(self, conn: psycopg.Connection[Any]) -> list[RetrievedObject]:
        rows = conn.execute(
            """
            SELECT schema_name || '.' || object_name AS qualified, object_type, ddl_summary, related_objects
              FROM sorvia.schema_doc
             ORDER BY object_type, schema_name, object_name
            """
        ).fetchall()
        return [
            RetrievedObject(r["qualified"], r["object_type"], r["ddl_summary"], 1.0, tuple(r["related_objects"]))
            for r in rows
        ]

    def retrieve(self, conn: psycopg.Connection[Any], question: str) -> list[RetrievedObject]:
        vector = to_pgvector(self.embedder.embed([question])[0])
        rows = conn.execute(
            """
            SELECT schema_name || '.' || object_name AS qualified, object_type, ddl_summary,
                   related_objects, 1 - (embedding <=> %s::vector) AS score
              FROM sorvia.schema_doc
             ORDER BY embedding <=> %s::vector
            """,
            (vector, vector),
        ).fetchall()
        ranked = [
            RetrievedObject(r["qualified"], r["object_type"], r["ddl_summary"], float(r["score"]),
                            tuple(r["related_objects"]))
            for r in rows
        ]
        return self.select(ranked)

    def select(self, ranked: list[RetrievedObject]) -> list[RetrievedObject]:
        """Pure selection logic (top-k + FK expansion); unit-testable without a database."""
        chosen = ranked[: self.top_k]
        names = {o.qualified for o in chosen}
        by_name = {o.qualified: o for o in ranked}
        seeds = [o for o in chosen if o.kind == "table"][: self.expansion_seeds]
        for seed in seeds:
            for neighbour in seed.related:
                if len(chosen) >= self.max_objects:
                    break
                if neighbour not in names and neighbour in by_name:
                    base = by_name[neighbour]
                    chosen.append(RetrievedObject(base.qualified, base.kind, base.ddl_summary,
                                                  base.score, base.related, via_expansion=True))
                    names.add(neighbour)
        return chosen

"""The question answering pipeline.

  question
    -> schema retrieval (pgvector + FK expansion)
    -> prompt (+ few-shot examples)
    -> language model
    -> guard (AST policy, LIMIT rewrite)            layer 1
    -> plan cost check                              layer 2
    -> scoped read-only execution under RLS         layer 3
    -> execution-guided repair on database errors (bounded)
    -> audit row in sorvia.nl_query
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from sorvia.config import Settings
from sorvia.db import Database
from sorvia.executor import CostLimitExceeded, ExecutionFailed, QueryTimeout, ScopedExecutor
from sorvia.guard import GuardPolicy, SqlRejected, check_sql
from sorvia.nl2sql.embeddings import Embedder
from sorvia.nl2sql.examples import select_examples
from sorvia.nl2sql.llm import LLMClient, LLMError, Message
from sorvia.nl2sql.prompt import (
    SYSTEM_PROMPT,
    CannotAnswer,
    build_repair_prompt,
    build_user_prompt,
    extract_sql,
)
from sorvia.nl2sql.retriever import RetrievedObject, SchemaRetriever
from sorvia.security import Principal

log = logging.getLogger(__name__)

STRATEGIES = ("full_schema", "retrieval", "retrieval_fewshot")

# Guard rejections that indicate a model mistake rather than an attack; these
# may be repaired. Security rejections are final.
_REPAIRABLE_GUARD_CODES = frozenset({"parse_error", "unknown_relation", "invalid_limit", "too_complex"})


@dataclass
class AskResult:
    query_id: int | None
    status: str
    question: str
    strategy: str
    sql: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    reason_code: str | None = None
    message: str | None = None
    relations: list[str] = field(default_factory=list)
    retrieved: list[str] = field(default_factory=list)
    repair_attempts: int = 0
    estimated_cost: float | None = None
    llm_ms: int = 0
    db_ms: int = 0
    total_ms: int = 0


class AskService:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        llm: LLMClient,
        embedder: Embedder,
        retriever: SchemaRetriever | None = None,
    ) -> None:
        self.settings = settings
        self.db = db
        self.llm = llm
        self.embedder = embedder
        self.retriever = retriever or SchemaRetriever(embedder, top_k=settings.retrieval_top_k)
        self.executor = ScopedExecutor(db, settings)
        self._policy: GuardPolicy | None = None
        self._lock = threading.Lock()

    # -- policy --------------------------------------------------------------

    def policy(self) -> GuardPolicy:
        with self._lock:
            if self._policy is None:
                with self.db.app.connection() as conn:
                    rows = conn.execute(
                        "SELECT schema_name || '.' || object_name AS q FROM sorvia.schema_doc"
                    ).fetchall()
                if not rows:
                    raise RuntimeError("Semantic layer is empty. Run `sorvia index-schema` first.")
                self._policy = GuardPolicy.from_relations(
                    [str(r["q"]) for r in rows],  # type: ignore[call-overload]
                    max_rows=self.settings.max_rows,
                    max_joins=self.settings.max_joins,
                    max_length=self.settings.max_sql_length,
                )
            return self._policy

    def invalidate_policy(self) -> None:
        with self._lock:
            self._policy = None

    # -- pipeline ------------------------------------------------------------

    def _context(self, question: str, strategy: str) -> list[RetrievedObject]:
        with self.db.app.connection() as conn:
            if strategy == "full_schema":
                return self.retriever.all_objects(conn)
            return self.retriever.retrieve(conn, question)

    def ask(self, principal: Principal, question: str, strategy: str | None = None) -> AskResult:
        strategy = strategy or self.settings.strategy
        if strategy not in STRATEGIES:
            raise ValueError(f"Unknown strategy {strategy!r}")
        question = question.strip()
        started = time.perf_counter()
        result = AskResult(query_id=None, status="error", question=question, strategy=strategy)
        generated_sql: str | None = None

        try:
            objects = self._context(question, strategy)
            result.retrieved = [o.qualified for o in objects]
            examples = select_examples(question, self.embedder) if strategy == "retrieval_fewshot" else []
            messages = [Message("user", build_user_prompt(question, objects, examples))]
            policy = self.policy()

            while True:
                completion = self.llm.complete(SYSTEM_PROMPT, messages)
                result.llm_ms += completion.latency_ms
                try:
                    generated_sql = extract_sql(completion.text)
                    guarded = check_sql(generated_sql, policy)
                    result.sql = guarded.sql
                    result.relations = list(guarded.relations)
                    execution = self.executor.run(principal.user_id, guarded.sql)
                except CannotAnswer as exc:
                    result.status, result.reason_code, result.message = "blocked", "cannot_answer", exc.reason
                    break
                except SqlRejected as exc:
                    if exc.code in _REPAIRABLE_GUARD_CODES and result.repair_attempts < self.settings.repair_attempts:
                        result.repair_attempts += 1
                        messages += [Message("assistant", completion.text),
                                     Message("user", build_repair_prompt(generated_sql or "", exc.message))]
                        continue
                    result.status, result.reason_code, result.message = "blocked", exc.code, exc.message
                    break
                except CostLimitExceeded as exc:
                    result.status, result.reason_code, result.message = "blocked", exc.code, exc.message
                    result.estimated_cost = exc.estimated_cost
                    break
                except QueryTimeout as exc:
                    result.status, result.reason_code, result.message = "timeout", exc.code, exc.message
                    result.estimated_cost = exc.estimated_cost
                    break
                except ExecutionFailed as exc:
                    if result.repair_attempts < self.settings.repair_attempts:
                        result.repair_attempts += 1
                        messages += [Message("assistant", completion.text),
                                     Message("user", build_repair_prompt(result.sql or "", exc.message))]
                        continue
                    result.status, result.reason_code, result.message = "error", exc.code, exc.message
                    result.estimated_cost = exc.estimated_cost
                    break

                result.status = "ok"
                result.columns = execution.columns
                result.rows = execution.rows
                result.row_count = execution.row_count
                result.truncated = execution.truncated
                result.estimated_cost = execution.estimated_cost
                result.db_ms = execution.db_ms
                break
        except LLMError as exc:
            result.status, result.reason_code, result.message = "error", "llm_unavailable", str(exc)
        finally:
            result.total_ms = int((time.perf_counter() - started) * 1000)

        result.query_id = self._log(principal, result, generated_sql)
        return result

    def _log(self, principal: Principal, r: AskResult, generated_sql: str | None) -> int | None:
        try:
            with self.db.app.connection() as conn:
                row = conn.execute(
                    """
                    INSERT INTO sorvia.nl_query
                        (user_id, question, generated_sql, executed_sql, status, block_reason, error_message,
                         provider, model, strategy, retrieved_objects, repair_attempts, estimated_cost,
                         row_count, llm_ms, db_ms, total_ms)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING query_id
                    """,
                    (
                        principal.user_id, r.question[:2000], generated_sql,
                        r.sql if r.status == "ok" else None,
                        r.status,
                        r.reason_code if r.status == "blocked" else None,
                        r.message if r.status in ("error", "timeout") else None,
                        self.llm.provider, self.llm.model, r.strategy, r.retrieved, r.repair_attempts,
                        r.estimated_cost, r.row_count if r.status == "ok" else None,
                        r.llm_ms, r.db_ms, r.total_ms,
                    ),
                ).fetchone()
            return int(row["query_id"]) if row else None  # type: ignore[call-overload]
        except Exception:
            log.exception("Failed to record nl_query")
            return None

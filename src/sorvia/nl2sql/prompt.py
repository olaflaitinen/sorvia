"""Prompt construction and SQL extraction."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date

from sorvia.nl2sql.examples import Example
from sorvia.nl2sql.retriever import RetrievedObject

SYSTEM_PROMPT = """You are Sorvia, an expert PostgreSQL 16 analyst for a pharmacy network in Azerbaijan.
Translate the user's question (usually Azerbaijani, sometimes English) into ONE read-only PostgreSQL query.

Rules:
1. Use only the relations listed under SCHEMA. Always qualify them with their schema
   (pharma.sale, analytics.fact_sales).
2. Produce exactly one SELECT statement (CTEs allowed). Never modify data. Never use system catalogs.
3. Name every output column with a clear snake_case alias. Never use SELECT * on pharma.customer.
4. Business dates are in Asia/Baku time. For sale dates use pharma.business_date(sold_at)
   or the sale_date column of pharma.v_sale_lines.
5. Money is in AZN. Revenue means net_amount unless the question says gross.
6. "Expired" means expires_on < current_date. Relative periods ("this month", "last year") are relative to current_date.
7. For rankings use ORDER BY with LIMIT. Round money to 2 decimals.
8. Match text literals case-insensitively (ILIKE) unless they are codes.
9. If the question asks to change, delete or insert data, or cannot be answered from the schema, reply with
   exactly: -- CANNOT_ANSWER: <short reason in Azerbaijani>

Reply with the SQL only, inside a ```sql code block."""


def build_user_prompt(
    question: str,
    objects: Sequence[RetrievedObject],
    examples: Sequence[Example] = (),
    today: date | None = None,
) -> str:
    parts = [f"Today is {(today or date.today()).isoformat()}.", "", "SCHEMA:"]
    parts.extend(o.ddl_summary for o in objects)
    if examples:
        parts.append("")
        parts.append("EXAMPLES:")
        for ex in examples:
            parts.append(f"Question: {ex.question}\n```sql\n{ex.sql}\n```")
    parts.append("")
    parts.append(f"Question: {question}")
    return "\n".join(parts)


def build_repair_prompt(sql: str, error: str) -> str:
    return (
        "The query failed when executed on PostgreSQL.\n"
        f"```sql\n{sql}\n```\n"
        f"Error: {error}\n"
        "Fix the query. Follow the same rules and reply with the corrected SQL only."
    )


_FENCE_RE = re.compile(r"```(?:sql|postgresql)?\s*\n?(.*?)```", re.DOTALL | re.IGNORECASE)
_CANNOT_RE = re.compile(r"--\s*CANNOT_ANSWER:\s*(.+)", re.IGNORECASE)


class CannotAnswer(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def extract_sql(text: str) -> str:
    """Return the SQL in a model reply. Raises CannotAnswer for explicit refusals."""
    match = _FENCE_RE.search(text)
    body = match.group(1) if match else text
    refusal = _CANNOT_RE.search(body) or _CANNOT_RE.search(text)
    if refusal and not re.search(r"\bselect\b", _CANNOT_RE.sub("", body), re.IGNORECASE):
        raise CannotAnswer(refusal.group(1).strip())
    return body.strip()

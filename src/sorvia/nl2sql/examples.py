"""Curated few-shot examples.

These are written independently of the benchmark test set (benchmark/data)
and are never evaluated, so that few-shot prompting does not leak test answers.
"""

from __future__ import annotations

from dataclasses import dataclass

from sorvia.nl2sql.embeddings import Embedder, cosine


@dataclass(frozen=True)
class Example:
    question: str
    sql: str


EXAMPLES: tuple[Example, ...] = (
    Example(
        "Hər filialda neçə işçi işləyir?",
        "SELECT b.name AS branch_name, count(*) AS employee_count\n"
        "FROM pharma.employee e JOIN pharma.branch b ON b.branch_id = e.branch_id\n"
        "WHERE e.is_active\nGROUP BY b.name\nORDER BY employee_count DESC",
    ),
    Example(
        "Bu il ən çox gəlir gətirən 3 kateqoriya hansıdır?",
        "SELECT category_name, sum(line_amount) AS revenue\n"
        "FROM pharma.v_sale_lines\n"
        "WHERE sale_date >= date_trunc('year', current_date)::date\n"
        "GROUP BY category_name\nORDER BY revenue DESC\nLIMIT 3",
    ),
    Example(
        "Reseptlə satılan neçə dərman var?",
        "SELECT count(*) AS rx_drug_count FROM pharma.drug WHERE requires_prescription",
    ),
    Example(
        "Ötən həftə hər gün üzrə satış sayı",
        "SELECT pharma.business_date(sold_at) AS day, count(*) AS sale_count\n"
        "FROM pharma.sale\n"
        "WHERE sold_at >= date_trunc('week', current_date) - interval '7 days'\n"
        "  AND sold_at < date_trunc('week', current_date)\n"
        "GROUP BY day\nORDER BY day",
    ),
    Example(
        "Hansı ölkənin istehsalçıları ən çox dərman təqdim edir?",
        "SELECT manufacturer_country, count(*) AS drug_count\n"
        "FROM pharma.v_drug_catalog\nGROUP BY manufacturer_country\nORDER BY drug_count DESC",
    ),
    Example(
        "2025-ci ildə rüblər üzrə xalis gəlir (analitik sxem)",
        "SELECT d.quarter, sum(f.net_amount) AS net_revenue\n"
        "FROM analytics.fact_sales f JOIN analytics.dim_date d ON d.date_key = f.date_key\n"
        "WHERE d.year = 2025\nGROUP BY d.quarter\nORDER BY d.quarter",
    ),
)


def select_examples(question: str, embedder: Embedder, k: int = 3) -> list[Example]:
    vectors = embedder.embed([question, *[e.question for e in EXAMPLES]])
    q, rest = vectors[0], vectors[1:]
    ranked = sorted(zip(EXAMPLES, rest, strict=True), key=lambda pair: cosine(q, pair[1]), reverse=True)
    return [e for e, _ in ranked[:k]]

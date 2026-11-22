from __future__ import annotations

import json
from pathlib import Path

import pytest

from sorvia.nl2sql.embeddings import HashingEmbedder, cosine, normalize, to_pgvector, tokenize
from sorvia.nl2sql.examples import EXAMPLES, select_examples
from sorvia.nl2sql.llm import Message, StaticClient
from sorvia.nl2sql.prompt import CannotAnswer, build_repair_prompt, build_user_prompt, extract_sql
from sorvia.nl2sql.retriever import RetrievedObject, SchemaRetriever

DATASET = Path(__file__).resolve().parents[2] / "benchmark" / "data" / "az_text2sql_v1.jsonl"


def test_azerbaijani_lowercase() -> None:
    assert normalize("İLKİN IŞIQ") == "ilkin ışıq"
    assert tokenize("Bakıda neçə filial var?") == ["bakıda", "neçə", "filial", "var"]


def test_embeddings_are_normalised_and_deterministic() -> None:
    e = HashingEmbedder(dim=128)
    a, b = e.embed(["satışlar", "satışlar"])
    assert a == b
    assert abs(sum(x * x for x in a) - 1.0) < 1e-9


def test_morphology_and_ascii_folding() -> None:
    e = HashingEmbedder(dim=512)
    base, inflected, folded, other = e.embed(["satış", "satışların", "satis", "həkim"])
    assert cosine(base, inflected) > cosine(base, other)
    assert cosine(base, folded) > cosine(base, other)


def test_pgvector_literal() -> None:
    assert to_pgvector([0.5, -1.0]) == "[0.500000,-1.000000]"


def _obj(name: str, kind: str = "table", related: tuple[str, ...] = ()) -> RetrievedObject:
    return RetrievedObject(name, kind, f"TABLE {name}", 0.5, related)


def test_retriever_fk_expansion() -> None:
    ranked = [_obj("pharma.sale", related=("pharma.branch", "pharma.employee")), _obj("pharma.v_sale_lines", "view"),
              _obj("pharma.drug"), _obj("pharma.branch"), _obj("pharma.employee")]
    chosen = SchemaRetriever(HashingEmbedder(64), top_k=2).select(ranked)
    names = [o.qualified for o in chosen]
    assert names[:2] == ["pharma.sale", "pharma.v_sale_lines"]
    assert "pharma.branch" in names and "pharma.employee" in names
    assert all(o.via_expansion for o in chosen[2:])


def test_retriever_respects_max_objects() -> None:
    ranked = [_obj("a.t0", related=tuple(f"a.t{i}" for i in range(1, 30)))] + [_obj(f"a.t{i}") for i in range(1, 30)]
    chosen = SchemaRetriever(HashingEmbedder(64), top_k=3, max_objects=5).select(ranked)
    assert len(chosen) == 5


def test_extract_sql_from_fence() -> None:
    assert extract_sql("Here:\n```sql\nSELECT 1\n```\nDone") == "SELECT 1"
    assert extract_sql("SELECT 2") == "SELECT 2"


def test_extract_refusal() -> None:
    with pytest.raises(CannotAnswer) as info:
        extract_sql("```sql\n-- CANNOT_ANSWER: məlumatı silmək olmaz\n```")
    assert "silmək" in info.value.reason


def test_prompt_contains_schema_examples_and_question() -> None:
    prompt = build_user_prompt("Neçə filial var?", [_obj("pharma.branch")], EXAMPLES[:1])
    assert "TABLE pharma.branch" in prompt and "EXAMPLES" in prompt and prompt.endswith("Question: Neçə filial var?")
    assert "Error: boom" in build_repair_prompt("SELECT 1", "boom")


def test_fewshot_selection_is_relevant() -> None:
    picked = select_examples("filiallarda işçi sayı", HashingEmbedder(512), k=1)
    assert "employee" in picked[0].sql


def test_static_client_round_trip() -> None:
    client = StaticClient.from_jsonl(DATASET)
    record = json.loads(DATASET.read_text(encoding="utf-8").splitlines()[0])
    reply = client.complete("system", [Message("user", f"SCHEMA...\nQuestion: {record['question']}")])
    assert extract_sql(reply.text) == record["sql"]
    reply_en = client.complete("system", [Message("user", f"Question: {record['question_en']}")])
    assert extract_sql(reply_en.text) == record["sql"]
    with pytest.raises(CannotAnswer):
        extract_sql(client.complete("s", [Message("user", "Question: unknown")]).text)

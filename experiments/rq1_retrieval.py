"""RQ1 (retrieval component): does schema retrieval find the relations a question needs?

For each benchmark question the relations used by the gold SQL are extracted
with the guard's parser. Retrieval is evaluated without any language model:

  recall        |gold relations found| / |gold relations|, averaged
  coverage      share of questions for which every gold relation was found
  prompt size   number of relations put in the prompt (a cost proxy)

for top-k in {2, 4, 6, 8}, with and without foreign-key expansion, for
Azerbaijani and English questions.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from common import admin_dsn, out_dir, try_plot, write_csv
from sorvia.guard import GuardPolicy, check_sql
from sorvia.nl2sql.embeddings import HashingEmbedder
from sorvia.nl2sql.retriever import RetrievedObject, SchemaRetriever

DATA = Path(__file__).resolve().parents[1] / "benchmark" / "data" / "az_text2sql_v1.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dim", type=int, default=512)
    args = ap.parse_args()

    out = out_dir("rq1_retrieval")
    items = [json.loads(x) for x in DATA.read_text(encoding="utf-8").splitlines() if x.strip()]
    embedder = HashingEmbedder(args.dim)

    with psycopg.connect(admin_dsn(), row_factory=dict_row) as conn:
        docs = conn.execute("SELECT schema_name || '.' || object_name AS q, object_type, ddl_summary, "
                            "related_objects, embedding::text AS emb FROM sorvia.schema_doc").fetchall()
        policy = GuardPolicy.from_relations([d["q"] for d in docs])

        def ranked(question: str) -> list[RetrievedObject]:
            vec = "[" + ",".join(f"{v:.6f}" for v in embedder.embed([question])[0]) + "]"
            rows = conn.execute(
                "SELECT schema_name || '.' || object_name AS q, object_type, ddl_summary, related_objects, "
                "1 - (embedding <=> %s::vector) AS score FROM sorvia.schema_doc ORDER BY embedding <=> %s::vector",
                (vec, vec)).fetchall()
            return [RetrievedObject(r["q"], r["object_type"], r["ddl_summary"], float(r["score"]),
                                    tuple(r["related_objects"])) for r in rows]

        cache: dict[tuple[str, str], list[RetrievedObject]] = {}
        for item in items:
            for lang, key in (("az", "question"), ("en", "question_en")):
                cache[(item["id"], lang)] = ranked(item[key])

    rows: list[list[Any]] = []
    for lang in ("az", "en"):
        for expansion in (False, True):
            for k in (2, 4, 6, 8):
                retriever = SchemaRetriever(embedder, top_k=k, expansion_seeds=2 if expansion else 0, max_objects=k + 4)
                recalls, full, sizes = [], 0, []
                for item in items:
                    gold = set(check_sql(item["sql"], policy).relations)
                    chosen = {o.qualified for o in retriever.select(list(cache[(item["id"], lang)]))}
                    hit = len(gold & chosen) / len(gold)
                    recalls.append(hit)
                    full += hit == 1.0
                    sizes.append(len(chosen))
                rows.append([lang, expansion, k, round(statistics.fmean(recalls), 4), round(full / len(items), 4),
                             round(statistics.fmean(sizes), 2)])
                print(f"{lang} expansion={expansion!s:5s} k={k}  recall={rows[-1][3]:.3f}  "
                      f"coverage={rows[-1][4]:.3f}  objects={rows[-1][5]}")
    write_csv(out / "retrieval.csv", ["lang", "fk_expansion", "top_k", "recall", "coverage", "objects_in_prompt"], rows)

    plt = try_plot()
    if plt is not None:
        fig, ax = plt.subplots(figsize=(7, 4))
        for lang, style in (("az", "-"), ("en", "--")):
            for exp_flag, color in ((False, "#9aa5b1"), (True, "#2f6fde")):
                pts = [(r[2], r[4]) for r in rows if r[0] == lang and r[1] == exp_flag]
                ax.plot([p[0] for p in pts], [p[1] for p in pts], style, marker="o", color=color,
                        label=f"{lang}, FK genişlənmə={'var' if exp_flag else 'yox'}")
        ax.set_xlabel("top-k")
        ax.set_ylabel("Tam əhatə (bütün lazımi cədvəllər tapılıb)")
        ax.set_ylim(0, 1.05)
        ax.set_title("RQ1: Sxem axtarışının keyfiyyəti")
        ax.legend(frameon=False, fontsize=8)
        fig.tight_layout()
        fig.savefig(out / "rq1_retrieval.png", dpi=160)
    print(f"Results: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

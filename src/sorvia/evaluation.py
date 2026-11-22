"""Execution-accuracy metrics for Text-to-SQL evaluation.

Two metrics are reported:

  EX (strict)    The predicted result equals the gold result as a multiset of
                 rows (a list when the gold query defines an order). Values in
                 a row are compared as an unordered bag so that the order of
                 output columns does not matter.

  EX (relaxed)   Every gold column must be found among the predicted columns
                 (identical value multiset); extra predicted columns are
                 ignored. This forgives answers that add helpful context
                 columns, e.g. strength next to a drug name.

Numbers are compared after rounding to 2 decimals, which absorbs the usual
numeric vs. float differences between equivalent queries.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import Sequence
from decimal import Decimal
from typing import Any


def norm(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float | Decimal):
        number = float(value)
        if number == 0:
            return "0.00"
        return f"{number:.2f}"
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    text = str(value).strip()
    try:
        return f"{float(text):.2f}"
    except ValueError:
        return text


def _row_bag(row: Sequence[Any]) -> tuple[str, ...]:
    return tuple(sorted(norm(v) for v in row))


def strict_match(gold: Sequence[Sequence[Any]], pred: Sequence[Sequence[Any]], ordered: bool) -> bool:
    if len(gold) != len(pred):
        return False
    g = [_row_bag(r) for r in gold]
    p = [_row_bag(r) for r in pred]
    return g == p if ordered else Counter(g) == Counter(p)


def relaxed_match(
    gold: Sequence[Sequence[Any]], pred: Sequence[Sequence[Any]], ordered: bool
) -> bool:
    if len(gold) != len(pred):
        return False
    if not gold:
        return True
    n_gold, n_pred = len(gold[0]), len(pred[0])
    if n_pred < n_gold:
        return False
    gold_cols = [[norm(r[i]) for r in gold] for i in range(n_gold)]
    pred_cols = [[norm(r[j]) for r in pred] for j in range(n_pred)]

    # Assign each gold column to a distinct predicted column with the same values.
    candidates = [
        [j for j in range(n_pred) if Counter(pred_cols[j]) == Counter(gold_cols[i])] for i in range(n_gold)
    ]

    def assign(i: int, used: frozenset[int]) -> list[int] | None:
        if i == n_gold:
            return []
        for j in candidates[i]:
            if j in used:
                continue
            rest = assign(i + 1, used | {j})
            if rest is not None:
                projected = [j, *rest]
                if i == 0 and not _rows_agree(gold, pred, projected, ordered):
                    continue
                return projected
        return None

    return assign(0, frozenset()) is not None


def _rows_agree(gold: Sequence[Sequence[Any]], pred: Sequence[Sequence[Any]], mapping: list[int],
                ordered: bool) -> bool:
    g = [tuple(norm(v) for v in r) for r in gold]
    p = [tuple(norm(r[j]) for j in mapping) for r in pred]
    return g == p if ordered else Counter(g) == Counter(p)

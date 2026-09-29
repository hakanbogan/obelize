"""An answer key may carry only the keys its test declares; test_answer_keys.py says why."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def unknown(mapping: Mapping[str, Any], allowed: Iterable[str], where: str) -> list[str]:
    """Keys of `mapping` that `allowed` does not name, labelled with `where`."""
    known = frozenset(allowed)
    return [f"{where}: {key!r}" for key in mapping if key not in known]


def each(rows: Iterable[Mapping[str, Any]], allowed: Iterable[str], where: str) -> list[str]:
    """`unknown` over a list of rows, each labelled with its index."""
    known = frozenset(allowed)
    return [
        problem
        for index, row in enumerate(rows)
        for problem in unknown(row, known, f"{where}[{index}]")
    ]

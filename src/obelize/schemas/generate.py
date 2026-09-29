"""Write the committed JSON Schemas from their models; `--check` reports drift and writes nothing.

`ci / schema-drift` runs the writing form, then `git diff --exit-code`. `verify/verify.json` has no
schema: `run.schema.json` carries it; the `model/` documents do, as `run.json` reaches neither.
`pack.schema.json` lets a pack be checked without installing obelize.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from obelize.models import (
    FindingsDocument,
    ModelDocument,
    PlanDocument,
    ProposalRecord,
    RunRecord,
    UndoRecord,
)
from obelize.packs.schema import PackDocument

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

HERE = Path(__file__).resolve().parent

# The dialect pydantic v2 emits, stated so a reader knows which validator to use.
DIALECT = "https://json-schema.org/draft/2020-12/schema"

# Names carry no version: every format is unstable through 0.x.
SCHEMAS: tuple[tuple[str, type[BaseModel]], ...] = (
    ("findings.schema.json", FindingsDocument),
    ("model.schema.json", ModelDocument),
    ("pack.schema.json", PackDocument),
    ("plan.schema.json", PlanDocument),
    ("proposal.schema.json", ProposalRecord),
    ("run.schema.json", RunRecord),
    ("undo.schema.json", UndoRecord),
)

# Input schemas (defaults optional); the rest are output, where every writer writes every field.
READ: frozenset[type[BaseModel]] = frozenset({PackDocument})


def render(model: type[BaseModel]) -> str:
    """The exact bytes of a committed schema; `sort_keys` keeps a reordered field from diffing."""
    if model in READ:
        schema = model.model_json_schema(mode="validation")
    else:
        schema = model.model_json_schema(mode="serialization")
    schema["$schema"] = DIALECT
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def write(directory: Path | None = None) -> list[Path]:
    """Write every schema and return the paths, changed or not."""
    target = HERE if directory is None else directory
    written = []
    for name, model in SCHEMAS:
        path = target / name
        path.write_bytes(render(model).encode("utf-8"))
        written.append(path)
    return written


def stale(directory: Path | None = None) -> list[str]:
    """The names whose committed bytes differ from `render(model)`."""
    target = HERE if directory is None else directory
    drifted = []
    for name, model in SCHEMAS:
        path = target / name
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current != render(model):
            drifted.append(name)
    return drifted


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    unknown = [argument for argument in arguments if argument != "--check"]
    if unknown:
        print(f"usage: generate.py [--check]; unknown argument {unknown[0]!r}", file=sys.stderr)
        return 2
    if "--check" in arguments:
        drifted = stale()
        for name in drifted:
            print(f"stale: {name} (run `python src/obelize/schemas/generate.py`)", file=sys.stderr)
        return 1 if drifted else 0
    for path in write():
        print(f"wrote {path.name}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    raise SystemExit(main())

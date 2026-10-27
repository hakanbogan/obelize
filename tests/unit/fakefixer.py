"""A tool for the `external_fixer` tests: the interpreter, started as a fixer is.

A pack of an invented library whose module keeps its name has one fixer, a `rewrite_pattern` that
writes a line and an import, and a flagged name that holds a file back (ADR-074). The tool is a
Python one-liner over `data`, so the tests are offline and run on every system.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from obelize.packs import loader
from obelize.packs.schema import (
    ExternalFixerChange,
    ExternalFixerParams,
    FlagOnlyChange,
    FlagOnlyParams,
    Legacy,
    Match,
    PackDocument,
    PackSource,
    RewritePatternChange,
    RewritePatternParams,
    Target,
)
from obelize.transforms import fixers
from support import migrate

if TYPE_CHECKING:
    import pytest

    from obelize.models import BailCode
    from obelize.transforms import codemod

FIXTURES = ("fixtures/negative/none.py", "fixtures/positive/one.before.py")
TOOL = ExternalFixerChange(
    id="tool",
    kind="external_fixer",
    citation="Acme Kit 2 notes, 'Names'",
    fixtures=FIXTURES,
    params=ExternalFixerParams(fixer="ruff:NPY201", symbols=("acme.kit.old_a", "acme.kit.old_b")),
)
DUMP = RewritePatternChange(
    id="dump",
    kind="rewrite_pattern",
    citation="Acme Kit 2 notes, 'Dumping'",
    fixtures=FIXTURES,
    params=RewritePatternParams(
        before="acme.kit.dump($x)", after="json.dumps($x)", imports=("json",)
    ),
)
GONE = FlagOnlyChange(
    id="gone",
    kind="flag_only",
    citation="Acme Kit 2 notes, 'Dropped'",
    fixtures=FIXTURES,
    params=FlagOnlyParams(
        message="acme.kit 2 dropped it.", suggestion="Port by hand.", symbols=("acme.kit.gone",)
    ),
)
PACK = PackDocument(
    id="acme/acme-kit-fixed",
    pack_version="0.1.0",
    provider="acme",
    language="python",
    source=PackSource(
        type="official_guide",
        url="https://example.invalid/acme-kit",
        retrieved_at=dt.date(2026, 10, 27),
    ),
    **{"from": Legacy(package="acme-kit", version="<2")},
    to=Target(package="acme-kit", version=">=2", requires_python=">=3.9"),
    match=Match(
        imports=("acme.kit",),
        shared=True,
        symbols=(
            "acme.kit.dump",
            "acme.kit.gone",
            "acme.kit.old_a",
            "acme.kit.old_b",
        ),
        prefilter_tokens=("dump", "gone", "old_a", "old_b"),
    ),
    changes=(TOOL, DUMP, GONE),
    limitations=("Invented for the tests; no library of this name exists.",),
)
SPEC = loader.to_scan_spec(
    loader.LoadedPack(
        pack=PACK,
        sha256="0" * 64,
        data=b"",
        reference=PACK.id,
        bundled=False,
        path=Path("pack.yaml"),
    )
)

SOURCE = "import acme.kit as kit\n\nA = kit.old_a(1)\nUNRELATED = 1\nB = kit.old_b(2)\n"
RENAMES = "out = data.replace(b'kit.old_a', b'kit.new_a').replace(b'kit.old_b', b'kit.new_b')"
FIXED = SOURCE.replace("old_a", "new_a").replace("old_b", "new_b")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def made(
    body: str = RENAMES,
    *,
    version: str = "9.9.9",
    releases: str = "==9.9.9",
    probe: str | None = None,
    record: Path | None = None,
) -> fixers.Fixer:
    """The interpreter, started as a fixer is, running `body` over `data` to make `out`."""
    script = f"import sys\ndata = sys.stdin.buffer.read()\n{body}\nsys.stdout.buffer.write(out)\n"
    if record is not None:
        script = (
            "import json, os, sys\n"
            "json.dump({'cwd': os.getcwd(), 'listing': os.listdir('.'), 'env': sorted(os.environ),"
            " 'argv': sys.argv[1:]}, open(sys.argv[1], 'w'))\n" + script
        )
    # One line, so no system reads a newline in a command line differently.
    argv = ("-c", f"exec({script!r})", str(record) if record else "unused", "{name}")
    name = Path(sys.executable).name
    return fixers.Fixer(
        name, releases, argv, f"{name}==9.9.9", ("-c", probe or f"print('fake {version}')")
    )


def tool(monkeypatch: pytest.MonkeyPatch, spec: fixers.Fixer | None = None) -> None:
    """`spec` for the one fixer the registry holds, and the interpreter's folder on the `PATH`."""
    monkeypatch.setattr(fixers, "FIXERS", {"ruff:NPY201": spec or made()})
    monkeypatch.setenv("PATH", f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}")


def run(tmp_path: Path, source: str = SOURCE) -> codemod.Run:
    (tmp_path / "app.py").write_bytes(source.encode())
    return migrate(tmp_path, SPEC, PACK)


def codes(done: codemod.Run) -> set[BailCode]:
    return {row.reason for row in done.edits if row.reason is not None}

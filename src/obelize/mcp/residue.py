"""The places a migration left, each with the code around it, for a coding agent to finish.

Built from a scan's findings and the files as they are. The text is the window a model would be
shown (`providers.base.excerpt`), redacted by the same redactor, so what an agent reads here is
what the model adapter would send and no more.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from obelize.models import BAIL_ACTIONS, WITHHELD, Config, Finding, FindingsDocument
from obelize.packs import loader
from obelize.providers import base
from obelize.scan import parse
from obelize.transforms.kinds import flag_only
from obelize.verify.runner import config_home, user_config

if TYPE_CHECKING:
    from collections.abc import Mapping

# Rows with no source text to show: a dependency declaration, or a file that did not parse.
_NO_WINDOW = frozenset({"manifest", "parse_error"})


def collect(
    root: Path, document: Mapping[str, Any], limit: int, environ: Mapping[str, str]
) -> dict[str, Any]:
    """The withheld rows of a scan's `--json` document, `limit` of them, in document order."""
    scan = FindingsDocument.model_validate(document)
    # The code to change first, then the dependency lines that follow from it.
    held = sorted(
        (row for row in scan.findings if row.scan_status in WITHHELD),
        key=lambda row: row.kind == "manifest",
    )
    places = [_place(root, row, environ) for row in held[:limit]]
    dirs = tuple(Path(entry) for entry in user_config(config_home(environ)).pack_dirs)
    packs: list[dict[str, str]] = []
    guides: list[dict[str, Any]] = []
    for ref in scan.packs:
        try:
            pack = loader.load(ref.id, dirs=dirs).pack
        except loader.PackError:
            # An inventory has no pack, and a pack that has moved since the scan has no words.
            continue
        packs.append({"id": pack.id, "version": pack.pack_version, "guide": pack.source.url})
        guides.extend(
            {
                "rule": guide.rule_id,
                "places": guide.findings,
                "message": guide.message,
                "suggestion": guide.suggestion,
            }
            for guide in flag_only.guides(pack, scan.findings)
        )
    return {
        "packs": packs,
        "total": len(held),
        "shown": len(places),
        "places": places,
        "guides": guides,
    }


def _place(root: Path, row: Finding, environ: Mapping[str, str]) -> dict[str, Any]:
    assert row.bail is not None  # noqa: S101 - a withheld row always names a reason
    context = None
    if row.kind not in _NO_WINDOW:
        data, _refused = parse.contents(root, row.path, Config())
        shown = None if data is None else base.excerpt(row.path, data, row.line, environ)
        if shown is not None:
            context = {
                "start_line": shown.start_line,
                "end_line": shown.end_line,
                "text": shown.text,
            }
    return {
        "path": row.path,
        "line": row.line,
        "column": row.column,
        "kind": row.kind,
        "symbol": row.symbol,
        "status": row.scan_status,
        "reason": row.bail,
        "caused_by": list(row.caused_by) if row.caused_by else None,
        "action": BAIL_ACTIONS[row.bail],
        "context": context,
    }


__all__ = ["collect"]

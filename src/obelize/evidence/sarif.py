"""A scan's findings as SARIF 2.1.0, the format GitHub code scanning reads.

One result per finding that is not prose or context. The rule of a result is the code that withheld
it, or `eligible` where obelize can write the migration, so a viewer groups the places by what to
do about them. Nothing here is time-derived: two scans of one input print the same bytes.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Final

from obelize import __version__
from obelize.models import BAIL_ACTIONS

if TYPE_CHECKING:
    from collections.abc import Sequence

    from obelize.models import Finding, PackRef

SCHEMA: Final = "https://json.schemastore.org/sarif-2.1.0.json"
HOME: Final = "https://github.com/hakanbogan/obelize"
ELIGIBLE: Final = "eligible"

# What a viewer shows: a place obelize can write is a note, one that needs a person a warning, and
# one no change can express an error.
LEVELS: Final = {"eligible": "note", "needs_review": "warning", "unsupported": "error"}
_ELIGIBLE_TEXT: Final = "obelize can migrate this place. Run `obelize fix` to see the change."


def _rule(finding: Finding) -> str:
    return finding.bail or ELIGIBLE


def _help(finding: Finding) -> str:
    return _ELIGIBLE_TEXT if finding.bail is None else BAIL_ACTIONS[finding.bail]


def _message(finding: Finding) -> str:
    text = _help(finding)
    held = f" Held back by: {', '.join(finding.caused_by)}." if finding.caused_by else ""
    return f"`{finding.symbol}` is affected by the migration. {text}{held}"


def _result(finding: Finding, index: int) -> dict[str, Any]:
    return {
        "ruleId": _rule(finding),
        "ruleIndex": index,
        "level": LEVELS[finding.scan_status],
        "message": {"text": _message(finding)},
        "locations": [
            {
                "physicalLocation": {
                    "artifactLocation": {"uri": finding.path, "uriBaseId": "%SRCROOT%"},
                    "region": {"startLine": finding.line, "startColumn": finding.column + 1},
                }
            }
        ],
    }


def document(findings: Sequence[Finding], packs: Sequence[PackRef] = ()) -> str:
    """The SARIF document for `findings`, as the bytes `--sarif` prints."""
    shown = [row for row in findings if row.scan_status != "not_a_usage"]
    described = {_rule(row): _help(row) for row in shown}
    codes = sorted(described)
    rules = [
        {"id": code, "shortDescription": {"text": code}, "help": {"text": described[code]}}
        for code in codes
    ]
    run = {
        "tool": {
            "driver": {
                "name": "obelize",
                "version": __version__,
                "informationUri": HOME,
                "rules": rules,
            }
        },
        "results": [_result(row, codes.index(_rule(row))) for row in shown],
        "properties": {
            "packs": [
                {"id": pack.id, "version": pack.version, "sha256": pack.sha256} for pack in packs
            ]
        },
    }
    sarif = {"$schema": SCHEMA, "version": "2.1.0", "runs": [run]}
    return json.dumps(sarif, indent=2) + "\n"


__all__ = ["document"]

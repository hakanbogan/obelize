"""docs/ROADMAP.md is prose now, not a task table; nothing in the repository can cite a task id.

A `partial` row in docs/THREAT_MODEL.md's status table names the docs/KNOWN_ISSUES.md entry
that covers what is still open, or cites ADR-048 where that ADR accepts the gap, instead of
naming a task.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
THREAT_MODEL = ROOT / "docs" / "THREAT_MODEL.md"

# A bare task id. `TM-7` does not match, because `\b` does not fall between T and M.
TASK_ID = re.compile(r"\bT\d+\b")


def _front_facing_files() -> list[Path]:
    """Documents that once cited task ids and must not have started again.

    docs/adr/ and docs/DECISIONS.md keep a historical record that may legitimately cite one
    (test_voice_lint.py excludes them for the same reason), so neither is scanned here.
    """
    return [
        ROOT / "CONTRIBUTING.md",
        ROOT / "README.md",
        ROOT / "CHANGELOG.md",
        ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md",
        *sorted(p for p in (ROOT / "docs").glob("*.md") if p.name != "DECISIONS.md"),
        *sorted((ROOT / ".github" / "workflows").glob("*.yml")),
    ]


@pytest.mark.parametrize("path", _front_facing_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_front_facing_document_cites_a_task_id(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    found = TASK_ID.findall(text)
    assert not found, f"{path.relative_to(ROOT)} cites a task id: {found}"


def test_the_task_id_pattern_does_not_catch_a_threat_id() -> None:
    assert not TASK_ID.search("TM-7 reads partial.")
    assert TASK_ID.search("Fixed in T42.")


# THREAT_MODEL.md status table: id, threat, mitigation, test.
THREAT_ROW = re.compile(r"^\| (TM-\d+) \| [^|]+ \| ([^|]+) \| [^|]+ \|$", re.MULTILINE)

KNOWN_ISSUES_LINK = "KNOWN_ISSUES.md"
ADR_048 = "ADR-048"


def _unowned_partial_rows(threat_model: str) -> list[str]:
    """`partial` rows naming neither docs/KNOWN_ISSUES.md nor ADR-048."""
    offenders = []
    for threat, mitigation in THREAT_ROW.findall(threat_model):
        if not mitigation.strip().startswith("partial"):
            continue
        if KNOWN_ISSUES_LINK not in mitigation and ADR_048 not in mitigation:
            offenders.append(threat)
    return offenders


def test_every_partial_threat_row_names_known_issues_or_adr_048() -> None:
    offenders = _unowned_partial_rows(THREAT_MODEL.read_text(encoding="utf-8"))
    assert not offenders, (
        f"{offenders} read `partial` in docs/THREAT_MODEL.md and name neither "
        f"docs/KNOWN_ISSUES.md nor ADR-048. Name the one that covers what is still open."
    )


def test_the_partial_row_check_finds_each_planted_defect() -> None:
    """The real table may have no offender, so each kind is planted."""
    planted = "\n".join(
        [
            "| TM-1 | a | yes — done | yes |",
            "| TM-2 | b | partial — nothing named | yes |",
            "| TM-3 | c | partial — see [KNOWN_ISSUES.md](KNOWN_ISSUES.md#x) | yes |",
            "| TM-4 | d | partial — accepted for 0.1.0 (ADR-048) | yes |",
            "| TM-5 | e | yes — not a partial row at all | yes |",
        ]
    )
    assert _unowned_partial_rows(planted) == ["TM-2"]

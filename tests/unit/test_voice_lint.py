"""Front-facing text keeps the voice CONTRIBUTING.md's "Beyond that" section describes.

Scope is the files a newcomer reads first: README, CONTRIBUTING, SECURITY, CHANGELOG and the
issue/PR templates. The ADR corpus is plan item 5.5's job, and docs/DECISIONS.md keeps a
historical record that may legitimately need what this file bans, so neither is scanned here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

FRONT_FACING_FILES: tuple[Path, ...] = (
    ROOT / "README.md",
    ROOT / "CONTRIBUTING.md",
    ROOT / "SECURITY.md",
    ROOT / "CHANGELOG.md",
    ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md",
    *sorted((ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.yml")),
)

TASK_ID = re.compile(r"\bT[0-9]+\b")
# A checkbox ("- [ ] **word**") is not a bullet opening on bold text; only whitespace may sit
# between the marker and the `**`.
BOLD_BULLET = re.compile(r"^[ \t]*[-*][ \t]*\*\*", re.MULTILINE)
EM_DASH = "—"


def voice_violations(text: str) -> list[str]:
    """Every reason `text` would fail CONTRIBUTING.md's "Beyond that" rules, empty if none."""
    lowered = text.lower()
    found: list[str] = []
    if "founder" in lowered:
        found.append("the word 'founder'")
    if "handover" in lowered:
        found.append("the word 'handover'")
    if TASK_ID.search(text):
        found.append("a task id")
    if BOLD_BULLET.search(text):
        found.append("a bullet that opens with bold text")
    if EM_DASH in text:
        found.append("an em dash")
    if " -- " in text:
        found.append("a double hyphen standing in for one")
    return found


@pytest.mark.parametrize("path", FRONT_FACING_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_a_front_facing_file_keeps_the_maintainers_voice(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    violations = voice_violations(text)
    assert not violations, f"{path.relative_to(ROOT)}: {', '.join(violations)}"


# Planted defects, one per branch `voice_violations` can take. The two word checks use the
# literal banned words on purpose, as fixture data proving detection, the same way
# `test_status_claims.py`'s own CITATIONS list must spell out the phrases it forbids elsewhere.
PLANTED = (
    ("Written by the founder, who kept every gate green.", "the word 'founder'"),
    ("Read handover notes before you start.", "the word 'handover'"),
    ("Fixed in T42, see the diff.", "a task id"),
    ("- **Bold lead.** The rest of the bullet.", "a bullet that opens with bold text"),
    ("A pause—then a second thought.", "an em dash"),
    ("A pause -- then a second thought.", "a double hyphen standing in for one"),
)


@pytest.mark.parametrize(("planted", "expected"), PLANTED, ids=lambda v: str(v)[:24])
def test_a_planted_violation_is_reported(planted: str, expected: str) -> None:
    assert voice_violations(planted) == [expected]


def test_a_checkbox_is_not_a_bold_led_bullet() -> None:
    """`- [ ] **word**` is a checklist item; the bold does not open the bullet."""
    assert voice_violations("- [ ] **Every claim is backed by a test.**") == []


def test_clean_text_has_no_violations() -> None:
    assert voice_violations("A plain sentence in the maintainer's own voice.") == []


def test_a_task_id_shaped_substring_inside_a_larger_token_is_not_flagged() -> None:
    """`\\bT[0-9]+\\b` names a whole word; `T42x` is not one, so nothing here is a task id."""
    assert voice_violations("See error T42x for details.") == []


def test_several_planted_violations_are_all_reported_together() -> None:
    text = "Written by the founder—see handover notes, T7."
    assert voice_violations(text) == [
        "the word 'founder'",
        "the word 'handover'",
        "a task id",
        "an em dash",
    ]

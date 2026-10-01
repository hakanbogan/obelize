"""`patch.diff`, graded by `git apply`: each patch must turn a copy of `before` into `after`.

Bytes throughout: latin-1, CRLF, BOM and bare-CR files must pass through unchanged, and no
decoding can be chosen for a file whose encoding is under test.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from obelize.evidence import patch
from obelize.fsutil import Change
from platforms import posix_only

# Ten lines apart is more than 2 * CONTEXT, so the two changes below cannot share a hunk.
FILLER = b"".join(b"pad %d\n" % index for index in range(10))

# (id, path, before, after, hunks): hunk counts are hand-written; the bytes are graded by git.
CASES: tuple[tuple[str, str, bytes, bytes, int], ...] = (
    (
        "one hunk",
        "plain.py",
        b"import a\nimport b\nx = 1\n",
        b"import a\nimport c\nx = 1\n",
        1,
    ),
    (
        "two changes too far apart to share a hunk",
        "far.py",
        b"first\n" + FILLER + b"second\n",
        b"FIRST\n" + FILLER + b"SECOND\n",
        2,
    ),
    (
        "two changes close enough to share one",
        "near.py",
        b"first\nkeep\nsecond\n",
        b"FIRST\nkeep\nSECOND\n",
        1,
    ),
    (
        "a last line that gains a terminator",
        "grew.py",
        b"x = 1\ny = 2",
        b"x = 1\ny = 3\n",
        1,
    ),
    (
        "a last line that loses one",
        "shrank.py",
        b"x = 1\ny = 2\n",
        b"x = 1\ny = 3",
        1,
    ),
    (
        "neither side ends with a terminator",
        "neither.py",
        b"x = 1\ny = 2",
        b"x = 1\ny = 3",
        1,
    ),
    (
        "CRLF, which stays CRLF",
        "windows.py",
        b"import a\r\nimport b\r\n",
        b"import a\r\nimport c\r\n",
        1,
    ),
    (
        "a bare CR, which is one line and not nine",
        "oldmac.py",
        b"a = 1\rb = 2\rc = 3",
        b"a = 1\rb = 9\rc = 3",
        1,
    ),
    (
        "latin-1 bytes nothing decodes",
        "latin.py",
        b"# caf\xe9\nx = 1\n",
        b"# caf\xe9\nx = 2\n",
        1,
    ),
    (
        "a BOM, which is content and not a marker",
        "bom.py",
        b"\xef\xbb\xbfx = 1\n",
        b"\xef\xbb\xbfx = 2\n",
        1,
    ),
    (
        "every line removed",
        "emptied.py",
        b"x = 1\ny = 2\n",
        b"",
        1,
    ),
    (
        "a file that had nothing in it",
        "filled.py",
        b"",
        b"x = 1\n",
        1,
    ),
    ("a space in the name", "with space.py", b"x = 1\n", b"x = 2\n", 1),
    ("a quote in the name", 'qu"ote.py', b"x = 1\n", b"x = 2\n", 1),
    ("a tab in the name", "ta\tb.py", b"x = 1\n", b"x = 2\n", 1),
    ("bytes above ASCII in the name", "café.py", b"x = 1\n", b"x = 2\n", 1),
)

UNSTORABLE = posix_only("Windows cannot store this name; the POSIX runs grade the same bytes")

NAMED = [
    pytest.param(*case, marks=[UNSTORABLE] if set(case[1]) & {'"', "\t"} else []) for case in CASES
]
IDS = [case[0] for case in CASES]


def git(root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", "-C", str(root), *arguments], check=True, capture_output=True)


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    git(work, "init", "-q", "-b", "work")
    return work


@pytest.mark.parametrize(("name", "path", "before", "after", "hunks"), NAMED, ids=IDS)
def test_git_applies_the_patch_and_gets_the_migration_back(
    name: str, path: str, before: bytes, after: bytes, hunks: int, repository: Path
) -> None:
    one = patch.diff([Change(path=path, before=before, after=after)])
    assert len(one) == 1, name
    assert one[0].hunks == hunks, one[0].text.decode("utf-8", "replace")
    (repository / path).write_bytes(before)
    (repository / "change.patch").write_bytes(one[0].text)
    git(repository, "apply", "--check", "--verbose", "change.patch")
    git(repository, "apply", "change.patch")
    assert (repository / path).read_bytes() == after, name


def test_a_file_whose_bytes_did_not_change_contributes_nothing() -> None:
    """No empty entry: read against `file_edits`, a hunkless row would claim a file it lacks."""
    assert patch.diff([Change(path="same.py", before=b"x = 1\n", after=b"x = 1\n")]) == ()


def test_the_document_is_every_file_in_path_order() -> None:
    """Path order, matching `plan.json`'s `files[]`."""
    changes = [
        Change(path="z.py", before=b"z = 1\n", after=b"z = 2\n"),
        Change(path="a.py", before=b"a = 1\n", after=b"a = 2\n"),
    ]
    patches = patch.diff(changes)
    assert [one.path for one in patches] == ["a.py", "z.py"]
    assert patch.render(patches) == patches[0].text + patches[1].text


def test_a_diff_of_no_changes_is_empty() -> None:
    assert patch.render(()) == b""


def test_a_bare_cr_is_one_line_and_not_nine() -> None:
    """`bytes.splitlines` splits on a bare CR; `git diff` does not, and git is the reference."""
    data = b"a = 1\rb = 2\rc = 3\r"
    assert len(data.splitlines()) == 3
    assert patch._lines(data) == [data]
    assert patch._lines(b"") == []
    assert patch._lines(b"one\ntwo") == [b"one\n", b"two"]
    assert patch._lines(b"one\n") == [b"one\n"]


def test_a_missing_terminator_is_marked_the_way_the_applier_reads_it() -> None:
    assert patch._row(b"-", b"x = 1\n") == b"-x = 1\n"
    assert patch._row(b"+", b"x = 1") == b"+x = 1\n" + patch.NO_NEWLINE


def test_a_hunk_header_shortens_a_single_line_and_points_before_an_empty_side() -> None:
    """A one-line side omits its length; an empty side starts at the line *before* it."""
    assert patch._span(4, 5) == "5"
    assert patch._span(0, 0) == "0,0"
    assert patch._span(0, 2) == "1,2"
    assert patch._span(3, 7) == "4,4"
    emptied = patch.diff([Change(path="e.py", before=b"x = 1\ny = 2\n", after=b"")])
    assert b"@@ -1,2 +0,0 @@\n" in emptied[0].text


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("plain.py", b"--- a/plain.py\n+++ b/plain.py\n"),
        ("with space.py", b"--- a/with space.py\t\n+++ b/with space.py\t\n"),
        ('qu"ote.py', b'--- "a/qu\\"ote.py"\n+++ "b/qu\\"ote.py"\n'),
        ("back\\slash.py", b'--- "a/back\\\\slash.py"\n+++ "b/back\\\\slash.py"\n'),
        ("ta\tb.py", b'--- "a/ta\\tb.py"\n+++ "b/ta\\tb.py"\n'),
        ("café.py", b'--- "a/caf\\303\\251.py"\n+++ "b/caf\\303\\251.py"\n'),
        # Below 0o100: the only escape that tells `\%03o` from `\%o` (the rest are 3 digits anyway).
        ("ctrl\x01.py", b'--- "a/ctrl\\001.py"\n+++ "b/ctrl\\001.py"\n'),
    ],
)
def test_the_name_is_quoted_the_way_git_quotes_it(path: str, expected: bytes) -> None:
    """Spaces stay bare (a tab ends the name); C-quoting uses named escapes, else octal UTF-8."""
    preamble = patch._preamble(path)
    assert preamble.endswith(expected)
    assert preamble.startswith(b"diff --git ")
    assert b"\nindex " not in preamble, "an index line needs git's blob hash and is not written"


def test_a_plain_name_is_not_quoted_and_an_awkward_one_is() -> None:
    assert not patch._awkward(b"src/app.py")
    assert not patch._awkward(b"with space.py")
    assert patch._awkward(b'qu"ote.py')
    assert patch._awkward(b"bell\x07.py")
    assert patch._awkward("café.py".encode())
    assert patch._quote(b"bell\x07.py") == b'"bell\\a.py"'
    assert patch._quote(b"ctrl\x01.py") == b'"ctrl\\001.py"'
    assert patch._quote(b"nl\n.py") == b'"nl\\n.py"'


def test_the_context_is_the_three_lines_every_differ_defaults_to() -> None:
    """Public because `plan.json`'s hunk count depends on it."""
    assert patch.CONTEXT == 3
    nine = b"".join(b"%d\n" % number for number in range(9))
    one = patch.diff([Change(path="c.py", before=nine, after=nine.replace(b"4\n", b"X\n"))])
    assert one[0].hunks == 1
    assert one[0].text.count(b"@@ -") == 1
    context = [line for line in one[0].text.split(b"\n") if line.startswith(b" ")]
    assert len(context) == 2 * patch.CONTEXT, context
    hunk = one[0].text.split(b"@@ -2,7 +2,7 @@\n")[1]
    assert b"0\n" not in hunk, "the first line is four away and out of range"

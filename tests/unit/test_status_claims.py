"""What the repository says about itself, checked against what it does.

1. Command lists match exactly what the Typer app registers.
2. Every count a document prints is recomputed from disk; only its spelling is written here.
3. No tracked file cites the out-of-repository planning document, bar a short allowlist.
4. Relative links and anchors resolve from the citing file's own directory.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import typer.main
import yaml

from obelize.cli import app

ROOT = Path(__file__).resolve().parents[2]


def registered() -> frozenset[str]:
    """Every command a user can type, as Click sees it, `pack validate` included."""
    root = typer.main.get_command(app)
    names: set[str] = set()
    for name, command in root.commands.items():  # type: ignore[attr-defined]
        children = getattr(command, "commands", None)
        if children:
            names.update(f"{name} {child}" for child in children)
        else:
            names.add(name)
    return frozenset(names)


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _commands_in(text: str) -> frozenset[str]:
    """`obelize <name>` and `obelize <group> <name>`, ignoring bare flags."""
    found: set[str] = set()
    for match in re.finditer(r"obelize ((?:[a-z][a-z-]*)(?: [a-z][a-z-]*)?)", text):
        words = match.group(1).split()
        found.add(" ".join(words[:2]) if len(words) == 2 and words[0] == "pack" else words[0])
    return frozenset(found)


def test_the_readme_commands_table_lists_exactly_the_commands_that_exist() -> None:
    """A command is listed only once it ships, so the table is also the status."""
    section = _read("README.md").split("\n## Commands\n")[1]
    rows = [line for line in section.splitlines() if line.startswith("| `obelize ")]
    listed = frozenset(row.split("`")[1].removeprefix("obelize ").strip() for row in rows)
    assert listed == registered()


def test_contributing_lists_exactly_the_commands_that_exist() -> None:
    block = _read("CONTRIBUTING.md").split("## Commands")[1]
    block = block.split("```bash")[1].split("```")[0]
    assert _commands_in(block) == registered()


# Once published and false. Only a floor against reverts: 1 and 2 catch new wordings.
DENIALS = (
    "are **not implemented**",
    "nothing applies it yet",
    "no rule kind does",
    "no benchmark round has\n> been run",
    "not shipped behaviour",
    "the only commands that run are",
    "only `obelize --help` and `obelize --version` do anything",
    "`pack validate` do not exist yet",
    "Most of it is not written yet",
    "the model adapter\nhas not been written",
    "not on PyPI",
    "Not published yet",
    "Windows is untested",
    "untested, unsupported",
    "which is not supported yet",
    "has not run on Windows yet",
)


def _claim_bearing_files() -> list[Path]:
    """Documents a reader takes as current; dated records are excluded."""
    return [
        ROOT / "README.md",
        ROOT / "CONTRIBUTING.md",
        ROOT / "SECURITY.md",
        *sorted((ROOT / "docs").glob("*.md")),
        *sorted((ROOT / "bench").glob("*.md")),
        *sorted((ROOT / ".github" / "ISSUE_TEMPLATE").glob("*.yml")),
        *sorted((ROOT / ".github" / "workflows").glob("*.yml")),
    ]


@pytest.mark.parametrize("path", _claim_bearing_files(), ids=lambda p: p.name)
def test_no_current_document_denies_a_command_that_ships(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    for phrase in DENIALS:
        assert phrase not in text, f"{path.relative_to(ROOT)} still says {phrase!r}"


def test_every_adr_has_an_index_row_and_every_row_has_an_adr() -> None:
    """`docs/DECISIONS.md` says an ADR it does not list "does not count as a decision"."""
    index = _read("docs/DECISIONS.md")
    listed = set(re.findall(r"^\| (ADR-\d+) \|", index, re.MULTILINE))
    on_disk = {
        path.name.split("-")[0] + "-" + path.name.split("-")[1]
        for path in (ROOT / "docs" / "adr").glob("ADR-*.md")
    }
    assert listed == on_disk
    for name in sorted(on_disk):
        assert f"](adr/{name}-" in index, f"{name} is listed but not linked"


_ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_TENS = ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def spell(n: int) -> str:
    """`n` in words, the way these documents write it: "one hundred and ten"."""
    if not 0 <= n < 1000:
        raise ValueError(f"{n} is outside what a document here spells out")
    if n < 20:
        return _ONES[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _TENS[tens - 2] + (f"-{_ONES[ones]}" if ones else "")
    hundreds, rest = divmod(n, 100)
    return f"{_ONES[hundreds]} hundred" + (f" and {spell(rest)}" if rest else "")


# Today's document spellings, plus a round hundred, a teen and zero.
SPELLINGS = [
    (0, "zero"),
    (10, "ten"),
    (11, "eleven"),
    (16, "sixteen"),
    (18, "eighteen"),
    (24, "twenty-four"),
    (32, "thirty-two"),
    (34, "thirty-four"),
    (54, "fifty-four"),
    (81, "eighty-one"),
    (110, "one hundred and ten"),
    (300, "three hundred"),
    (913, "nine hundred and thirteen"),
]


@pytest.mark.parametrize(("number", "words"), SPELLINGS)
def test_a_number_is_spelt_the_way_the_documents_spell_it(number: int, words: str) -> None:
    assert spell(number) == words


def test_a_number_no_document_would_spell_is_refused() -> None:
    with pytest.raises(ValueError, match="outside"):
        spell(1000)


# Documents that write 10 and above in digits, and smaller numbers in words.
DIGITS = frozenset({"README.md"})


def written(n: int, *, digits: bool) -> str:
    return str(n) if digits and n >= 10 else spell(n)


@pytest.mark.parametrize(
    ("number", "digits", "words"),
    [(9, True, "nine"), (10, True, "10"), (36, True, "36"), (36, False, "thirty-six")],
)
def test_a_number_is_written_in_digits_from_ten_where_a_document_says_so(
    number: int, digits: bool, words: str
) -> None:
    assert written(number, digits=digits) == words


def says(text: str, sentence: str, count: int, *, digits: bool = False) -> bool:
    """Whether `text` prints `sentence` with `count` in it, ignoring case and wrapping."""
    flat = re.sub(r"\s+", " ", text).lower()
    return sentence.format(n=written(count, digits=digits)).lower() in flat


def _pack() -> dict[str, object]:
    path = ROOT / "src/obelize/packs/gemini/google-generativeai-to-google-genai/pack.yaml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _cases_in(relative: str) -> int:
    loaded = yaml.safe_load(_read(relative))
    return len(loaded["cases"])


def _before_files(corpus: str) -> int:
    return len(list((ROOT / "tests/fixtures/transforms" / corpus).glob("*.before.py")))


def _negative_packs() -> int:
    return len(list((ROOT / "tests/packs/_negative").glob("*.yaml")))


def _coverage_gaps(closed: bool) -> int:
    pattern = r"^\d+\. ~~" if closed else r"^\d+\. "
    return len(re.findall(pattern, _read("tests/fixtures/scan/COVERAGE.md"), re.MULTILINE))


CORPORA = (
    "rename_import",
    "configure_to_client",
    "generative_model_calls",
    "rewrite_call",
    "flag_only",
)


def _fixture_key_zeros() -> int:
    """The TM-3 fixture key's trailing zeros, counted in the fixture."""
    text = _read("tests/fixtures/providers/deep/nested.py")
    match = re.search(r"AIzaSyD(0+)", text)
    assert match, "the TM-3 fixture key is gone from tests/fixtures/providers/"
    return len(match.group(1))


# (document, sentence with a `{n}` hole, count); whitespace is normalised, so a reflow passes.
COUNTS: tuple[tuple[str, str, int], ...] = (
    (
        ".github/secret_scanning.yml",
        "and then {n} zeros",
        _fixture_key_zeros(),
    ),
    ("docs/THREAT_MODEL.md", "{n} packs under `tests/packs/_negative/`", _negative_packs()),
    ("docs/THREAT_MODEL.md", "{n} negative packs, one per documented refusal", _negative_packs()),
    (
        "docs/THREAT_MODEL.md",
        "over {n} cases in five fixture repositories",
        _cases_in("tests/fixtures/commands/answers.yaml"),
    ),
    (
        "docs/THREAT_MODEL.md",
        "and {n} cases over the commands",
        _cases_in("tests/fixtures/commands/answers.yaml"),
    ),
    ("README.md", "the {n} changes the migration makes", len(_pack()["changes"])),  # type: ignore[arg-type]
    ("README.md", "and {n} limitations. The limitations say", len(_pack()["limitations"])),  # type: ignore[arg-type]
    ("README.md", "lists {n} gaps the fixtures do not cover", _coverage_gaps(closed=False)),
    ("README.md", "{n} of them closed", _coverage_gaps(closed=True)),
    ("tests/fixtures/scan/COVERAGE.md", "{n} are written down", _coverage_gaps(closed=False)),
    ("tests/fixtures/scan/COVERAGE.md", "**{n} are closed**", _coverage_gaps(closed=True)),
    (
        "CONTRIBUTING.md",
        "the verification runner over {n} more",
        _cases_in("tests/fixtures/verify/answers.yaml"),
    ),
    (
        "CONTRIBUTING.md",
        "the transform rules over {n} more",
        sum(_before_files(c) for c in CORPORA),
    ),
    *tuple(
        ("CONTRIBUTING.md", "{n} for `" + corpus + "`", _before_files(corpus)) for corpus in CORPORA
    ),
)


@pytest.mark.parametrize(("relative", "sentence", "count"), COUNTS, ids=lambda v: str(v)[:40])
def test_a_count_a_document_prints_is_the_count_on_disk(
    relative: str, sentence: str, count: int
) -> None:
    digits = relative in DIGITS
    assert says(_read(relative), sentence, count, digits=digits), (
        f"{relative} does not say {sentence.format(n=written(count, digits=digits))!r}; "
        f"the number on disk is {count}"
    )


def test_the_coverage_gaps_run_from_one_in_order() -> None:
    """Documents cite a gap by number, and the counts above count numbered lines, not numbers."""
    text = _read("tests/fixtures/scan/COVERAGE.md")
    numbers = [int(n) for n in re.findall(r"^(\d+)\. ", text, re.MULTILINE)]
    assert numbers == list(range(1, len(numbers) + 1)), (
        f"tests/fixtures/scan/COVERAGE.md numbers its gaps {numbers}: a repeated or skipped "
        f"number makes a citation ambiguous and the count disagree with the last gap"
    )


# Citation shapes, not bare words: a document may name the out-of-repository planning document,
# never point into it.
CITATIONS = (
    "the handover",
    "plan §",
    "plan section",
    "the plan called",
    "planning document called",
)

# This file defines the rule, so it must spell out the shapes above. The scan walks
# `git ls-files`: an untracked file is invisible to it.
CITATION_ALLOWLIST = ("tests/unit/test_status_claims.py",)


def _tracked_text_files(*, allowlisted: bool = False) -> list[Path]:
    """Tracked text files. `allowlisted=True` returns the ones the scan skips."""
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    keep = {".md", ".py", ".yaml", ".yml", ".toml", ".txt", ".cfg"}
    return [
        ROOT / name
        for name in out.split("\0")
        if name
        and Path(name).suffix in keep
        and any(name.startswith(p) for p in CITATION_ALLOWLIST) is allowlisted
    ]


def test_no_document_cites_the_out_of_repository_planning_document() -> None:
    offenders: list[str] = []
    for path in _tracked_text_files():
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        for citation in CITATIONS:
            if citation in text:
                offenders.append(f"{path.relative_to(ROOT)}: {citation!r}")
    assert not offenders, "a reader cannot open it:\n" + "\n".join(offenders)


# CITATIONS is literal strings; a plan item's number varies, so it needs its own pattern.
PLAN_ITEM_CITATION = re.compile(r"\bplan \d+\.\d+")


def test_the_plan_item_pattern_matches_a_numbered_citation_and_nothing_else() -> None:
    assert PLAN_ITEM_CITATION.search("reads plan 9.9 for the reasoning")
    assert not PLAN_ITEM_CITATION.search("the megaplan 4.5 release cycle")
    assert not PLAN_ITEM_CITATION.search("planning for 4.5 hours")


def test_no_document_cites_a_plan_item_by_number() -> None:
    """`CITATIONS` cannot spell a moving number, so this is a second, regex-based scan."""
    offenders: list[str] = []
    for path in _tracked_text_files():
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        if PLAN_ITEM_CITATION.search(text):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, "a reader cannot open it:\n" + "\n".join(offenders)


FENCE = re.compile(r"^```.*?^```", re.MULTILINE | re.DOTALL)
LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)\)")
INLINE_LINK_IN_HEADING = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def slug(heading: str) -> str:
    """GitHub's heading anchor. Each space becomes one hyphen; runs are kept."""
    text = INLINE_LINK_IN_HEADING.sub(r"\1", heading).lstrip("#").strip().lower()
    text = "".join(c for c in text if c.isalnum() or c in " -_")
    return text.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    seen: dict[str, int] = {}
    out: set[str] = set()
    body = FENCE.sub("", path.read_text(encoding="utf-8"))
    for line in body.splitlines():
        if line.startswith("#"):
            base = slug(line.lstrip("#"))
            n = seen.get(base, 0)
            seen[base] = n + 1
            out.add(base if n == 0 else f"{base}-{n}")
    return out


def broken_links(path: Path) -> list[str]:
    """Relative targets that do not resolve from `path`'s own directory."""
    body = FENCE.sub("", path.read_text(encoding="utf-8"))
    broken: list[str] = []
    for target in LINK.findall(body):
        if target.startswith(("http://", "https://", "mailto:", "#!")):
            continue
        location, _, fragment = target.partition("#")
        destination = path if location == "" else (path.parent / location).resolve()
        if not destination.exists():
            broken.append(f"{target} -> no such path")
            continue
        if fragment and destination.suffix == ".md" and fragment not in anchors(destination):
            broken.append(f"{target} -> no such heading")
    return broken


def _markdown_files(root: Path = ROOT) -> list[Path]:
    """Markdown git tracks or would track; a staged deletion is dropped by the `is_file` check."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "*.md"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    return sorted(
        root / name for name in set(listed.split("\0")) if name and (root / name).is_file()
    )


@pytest.mark.parametrize("path", _markdown_files(), ids=lambda p: p.name)
def test_every_relative_link_and_anchor_in_a_document_resolves(path: Path) -> None:
    broken = broken_links(path)
    assert not broken, f"{path.relative_to(ROOT)}:\n  " + "\n  ".join(broken)


def test_the_link_check_reads_what_git_would_publish_and_nothing_it_ignores(
    tmp_path: Path,
) -> None:
    """Ignored files (private notes, `bench/work/` clones) are skipped; unstaged ones are read."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("private.md\n", encoding="utf-8")
    (tmp_path / "private.md").write_text("[gone](nowhere.md)\n", encoding="utf-8")
    (tmp_path / "public.md").write_text("# Public\n", encoding="utf-8")
    assert _markdown_files(tmp_path) == [tmp_path / "public.md"]


# Planted defects: a guard that finds nothing here passes whether or not it works.

SLUGS = (
    ("Phase 4 — benchmark", "phase-4--benchmark"),
    ("## Exit codes", "exit-codes"),
    ("`run.json` and what it may carry", "runjson-and-what-it-may-carry"),
    ("What this file is *not*", "what-this-file-is-not"),
    ("See [ADR-004](adr/ADR-004-repo-visibility-and-ci.md)", "see-adr-004"),
)


@pytest.mark.parametrize(("heading", "expected"), SLUGS, ids=lambda v: str(v)[:32])
def test_slug_is_githubs_heading_anchor(heading: str, expected: str) -> None:
    """One hyphen per space, so a dropped em dash leaves two; collapsing them breaks links."""
    assert slug(heading) == expected


def test_anchors_numbers_a_repeated_heading(tmp_path: Path) -> None:
    """GitHub suffixes the second `## Notes` with `-1`, and a link may name it."""
    page = tmp_path / "page.md"
    page.write_text("# Notes\n\n## Notes\n\n## Notes\n", encoding="utf-8")
    assert anchors(page) == {"notes", "notes-1", "notes-2"}


def test_anchors_ignores_a_heading_inside_a_fenced_block(tmp_path: Path) -> None:
    page = tmp_path / "page.md"
    page.write_text("# Real\n\n```bash\n# Not a heading\n```\n", encoding="utf-8")
    assert anchors(page) == {"real"}


def test_a_planted_broken_link_and_a_planted_broken_anchor_are_both_reported(
    tmp_path: Path,
) -> None:
    (tmp_path / "there.md").write_text("# A heading\n", encoding="utf-8")
    page = tmp_path / "here.md"
    page.write_text(
        "[fine](there.md#a-heading)\n"
        "[gone](nowhere.md)\n"
        "[wrong anchor](there.md#no-such-heading)\n"
        "[external](https://example.invalid/x#frag)\n",
        encoding="utf-8",
    )
    assert broken_links(page) == [
        "nowhere.md -> no such path",
        "there.md#no-such-heading -> no such heading",
    ]


def test_a_relative_link_resolves_from_the_citing_file_not_from_the_root(
    tmp_path: Path,
) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "sibling.md").write_text("# X\n", encoding="utf-8")
    (tmp_path / "sibling.md").write_text("# X\n", encoding="utf-8")
    page = tmp_path / "docs" / "page.md"
    page.write_text("[a](sibling.md)\n[b](missing-sibling.md)\n", encoding="utf-8")
    assert broken_links(page) == ["missing-sibling.md -> no such path"]


def test_every_allowlisted_prefix_actually_excludes_its_files() -> None:
    """Both ways: a prefix that matches nothing on disk is a silent standing exception."""
    considered = {path.relative_to(ROOT).as_posix() for path in _tracked_text_files()}
    skipped = {path.relative_to(ROOT).as_posix() for path in _tracked_text_files(allowlisted=True)}
    for prefix in CITATION_ALLOWLIST:
        assert not [name for name in considered if name.startswith(prefix)], prefix
        assert [name for name in skipped if name.startswith(prefix)], prefix
    assert considered, "the citation scan looked at nothing at all"


def test_a_count_that_disagrees_with_the_disk_is_not_found_in_the_document() -> None:
    """On local text, not the live README, so a README edit cannot void this control."""
    text = "the pack carries Eighteen `limitations`\n  naming each surface, and 36\n gaps."
    assert says(text, "The pack carries {n} `limitations` naming", 18)
    assert not says(text, "The pack carries {n} `limitations` naming", 16)
    assert says(text, "surface, and {n} gaps", 36, digits=True)
    assert not says(text, "surface, and {n} gaps", 35, digits=True)

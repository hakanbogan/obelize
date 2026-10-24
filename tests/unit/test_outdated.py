"""`obelize outdated`: what the index says of each dependency the manifests declare."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from packaging.version import Version
from typer.testing import CliRunner

import fakeindex
from obelize import outdated
from obelize.cli import app
from obelize.net import Fetcher
from obelize.packs import loader
from obelize.scan.manifests import Declaration
from support import committed

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

runner = CliRunner()
SOURCE = {"__init__.py": "def f(x):\n    return x\n"}
INACTIVE = ["Development Status :: 7 - Inactive"]


def row(**changes: object) -> outdated.Row:
    found: dict[str, object] = {
        "distribution": "lib",
        "declared": "==1.0",
        "current": "1.0",
        "newest": "2.0",
        "gap": "major",
        "flags": (),
        "advisories": (),
        "knowledge": "synthesizable",
        "pack": None,
        "paths": ("requirements.txt",),
        "error": None,
    }
    return outdated.Row.model_validate({**found, **changes})


def declared(
    name: str, spec: str | None, path: str = "requirements.txt", *, constraint: bool = False
) -> Declaration:
    return Declaration(path, 1, 0, name, name, len(name), None, spec, constraint=constraint)


# What a declaration starts at, and how far that is from the newest.


def test_each_distribution_is_one_dependency_with_the_files_and_specifiers_that_name_it() -> None:
    found = outdated.dependencies(
        [
            declared("b", "==1.0"),
            declared("a", ">=2", "pyproject.toml"),
            declared("a", "<3", "requirements.txt"),
            declared("b", "==1.0", "dev.txt"),
            declared("c", None),
            declared("pinned", "==9", constraint=True),
        ]
    )
    assert [(one.name, one.specs, one.paths) for one in found] == [
        ("a", ("<3", ">=2"), ("pyproject.toml", "requirements.txt")),
        ("b", ("==1.0",), ("dev.txt", "requirements.txt")),
        ("c", (), ("requirements.txt",)),
    ]


@pytest.mark.parametrize(
    ("specs", "expected"),
    [
        (("==1.4.2",), "1.4.2"),
        ((">=1.4,<2",), "1.4"),
        (("~=1.4",), "1.4"),
        (("==1.*",), "1"),
        (("<2",), None),
        (("not a specifier", ">=3"), "3"),
        (("not a specifier",), None),
        ((), None),
    ],
)
def test_the_release_a_declaration_starts_at_is_the_one_it_pins_or_its_floor(
    specs: tuple[str, ...], expected: str | None
) -> None:
    found = outdated.current(specs)
    assert (None if found is None else str(found)) == expected


@pytest.mark.parametrize(
    ("now", "newest", "expected"),
    [
        ("1.0", "2.0", "major"),
        ("1.0", "1.1", "minor"),
        ("1.0.0", "1.0.1", "patch"),
        ("1.0", "1.0", "none"),
        ("2.0", "1.0", "none"),
        ("1.2", "1.1", "none"),
        ("1.0.2", "1.0.1", "none"),
        (None, "1.0", "unknown"),
        ("1.0", None, "unknown"),
    ],
)
def test_the_gap_between_two_releases_is_the_part_of_the_version_that_moved(
    now: str | None, newest: str | None, expected: str
) -> None:
    assert (
        outdated.gap(*(None if one is None else Version(one) for one in (now, newest))) == expected
    )


# What the index says.


@pytest.fixture(scope="module")
def served() -> Iterator[fakeindex.FakeIndex]:
    for found in fakeindex.FakeIndex().serve():
        found.add("acme-kit", "1.0", SOURCE)
        found.add("acme-kit", "2.0", SOURCE)
        found.add("old-lib", "3.0", SOURCE, classifiers=INACTIVE)
        found.add("yank-lib", "1.0", SOURCE, yanked="broken")
        found.add("yank-lib", "1.1", SOURCE)
        found.add("vuln-lib", "1.0", SOURCE)
        found.add("vuln-lib", "1.1", SOURCE)
        found.projects["vuln-lib"].vulnerabilities = [
            {"id": "PYSEC-2", "summary": "bad", "versions": ["1.0"]},
            {"id": "PYSEC-1", "summary": "worse", "versions": ["1.0"]},
            {"id": "PYSEC-9", "withdrawn": "2026-01-01", "versions": ["1.0"]},
        ]
        found.add("pypdf2", "3.0.1", SOURCE)
        found.add("pypdf", "6.19.0", SOURCE)
        found.add("setuptools", "81.0.0", SOURCE)
        found.add("setuptools", "82.0.0", SOURCE)
        yield found


def judged(
    served: fakeindex.FakeIndex, name: str, *specs: str, packs: bool = False
) -> outdated.Row:
    known = [loader.load(reference) for reference in loader.known()] if packs else []
    return outdated.judge(
        Fetcher(index=served.url), outdated.Dependency(name, specs, ("r.txt",)), known
    )


def test_a_dependency_behind_a_major_release_is_a_gap_to_compare(
    served: fakeindex.FakeIndex,
) -> None:
    found = judged(served, "acme-kit", "==1.0")
    assert (found.current, found.newest, found.gap, found.knowledge, found.pack) == (
        "1.0",
        "2.0",
        "major",
        "synthesizable",
        None,
    )
    assert found.flags == ()
    assert found.error is None


def test_a_library_that_marks_itself_inactive_is_flagged(served: fakeindex.FakeIndex) -> None:
    assert judged(served, "old-lib", ">=3").flags == ("inactive",)


def test_a_release_in_use_that_was_withdrawn_is_flagged(served: fakeindex.FakeIndex) -> None:
    found = judged(served, "yank-lib", "==1.0")
    assert found.flags == ("yanked",)
    assert found.newest == "1.1"


def test_the_advisories_of_the_release_in_use_are_listed_by_id_and_the_withdrawn_are_not(
    served: fakeindex.FakeIndex,
) -> None:
    found = judged(served, "vuln-lib", "==1.0")
    assert (found.flags, found.advisories) == (("advisory",), ("PYSEC-1", "PYSEC-2"))
    assert judged(served, "vuln-lib", "==1.1").advisories == ()


def test_a_declaration_that_names_no_release_cannot_be_judged_for_advisories(
    served: fakeindex.FakeIndex,
) -> None:
    found = judged(served, "vuln-lib")
    assert (found.current, found.gap, found.advisories) == (None, "unknown", ())


def test_a_distribution_a_bundled_pack_migrates_says_which(served: fakeindex.FakeIndex) -> None:
    found = judged(served, "pypdf2", "==3.0.1", packs=True)
    assert (found.knowledge, found.pack) == ("bundled", "py-pdf/pypdf2-to-pypdf")
    outside = judged(served, "pypdf2", "==2.0", packs=True)
    assert outside.knowledge == "synthesizable"
    assert judged(served, "pypdf2", packs=True).pack == "py-pdf/pypdf2-to-pypdf"


def test_a_distribution_a_pack_moves_to_the_python_says_which_pack(
    served: fakeindex.FakeIndex,
) -> None:
    """`pkg_resources` is a module of setuptools below 82, and its pack is run by its id."""
    found = judged(served, "setuptools", "==81.0.0", packs=True)
    assert (found.knowledge, found.pack) == ("bundled", "setuptools/pkg-resources-to-importlib")
    assert outdated.next_step([found]) == "obelize fix --pack setuptools/pkg-resources-to-importlib"
    beyond = judged(served, "setuptools", "==82.0.0", packs=True)
    assert (beyond.knowledge, beyond.pack) == ("synthesizable", None)


def test_a_distribution_the_index_does_not_have_is_a_row_with_the_reason(
    served: fakeindex.FakeIndex,
) -> None:
    found = judged(served, "private-lib", "==1.0")
    assert (found.error, found.knowledge, found.newest) == ("not on the index", "none", None)


def test_an_index_that_is_down_is_a_row_with_the_reason() -> None:
    dead = Fetcher(index="http://127.0.0.1:1/simple")
    found = outdated.judge(dead, outdated.Dependency("lib", ("==1.0",), ()), [])
    assert found.error is not None
    assert "127.0.0.1" in found.error


def test_a_project_with_only_withdrawn_releases_has_no_newest(served: fakeindex.FakeIndex) -> None:
    served.add("all-gone", "1.0", SOURCE, yanked="broken")
    found = judged(served, "all-gone", "==1.0")
    assert (found.newest, found.knowledge, found.flags) == (None, "none", ("yanked",))


# The rows, in order.


def test_rows_come_worst_first_and_a_row_is_shown_only_if_it_says_something(
    served: fakeindex.FakeIndex,
) -> None:
    found = outdated.survey(
        Fetcher(index=served.url),
        [
            outdated.Dependency("acme-kit", ("==1.0",), ()),
            outdated.Dependency("vuln-lib", ("==1.0",), ()),
            outdated.Dependency("pypdf", ("==6.19.0",), ()),
            outdated.Dependency("private-lib", ("==1.0",), ()),
            outdated.Dependency("old-lib", (">=3",), ()),
        ],
        [],
    )
    assert [one.distribution for one in found] == [
        "vuln-lib",
        "acme-kit",
        "private-lib",
        "old-lib",
        "pypdf",
    ]
    assert [outdated.worth_showing(one) for one in found] == [True, True, True, True, False]


def test_the_index_answering_nothing_is_told_from_a_project_it_does_not_have() -> None:
    gone = row(error="not on the index", newest=None)
    down = row(error="127.0.0.1: refused", newest=None)
    assert outdated.unreachable([gone, down])
    assert not outdated.unreachable([gone])
    assert not outdated.unreachable([gone, row()])
    assert not outdated.unreachable([])


def test_the_table_aligns_the_columns_and_names_what_to_migrate_with() -> None:
    lines = outdated.table(
        [
            row(
                distribution="pypdf2",
                knowledge="bundled",
                pack="py-pdf/pypdf2-to-pypdf",
                flags=("inactive",),
            ),
            row(
                distribution="lib",
                advisories=("PYSEC-1", "PYSEC-2", "PYSEC-3", "PYSEC-4"),
                flags=("advisory",),
            ),
            row(
                distribution="private",
                error="not on the index",
                newest=None,
                knowledge="none",
                gap="unknown",
                current=None,
            ),
        ]
    )
    assert lines[0].startswith("Distribution")
    assert "bundled pack py-pdf/pypdf2-to-pypdf" in lines[1]
    assert "advisory; PYSEC-1; PYSEC-2; +2 more" in lines[2]
    assert "PYSEC-3" not in lines[2]
    assert (
        lines[3].split()[-5:] == ["unknown", "not", "on", "the", "index"]
        or "not on the index" in lines[3]
    )
    assert len({line.index("Gap") if "Gap" in line else -1 for line in lines[:1]}) == 1


def test_the_next_step_is_the_first_row_that_has_a_way_to_migrate() -> None:
    assert outdated.next_step([row(knowledge="bundled", pack="a/b")]) == "obelize fix --pack a/b"
    assert outdated.next_step([row(knowledge="none"), row(distribution="x")]) == "obelize upgrade x"
    assert outdated.next_step([row(error="down")]) is None
    assert outdated.next_step([]) is None


# The command.


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, served: fakeindex.FakeIndex) -> Path:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("OBELIZE_INDEX_URL", served.url)
    monkeypatch.delenv("OBELIZE_OFFLINE", raising=False)
    return tmp_path


REQUIREMENTS = "acme-kit==1.0\nvuln-lib==1.0\npypdf==6.19.0\nprivate-lib==1.0\n"


def test_the_command_lists_what_is_behind_with_the_way_to_move_it(home: Path) -> None:
    repo = committed(home / "repo", {"requirements.txt": REQUIREMENTS})
    result = runner.invoke(app, ["outdated", "--repo", str(repo)])
    assert result.exit_code == 0, result.output
    assert "vuln-lib" in result.output
    assert "advisory; PYSEC-1; PYSEC-2" in result.output
    assert "two releases to compare" in result.output
    assert "pypdf " not in result.output
    assert "Next: obelize upgrade" in result.output
    assert "obelize contacts 127.0.0.1" in result.output


def test_all_lists_the_current_ones_too_and_json_is_the_document(home: Path) -> None:
    repo = committed(home / "repo", {"requirements.txt": REQUIREMENTS})
    result = runner.invoke(app, ["outdated", "--repo", str(repo), "--all", "--json"])
    assert result.exit_code == 0, result.output
    document = json.loads(result.stdout)
    assert document["index"] == "127.0.0.1"
    assert [one["distribution"] for one in document["rows"]] == [
        "vuln-lib",
        "acme-kit",
        "private-lib",
        "pypdf",
    ]
    assert document["rows"][0]["advisories"] == ["PYSEC-1", "PYSEC-2"]


def test_a_repository_with_nothing_behind_says_so(home: Path) -> None:
    repo = committed(home / "repo", {"requirements.txt": "pypdf==6.19.0\n"})
    result = runner.invoke(app, ["outdated", "--repo", str(repo)])
    assert result.exit_code == 0
    assert "1 dependencies read, none behind a major release or flagged." in result.output


def test_an_index_that_cannot_be_reached_for_any_dependency_exits_six(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OBELIZE_INDEX_URL", "http://127.0.0.1:1/simple")
    repo = committed(home / "repo", {"requirements.txt": REQUIREMENTS})
    result = runner.invoke(app, ["outdated", "--repo", str(repo)])
    assert result.exit_code == 6
    assert "could not be reached" in result.output


def test_offline_with_nothing_kept_exits_six(home: Path) -> None:
    repo = committed(home / "repo", {"requirements.txt": REQUIREMENTS})
    assert runner.invoke(app, ["outdated", "--repo", str(repo), "--offline"]).exit_code == 6


def test_a_repository_that_is_not_a_directory_exits_two(home: Path) -> None:
    result = runner.invoke(app, ["outdated", "--repo", str(home / "nothing")])
    assert result.exit_code == 2


def test_a_listing_of_nothing_to_migrate_with_ends_with_no_next_step(home: Path) -> None:
    repo = committed(home / "repo", {"requirements.txt": "private-lib==1.0\n"})
    result = runner.invoke(app, ["outdated", "--repo", str(repo)])
    assert result.exit_code == 0
    assert "not on the index" in result.output
    assert "Next:" not in result.output

"""A release `upgrade --from` names, against the declarations of a library that keeps its name.

The pack is `acme-kit` 1.2 up to 2 (one distribution for both sides, as pydantic is), so the floor
is 1.2 and the release stated below is 1.5. A declaration that admits it stands for it, one that
rules it out blocks, and everything that asks no statement (`fix`, `scan`, `--pack`, `upgrade`
without `--from`) is gated as it was.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import acme_kept
import pytest
from pdf_repo import git_repo

from obelize.models import Config
from obelize.scan import runner

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

SPEC = acme_kept.SPEC
CODE = "import acme.kit\n\nGREETER = acme.kit.Greeter()\n"
STATED = "1.5"


def scanned(
    root: Path, files: Mapping[str, str], stated: str | None = STATED, code: str = CODE
) -> runner.Scan:
    git_repo(root, {"main.py": code, **files})
    return runner.scan(root, Config(), SPEC, jobs=1, stated=stated)


# (files, blocked without the statement, what the statement does with it)
# "stands": the statement lets it pass and is said; "alone": the floor passes it on its own and
# the statement decides nothing; "ruled": it rules the statement out; "unread": nobody can read it.
FORMS: dict[str, tuple[dict[str, str], str, str]] = {
    "bare": ({"requirements.txt": "acme-kit\n"}, "blocks", "stands"),
    "upper-bound-only": ({"requirements.txt": "acme-kit<2\n"}, "blocks", "stands"),
    "low-floor": ({"requirements.txt": "acme-kit>=1.0\n"}, "blocks", "stands"),
    "low-floor-and-ceiling": ({"requirements.txt": "acme-kit>=1.0,<2\n"}, "blocks", "stands"),
    "not-equal": ({"requirements.txt": "acme-kit!=1.4\n"}, "blocks", "stands"),
    "extras": ({"requirements.txt": "acme-kit[x]>=1.0\n"}, "blocks", "stands"),
    "marker": (
        {"requirements.txt": 'acme-kit>=1.0; python_version >= "3.8"\n'},
        "blocks",
        "stands",
    ),
    "caret": (
        {"pyproject.toml": '[tool.poetry.dependencies]\nacme-kit = "^1.0"\n'},
        "blocks",
        "stands",
    ),
    "alternatives": (
        {"pyproject.toml": '[tool.poetry.dependencies]\nacme-kit = "^0.5 || ^1.0"\n'},
        "blocks",
        "stands",
    ),
    "setup-py": (
        {"setup.py": 'from setuptools import setup\nsetup(install_requires=["acme-kit>=1.0"])\n'},
        "blocks",
        "stands",
    ),
    "two-that-admit": (
        {"requirements.txt": "acme-kit>=1.0\n", "requirements-dev.txt": "acme-kit<2\n"},
        "blocks",
        "stands",
    ),
    "pinned": ({"requirements.txt": "acme-kit==1.5\n"}, "passes", "alone"),
    "compatible": ({"requirements.txt": "acme-kit~=1.3\n"}, "passes", "alone"),
    "range-at-the-floor": ({"requirements.txt": "acme-kit>=1.2,<2\n"}, "passes", "alone"),
    "other-pin": ({"requirements.txt": "acme-kit==1.3\n"}, "passes", "ruled"),
    "new-side": ({"requirements.txt": "acme-kit>=2\n"}, "passes", "ruled"),
    "floor-above": ({"requirements.txt": "acme-kit>=1.6\n"}, "passes", "ruled"),
    "tilde": (
        {"pyproject.toml": '[tool.poetry.dependencies]\nacme-kit = "~1.2"\n'},
        "passes",
        "ruled",
    ),
    "epoch": ({"requirements.txt": "acme-kit>=1!1.0\n"}, "passes", "ruled"),
    "below": ({"requirements.txt": "acme-kit<1.0\n"}, "blocks", "ruled"),
    "marked-other-pin": (
        {"requirements.txt": 'acme-kit==1.3; python_version < "3.9"\n'},
        "passes",
        "ruled",
    ),
    "second-rules-out": (
        {"requirements.txt": "acme-kit>=1.0\n", "requirements-dev.txt": "acme-kit<1.4\n"},
        "blocks",
        "ruled",
    ),
    "lock-that-pins-the-new-release": (
        {"requirements.txt": "acme-kit>=1.0\n", "requirements-lock.txt": "acme-kit==2.0\n"},
        "blocks",
        "ruled",
    ),
    "a-constraint-that-rules-it-out": (
        {"requirements.txt": "-c constraints.txt\nacme-kit\n", "constraints.txt": "acme-kit<1.4\n"},
        "blocks",
        "ruled",
    ),
    "url": (
        {"requirements.txt": "acme-kit @ https://example.invalid/acme_kit-1.5.whl\n"},
        "blocks",
        "unread",
    ),
    "unreadable-version": ({"requirements.txt": "acme-kit==1.*.*\n"}, "blocks", "unread"),
    "unreadable-poetry": (
        {"pyproject.toml": '[tool.poetry.dependencies]\nacme-kit = "^one"\n'},
        "blocks",
        "unread",
    ),
    "editable": (
        {"requirements.txt": "-e git+https://host/acme.git#egg=acme-kit\n"},
        "blocks",
        "unread",
    ),
}


def verdict(scan: runner.Scan) -> str:
    return "blocks" if scan.blocked else "passes"


@pytest.mark.parametrize("name", FORMS)
def test_a_declaration_is_gated_as_it_was_without_a_statement(tmp_path: Path, name: str) -> None:
    """`fix`, `scan`, a pack named with `--pack` and `upgrade` without `--from` give none."""
    files, plain, _ = FORMS[name]
    scan = scanned(tmp_path, files, stated=None)
    assert verdict(scan) == plain
    assert (scan.stated, scan.narrowed) == ((), ())
    assert all(row.stated == "" and not row.covered for row in scan.blocked)


@pytest.mark.parametrize("name", FORMS)
def test_a_declaration_that_admits_the_statement_lets_it_stand_and_one_that_does_not_stops_it(
    tmp_path: Path, name: str
) -> None:
    files, _, outcome = FORMS[name]
    scan = scanned(tmp_path, files)
    if outcome in {"stands", "alone"}:
        assert scan.blocked == ()
    else:
        [blocked] = scan.blocked
        assert (blocked.reason, blocked.stated, blocked.covered) == (
            "legacy_version_unsupported",
            STATED,
            True,
        )
        assert (blocked.declared is None) == (outcome == "unread")
        assert blocked.evidence == ""
    said = (("acme-kit", STATED),) if outcome == "stands" else ()
    assert scan.stated == said
    assert scan.narrowed == (("acme-kit",) if said else ())


def test_the_declaration_that_stops_the_statement_is_named_among_several(tmp_path: Path) -> None:
    files = FORMS["second-rules-out"][0]
    [blocked] = scanned(tmp_path, files).blocked
    assert (blocked.path, blocked.declared) == ("requirements-dev.txt", "<1.4")
    [again] = scanned(tmp_path / "again", FORMS["lock-that-pins-the-new-release"][0]).blocked
    assert (again.path, again.declared) == ("requirements-lock.txt", "==2.0")


def test_a_release_below_the_floor_or_above_the_range_stands_for_nothing(tmp_path: Path) -> None:
    for index, stated in enumerate(["1.1", "2.0", "1.2rc1", "3"]):
        loose = scanned(tmp_path / f"loose{index}", {"requirements.txt": "acme-kit<2\n"}, stated)
        [blocked] = loose.blocked
        assert (blocked.path, blocked.stated, blocked.covered) == (
            "requirements.txt",
            stated,
            False,
        )
        assert loose.stated == ()
        tight = scanned(tmp_path / f"tight{index}", {"requirements.txt": "acme-kit==1.5\n"}, stated)
        assert (tight.blocked, tight.stated) == ((), ())
        bare = scanned(tmp_path / f"bare{index}", {}, stated)
        assert [(row.path, row.stated, row.covered) for row in bare.blocked] == [
            ("", stated, False)
        ]


@pytest.mark.parametrize(
    ("declared", "stands"),
    [
        ("acme-kit>=1.0", True),
        ("acme-kit<1.9", True),
        ("acme-kit==1.5", False),
        ("acme-kit<1.5", False),
    ],
)
def test_a_pre_release_inside_the_range_is_asked_of_each_declaration_as_one(
    tmp_path: Path, declared: str, stands: bool
) -> None:
    scan = scanned(tmp_path, {"requirements.txt": f"{declared}\n"}, "1.5rc1")
    assert scan.stated == ((("acme-kit", "1.5rc1"),) if stands else ())
    assert bool(scan.blocked) is not stands


def test_a_library_the_code_does_not_use_is_not_asked_and_says_nothing(tmp_path: Path) -> None:
    for index, declared in enumerate(["acme-kit<2", "acme-kit==1.3", "acme-kit>=2"]):
        scan = scanned(tmp_path / str(index), {"requirements.txt": f"{declared}\n"}, code="x = 1\n")
        assert (scan.blocked, scan.stated, scan.narrowed) == ((), (), ())


def test_a_library_no_manifest_declares_stands_as_it_did_and_is_not_narrowed(
    tmp_path: Path,
) -> None:
    scan = scanned(tmp_path, {})
    assert (scan.blocked, scan.stated, scan.narrowed) == ((), (("acme-kit", STATED),), ())


def test_a_pack_with_no_floor_asks_nothing_of_a_declaration(tmp_path: Path) -> None:
    open_range = SPEC.model_copy(update={"legacy_floor": None})
    git_repo(tmp_path, {"main.py": CODE, "requirements.txt": "acme-kit>=2\n"})
    scan = runner.scan(tmp_path, Config(), open_range, jobs=1, stated=STATED)
    assert (scan.blocked, scan.stated) == ((), ())


def test_a_python_the_new_release_does_not_run_on_still_stops_what_the_statement_allows(
    tmp_path: Path,
) -> None:
    files = {
        "requirements.txt": "acme-kit>=1.0\n",
        "pyproject.toml": '[project]\nname = "x"\nrequires-python = ">=3.7"\n',
    }
    scan = scanned(tmp_path, files)
    assert [row.reason for row in scan.blocked] == ["runtime_unsupported"]
    assert (scan.stated, scan.narrowed) == ((), ())


def test_the_statements_of_several_packs_keep_what_each_declaration_said(tmp_path: Path) -> None:
    root = git_repo(tmp_path, {"main.py": CODE, "requirements.txt": "acme-kit<2\n"})
    first = runner.scan(root, Config(), SPEC, jobs=1, stated=STATED)
    tree = runner.read(root, Config(), (SPEC,))
    assert runner.merged([first, first], tree).narrowed == ("acme-kit",)
    bare = runner.scan(root, Config(), SPEC, jobs=1)
    assert runner.merged([first, bare], tree).narrowed == ("acme-kit",)
    assert runner.merged([bare, bare], tree).narrowed == ()

"""Manifest declarations and ADR-010 F-2's edits, one rule per test, on inline `acme-sdk` text."""

from __future__ import annotations

import ast
import ntpath
import os
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from acme import SPEC

from obelize.impact import planner
from obelize.models import Config, ImpactPlan, ManifestPlan
from obelize.scan import analysis, manifests, parse, runner

if TYPE_CHECKING:  # pragma: no cover - typing only
    from pathlib import Path

LEGACY = SPEC.legacy_distribution
NEW = SPEC.new_distribution


def declared(text: str, path: str = "requirements.txt") -> list[tuple[int, int, str]]:
    """Line, column of the name, and the canonical name, for one manifest's text."""
    data = text.lstrip("\n").encode("utf-8")
    return [(row.line, row.column, row.name) for row in manifests.declarations(path, data)]


def names(text: str, path: str = "requirements.txt") -> list[str]:
    return [name for _, _, name in declared(text, path)]


def pin(line: int = 1, name: str = LEGACY, path: str = "requirements.txt") -> manifests.Declaration:
    return manifests.Declaration(
        path=path, line=line, column=0, name=name, raw=name, end=len(name), pin=None, spec=None
    )


def graded(
    found: tuple[manifests.Declaration, ...], migration: manifests.Migration
) -> list[tuple[str, int, str, str, str | None]]:
    plan = manifests.plan(found, migration, SPEC)
    return [(r.path, r.line, str(r.symbol), r.scan_status, r.bail) for r in plan.findings]


def planned(source: str, path: str) -> ImpactPlan:
    """One file's plan, from the same passes a real scan runs."""
    read = parse.gates(path, source.lstrip("\n").encode("utf-8"))
    return planner.plan(analysis.analyse(read, SPEC), SPEC)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("requirements.txt", "requirements"),
        ("requirements-dev.txt", "requirements"),
        ("requirements_test.txt", "requirements"),
        ("deploy/requirements.txt", "requirements"),
        ("requirements/base.txt", "requirements"),
        ("requirements/dev.txt", "requirements"),
        ("pyproject.toml", "toml"),
        ("packages/app/pyproject.toml", "toml"),
        ("Pipfile", "toml"),
        ("setup.cfg", "cfg"),
        ("setup.py", "setup_py"),
        ("constraints.txt", None),
        ("docs/notes.txt", None),
        ("requirements/README.md", None),
        ("poetry.lock", None),
        ("Pipfile.lock", None),
        ("app.py", None),
        ("tox.ini", None),
    ],
)
def test_a_manifest_is_chosen_by_name_and_the_set_is_closed(
    path: str, expected: str | None
) -> None:
    """Lock files are generated and hashed, so never edited; `constraints.txt` declares nothing."""
    assert manifests.layout(path) == expected
    assert manifests.is_manifest(path) is (expected is not None)


def test_a_manifest_name_keeps_its_case_where_the_system_folds_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`fnmatch` folds case through `os.path.normcase`, which does so on Windows alone."""
    monkeypatch.setattr(os.path, "normcase", ntpath.normcase)
    assert manifests.layout("Requirements-Dev.TXT") is None
    assert manifests.layout("Requirements-dev.txt") is None
    assert manifests.layout("requirements/base.TXT") is None
    assert manifests.layout("requirements-dev.txt") == "requirements"


def test_a_requirements_file_declares_one_dependency_a_line() -> None:
    """And the three shapes that are not one: a comment, an option, and noise."""
    text = """
# acme-sdk==1.0
acme-sdk==1.0  # the real one
-e .
--index-url https://example.invalid/simple/acme-sdk/
this is not a requirement

requests>=2.31
"""
    assert declared(text) == [(2, 0, "acme-sdk"), (7, 0, "requests")]


def test_a_name_is_matched_after_canonicalisation() -> None:
    """PEP 503 folds case and runs of `-`, `_` and `.` into one dash."""
    text = """
Acme_SDK==1.0
ACME.SDK>=1
acme--sdk[fast]==1.0
acme-sdk @ https://example.invalid/acme.whl
"""
    assert names(text) == ["acme-sdk"] * 4


def test_the_column_is_the_name_and_not_the_line() -> None:
    assert declared("\n    acme-sdk==1.0\n") == [(1, 4, "acme-sdk")]


def test_a_byte_order_mark_does_not_hide_the_first_declaration() -> None:
    data = "﻿acme-sdk==1.0\n".encode()
    assert [row.name for row in manifests.declarations("requirements.txt", data)] == ["acme-sdk"]


def test_a_line_that_is_not_utf_8_does_not_lose_the_declaration() -> None:
    """Decoded with `surrogateescape`, not `replace`, so the comment's bytes survive a rewrite."""
    data = b"acme-sdk==1.0  # \xf6l\xe7\xfcm\n"
    assert [row.name for row in manifests.declarations("requirements.txt", data)] == ["acme-sdk"]


def test_a_pep_621_array_may_run_over_several_lines() -> None:
    """With a commented-out pin inside, the decoy the example application has."""
    text = """
[project]
name = "app"
description = "helpers for acme-sdk"
dependencies = [
  # "acme-sdk==1.0"
  "acme-sdk==1.0",
  "requests>=2.31",
]

[project.optional-dependencies]
dev = ["pytest>=8.3"]
"""
    assert declared(text, "pyproject.toml") == [
        (6, 3, "acme-sdk"),
        (7, 3, "requests"),
        (11, 8, "pytest"),
    ]


def test_a_single_line_array_closes_itself() -> None:
    text = """
[project]
dependencies = ["acme-sdk==1.0"]
name = "acme-sdk-is-not-a-dependency-here"
"""
    assert declared(text, "pyproject.toml") == [(2, 17, "acme-sdk")]


def test_a_dependency_group_is_an_array_and_build_system_is_not() -> None:
    """`[build-system] requires` builds the project; a pin there reaches no importing code."""
    text = """
[build-system]
requires = ["hatchling", "acme-sdk==1.0"]

[dependency-groups]
test = ["acme-sdk==1.0"]
"""
    assert declared(text, "pyproject.toml") == [(5, 9, "acme-sdk")]


@pytest.mark.parametrize(
    "table",
    [
        "tool.poetry.dependencies",
        "tool.poetry.dev-dependencies",
        "tool.poetry.group.dev.dependencies",
        "packages",
        "dev-packages",
    ],
)
def test_a_dependency_table_declares_its_distributions_as_keys(table: str) -> None:
    """Poetry and Pipenv, where the key is the name and the value is the range."""
    text = f"""
[{table}]
acme-sdk = "^1.0"
"""
    assert declared(text, "pyproject.toml") == [(2, 0, "acme-sdk")]


def test_a_table_that_is_not_a_dependency_location_declares_nothing() -> None:
    text = """
[[source]]
url = "https://example.invalid/simple/acme-sdk/"

[tool.poetry]
name = "acme-sdk"

[tool.poetry.group.dev]
optional = true

[requires]
python_version = "3.10"
"""
    assert declared(text, "Pipfile") == []


def test_a_key_toml_allows_and_pep_508_does_not_is_no_declaration() -> None:
    text = """
[packages]
"" = "*"
acme-sdk = "*"
"""
    assert declared(text, "Pipfile") == [(3, 0, "acme-sdk")]


def test_a_string_in_a_dependency_array_that_is_not_a_requirement_is_skipped() -> None:
    text = """
[project]
dependencies = ["!!!", "acme-sdk==1.0"]
"""
    assert declared(text, "pyproject.toml") == [(2, 24, "acme-sdk")]


def test_a_hash_inside_a_requirement_string_is_not_a_comment() -> None:
    """A URL fragment starts with `#`, and cutting there still parses, so the error is silent."""
    text = """
[project]
dependencies = ["acme-sdk @ https://example.invalid/acme.whl#sha256=abc"]
"""
    assert declared(text, "pyproject.toml") == [(2, 17, "acme-sdk")]


def test_the_column_skips_whitespace_inside_a_quoted_string() -> None:
    """TOML allows it and PEP 508 accepts it, so the name is not at the quote."""
    text = """
[project]
dependencies = ["  acme-sdk==1.0"]
"""
    assert declared(text, "pyproject.toml") == [(2, 19, "acme-sdk")]


def test_an_unterminated_quote_ends_the_line_rather_than_the_run() -> None:
    """Nothing validates the TOML first, and a half-edited file must not fail the whole run."""
    text = """
[project]
dependencies = ["acme-sdk==1.0
"""
    assert declared(text, "pyproject.toml") == []


def test_a_setup_cfg_value_continues_on_indented_lines() -> None:
    """Only a leading `#` comments in setup.cfg; setuptools keeps an inline one in the value."""
    text = """
[metadata]
name = app
description = helpers for acme-sdk
long_description =
    acme-sdk is mentioned here and declared below

[options]
install_requires =
    # acme-sdk==1.0
    acme-sdk==1.0
    requests>=2.31  # not a comment, so not a requirement either
    -e .

[options.extras_require]
dev =
    pytest>=8.3
"""
    assert declared(text, "setup.cfg") == [(10, 4, "acme-sdk"), (16, 4, "pytest")]


def test_a_setup_cfg_value_may_sit_on_the_key_s_own_line() -> None:
    """`:` separates a key from its value as well as `=` does."""
    text = """
[options]
setup_requires = acme-sdk==1.0
tests_require = -e .
zip_safe = False

[options.extras_require]
gemini: acme-sdk>=1
"""
    assert declared(text, "setup.cfg") == [(2, 17, "acme-sdk"), (7, 8, "acme-sdk")]


def test_an_indented_line_under_another_key_is_not_a_requirement() -> None:
    """`keywords` continues on indented lines too, and `acme-sdk` there is a name, not a pin."""
    text = """
[metadata]
keywords =
    gemini
    acme-sdk

[options]
install_requires =
    acme-sdk==1.0
"""
    assert declared(text, "setup.cfg") == [(8, 4, "acme-sdk")]


def test_a_line_with_no_separator_ends_the_value_it_followed() -> None:
    """Otherwise the next indented line would be read as another of its requirements."""
    text = """
[options]
install_requires =
    acme-sdk==1.0
stray
    requests>=2.31
"""
    assert declared(text, "setup.cfg") == [(3, 4, "acme-sdk")]


def test_setup_py_declarations_are_resolved_and_a_docstring_is_not() -> None:
    """Only strings in requirement arguments count; an `extras_require` key names an extra."""
    text = '''
"""Packaging for the app, which pins acme-sdk."""

from setuptools import setup

setup(
    name="acme-sdk-user",
    url="https://example.invalid/acme-sdk",
    install_requires=[
        "acme-sdk==1.0",
        "requests>=2.31",
    ],
    extras_require={"dev": ["pytest>=8.3"]},
)
'''
    assert [(line, name) for line, _, name in declared(text, "setup.py")] == [
        (9, "acme-sdk"),
        (10, "requests"),
        (12, "pytest"),
    ]


def test_a_setup_py_string_that_is_not_a_requirement_is_skipped() -> None:
    text = """
from setuptools import setup

setup(install_requires=["!!!", b"acme-sdk", "acme-sdk==1.0"])
"""
    assert declared(text, "setup.py") == [(3, 45, "acme-sdk")]


def test_a_setup_py_string_python_cannot_read_declares_nothing_and_stops_nothing() -> None:
    """`"C:\\Users"` is no string at all; the requirement beside it still reads."""
    text = (
        "setup(install_requires=[\n"
        '    "acme-sdk==1",\n'
        '    "pkg @ file:///C:\\Users\\x\\pkg.whl",\n'
        "])\n"
    )
    assert names(text, "setup.py") == ["acme-sdk"]


def test_a_setup_py_that_does_not_parse_declares_nothing() -> None:
    """The code pass reads the same bytes and owns the `parse_error` row."""
    assert manifests.declarations("setup.py", b"setup(install_requires=[\n") == ()


def test_a_manifest_is_read_through_the_same_limit_as_a_source_file(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("acme-sdk==1.0\n", encoding="utf-8")
    reading = manifests.read("requirements.txt", parse.disk(tmp_path, Config()))
    assert [row.name for row in reading.declarations] == ["acme-sdk"]
    assert reading.limitations == ()

    refused = manifests.read("requirements.txt", parse.disk(tmp_path, Config(max_file_bytes=4)))
    assert refused.declarations == ()
    assert [row.code for row in refused.limitations] == ["file_too_large"]


def test_only_an_excluded_file_that_names_the_distribution_is_reported(tmp_path: Path) -> None:
    """An excluded file is only named: it never blocks the removal or comes back as a finding."""
    (tmp_path / "uses.py").write_text("import acme.sdk\n", encoding="utf-8")
    (tmp_path / "plain.py").write_text("import json\n", encoding="utf-8")
    hits, limitations = manifests.prefiltered(
        ["plain.py", "uses.py", "gone.py"], SPEC, parse.disk(tmp_path, Config())
    )
    assert hits == ("uses.py",)
    assert [row.code for row in limitations] == ["unreadable"]


MIGRATES = """
import acme.sdk as sdk

sdk.configure(key="k")
MODEL = sdk.Model("m")
MODEL.run("t")
"""

NO_CLIENT = """
import acme.sdk as sdk


def classify(text):
    model = sdk.Model("m")
    return model.run(text)
"""

PROSE = '''
"""This module used to call acme.sdk.Model and no longer does."""
'''

MOCK_TARGET = """
from unittest import mock


def test_it():
    with mock.patch("acme.sdk.Model"):
        pass
"""


def test_a_file_with_an_edit_migrated_and_one_left_importing_blocks() -> None:
    plans = [planned(MIGRATES, "app.py"), planned(NO_CLIENT, "worker.py")]
    assert manifests.survey(plans) == manifests.Migration(
        migrated=("app.py",), blocking=("worker.py",), excluded=()
    )


def test_a_prose_mention_does_not_block_and_a_mock_target_does() -> None:
    """`mock.patch` imports its target by name when entered; a docstring imports nothing."""
    plans = [planned(PROSE, "notes.py"), planned(MOCK_TARGET, "test_it.py")]
    assert manifests.survey(plans, excluded=("scripts/old.py",)) == manifests.Migration(
        migrated=(), blocking=("test_it.py",), excluded=("scripts/old.py",)
    )


def test_a_file_that_does_not_parse_blocks_the_removal() -> None:
    """Fail closed: it matched the byte prefilter and nothing could be proved."""
    read = parse.gates("broken.py", b"import acme.sdk as sdk\ndef f(:\n")
    plan = planner.plan(analysis.analyse(read, SPEC), SPEC)
    assert manifests.survey([plan]).blocking == ("broken.py",)


MIGRATED = manifests.Migration(migrated=("app.py",))
PARTIAL = manifests.Migration(migrated=("app.py",), blocking=("worker.py",))
NOTHING = manifests.Migration()
STUCK = manifests.Migration(blocking=("worker.py",))


def test_both_halves_clear_collapse_into_one_rewrite() -> None:
    """Nothing still needs the legacy pin, so the two edits are one line edit."""
    assert graded((pin(),), MIGRATED) == [("requirements.txt", 1, LEGACY, "eligible", None)]


def test_a_blocked_removal_adds_the_new_pin_and_keeps_the_old() -> None:
    """A partial migration needs both distributions; both rows sit where the new pin is written."""
    assert graded((pin(),), PARTIAL) == [
        ("requirements.txt", 1, NEW, "eligible", None),
        ("requirements.txt", 1, LEGACY, "needs_review", "repo_not_fully_migrated"),
    ]


def test_a_manifest_that_already_declares_the_new_distribution_gets_no_second_pin() -> None:
    """This is what keeps a second run of the same command idempotent."""
    found = (pin(line=1), pin(line=2, name=NEW))
    assert graded(found, PARTIAL) == [
        ("requirements.txt", 1, LEGACY, "needs_review", "repo_not_fully_migrated")
    ]


def test_the_pin_is_per_manifest_and_not_per_repository() -> None:
    """Installing one file does not install another, so each owes its own pin."""
    found = (pin(path="requirements.txt"), pin(path="requirements/dev.txt", name=NEW))
    assert graded(found, PARTIAL) == [
        ("requirements.txt", 1, NEW, "eligible", None),
        ("requirements.txt", 1, LEGACY, "needs_review", "repo_not_fully_migrated"),
        ("requirements/dev.txt", 1, NEW, "needs_review", "manifest_code_mismatch"),
    ]


def test_nothing_migrated_and_something_importing_withholds_the_pin() -> None:
    assert graded((pin(),), STUCK) == [
        ("requirements.txt", 1, LEGACY, "needs_review", "repo_not_fully_migrated")
    ]


def test_a_pin_no_code_uses_is_context_and_never_an_edit() -> None:
    """Removing it would tidy the manifest for a migration this run did not make."""
    assert graded((pin(),), NOTHING) == [("requirements.txt", 1, LEGACY, "not_a_usage", None)]


def test_the_new_distribution_over_legacy_code_is_a_review_item() -> None:
    """The environment this manifest builds lacks the SDK the code still imports."""
    assert graded((pin(name=NEW),), STUCK) == [
        ("requirements.txt", 1, NEW, "needs_review", "manifest_code_mismatch")
    ]


def test_a_manifest_declaring_both_distributions_is_the_intermediate_state() -> None:
    """The shape F-2 produces, so a second scan must not report it as a defect."""
    found = (pin(line=1), pin(line=2, name=NEW))
    assert [row[2:] for row in graded(found, PARTIAL)] == [
        (LEGACY, "needs_review", "repo_not_fully_migrated")
    ]


def test_an_unrelated_distribution_is_never_a_row() -> None:
    assert graded((pin(name="requests"),), PARTIAL) == []


def test_the_plan_carries_the_evidence_the_report_owes() -> None:
    plan = manifests.plan(
        (pin(),),
        manifests.Migration(
            migrated=("app.py",), blocking=("worker.py",), excluded=("scripts/old.py",)
        ),
        SPEC,
    )
    assert plan.blocking == ("worker.py",)
    assert plan.excluded == ("scripts/old.py",)


def test_a_module_only_the_legacy_distribution_installed_keeps_the_pin() -> None:
    """Nothing imports the legacy distribution, and `retry.py` needs what it brought."""
    migration = manifests.Migration(migrated=("app.py",), transitive=(("retry.py", "acme-wire"),))
    assert graded((pin(),), migration) == [
        ("requirements.txt", 1, NEW, "eligible", None),
        ("requirements.txt", 1, LEGACY, "needs_review", "transitive_dependency_in_use"),
    ]
    assert manifests.plan((pin(),), migration, SPEC).transitive == ("retry.py",)


def test_a_distribution_a_manifest_declares_keeps_nothing() -> None:
    """Declared anywhere in the repository, it survives the legacy pin."""
    migration = manifests.Migration(migrated=("app.py",), transitive=(("retry.py", "acme-wire"),))
    found = (pin(), pin(name="acme-wire", path="requirements/dev.txt"))
    assert graded(found, migration) == [("requirements.txt", 1, LEGACY, "eligible", None)]
    assert manifests.plan(found, migration, SPEC).transitive == ()


def test_an_import_of_the_legacy_distribution_is_the_reason_given_first() -> None:
    """`repo_not_fully_migrated` names a file that still imports the SDK itself."""
    migration = manifests.Migration(
        migrated=("app.py",), blocking=("worker.py",), transitive=(("retry.py", "acme-wire"),)
    )
    assert graded((pin(),), migration)[-1][-1] == "repo_not_fully_migrated"


@pytest.mark.parametrize(
    ("source", "found"),
    [
        ("import acme.wire\n", True),
        ("import acme.wire.frames as frames\n", True),
        ("from acme.wire import frames\n", True),
        ("from acme import wire\n", True),
        ("import acme.wirex\n", False),
        ("# acme.wire is what the retry uses\n", False),
        ("from .acme.wire import frames\n", False),
        ("import acme.wire\ndef (:\n", False),
    ],
    ids=[
        "an import",
        "a submodule",
        "from the module",
        "from its package",
        "a longer name",
        "a comment",
        "a relative import",
        "a file that does not parse",
    ],
)
def test_the_imports_that_need_a_transitive_distribution(source: str, found: bool) -> None:
    """By the imports the code makes, and never by the text."""
    rows = manifests.provided("retry.py", source.encode(), SPEC)
    assert rows == ((("retry.py", "acme-wire"),) if found else ())


def test_a_file_include_leaves_out_blocks_like_an_import() -> None:
    migration = manifests.survey([planned(MIGRATES, "app.py")], unanalysed=("analysis.ipynb",))
    assert migration.blocking == ("analysis.ipynb",)


NOTEBOOK = '{"cells": [{"cell_type": "code", "source": ["import acme.sdk as sdk"]}]}\n'


def test_a_notebook_keeps_the_pin_under_the_default_include(tmp_path: Path) -> None:
    """Nothing analyses it and its bytes name the distribution."""
    for name, text in (
        ("app.py", MIGRATES),
        ("analysis.ipynb", NOTEBOOK),
        ("requirements.txt", "acme-sdk==0.1.0\n"),
    ):
        (tmp_path / name).write_text(text, encoding="utf-8")
    scanned = runner.scan(tmp_path, Config(), SPEC, jobs=1)
    assert scanned.manifests.blocking == ("analysis.ipynb",)
    assert scanned.unanalysed == ("analysis.ipynb",)
    narrowed = runner.scan(tmp_path, Config(include="*.py"), SPEC, jobs=1)
    assert narrowed.manifests.blocking == ()
    assert narrowed.manifests.excluded == ("analysis.ipynb",)


def test_a_scan_reads_the_imports_of_every_selected_file(tmp_path: Path) -> None:
    for name, text in (
        ("app.py", MIGRATES),
        ("retry.py", "import acme.wire\n"),
        ("requirements.txt", "acme-sdk==0.1.0\n"),
    ):
        (tmp_path / name).write_text(text, encoding="utf-8")
    scanned = runner.scan(tmp_path, Config(), SPEC, jobs=1)
    assert scanned.transitive == (("retry.py", "acme-wire"),)
    assert scanned.manifests.transitive == ("retry.py",)


def test_a_file_that_names_no_such_module_is_never_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every selected file passes through here, so the bytes decide before a parse."""
    parsed: list[bytes] = []

    def spy(source: bytes, *args: Any, **kwargs: Any) -> Any:
        parsed.append(source)
        return ast.parse(source, *args, **kwargs)

    # Patch the module's `ast`, never `ast.parse` itself: pytest and coverage call it too.
    monkeypatch.setattr(manifests, "ast", SimpleNamespace(**{**vars(ast), "parse": spy}))
    assert manifests.provided("app.py", b"import acme.sdk\n", SPEC) == ()
    assert parsed == []
    assert manifests.provided("retry.py", b"import acme.wire\n", SPEC) == (
        ("retry.py", "acme-wire"),
    )
    assert parsed == [b"import acme.wire\n"]


def test_a_withheld_pin_must_name_the_files_that_need_it() -> None:
    row = manifests.plan(
        (pin(),),
        manifests.Migration(migrated=("app.py",), transitive=(("r.py", "acme-wire"),)),
        SPEC,
    ).findings[-1]
    with pytest.raises(ValueError, match="imports a module only the legacy distribution installs"):
        ManifestPlan(findings=(row,), transitive=())


def specs(text: str, path: str) -> list[str | None]:
    return [row.spec for row in manifests.declarations(path, text.lstrip("\n").encode("utf-8"))]


@pytest.mark.parametrize(
    ("path", "text", "expected"),
    [
        ("requirements.txt", f"{LEGACY}>=1,<2\n", ["<2,>=1"]),
        ("requirements.txt", f"{LEGACY}\n", [""]),
        ("requirements.txt", f"{LEGACY}[extra]==1.2 ; python_version < '3.12'\n", ["==1.2"]),
        ("requirements.txt", f"{LEGACY} @ https://example.invalid/x.whl\n", [None]),
        ("pyproject.toml", f'[project]\ndependencies = ["{LEGACY}~=1.0"]\n', ["~=1.0"]),
        ("pyproject.toml", f'[tool.poetry.dependencies]\n{LEGACY} = "^1.0"\n', ["^1.0"]),
        (
            "pyproject.toml",
            f'[tool.poetry.dependencies]\n{LEGACY} = {{ version = "^1.0", extras = ["x"] }}\n',
            ["^1.0"],
        ),
        (
            "pyproject.toml",
            f"[tool.poetry.dependencies]\n{LEGACY} = {{ git = 'https://example.invalid/x' }}\n",
            [None],
        ),
        ("Pipfile", f'[packages]\n{LEGACY} = "*"\n', ["*"]),
        ("setup.cfg", f"[options]\ninstall_requires =\n    {LEGACY}>=1\n", [">=1"]),
        (
            "setup.py",
            f"from setuptools import setup\nsetup(install_requires=['{LEGACY}>=1'])\n",
            [">=1"],
        ),
    ],
    ids=[
        "pep-508-set",
        "unpinned",
        "extras-and-marker",
        "url",
        "pep-621",
        "poetry-string",
        "poetry-inline-table",
        "poetry-inline-table-without-a-version",
        "pipenv",
        "setup-cfg",
        "setup-py",
    ],
)
def test_a_declaration_carries_the_version_as_declared_in_every_layout(
    path: str, text: str, expected: list[str | None]
) -> None:
    assert specs(text, path) == expected

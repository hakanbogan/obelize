"""Manifest declarations and ADR-010 F-2's edits, one rule per test, on inline `acme-sdk` text."""

from __future__ import annotations

import ast
import ntpath
import os
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from acme import SPEC
from libcst.metadata import MetadataWrapper, ScopeProvider
from packaging.version import Version

from obelize.impact import planner
from obelize.models import Config, ImpactPlan, ManifestPlan, ProvidedModule
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
        ("dev-requirements.txt", "requirements"),
        ("requirement.txt", "requirements"),
        ("docs/pip_requirements.txt", "requirements"),
        ("deploy/requirements.txt", "requirements"),
        ("requirements/base.txt", "requirements"),
        ("requirements/dev.txt", "requirements"),
        ("pyproject.toml", "toml"),
        ("packages/app/pyproject.toml", "toml"),
        ("Pipfile", "toml"),
        ("setup.cfg", "cfg"),
        ("setup.py", "setup_py"),
        ("constraints.txt", "unwritten"),
        ("constraints-3.12.txt", "unwritten"),
        ("constraints/prod-constraints.txt", "unwritten"),
        ("requirements/constraints.txt", "unwritten"),
        ("requirements-constraints.txt", "unwritten"),
        ("requirements.in", "unwritten"),
        ("dev-requirements.in", "unwritten"),
        ("docs/notes.txt", None),
        ("base.in", None),
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
    """Lock files are generated and hashed, so never edited; a constraints file and a pip-tools
    input are read and never written, which `unwritten` says."""
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
    """And the three shapes that are not one: a comment, an option, and a line with no name."""
    text = """
# acme-sdk==1.0
acme-sdk==1.0  # the real one
-e .
--index-url https://example.invalid/simple/acme-sdk/
*** not a requirement

requests>=2.31
"""
    assert declared(text) == [(2, 0, "acme-sdk"), (7, 0, "requests")]


def read(text: str) -> list[manifests.Declaration]:
    return list(manifests.declarations("requirements.txt", text.lstrip("\n").encode("utf-8")))


@pytest.mark.parametrize(
    ("text", "pin", "spec"),
    [
        ("acme-sdk==1.0 --hash=sha256:aaaa\n", None, "==1.0"),
        ("acme-sdk==1.0 \\\n    --hash=sha256:aaaa \\\n    --hash=sha256:bbbb\n", None, "==1.0"),
        ("acme-sdk==1.0 \\\r\n    --hash=sha256:aaaa\r\n", None, "==1.0"),
        ("acme-sdk \\\n    >=1.0\n", None, ">=1.0"),
        ("acme-sdk==1.0 \\", None, "==1.0"),
        ("acme-sdk==1.0 --config-settings x=y\n", (8, 13), "==1.0"),
        ("acme-sdk>=1.0 ; python_version < '3.12' --global-option=-q\n", (8, 13), ">=1.0"),
        ("# a note \\\nacme-sdk==1.0\n", (8, 13), "==1.0"),
    ],
    ids=[
        "inline-hash",
        "hashes-on-continued-lines",
        "crlf",
        "requirement-split-over-lines",
        "file-ends-in-a-backslash",
        "option-without-a-hash",
        "marker-and-option",
        "comment-does-not-continue",
    ],
)
def test_a_requirement_is_read_as_pip_joins_and_cuts_its_line(
    text: str, pin: tuple[int, int] | None, spec: str
) -> None:
    """A hash is tied to the version and a line that goes on cannot be copied: neither has a pin."""
    (found,) = read(text)
    line = 2 if text.startswith("#") else 1
    assert (found.name, found.line, found.column, found.pin, found.spec) == (
        "acme-sdk",
        line,
        0,
        pin,
        spec,
    )


@pytest.mark.parametrize(
    ("text", "written"),
    [
        ("-e git+https://example.invalid/repo.git#egg=Acme_SDK\n", "Acme_SDK"),
        ("--editable git+https://example.invalid/r.git#egg=acme-sdk&subdirectory=x\n", "acme-sdk"),
        ("-e acme-sdk\n", "acme-sdk"),
        ("--editable=acme-sdk[extra]\n", "acme-sdk"),
        ("git+https://example.invalid/repo.git#egg=acme-sdk[extra]\n", "acme-sdk"),
        ("./acme_sdk-1.0-py3-none-any.whl\n", "acme_sdk"),
        ("./acme-sdk-1.0.whl\n", "acme-sdk"),
        ("dist/acme-sdk-1.0.tar.gz\n", "acme-sdk"),
        ("https://example.invalid/a-1/acme-sdk-1.0.zip#sha256=ab\n", "acme-sdk"),
        ("https://example.invalid/acme-sdk-1.0.tgz?raw=1\n", "acme-sdk"),
    ],
)
def test_a_requirement_pip_takes_and_pep_508_refuses_is_known_by_its_name_alone(
    text: str, written: str
) -> None:
    """An `#egg=` or an archive's file name says which distribution; no version is read from it."""
    (found,) = read(text)
    assert (found.name, found.line, found.raw) == ("acme-sdk", 1, written)
    assert text[found.column : found.end] == written
    assert (found.pin, found.spec) == (None, None)


@pytest.mark.parametrize(
    "text",
    [
        "-e .\n",
        "-e ./local/acme-sdk\n",
        "-eacme-sdk\n",
        "./notes.whl.txt\n",
        "dist/acme-sdk.zip\n",
        "https://example.invalid/acme\n",
        "acme-sdk.==1.0\n",
        "acme-sdk+extra\n",
        "-r base.txt\n",
    ],
)
def test_a_line_that_names_no_distribution_declares_nothing(text: str) -> None:
    assert read(text) == []


@pytest.mark.parametrize(
    ("text", "raw"),
    [
        ("acme-sdk==1.0#not-a-comment", "acme-sdk"),
        ("acme-sdk==", "acme-sdk"),
        ("acme-sdk~=1", "acme-sdk"),
        ("acme-sdk==1.*.*", "acme-sdk"),
        ("acme-sdk>=1.*", "acme-sdk"),
        ("acme-sdk=1.0", "acme-sdk"),
        ("acme-sdk 1.0", "acme-sdk"),
        ("Acme_SDK[x] ~= 1", "Acme_SDK"),
        ("  acme-sdk ~=1", "acme-sdk"),
        ("acme-sdk;python_version<'3'~=1", "acme-sdk"),
    ],
)
def test_a_requirement_whose_version_nobody_can_read_is_still_a_row_with_no_pin_or_version(
    text: str, raw: str
) -> None:
    """The gate asks every row, so a line it skipped could hide a pin the floor would refuse."""
    (found,) = read(text + "\n")
    assert (found.name, found.raw, found.pin, found.spec) == ("acme-sdk", raw, None, None)
    assert text[found.column : found.end] == raw


@pytest.mark.parametrize(
    ("path", "text"),
    [
        ("pyproject.toml", '[project]\ndependencies = [\n  "acme-sdk~=1",\n]\n'),
        ("pyproject.toml", '[dependency-groups]\ndev = ["acme-sdk==1.*.*"]\n'),
        ("setup.cfg", "[options]\ninstall_requires =\n    acme-sdk~=1\n"),
        ("setup.cfg", "[options]\nsetup_requires = acme-sdk~=1\n"),
        ("setup.py", 'setup(install_requires=["acme-sdk~=1"])\n'),
    ],
)
def test_a_requirement_nobody_can_read_is_a_row_in_every_layout(path: str, text: str) -> None:
    (found,) = manifests.declarations(path, text.encode())
    assert (found.name, found.pin, found.spec) == ("acme-sdk", None, None)
    assert found.raw == "acme-sdk"


def test_a_line_of_prose_holds_a_row_named_for_its_first_word() -> None:
    """Harmless unless that word is a distribution the pack asks about, which is the point."""
    assert declared("acme-sdk is great\nthis is not a requirement\n") == [
        (1, 0, "acme-sdk"),
        (2, 0, "this"),
    ]


def test_an_editable_requirement_names_the_distribution_and_nothing_else() -> None:
    (found,) = read("-e acme-sdk==1.0\n")
    assert (found.name, found.pin, found.spec) == ("acme-sdk", None, None)


def test_an_archive_name_is_cut_at_the_first_dash_before_a_digit() -> None:
    names = [row.name for row in read("./py-3d-1.0.whl\n./acme_sdk-extras-1.0.tar.gz\n")]
    assert names == ["py", "acme-sdk-extras"]


def test_a_very_long_line_is_read_in_linear_time() -> None:
    """None of the patterns that read a line backtracks over a name, a path or a run of blanks."""
    lines = [
        "a-" * 300_000,
        "a-1" * 200_000,
        "#egg=" * 100_000,
        " " * 500_000 + "#",
        "a -" * 200_000,
    ]
    began = time.monotonic()
    for line in lines:
        read(line + "\n")
    assert time.monotonic() - began < 5


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


@pytest.mark.parametrize(
    ("table", "key"),
    [
        ("tool.uv", "dev-dependencies"),
        ("tool.pdm.dev-dependencies", "lint"),
        ("tool.hatch.envs.default", "dependencies"),
        ("tool.hatch.envs.default", "extra-dependencies"),
    ],
)
def test_the_arrays_uv_pdm_and_hatch_keep_requirements_in_are_read(table: str, key: str) -> None:
    """The decoys: a commented pin, and the same key in a table of the same tool that is no list."""
    text = f"""
[{table}]
{key} = [
  # "acme-sdk==1.0"
  "acme-sdk==1.0",
]

[{table}.sources]
{key} = ["acme-sdk==1.0"]
"""
    assert declared(text, "pyproject.toml") == [(4, 3, "acme-sdk")]


def test_only_the_keys_uv_and_hatch_install_from_are_read() -> None:
    text = """
[tool.uv]
dev-dependencies = ["acme-sdk==1.0"]
constraint-dependencies = ["acme-sdk==1.0"]

[tool.hatch.envs.default]
extra-dependencies = ["acme-sdk==1.0"]
scripts = ["acme-sdk==1.0"]

[tool.hatch.envs.default.scripts]
lock = "pip install acme-sdk==1.0"
"""
    assert declared(text, "pyproject.toml") == [(2, 21, "acme-sdk"), (6, 23, "acme-sdk")]


def test_every_group_of_a_pdm_table_is_read() -> None:
    text = """
[tool.pdm.dev-dependencies]
test = ["acme-sdk==1.0"]
lint = ["acme-sdk==1.0"]
"""
    assert declared(text, "pyproject.toml") == [(2, 9, "acme-sdk"), (3, 9, "acme-sdk")]


@pytest.mark.parametrize(
    ("header", "name"),
    [
        ("[tool.poetry.dependencies.acme-sdk]", 26),
        ("[tool.poetry.dev-dependencies.acme-sdk]", 30),
        ("[tool.poetry.group.test.dependencies.acme-sdk]", 37),
        ('[tool.poetry.dependencies."acme-sdk"]', 27),
        ("[ tool.poetry.dependencies.acme-sdk ] # why", 27),
        ("[packages.acme-sdk]", 10),
        ("[dev-packages.acme-sdk]", 14),
    ],
)
def test_a_dependency_given_as_its_own_table_is_named_by_its_header_and_read_only(
    header: str, name: int
) -> None:
    """The version is a key below the header, and the name and the version are on two lines, so
    the declaration has no pin to write."""
    text = f"""
{header}
python = "^3.9"
version = "^1.0"
extras = ["grpc"]

[tool.poetry]
version = "2.0"
"""
    (found,) = manifests.declarations("pyproject.toml", text.lstrip("\n").encode())
    assert (found.line, found.column, found.name, found.pin, found.spec) == (
        1,
        name,
        "acme-sdk",
        None,
        "^1.0",
    )


@pytest.mark.parametrize(
    ("body", "spec"),
    [
        ('version = "^1.0"\n', "^1.0"),
        ("version='>=1,<2'\n", ">=1,<2"),
        ("  version  =  '1.0'  # the old one\n", "1.0"),
        ('git = "https://example.invalid/acme.git"\n', None),
        ("extras = [\n  'grpc',\n]\n", None),
        ("version = 1\n", None),
        ('version = "1.0\n', None),
        ("version\n", None),
        ("\n[tool.poetry]\nversion = '1.0'\n", None),
        ('version = "1.0"\nversion = "2.0"\n', "1.0"),
        ("", None),
    ],
    ids=[
        "plain",
        "single-quoted",
        "spaced-and-commented",
        "git",
        "no-version-key",
        "not-a-string",
        "unclosed-quote",
        "no-equals",
        "version-of-the-next-table",
        "first-version-wins",
        "empty-table",
    ],
)
def test_the_version_of_a_dependency_table_is_the_string_under_its_own_header(
    body: str, spec: str | None
) -> None:
    text = f"[tool.poetry.dependencies.acme-sdk]\n{body}"
    (found,) = manifests.declarations("pyproject.toml", text.encode())
    assert (found.name, found.pin, found.spec) == ("acme-sdk", None, spec)


@pytest.mark.parametrize(
    ("value", "version"),
    [
        ('{version = "^1.0"}', "^1.0"),
        ("{ version='>=1,<2' }", ">=1,<2"),
        ('{version = "==1.0",}', "==1.0"),
        ('  {version = ""}  # unpinned', ""),
    ],
)
@pytest.mark.parametrize("path", ["pyproject.toml", "Pipfile"])
def test_an_inline_table_holding_only_a_version_has_its_pin_inside_the_quotes(
    path: str, value: str, version: str
) -> None:
    table = "packages" if path == "Pipfile" else "tool.poetry.dependencies"
    text = f"[{table}]\nacme-sdk = {value}\n"
    (found,) = manifests.declarations(path, text.encode())
    assert found.pin is not None
    assert (text.splitlines()[1][found.pin[0] : found.pin[1]], found.spec) == (version, version)


@pytest.mark.parametrize(
    ("value", "spec"),
    [
        ('{version = "^1.0", extras = ["x"]}', "^1.0"),
        ('{version = "^1.0", python = ">=3.9"}', "^1.0"),
        ('{extras = ["x"], version = "^1.0"}', "^1.0"),
        ('{version = "^1.0", markers = "a == \'b\'"}', "^1.0"),
        ("{version = '^1.0'", "^1.0"),
        ("{version = 1}", None),
        ('{git = "https://example.invalid/x"}', None),
        ("{}", None),
    ],
)
def test_an_inline_table_with_another_key_beside_the_version_has_no_pin(
    value: str, spec: str | None
) -> None:
    """The other keys would be carried to a distribution that may not have them."""
    (found,) = manifests.declarations(
        "pyproject.toml", f"[tool.poetry.dependencies]\nacme-sdk = {value}\n".encode()
    )
    assert (found.pin, found.spec) == (None, spec)


def test_a_dependency_table_with_a_name_pep_508_refuses_declares_nothing() -> None:
    text = """
[tool.poetry.dependencies."not a name"]
version = "1.0"

[tool.poetry.dependencies.""]
version = "1.0"
"""
    assert declared(text, "pyproject.toml") == []


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
    """Only a leading `#` comments in setup.cfg; setuptools keeps an inline one in the value, so
    the line is no requirement it reads, and is known by its name alone."""
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
    assert declared(text, "setup.cfg") == [
        (10, 4, "acme-sdk"),
        (11, 4, "requests"),
        (16, 4, "pytest"),
    ]


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


def test_a_setup_py_with_a_string_python_cannot_read_declares_nothing() -> None:
    """`"C:\\Users"` is no string at all, so the file is not Python and the code pass reports it."""
    text = (
        "setup(install_requires=[\n"
        '    "acme-sdk==1",\n'
        '    "pkg @ file:///C:\\Users\\x\\pkg.whl",\n'
        "])\n"
    )
    assert names(text, "setup.py") == []


@pytest.mark.parametrize(
    ("what", "data"),
    [
        ("a lone CR in the docstring", b'"""a\rb"""\nsetup(install_requires=["acme-sdk==1"])\n'),
        ("a BOM on the line", b'\xef\xbb\xbfsetup(install_requires=["acme-sdk==1"])\n'),
    ],
)
def test_a_setup_py_whose_lines_libcst_counts_differently_names_the_row_without_a_pin(
    what: str, data: bytes
) -> None:
    """libcst breaks a line at a lone CR and drops a BOM; the edit's lines do neither."""
    (found,) = manifests.declarations("setup.py", data)
    assert (found.name, found.pin) == ("acme-sdk", None), what


def test_a_setup_py_libcst_cannot_walk_declares_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """It parses and compiles, then overruns the stack in the metadata pass (about 400 terms)."""

    class TooDeep:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None: ...

        def resolve(self, *_args: Any) -> None:
            raise RecursionError

    monkeypatch.setattr(manifests, "MetadataWrapper", TooDeep)
    assert manifests.declarations("setup.py", b'setup(install_requires=["acme-sdk==1"])\n') == ()


def setup_py(text: str) -> list[tuple[int, int, str, bool]]:
    """Line, column, name and whether the declaration has a pin, of each one a `setup.py` makes."""
    found = manifests.declarations("setup.py", text.lstrip("\n").encode())
    return [(row.line, row.column, row.name, row.pin is not None) for row in found]


@pytest.mark.parametrize(
    "arguments",
    [
        "install_requires=REQS",
        "setup_requires=REQS",
        "tests_require=REQS",
        'extras_require={"dev": REQS}',
        "install_requires=(REQS, [])",
        "install_requires=[REQS]",
    ],
)
def test_a_name_standing_for_a_requirements_list_is_read_where_the_list_is_assigned(
    arguments: str,
) -> None:
    text = f"""
from setuptools import setup

REQS = [
    "acme-sdk==1.0",  # not this one: "acme-sdk==2.0"
    "requests>=2.31",
]

setup({arguments})
"""
    assert setup_py(text) == [(4, 5, "acme-sdk", True), (5, 5, "requests", True)]


def test_a_tuple_a_name_stands_for_is_read_and_a_list_used_twice_is_declared_once() -> None:
    text = """
REQS = ("acme-sdk==1.0",)
setup(install_requires=REQS, tests_require=REQS, extras_require={"a": REQS, "b": REQS})
"""
    assert setup_py(text) == [(1, 9, "acme-sdk", True)]


def test_the_declarations_of_a_setup_py_come_in_the_order_of_the_file() -> None:
    text = """
setup(
    install_requires=["acme-sdk==1.0", TESTS],
    extras_require={"dev": DEV},
)
DEV = ["httpx>=0.27"]
TESTS = ["requests>=2.31"]
"""
    assert [(line, name) for line, _, name, _ in setup_py(text)] == [
        (2, "acme-sdk"),
        (5, "httpx"),
        (6, "requests"),
    ]


def test_a_name_in_a_function_is_followed_to_the_assignment_beside_it() -> None:
    text = """
def main():
    reqs = ["acme-sdk==1.0"]
    setup(install_requires=reqs)
"""
    assert setup_py(text) == [(2, 13, "acme-sdk", True)]


@pytest.mark.parametrize(
    "binding",
    [
        'REQS = ["acme-sdk==1.0"]\nREQS += ["httpx"]',
        'REQS = ["acme-sdk==1.0"]\nREQS = ["acme-sdk==2.0"]',
        'if PY2:\n    REQS = ["acme-sdk==1.0"]\nelse:\n    REQS = ["acme-sdk==2.0"]',
        'REQS = ["acme-sdk==1.0"]\ndef widen():\n    global REQS\n    REQS = []',
        'REQS: list[str] = ["acme-sdk==1.0"]',
        'REQS = OTHER = ["acme-sdk==1.0"]',
        '(REQS, OTHER) = (["acme-sdk==1.0"], 1)',
        'REQS = ["acme-sdk==1.0"] + OTHER',
        'REQS = list(["acme-sdk==1.0"])',
        'REQS = {"acme-sdk==1.0"}',
        'REQS = [name for name in ["acme-sdk==1.0"]]',
        "from reqs import REQS",
        "import REQS",
        "def REQS():\n    return ['acme-sdk==1.0']",
        "for REQS in [['acme-sdk==1.0']]:\n    pass",
        'with open("reqs.txt") as REQS:\n    pass',
    ],
    ids=[
        "augmented",
        "assigned-twice",
        "assigned-in-two-branches",
        "assigned-by-a-function",
        "annotated",
        "chained",
        "unpacked",
        "added-to-another",
        "built-by-a-call",
        "a-set",
        "a-comprehension",
        "imported-from",
        "imported",
        "a-function",
        "a-loop-target",
        "a-with-target",
    ],
)
def test_a_name_that_is_not_bound_once_to_a_list_or_tuple_literal_is_not_followed(
    binding: str,
) -> None:
    assert setup_py(f"{binding}\nsetup(install_requires=REQS)\n") == []


@pytest.mark.parametrize(
    "use",
    [
        "install_requires=sorted(REQS)",
        "install_requires=[*REQS]",
        "install_requires=REQS.copy()",
        "install_requires=[r for r in REQS]",
        "python_requires=REQS",
        "name=REQS",
        "install_requires=OTHER",
        "extras_require={REQS: []}",
    ],
)
def test_a_name_is_followed_only_where_it_is_a_whole_requirements_value(use: str) -> None:
    text = f'REQS = ["acme-sdk==1.0"]\nOTHER = 1\nsetup({use})\n'
    assert setup_py(text) == []


def test_a_name_in_a_parameter_or_the_module_with_no_binding_is_not_followed() -> None:
    text = """
def build(reqs):
    setup(install_requires=reqs)

setup(install_requires=MISSING, tests_require=None)
"""
    assert setup_py(text) == []


@pytest.mark.parametrize(
    ("assigned", "pinned"),
    [
        ('["acme-sdk==1.0"]', True),
        ('["acme-sdk" ">=1.0"]', False),
        ('["acme-sdk" + VERSION]', False),
        ('["acme-sdk>=1".format()]', False),
        ('[read("acme-sdk")]', False),
    ],
)
def test_a_requirement_built_around_its_string_in_the_assigned_list_has_no_pin(
    assigned: str, pinned: bool
) -> None:
    found = setup_py(f"REQS = {assigned}\nsetup(install_requires=REQS)\n")
    assert [(name, pin) for _, _, name, pin in found] == [("acme-sdk", pinned)]


def test_a_requirement_in_an_assigned_list_whose_line_libcst_counts_differently_has_no_pin() -> (
    None
):
    data = b'\xef\xbb\xbfREQS = ["acme-sdk==1"]\nsetup(install_requires=REQS)\n'
    (found,) = manifests.declarations("setup.py", data)
    assert (found.name, found.pin) == ("acme-sdk", None)


def test_a_setup_py_libcst_cannot_resolve_scopes_for_declares_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scope pass walks the tree again after the metadata pass and can overrun the stack."""

    class TooDeep(MetadataWrapper):
        def resolve(self, provider: Any) -> Any:
            if provider is ScopeProvider:
                raise RecursionError
            return super().resolve(provider)

    monkeypatch.setattr(manifests, "MetadataWrapper", TooDeep)
    data = b'REQS = ["acme-sdk==1"]\nsetup(install_requires=REQS)\n'
    assert manifests.declarations("setup.py", data) == ()


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


def test_a_pin_no_code_uses_is_a_review_item_and_never_an_edit() -> None:
    """Code already on the new SDK with the old pin left: removing it is the user's to decide."""
    assert graded((pin(),), NOTHING) == [
        ("requirements.txt", 1, LEGACY, "needs_review", "manifest_code_mismatch")
    ]


@pytest.mark.parametrize(
    "migration",
    [
        manifests.Migration(excluded=("scripts/old.py",)),
        manifests.Migration(transitive=(("app.py", "acme-wire"),)),
    ],
    ids=["an excluded file names it", "a module only it installs is imported"],
)
def test_a_pin_something_may_still_need_is_context(migration: manifests.Migration) -> None:
    assert graded((pin(),), migration) == [("requirements.txt", 1, LEGACY, "not_a_usage", None)]


def test_one_distribution_for_both_apis_is_not_a_pin_over_new_code() -> None:
    """`openai>=1` over 1.x code is the same line as `openai==0.28.1` over 1.x code: not judged."""
    one = SPEC.model_copy(update={"new_distribution": LEGACY})
    found = manifests.plan((pin(),), NOTHING, one).findings
    assert [(r.scan_status, r.bail) for r in found] == [("not_a_usage", None)]


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
        ("def go():\n    import acme.wire\n", True),
        ("try:\n    pass\nexcept OSError:\n    import acme.wire\n", True),
        ("try:\n    pass\nfinally:\n    import acme.wire\n", True),
        ("for _ in ():\n    pass\nelse:\n    import acme.wire\n", True),
        ("match 1:\n    case 1:\n        import acme.wire\n", True),
        (
            "if x:\n    pass\n" + "elif x:\n    pass\n" * 2000 + "else:\n    import acme.wire\n",
            True,
        ),
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
        "in a function",
        "in a handler",
        "in a finally",
        "in a loop's else",
        "in a case",
        "after a long elif chain",
    ],
)
def test_the_imports_that_need_a_transitive_distribution(source: str, found: bool) -> None:
    """By the imports the code makes, and never by the text."""
    rows = manifests.provided("retry.py", source.encode(), SPEC)
    assert rows == ((("retry.py", "acme-wire"),) if found else ())


# `retry.py` names no token of the pack, so it is no candidate; its import of `requests` counts.
REQUESTS = SPEC.model_copy(
    update={"transitive_modules": (ProvidedModule(module="requests", distribution="acme-wire"),)}
)


def test_a_pack_with_no_code_and_no_pin_does_not_survey_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Parsing every file that names a module for a pack the repository does not use is waste."""
    (tmp_path / "retry.py").write_text("import requests\n", encoding="utf-8")
    monkeypatch.setattr(manifests, "provided", pytest.fail)
    assert runner.scan(tmp_path, Config(), REQUESTS, jobs=1).transitive == ()


def test_a_pin_with_no_code_still_waits_for_the_module_only_it_installs(tmp_path: Path) -> None:
    """Dropping it would break `retry.py`, so it is not reported as an unused pin."""
    (tmp_path / "retry.py").write_text("import requests\n", encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("acme-sdk==0.1.0\n", encoding="utf-8")
    scanned = runner.scan(tmp_path, Config(), REQUESTS, jobs=1)
    assert [row.scan_status for row in scanned.manifests.findings] == ["not_a_usage"]
    assert scanned.transitive == (("retry.py", "acme-wire"),)


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


def test_a_notebook_the_user_excludes_no_longer_keeps_the_pin(tmp_path: Path) -> None:
    for name, text in (
        ("app.py", MIGRATES),
        ("analysis.ipynb", NOTEBOOK),
        ("requirements.txt", "acme-sdk==0.1.0\n"),
    ):
        (tmp_path / name).write_text(text, encoding="utf-8")
    scanned = runner.scan(tmp_path, Config(exclude=("*.ipynb",)), SPEC, jobs=1)
    assert scanned.manifests.blocking == ()
    assert scanned.manifests.excluded == ("analysis.ipynb",)
    assert scanned.unanalysed == ()
    assert scanned.counts.eligible > 0


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


@pytest.mark.parametrize(
    ("declared", "upper"),
    [
        ("^1.2.3", "<2"),
        ("^2.10", "<3"),
        ("^3", "<4"),
        ("^0.27", "<0.28"),
        ("^0.27.3", "<0.28"),
        ("^0.0.3", "<0.0.4"),
        ("^0.0", "<0.1"),
        ("^0.0.0", "<0.0.1"),
        ("^0", "<1"),
        ("~3.9.1", "<3.10"),
        ("~3.9", "<3.10"),
        ("~3", "<4"),
        ("~0.27", "<0.28"),
    ],
)
def test_poetry_ends_a_caret_at_the_first_non_zero_part_and_a_tilde_at_the_minor(
    declared: str, upper: str
) -> None:
    found = manifests.alternatives(declared)
    assert found is not None
    (only,) = found
    assert {str(part) for part in only} == {f">={declared[1:]}", upper}


@pytest.mark.parametrize(
    ("declared", "floor"),
    [
        (">=1.2", "1.2"),
        ("==1.2.3", "1.2.3"),
        ("^1.2 || ^2.0", "1.2"),
        ("<3", None),
        ("^1 || <3", None),
        ("not a version", None),
        ("==1.2.3+corp", None),
        ("===1.2.3+corp", None),
        (">=1 || ==2.0+corp", None),
    ],
)
def test_a_local_build_names_no_floor_since_it_is_not_the_release_a_floor_is_measured_on(
    declared: str, floor: str | None
) -> None:
    assert manifests.lowest(declared) == (None if floor is None else Version(floor))


@pytest.mark.parametrize(
    ("requirement", "pinned"),
    [
        ('["acme-sdk"]', True),
        ('("acme-sdk")', True),
        ('["acme-sdk"] + EXTRA', True),
        ('{"x": ["acme-sdk"]}', True),
        ('{"x": "acme-sdk"}', True),
        ('"acme-sdk" if PY3 else "acme-sdk<2"', True),
        ('["acme-sdk" + VERSION]', False),
        ('["acme-sdk" ">=1"]', False),
        ('["acme-sdk>=1".format()]', False),
        ('[str("acme-sdk")]', False),
        ('["acme-sdk>=1"[:8]]', False),
        ('["acme-sdk"][0:1]', True),
        ('read("acme-sdk")', False),
    ],
)
def test_a_setup_py_requirement_built_around_the_literal_names_the_row_without_a_pin(
    requirement: str, pinned: bool
) -> None:
    data = f"setup(install_requires={requirement})\n".encode()
    found = [row for row in manifests.declarations("setup.py", data) if row.name == "acme-sdk"]
    assert found
    assert all((row.pin is not None) == pinned for row in found), requirement


@pytest.mark.parametrize(
    ("path", "text", "marked"),
    [
        ("requirements.txt", f"{LEGACY}>=1\n", False),
        ("requirements.txt", f"{LEGACY}>=1 ; python_version < '3.12'\n", True),
        ("requirements.txt", f"{LEGACY}; sys_platform == 'win32'\n", True),
        ("pyproject.toml", f'[project]\ndependencies = ["{LEGACY}>=1"]\n', False),
        (
            "pyproject.toml",
            f"[project]\ndependencies = [\"{LEGACY}>=1; python_version < '3.12'\"]\n",
            True,
        ),
        ("Pipfile", f'[packages]\n{LEGACY} = "*"\n', False),
        ("setup.cfg", f"[options]\ninstall_requires =\n    {LEGACY}; python_version < '3'\n", True),
        (
            "setup.py",
            "from setuptools import setup\n"
            f"setup(install_requires=['{LEGACY}; os_name == \"a\"'])\n",
            True,
        ),
        (
            "setup.py",
            f"from setuptools import setup\nsetup(install_requires=['{LEGACY}>=1'])\n",
            False,
        ),
    ],
)
def test_a_declaration_says_whether_an_environment_marker_follows_its_version(
    path: str, text: str, marked: bool
) -> None:
    (found,) = manifests.declarations(path, text.encode())
    assert found.marked is marked


def test_a_declaration_is_unmarked_unless_one_is_said() -> None:
    assert pin().marked is False


@pytest.mark.parametrize(
    "path",
    [
        "poetry.lock",
        "Pipfile.lock",
        "uv.lock",
        "pdm.lock",
        "pixi.lock",
        "conda-lock.yml",
        "pylock.toml",
        "environment.yml",
        "environment.yaml",
        "pip.conf",
        "uv.toml",
        "services/api/poetry.lock",
        "pylock.dev.toml",
        "requirements.lock",
        "requirements-dev.lock",
    ],
)
def test_a_lock_nothing_reads_can_still_decide_the_release(path: str) -> None:
    assert manifests.is_lock(path) is True
    assert manifests.is_manifest(path) is False


@pytest.mark.parametrize(
    "path",
    [
        "requirements.txt",
        "requirements-dev.txt",
        "requirements/base.txt",
        "dev-requirements.txt",
        "constraints.txt",
        "requirements.in",
        "pyproject.toml",
        "Pipfile",
        "setup.cfg",
        "setup.py",
        "yarn.lock",
        "package-lock.json",
        "Cargo.lock",
        "pylock.toml.bak",
        "README.md",
        "docs/notes.txt",
        "app.py",
        "Poetry.lock",
    ],
)
def test_a_manifest_this_reads_and_a_file_that_is_no_lock_of_python_is_not_one(path: str) -> None:
    assert manifests.is_lock(path) is False


@pytest.mark.parametrize(
    ("path", "text"),
    [
        ("constraints.txt", "acme-sdk==1.0\n"),
        ("constraints-3.12.txt", "acme-sdk==1.0\n"),
        ("requirements.in", "acme-sdk==1.0  # pinned\n"),
        ("dev-requirements.in", "-c constraints.txt\nacme-sdk==1.0\n"),
    ],
)
def test_a_constraints_file_and_a_pip_tools_input_are_read_and_have_no_pin(
    path: str, text: str
) -> None:
    """The compiled file is what installs, so a rule that edited the input would be undone."""
    (found,) = manifests.declarations(path, text.encode())
    assert (found.name, found.pin, found.spec) == ("acme-sdk", None, "==1.0")


def test_a_bare_name_in_such_a_file_constrains_nothing_and_declares_nothing() -> None:
    text = (
        "acme-sdk\nacme-sdk[x] ; python_version > '3'\nhttpx<1\n-e git+https://h/r#egg=acme-sdk\n"
    )
    found = manifests.declarations("requirements.in", text.encode())
    assert [(row.line, row.name, row.spec) for row in found] == [
        (3, "httpx", "<1"),
        (4, "acme-sdk", None),
    ]


def test_the_lock_set_is_what_the_module_lists() -> None:
    assert {"poetry.lock", "uv.lock", "pip.conf"} <= manifests.LOCKS
    assert all(manifests.is_lock(name) for name in manifests.LOCKS)
    assert not any(manifests.is_manifest(name) for name in manifests.LOCKS)

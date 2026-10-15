"""The declared Python and legacy pin: admitting a version the pack cannot migrate blocks the run.

With `requires_python: ">=3.10"` (on 3.9 pip quietly installs an older, different API) `>=3.9` is
`blocked: runtime_unsupported`. `>=3.7,!=3.9.*` blocks too: every version below 3.10 is asked.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import acme
import pytest

from obelize.models import Config
from obelize.scan import manifests, parse, runtime

if TYPE_CHECKING:  # pragma: no cover - typing only
    from obelize.models import ScanSpec

SPEC = acme.SPEC.model_copy(update={"requires_python": ">=3.10"})

# (declaration, admits an interpreter below 3.10), from PEP 440 and Poetry's caret/tilde rules.
DECLARATIONS = [
    (">=3.10", False),
    (">=3.11", False),
    (">=3.10,<4", False),
    ("==3.12.*", False),
    (">=3.9", True),
    (">=3.8,<4.0", True),
    (">=3.7,!=3.9.*", True),
    ("~=3.9", True),
    ("^3.10", False),
    ("^3.9", True),
    ("^3", True),
    ("~3.10", False),
    ("~3.9", True),
    ("~3", True),
    ("*", True),
    # Unreadable, so never blocking: refusing a migration on a guess is the failure to avoid.
    ("not a specifier", False),
    ("^three.nine", False),
    ("^", False),
    # A floor at a patch release admits the minor from its first patch on.
    (">=3.9.1", True),
    (">3.9", True),
    ("^3.9.1", True),
    (">=3.10.1", False),
    # Poetry's own forms: a comma list, alternatives, a bare version and a wildcard.
    ("^3.9,<3.12", True),
    ("^3.10,<3.12", False),
    ("^3.9 || ^3.10", True),
    ("^3.10 || ^3.11", False),
    ("3.9", True),
    ("3.9.*", True),
    ("3.12", False),
    (">=3.10 <4", False),
    (">= 3.10", False),
    # A release the declaration names is asked about too, though the grid has no such patch.
    ("==3.9.18", True),
    ("==3.10.2", False),
    ("==3.9.18 || ==3.11.4", True),
    ("3.9.18", True),
]


def _config() -> Config:
    return Config()


def _write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.mark.parametrize(("declared", "blocked"), DECLARATIONS, ids=[d for d, _ in DECLARATIONS])
def test_a_declaration_is_read_the_way_its_own_specification_defines_it(
    declared: str, blocked: bool
) -> None:
    assert runtime._admits_unsupported(declared, SPEC) is blocked


def test_the_versions_asked_about_are_every_one_a_pack_could_exclude() -> None:
    """A single-version check would pass most of the table above."""
    assert runtime.PYTHONS[:4] == ("2.7", "2.7.999999", "3.0", "3.0.999999")
    assert runtime.PYTHONS[-1] == "3.29.999999"
    assert len(runtime.PYTHONS) == 62


def test_the_floor_is_the_packs_not_a_constant() -> None:
    older = SPEC.model_copy(update={"requires_python": ">=3.9"})
    assert not runtime._admits_unsupported(">=3.9", older)
    assert runtime._admits_unsupported(">=3.8", older)
    assert runtime._admits_unsupported(
        ">=3.10,<3.12", SPEC.model_copy(update={"requires_python": ">=3.12"})
    )


def test_pep_621_is_read_from_pyproject(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", '[project]\nname = "x"\nrequires-python = ">=3.9"\n')
    found = runtime.declaration("pyproject.toml", parse.disk(tmp_path, _config()))
    assert found == runtime.Declared(path="pyproject.toml", declared=">=3.9")


def test_poetrys_own_key_is_read_when_there_is_no_pep_621_table(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pyproject.toml",
        '[tool.poetry]\nname = "x"\n\n[tool.poetry.dependencies]\npython = "^3.9"\n',
    )
    found = runtime.declaration("pyproject.toml", parse.disk(tmp_path, _config()))
    assert found == runtime.Declared(path="pyproject.toml", declared="^3.9")


def test_pep_621_wins_over_poetrys_key_when_a_document_has_both() -> None:
    """A project migrated to `[project]` has both, and the standard one binds."""
    document = (
        b'[project]\nrequires-python = ">=3.10"\n\n[tool.poetry.dependencies]\npython = "^3.9"\n'
    )
    assert runtime._from_toml(document) == ">=3.10"


def test_setup_cfg_is_read_with_the_parser_setuptools_reads_it_with(tmp_path: Path) -> None:
    _write(tmp_path, "setup.cfg", "[metadata]\nname = x\n\n[options]\npython_requires = >=3.8\n")
    found = runtime.declaration("setup.cfg", parse.disk(tmp_path, _config()))
    assert found == runtime.Declared(path="setup.cfg", declared=">=3.8")


@pytest.mark.parametrize(
    ("requires", "declared", "blocked"),
    [
        ('python_version = "3.9"', "==3.9.*", True),
        ('python_version = "3.10"', "==3.10.*", False),
        ('python_version = "3"', "==3.*", True),
        ('python_full_version = "3.9.18"', "==3.9.18", True),
        ('python_full_version = "3.12.1"', "==3.12.1", False),
        ('python_version = "3.9"\npython_full_version = "3.12.1"', "==3.12.1", False),
        ('python_version = " 3.9"', "== 3.9.*", True),
    ],
    ids=["minor", "newer-minor", "major", "full", "newer-full", "both", "padded"],
)
def test_a_pipfile_requires_is_the_python_the_environment_is_built_from(
    tmp_path: Path, requires: str, declared: str, blocked: bool
) -> None:
    _write(tmp_path, "Pipfile", f'[packages]\nacme-sdk = "*"\n\n[requires]\n{requires}\n')
    found = runtime.declaration("Pipfile", parse.disk(tmp_path, _config()))
    assert found == runtime.Declared(path="Pipfile", declared=declared)
    assert runtime._admits_unsupported(declared, SPEC) is blocked


@pytest.mark.parametrize(
    "document",
    [
        '[packages]\nacme-sdk = "*"\n',
        "requires = 3\n",
        "[requires]\n",
        "[requires]\npython_version = 3.9\n",
        '[requires]\npython_full_version = 3\npython_version = ["3.9"]\n',
    ],
    ids=["no-table", "not-a-table", "no-key", "number", "wrong-types"],
)
def test_a_pipfile_that_says_no_python_declares_none(tmp_path: Path, document: str) -> None:
    _write(tmp_path, "Pipfile", document)
    assert runtime.declaration("Pipfile", parse.disk(tmp_path, _config())) is None


def test_a_pipfile_below_the_floor_blocks_the_run(tmp_path: Path) -> None:
    _write(tmp_path, "Pipfile", '[requires]\npython_version = "3.7"\n')
    floor = runtime.detect(("Pipfile",), parse.disk(tmp_path, _config()), SPEC)
    assert floor.blocked == runtime.Blocked(
        reason="runtime_unsupported",
        package=SPEC.new_distribution,
        path="Pipfile",
        declared="==3.7.*",
        needed=">=3.10",
    )
    assert floor.declared == runtime.Declared(path="Pipfile", declared="==3.7.*")


def test_a_pipfile_in_a_package_does_not_hide_the_root_pyproject(tmp_path: Path) -> None:
    """Depth, then path, across every file that declares a floor."""
    _write(tmp_path, "pyproject.toml", '[project]\nrequires-python = ">=3.9"\n')
    _write(tmp_path, "app/Pipfile", '[requires]\npython_version = "3.8"\n')
    found = runtime.detect(("app/Pipfile", "pyproject.toml"), parse.disk(tmp_path, _config()), SPEC)
    assert found.blocked is not None
    assert found.blocked.path == "pyproject.toml"


@pytest.mark.parametrize(
    ("source", "declared"),
    [
        ('setup(name="x", python_requires=">=3.6")', ">=3.6"),
        ('setuptools.setup(python_requires=">=3.6, !=3.7.*")', ">=3.6, !=3.7.*"),
        ("setup(python_requires='>=3.6')", ">=3.6"),
        ('setup(python_requires=">=3.6" ",<4")', ">=3.6,<4"),
        ('setup(**dict(python_requires=">=3.6"))', ">=3.6"),
        (
            'if PY3:\n    setup(python_requires=">=3.6")\nelse:\n    setup(python_requires="3.9")',
            ">=3.6",
        ),
        (
            'def build():\n    setup(python_requires=">=3.6")\nsetup(python_requires=">=3.9")',
            ">=3.6",
        ),
        ('setup(python_requires=">=3.9")\nsetup(python_requires=">=3.6")', ">=3.9"),
        ('# coding: latin-1\nsetup(name="caf\xe9", python_requires=">=3.6")', ">=3.6"),
    ],
    ids=[
        "keyword",
        "attribute-call",
        "single-quoted",
        "adjacent-literals",
        "dict-call",
        "first-of-two-branches",
        "first-in-the-file-not-the-first-found",
        "two-calls",
        "encoding-line",
    ],
)
def test_a_setup_py_python_requires_literal_is_read(
    tmp_path: Path, source: str, declared: str
) -> None:
    (tmp_path / "setup.py").write_bytes(f"{source}\n".encode("latin-1"))
    found = runtime.declaration("setup.py", parse.disk(tmp_path, _config()))
    assert found == runtime.Declared(path="setup.py", declared=declared)


@pytest.mark.parametrize(
    "source",
    [
        "setup(python_requires=PYTHON_REQUIRES)",
        'setup(python_requires=">=" + MINIMUM)',
        'setup(python_requires=f">={MINIMUM}")',
        'setup(python_requires=">=%s" % MINIMUM)',
        'setup(python_requires=">=3.6".format())',
        "setup(python_requires=read_minimum())",
        "setup(python_requires=None)",
        "setup(python_requires=3.6)",
        'setup(**{"python_requires": ">=3.6"})',
        'setup(**kwargs, name=">=3.6")',
        'setup(python_version=">=3.6", name="python_requires")',
        'PYTHON_REQUIRES = ">=3.6"\nsetup(install_requires=[PYTHON_REQUIRES])',
        'print "python_requires=>=3.6"',
        "setup(python_requires='>=3.6'",
        "",
    ],
    ids=[
        "name",
        "concatenation",
        "f-string",
        "percent-format",
        "call-on-the-literal",
        "call",
        "none",
        "number",
        "dict-key",
        "unpacked",
        "other-keyword",
        "another-keyword",
        "python-2",
        "unclosed",
        "empty",
    ],
)
def test_a_setup_py_python_requires_that_is_not_a_literal_is_a_guess_and_declares_nothing(
    tmp_path: Path, source: str
) -> None:
    _write(tmp_path, "setup.py", f"from setuptools import setup\n{source}\n")
    assert runtime.declaration("setup.py", parse.disk(tmp_path, _config())) is None


def test_a_setup_py_that_is_not_python_declares_nothing_and_is_not_reported(tmp_path: Path) -> None:
    """The code pass reports a file `compile()` refuses, and a Python 2 `setup.py` is common."""
    (tmp_path / "setup.py").write_bytes(b'setup(python_requires=">=3.6")\0\xff')
    floor = runtime.detect(("setup.py",), parse.disk(tmp_path, _config()), SPEC)
    assert floor == runtime.Floor(None, None, ())


def test_a_setup_py_below_the_floor_blocks_the_run(tmp_path: Path) -> None:
    _write(tmp_path, "setup.py", 'setup(python_requires=">=3.6")\n')
    floor = runtime.detect(("setup.py",), parse.disk(tmp_path, _config()), SPEC)
    assert floor.blocked == runtime.Blocked(
        reason="runtime_unsupported",
        package=SPEC.new_distribution,
        path="setup.py",
        declared=">=3.6",
        needed=">=3.10",
    )


def test_a_setup_py_literal_that_is_no_specifier_is_reported_and_blocks_nothing(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "setup.py", 'setup(python_requires="3.x or later")\n')
    floor = runtime.detect(("setup.py",), parse.disk(tmp_path, _config()), SPEC)
    assert floor.blocked is None
    assert floor.limitations == (
        parse.Limitation(path="setup.py", code="input_does_not_parse", detail=runtime.UNREAD),
    )


def test_the_first_file_that_blocks_is_named_whichever_layout_declares_the_floor(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "setup.py", 'setup(python_requires=">=3.6")\n')
    _write(tmp_path, "setup.cfg", "[options]\npython_requires = >=3.7\n")
    _write(tmp_path, "Pipfile", '[requires]\npython_version = "3.8"\n')
    names = ("setup.py", "setup.cfg", "Pipfile")
    found = runtime.detect(names, parse.disk(tmp_path, _config()), SPEC)
    assert found.blocked is not None
    assert found.blocked.path == "Pipfile"


NOTHING_TO_READ = [
    ("requirements.txt", "acme-sdk==1.0.0\n", "a layout with no such key"),
    ("pyproject.toml", '[project]\nname = "x"\n', "a document that declares none"),
    ("pyproject.toml", "[project]\nrequires-python = 310\n", "a value of the wrong type"),
    ("setup.cfg", "[options]\nname = x\n", "a section with no such key"),
    ("Pipfile", "[packages]\nacme-sdk = '*'\n", "a layout with no such key"),
]


@pytest.mark.parametrize(
    ("name", "text", "why"), NOTHING_TO_READ, ids=[f"{n}-{w}" for n, _, w in NOTHING_TO_READ]
)
def test_a_manifest_that_declares_no_floor_declares_nothing(
    tmp_path: Path, name: str, text: str, why: str
) -> None:
    _write(tmp_path, name, text)
    assert runtime.declaration(name, parse.disk(tmp_path, _config())) is None, why


def test_a_manifest_that_is_not_there_declares_nothing(tmp_path: Path) -> None:
    assert runtime.declaration("pyproject.toml", parse.disk(tmp_path, _config())) is None


# An unread requirement is `input_does_not_parse` on the manifest; TOML 1.1 fails before 3.15.
NOT_TOML = "not TOML 1.0, so the Python it requires was not read"
BEFORE_3_15 = pytest.mark.skipif(
    sys.version_info >= (3, 15), reason="tomllib reads TOML 1.1 from 3.15"
)
NOT_CFG = "not a setup.cfg setuptools can read, so the Python it requires was not read"
TOML_1_1 = b'[project]\nrequires-python = ">=3.9"\nurls = { a = "x", }\n'
UNPARSED = [
    ("pyproject.toml", b"[project\n", NOT_TOML),
    pytest.param("pyproject.toml", TOML_1_1, NOT_TOML, marks=BEFORE_3_15),
    ("pyproject.toml", b'[project]\nrequires-python = ">=\xff3.9"\n', NOT_TOML),
    # `compile()` accepts a BOM before Python; TOML does not, and stripping it invents a dialect.
    ("pyproject.toml", b'\xef\xbb\xbf[project]\nrequires-python = ">=3.9"\n', NOT_TOML),
    ("setup.cfg", b"= not ini\n", NOT_CFG),
    ("setup.cfg", b"[options]\npython_requires = >=\xff3.9\n", NOT_CFG),
    ("Pipfile", b"[requires\n", NOT_TOML),
    pytest.param(
        "Pipfile",
        b'[requires]\npython_version = "3.9"\nx = { a = "x", }\n',
        NOT_TOML,
        marks=BEFORE_3_15,
    ),
    ("Pipfile", b'[requires]\npython_version = "3.\xff"\n', NOT_TOML),
]


@pytest.mark.skipif(sys.version_info < (3, 15), reason="tomllib refuses TOML 1.1 before 3.15")
def test_a_manifest_in_toml_1_1_is_read_where_tomllib_reads_it(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_bytes(TOML_1_1)
    floor = runtime.detect(("pyproject.toml",), parse.disk(tmp_path, _config()), SPEC)
    assert floor.limitations == ()
    assert floor.declared == runtime.Declared(path="pyproject.toml", declared=">=3.9")


@pytest.mark.parametrize(
    ("name", "data", "detail"),
    UNPARSED,
    ids=[
        "toml-unclosed",
        "toml-1.1",
        "toml-not-utf8",
        "toml-bom",
        "cfg-not-ini",
        "cfg-not-utf8",
        "pipfile-unclosed",
        "pipfile-toml-1.1",
        "pipfile-not-utf8",
    ],
)
def test_a_manifest_that_does_not_parse_is_reported_rather_than_ignored(
    tmp_path: Path, name: str, data: bytes, detail: str
) -> None:
    (tmp_path / name).write_bytes(data)
    floor = runtime.detect((name,), parse.disk(tmp_path, _config()), SPEC)
    assert floor.declared is None
    assert floor.limitations == (
        parse.Limitation(path=name, code="input_does_not_parse", detail=detail),
    )


def test_an_unparsed_manifest_does_not_hide_the_one_that_blocks(tmp_path: Path) -> None:
    (tmp_path / "setup.cfg").write_bytes(b"= not ini\n")
    _write(tmp_path, "pyproject.toml", '[project]\nrequires-python = ">=3.9"\n')
    floor = runtime.detect(("pyproject.toml", "setup.cfg"), parse.disk(tmp_path, _config()), SPEC)
    assert floor.declared == runtime.Declared(path="pyproject.toml", declared=">=3.9")
    assert [row.path for row in floor.limitations] == ["setup.cfg"]


def test_a_file_over_the_size_limit_is_not_read_here_either(tmp_path: Path) -> None:
    """The bytes come through `parse.contents`, so `max_file_bytes` applies to manifests too."""
    _write(tmp_path, "pyproject.toml", '[project]\nrequires-python = ">=3.9"\n')
    tiny = Config(max_file_bytes=8)
    assert runtime.declaration("pyproject.toml", parse.disk(tmp_path, tiny)) is None


def test_the_repository_is_blocked_when_any_manifest_blocks_it(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", '[project]\nrequires-python = ">=3.10"\n')
    _write(tmp_path, "packages/thing/pyproject.toml", '[project]\nrequires-python = ">=3.9"\n')
    found = runtime.detect(
        ("packages/thing/pyproject.toml", "pyproject.toml"), parse.disk(tmp_path, _config()), SPEC
    )
    assert found.declared == runtime.Declared(
        path="packages/thing/pyproject.toml", declared=">=3.9"
    )
    assert found.blocked is not None
    assert found.blocked.path == "packages/thing/pyproject.toml"


def test_the_row_named_is_the_shallowest_of_the_ones_that_block(tmp_path: Path) -> None:
    """Depth, then path: a plain path sort would put `packages/` first."""
    _write(tmp_path, "pyproject.toml", '[project]\nrequires-python = ">=3.9"\n')
    _write(tmp_path, "packages/thing/pyproject.toml", '[project]\nrequires-python = ">=3.8"\n')
    found = runtime.detect(
        ("packages/thing/pyproject.toml", "pyproject.toml"), parse.disk(tmp_path, _config()), SPEC
    )
    assert found.declared is not None
    assert found.declared.path == "pyproject.toml"


def test_with_nothing_blocking_the_first_declaration_is_still_reported(tmp_path: Path) -> None:
    """So `null` means "nothing declares one", not "nothing was looked at"."""
    _write(tmp_path, "setup.cfg", "[options]\npython_requires = >=3.11\n")
    _write(tmp_path, "pyproject.toml", '[project]\nrequires-python = ">=3.10"\n')
    found = runtime.detect(("pyproject.toml", "setup.cfg"), parse.disk(tmp_path, _config()), SPEC)
    assert found.declared == runtime.Declared(path="pyproject.toml", declared=">=3.10")
    assert found.blocked is None


def test_a_repository_that_declares_nothing_declares_nothing(tmp_path: Path) -> None:
    _write(tmp_path, "requirements.txt", "acme-sdk==1.0.0\n")
    assert runtime.detect(
        ("requirements.txt",), parse.disk(tmp_path, _config()), SPEC
    ) == runtime.Floor(None, None, ())
    assert runtime.detect((), parse.disk(tmp_path, _config()), SPEC) == runtime.Floor(
        None, None, ()
    )


OLD = acme.OLD_SPEC


def _pins(*rows: tuple[str, str | None]) -> list[manifests.Declaration]:
    return [
        manifests.Declaration(
            path=path, line=1, column=0, name="acme-old", raw="acme-old", end=8, pin=None, spec=spec
        )
        for path, spec in rows
    ]


@pytest.mark.parametrize(
    "pinned",
    [">=2,<3", "==2.4.1", "~=2.1", ">2", "^2.0", ">=2.5", "2.4.1", "2.*", "==2.*", "^2.0 || ^3.0"],
    ids=lambda value: value,
)
def test_a_legacy_pin_at_or_above_the_floor_blocks_nothing(pinned: str) -> None:
    assert OLD.legacy_floor == "2"
    assert runtime.legacy(_pins(("requirements.txt", pinned)), OLD, used=True) is None


@pytest.mark.parametrize("pinned", ["", "*", "<3", ">=1", "==1.9", "!=2.0", "^1.0", None])
def test_a_legacy_pin_that_admits_a_version_below_the_floor_blocks_the_run(
    pinned: str | None,
) -> None:
    found = runtime.legacy(_pins(("requirements.txt", pinned)), OLD, used=True)
    assert found == runtime.Blocked(
        reason="legacy_version_unsupported",
        package="acme-old",
        path="requirements.txt",
        declared=pinned,
        needed=">=2",
    )


def test_the_first_offending_declaration_is_named_by_depth_then_path() -> None:
    found = runtime.legacy(
        _pins(("pkg/requirements.txt", "<3"), ("z.txt", ">=1"), ("a.txt", ">=2")), OLD, used=True
    )
    assert found is not None
    assert found.path == "z.txt"


def test_a_declaration_of_another_distribution_is_not_the_legacy_pin() -> None:
    other = [replace(row, name="acme-new") for row in _pins(("requirements.txt", None))]
    assert runtime.legacy(other, OLD, used=False) is None
    blocked = runtime.legacy(other, OLD, used=True)
    assert blocked is not None
    assert blocked.path == ""


def test_a_pin_below_the_floor_blocks_nothing_where_no_code_uses_it() -> None:
    """The code has moved on and the pin was left: that is the manifest pass's row to report."""
    assert runtime.legacy(_pins(("requirements.txt", "==1.9")), OLD, used=False) is None


def test_a_legacy_distribution_declared_nowhere_blocks_only_where_the_code_uses_it() -> None:
    assert runtime.legacy([], OLD, used=False) is None
    assert runtime.legacy([], OLD, used=True) == runtime.Blocked(
        "legacy_version_unsupported", "acme-old", "", None, ">=2"
    )


def test_a_pack_with_an_open_range_has_no_floor_to_hold_a_pin_to() -> None:
    open_range = OLD.model_copy(update={"legacy_floor": None})
    assert runtime.legacy(_pins(("requirements.txt", None)), open_range, used=True) is None


def test_a_declaration_nobody_can_read_is_never_quoted_and_blocks_a_pin() -> None:
    """The text came from a manifest, so a report only repeats what reads as a version set."""
    for pinned in ("not a specifier", "^2\x1b]0;x\x07"):
        found = runtime.legacy(_pins(("requirements.txt", pinned)), OLD, used=True)
        assert found is not None
        assert found.declared is None


def test_an_unpinned_declaration_is_quoted_as_nothing_and_not_as_unreadable() -> None:
    found = runtime.legacy(_pins(("requirements.txt", "")), OLD, used=True)
    assert found is not None
    assert found.declared == ""


def test_a_python_requirement_of_a_form_nobody_reads_is_reported_not_ignored(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "pyproject.toml", '[project]\nrequires-python = "three point nine"\n')
    found = runtime.declaration("pyproject.toml", parse.disk(tmp_path, _config()))
    assert found == parse.Limitation(
        path="pyproject.toml", code="input_does_not_parse", detail=runtime.UNREAD
    )


NEWEST = OLD.model_copy(update={"legacy_newest": "2.4.1"})


def _plain(
    spec: str | None = "", path: str = "requirements.txt", **fields: Any
) -> manifests.Declaration:
    """A requirement a rewrite can carry: the pin span is set, which `_pins` leaves out."""
    row = manifests.Declaration(
        path=path, line=1, column=0, name="acme-old", raw="acme-old", end=8, pin=(8, 8), spec=spec
    )
    return replace(row, **fields)


@pytest.mark.parametrize(
    "pinned", ["", "*", ">=1", "<4", "===2.4.1", "!=2.0", "^1.0 || ^2.0", ">=1,<3"], ids=repr
)
def test_a_plain_requirement_that_admits_the_newest_release_installs_it(pinned: str) -> None:
    assert runtime.installs(_plain(pinned), "2.4.1") is True


@pytest.mark.parametrize(
    "pinned", ["<2.4", "~=1.2", "^1.0", "!=2.4.1", ">=2.0rc1", "==1.*", "<2", "not a specifier"]
)
def test_a_requirement_that_rules_out_the_newest_release_or_may_pick_a_pre_release_does_not(
    pinned: str,
) -> None:
    assert runtime.installs(_plain(pinned), "2.4.1") is False


@pytest.mark.parametrize(
    "fields",
    [{"pin": None}, {"marked": True}, {"spec": None}],
    ids=["pin-span-is-not-the-requirement", "a-marker-may-switch-it-off", "no-readable-spec"],
)
def test_a_requirement_a_rewrite_cannot_carry_or_a_marker_may_skip_installs_nothing(
    fields: dict[str, Any],
) -> None:
    assert runtime.installs(_plain(**{"spec": "", **fields}), "2.4.1") is False


@pytest.mark.parametrize("pinned", ["", "*", ">=1", "<4", "===2.4.1", "^1.0 || ^2.0"], ids=repr)
def test_a_declaration_that_installs_the_newest_release_passes_the_floor(pinned: str) -> None:
    assert runtime.legacy([_plain(pinned)], NEWEST, used=True, newest="2.4.1") is None
    assert runtime.legacy([_plain(pinned)], NEWEST, used=True) is not None


@pytest.mark.parametrize(
    "row",
    [
        _plain("<2.4"),
        _plain("~=1.2"),
        _plain("^1.0"),
        _plain("!=2.4.1"),
        _plain(">=2.0rc1"),
        _plain("not a specifier"),
        _plain("", pin=None),
        _plain("", marked=True),
        _plain(None),
    ],
    ids=lambda row: f"{row.spec!r}-{row.pin}-{row.marked}",
)
def test_a_declaration_that_does_not_install_the_newest_release_blocks_as_before(
    row: manifests.Declaration,
) -> None:
    found = runtime.legacy([row], NEWEST, used=True, newest="2.4.1")
    assert found is not None
    assert found == runtime.legacy([row], NEWEST, used=True)
    assert found.evidence == ""


def test_with_no_newest_release_the_gate_is_what_it_was() -> None:
    """The newest release is the caller's to pass, and a call that passes none blocks."""
    assert runtime.legacy([_plain("")], NEWEST, used=True) == runtime.Blocked(
        "legacy_version_unsupported", "acme-old", "requirements.txt", "", ">=2"
    )


def test_every_declaration_is_judged_and_not_only_the_first_that_passes() -> None:
    both = [_plain(">=2", "a.txt"), _plain("", "b.txt")]
    assert runtime.legacy(both, NEWEST, used=True, newest="2.4.1") is None
    held = [_plain("", "a.txt"), _plain("<2.4", "b.txt"), _plain(">=2", "c.txt")]
    found = runtime.legacy(held, NEWEST, used=True, newest="2.4.1")
    assert found is not None
    assert (found.path, found.declared) == ("b.txt", "<2.4")


def test_a_legacy_distribution_declared_nowhere_blocks_whatever_the_newest_release_is() -> None:
    assert runtime.legacy([], NEWEST, used=True, newest="2.4.1") == runtime.Blocked(
        "legacy_version_unsupported", "acme-old", "", None, ">=2"
    )


def test_contrary_evidence_takes_the_newest_release_back_and_is_the_blocks_evidence() -> None:
    rows = [_plain("", "z.txt"), _plain(">=1", "a.txt"), _plain(">=2", "b.txt")]
    found = runtime.legacy(rows, NEWEST, used=True, newest="2.4.1", contrary="poetry.lock")
    assert found == runtime.Blocked(
        "legacy_version_unsupported", "acme-old", "a.txt", ">=1", ">=2", "poetry.lock"
    )


def test_where_no_code_uses_the_pin_there_is_nothing_to_infer() -> None:
    assert runtime.legacy([_plain("")], NEWEST, used=False, newest="2.4.1") is None
    open_range = NEWEST.model_copy(update={"legacy_floor": None})
    assert runtime.legacy([_plain("")], open_range, used=True, newest="2.4.1") is None


def test_a_run_infers_the_newest_release_only_where_a_declaration_needs_it() -> None:
    assert runtime.inferred([_plain("")], NEWEST) is True
    assert runtime.inferred([_plain(">=2"), _plain(">=1", "b.txt")], NEWEST) is True
    assert runtime.inferred([_plain(">=2"), _plain("^2.0", "b.txt")], NEWEST) is False
    assert runtime.inferred([], NEWEST) is False


@pytest.mark.parametrize(
    ("spec", "rows"),
    [
        (OLD, [_plain("")]),
        (NEWEST.model_copy(update={"legacy_floor": None}), [_plain("")]),
        (NEWEST, [_plain("", name="acme-new")]),
        (NEWEST, [_plain("<2.4")]),
        (NEWEST, [_plain("", pin=None)]),
        (NEWEST, [_plain("", marked=True)]),
    ],
    ids=[
        "pack-names-no-newest",
        "no-floor",
        "other-distribution",
        "rules-it-out",
        "no-pin",
        "marker",
    ],
)
def test_a_run_infers_nothing_where_the_pack_or_the_declaration_gives_nothing_to_infer_from(
    spec: ScanSpec, rows: list[manifests.Declaration]
) -> None:
    assert runtime.inferred(rows, spec) is False

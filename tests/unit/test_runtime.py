"""The declared Python and legacy pin: admitting a version the pack cannot migrate blocks the run.

With `requires_python: ">=3.10"` (on 3.9 pip quietly installs an older, different API) `>=3.9` is
`blocked: runtime_unsupported`. `>=3.7,!=3.9.*` blocks too: every version below 3.10 is asked.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import acme
import pytest

from obelize.models import Config
from obelize.scan import manifests, parse, runtime

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


NOTHING_TO_READ = [
    ("requirements.txt", "acme-sdk==1.0.0\n", "a layout with no such key"),
    ("setup.py", "from setuptools import setup\nsetup(python_requires='>=3.9')\n", "code"),
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
    """`setup.py` is not read: a computed `python_requires=` is the guess this module refuses."""
    _write(tmp_path, name, text)
    assert runtime.declaration(name, parse.disk(tmp_path, _config())) is None, why


def test_a_manifest_that_is_not_there_declares_nothing(tmp_path: Path) -> None:
    assert runtime.declaration("pyproject.toml", parse.disk(tmp_path, _config())) is None


# An unread requirement is `input_does_not_parse` on the manifest; TOML 1.1 fails on every Python.
NOT_TOML = "not TOML 1.0, so the Python it requires was not read"
NOT_CFG = "not a setup.cfg setuptools can read, so the Python it requires was not read"
UNPARSED = [
    ("pyproject.toml", b"[project\n", NOT_TOML),
    ("pyproject.toml", b'[project]\nrequires-python = ">=3.9"\nurls = { a = "x", }\n', NOT_TOML),
    ("pyproject.toml", b'[project]\nrequires-python = ">=\xff3.9"\n', NOT_TOML),
    # `compile()` accepts a BOM before Python; TOML does not, and stripping it invents a dialect.
    ("pyproject.toml", b'\xef\xbb\xbf[project]\nrequires-python = ">=3.9"\n', NOT_TOML),
    ("setup.cfg", b"= not ini\n", NOT_CFG),
    ("setup.cfg", b"[options]\npython_requires = >=\xff3.9\n", NOT_CFG),
]


@pytest.mark.parametrize(
    ("name", "data", "detail"),
    UNPARSED,
    ids=["toml-unclosed", "toml-1.1", "toml-not-utf8", "toml-bom", "cfg-not-ini", "cfg-not-utf8"],
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


def test_a_manifest_this_module_reads_no_floor_from_is_not_reported_when_it_does_not_parse(
    tmp_path: Path,
) -> None:
    """No Python requirement is read from a Pipfile, so its parse failure answers no question."""
    (tmp_path / "Pipfile").write_bytes(b'[packages]\nx = { version = "*", }\n')
    assert runtime.detect(("Pipfile",), parse.disk(tmp_path, _config()), SPEC) == runtime.Floor(
        None, None, ()
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

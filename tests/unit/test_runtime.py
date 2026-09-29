"""The declared Python floor: admitting anything below 3.10 blocks the whole repository.

`google-genai` needs 3.10 (on 3.9 pip quietly installs 1.47.0, a different API), so `>=3.9` is
`blocked: runtime_unsupported`. `>=3.7,!=3.9.*` blocks too: every version below 3.10 is asked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from obelize.models import Config
from obelize.scan import parse, runtime

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
    assert runtime._admits_legacy(declared) is blocked


def test_the_versions_asked_about_are_every_one_below_the_floor() -> None:
    """A single-version check would pass most of the table above."""
    assert runtime.FLOOR == "3.10"
    assert runtime.BELOW_FLOOR[-1] == "3.9"
    assert len(runtime.BELOW_FLOOR) == 11


def test_pep_621_is_read_from_pyproject(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", '[project]\nname = "x"\nrequires-python = ">=3.9"\n')
    found = runtime.declaration(tmp_path, "pyproject.toml", _config())
    assert found == runtime.Declared(path="pyproject.toml", declared=">=3.9", blocked=True)


def test_poetrys_own_key_is_read_when_there_is_no_pep_621_table(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "pyproject.toml",
        '[tool.poetry]\nname = "x"\n\n[tool.poetry.dependencies]\npython = "^3.9"\n',
    )
    found = runtime.declaration(tmp_path, "pyproject.toml", _config())
    assert found == runtime.Declared(path="pyproject.toml", declared="^3.9", blocked=True)


def test_pep_621_wins_over_poetrys_key_when_a_document_has_both() -> None:
    """A project migrated to `[project]` has both, and the standard one binds."""
    document = (
        b'[project]\nrequires-python = ">=3.10"\n\n[tool.poetry.dependencies]\npython = "^3.9"\n'
    )
    assert runtime._from_toml(document) == ">=3.10"


def test_setup_cfg_is_read_with_the_parser_setuptools_reads_it_with(tmp_path: Path) -> None:
    _write(tmp_path, "setup.cfg", "[metadata]\nname = x\n\n[options]\npython_requires = >=3.8\n")
    found = runtime.declaration(tmp_path, "setup.cfg", _config())
    assert found == runtime.Declared(path="setup.cfg", declared=">=3.8", blocked=True)


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
    assert runtime.declaration(tmp_path, name, _config()) is None, why


def test_a_manifest_that_is_not_there_declares_nothing(tmp_path: Path) -> None:
    assert runtime.declaration(tmp_path, "pyproject.toml", _config()) is None


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
    floor = runtime.detect(tmp_path, (name,), _config())
    assert floor.declared is None
    assert floor.limitations == (
        parse.Limitation(path=name, code="input_does_not_parse", detail=detail),
    )


def test_a_manifest_this_module_reads_no_floor_from_is_not_reported_when_it_does_not_parse(
    tmp_path: Path,
) -> None:
    """No Python requirement is read from a Pipfile, so its parse failure answers no question."""
    (tmp_path / "Pipfile").write_bytes(b'[packages]\nx = { version = "*", }\n')
    assert runtime.detect(tmp_path, ("Pipfile",), _config()) == runtime.Floor(None, ())


def test_an_unparsed_manifest_does_not_hide_the_one_that_blocks(tmp_path: Path) -> None:
    (tmp_path / "setup.cfg").write_bytes(b"= not ini\n")
    _write(tmp_path, "pyproject.toml", '[project]\nrequires-python = ">=3.9"\n')
    floor = runtime.detect(tmp_path, ("pyproject.toml", "setup.cfg"), _config())
    assert floor.declared == runtime.Declared(path="pyproject.toml", declared=">=3.9", blocked=True)
    assert [row.path for row in floor.limitations] == ["setup.cfg"]


def test_a_file_over_the_size_limit_is_not_read_here_either(tmp_path: Path) -> None:
    """The bytes come through `parse.contents`, so `max_file_bytes` applies to manifests too."""
    _write(tmp_path, "pyproject.toml", '[project]\nrequires-python = ">=3.9"\n')
    tiny = Config(max_file_bytes=8)
    assert runtime.declaration(tmp_path, "pyproject.toml", tiny) is None


def test_the_repository_is_blocked_when_any_manifest_blocks_it(tmp_path: Path) -> None:
    _write(tmp_path, "pyproject.toml", '[project]\nrequires-python = ">=3.10"\n')
    _write(tmp_path, "packages/thing/pyproject.toml", '[project]\nrequires-python = ">=3.9"\n')
    found = runtime.detect(tmp_path, ("packages/thing/pyproject.toml", "pyproject.toml"), _config())
    assert found.declared == runtime.Declared(
        path="packages/thing/pyproject.toml", declared=">=3.9", blocked=True
    )


def test_the_row_named_is_the_shallowest_of_the_ones_that_block(tmp_path: Path) -> None:
    """Depth, then path: a plain path sort would put `packages/` first."""
    _write(tmp_path, "pyproject.toml", '[project]\nrequires-python = ">=3.9"\n')
    _write(tmp_path, "packages/thing/pyproject.toml", '[project]\nrequires-python = ">=3.8"\n')
    found = runtime.detect(tmp_path, ("packages/thing/pyproject.toml", "pyproject.toml"), _config())
    assert found.declared is not None
    assert found.declared.path == "pyproject.toml"


def test_with_nothing_blocking_the_first_declaration_is_still_reported(tmp_path: Path) -> None:
    """So `null` means "nothing declares one", not "nothing was looked at"."""
    _write(tmp_path, "setup.cfg", "[options]\npython_requires = >=3.11\n")
    _write(tmp_path, "pyproject.toml", '[project]\nrequires-python = ">=3.10"\n')
    found = runtime.detect(tmp_path, ("pyproject.toml", "setup.cfg"), _config())
    assert found.declared == runtime.Declared(
        path="pyproject.toml", declared=">=3.10", blocked=False
    )


def test_a_repository_that_declares_nothing_declares_nothing(tmp_path: Path) -> None:
    _write(tmp_path, "requirements.txt", "acme-sdk==1.0.0\n")
    assert runtime.detect(tmp_path, ("requirements.txt",), _config()) == runtime.Floor(None, ())
    assert runtime.detect(tmp_path, (), _config()) == runtime.Floor(None, ())

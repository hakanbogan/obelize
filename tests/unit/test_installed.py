"""`installed.contrary`: what else in a repository says another release than the newest is in use.

Each check is shown to trip and to stay quiet, over a real git repository, since the walk lists a
dot-directory and an ignored file only there.
"""

from __future__ import annotations

import errno
import subprocess
import time
import tomllib
from dataclasses import replace
from pathlib import Path

import pytest
from pdf_repo import MAIN, REMOVED, SPEC, git_repo

from obelize import fsutil
from obelize.models import Config, Finding, ScanSpec
from obelize.scan import installed, manifests, runner
from obelize.scan.walker import Skipped
from platforms import link, posix_only

REQUIRED = {"requirements.txt": "PyPDF2\n"}


def contrary(
    root: Path,
    *,
    findings: tuple[Finding, ...] = (),
    config: Config | None = None,
    spec: ScanSpec = SPEC,
    listed: tuple[str, ...] = (),
) -> str:
    """The evidence for the repository as a scan reads it; `listed` adds names to the listing."""
    tree = runner.read(root, config or Config(), (spec,))
    rows = tuple(
        row
        for path in tree.walk.manifests
        for row in manifests.read(path, tree.contents).declarations
    )
    walk = replace(tree.walk, listed=(*tree.walk.listed, *listed))
    return installed.contrary(tree.root, walk, tree.contents, rows, findings, spec)


REASONS = {
    "text_mention": "string_or_comment_mention",
    "manifest": "manifest_dependency",
}


def usage(
    symbol: str, *, status: str = "needs_review", kind: str = "call", path: str = "main.py"
) -> Finding:
    return Finding.model_validate(
        {
            "path": path,
            "line": 3,
            "column": 0,
            "kind": kind,
            "confidence_reason": REASONS.get(kind, "direct_import_resolved"),
            "symbol": symbol,
            "scan_status": status,
            "bail": None if status in {"eligible", "not_a_usage"} else "flag_only_surface",
        }
    )


def test_a_repository_that_shows_nothing_else_is_clean(tmp_path: Path) -> None:
    root = git_repo(tmp_path, {**REQUIRED, "main.py": MAIN, "README.md": "PyPDF2 reads PDFs.\n"})
    assert contrary(root) == ""


@pytest.mark.parametrize(
    ("symbol", "status", "kind", "evidence"),
    [
        ("PyPDF2.PdfFileReader", "needs_review", "call", "main.py"),
        ("PyPDF2.PdfFileWriter", "unsupported", "import", "main.py"),
        ("PyPDF2.PdfFileMerger", "needs_review", "attribute", "main.py"),
        ("PyPDF2.utils", "needs_review", "import", "main.py"),
        ("PyPDF2.pdf.PdfFileReader", "needs_review", "call", "main.py"),
        ("PyPDF2.merger.PdfFileMerger", "needs_review", "call", "main.py"),
        ("PyPDF2.PdfFileReader", "not_a_usage", "text_mention", ""),
        ("PyPDF2.PdfReader", "needs_review", "call", ""),
        ("PyPDF2.PdfMerger", "needs_review", "call", ""),
        ("PyPDF2.utilsx", "needs_review", "call", ""),
        ("PyPDF2.errors", "needs_review", "import", ""),
    ],
    ids=[
        "reader",
        "writer",
        "merger",
        "module",
        "member-of-a-module",
        "class-of-a-module",
        "prose-only",
        "kept-name",
        "dropped-later",
        "longer-name",
        "module-the-newest-has",
    ],
)
def test_code_that_uses_a_name_the_newest_release_lacks_cannot_have_run_on_it(
    tmp_path: Path, symbol: str, status: str, kind: str, evidence: str
) -> None:
    root = git_repo(tmp_path, {**REQUIRED, "main.py": MAIN})
    assert contrary(root, findings=(usage(symbol, status=status, kind=kind),)) == evidence


def test_a_manifest_row_is_not_code_that_uses_the_name(tmp_path: Path) -> None:
    root = git_repo(tmp_path, {**REQUIRED, "main.py": MAIN})
    row = usage("PyPDF2.PdfFileReader", status="eligible", kind="manifest")
    assert contrary(root, findings=(row,)) == ""


# A name the newest release lacks, written where the scan reads no code: a notebook, a Python 2
# file, a stub, code the user excluded, prose.


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("nb.ipynb", '{"source": ["from PyPDF2 import PdfFileReader\\n"]}\n'),
        ("py2.py", 'print "x"\nfrom PyPDF2 import PdfFileReader\n'),
        ("stubs/app.pyi", "from PyPDF2 import PdfFileWriter\n"),
        ("scripts/old.py", "m = PyPDF2.PdfFileMerger()\n"),
        ("docs/notes.md", "Reads with PdfFileReader.\n"),
        ("legacy/old.py", "from PyPDF2.utils import PdfReadError\n"),
        ("legacy/old.py", "import PyPDF2.pdf\n"),
        ("legacy/old.py", "x = PyPDF2.merger.PdfFileMerger\n"),
    ],
    ids=[
        "notebook",
        "python-2",
        "stub",
        "excluded-code",
        "prose",
        "module-import",
        "plain-import",
        "module-member",
    ],
)
def test_a_name_the_newest_release_lacks_is_evidence_wherever_it_is_written(
    tmp_path: Path, name: str, body: str
) -> None:
    root = git_repo(tmp_path, {**REQUIRED, name: body})
    assert contrary(root, config=Config(exclude=("scripts/**",))) == name


@pytest.mark.parametrize(
    "body",
    [
        "pdffilereader\n",
        "MyPdfFileReader PdfFileReader_ PdfFileReaders\n",
        "from PyPDF2 import utils\n",
        "import utils, pdf, merger\n",
        "mypypdf2.utils PyPDF2.utilsx PyPDF2.pdf_extra PyPDF2_utils\n",
        "pypdf2.utils.isString pypdf2.pdf\n",
        "PyPDF2.errors.PdfReadError PyPDF2.PdfReader\n",
    ],
    ids=[
        "lower-case",
        "longer-names",
        "from-import",
        "bare-words",
        "near-misses",
        "another-case",
        "kept-names",
    ],
)
def test_a_word_that_is_not_a_name_the_newest_release_lacks_is_not_evidence(
    tmp_path: Path, body: str
) -> None:
    root = git_repo(tmp_path, {**REQUIRED, "notes.txt": body})
    assert contrary(root) == ""


def test_a_pack_that_names_nothing_its_newest_release_lacks_reads_no_name(tmp_path: Path) -> None:
    root = git_repo(tmp_path, {**REQUIRED, "old.py": REMOVED})
    assert contrary(root) == "old.py"
    assert contrary(root, spec=SPEC.model_copy(update={"legacy_lacks": ()})) == ""


# What a manifest says: unreadable, a name with no row, an option that moves a release's source.

HASHED = "pypdf2==1.26.0 \\\n    --hash=sha256:aaaa\n"


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("requirements-lock.txt", HASHED),
        ("requirements-lock.txt", "https://host/PyPDF2-1.26.0-py3-none-any.whl\n"),
        ("requirements-lock.txt", "PYPDF2==1.26.0 \\\n"),
        ("requirements.txt", "PyPDF2\n-e git+https://host/repo#egg=PyPDF2\n"),
        ("requirements.txt", "PyPDF2\nsix\npypdf2==1.26.0 \\\n"),
        ("pyproject.toml", '[tool.uv]\nconstraint-dependencies = ["PyPDF2<3"]\n'),
        ("pyproject.toml", '[tool.uv.sources]\nPyPDF2 = { git = "https://host/repo" }\n'),
        ("setup.cfg", "[options.extras_require]\npdf = \n  PyPDF2 @ ./PyPDF2-1.26.0.tar.gz\n"),
    ],
    ids=[
        "hashed-lowercase-export",
        "wheel-url",
        "uppercase-continued",
        "editable-egg",
        "continued-after-a-row",
        "uv-constraints",
        "uv-sources",
        "setup-cfg-path",
    ],
)
def test_a_manifest_that_names_the_distribution_where_no_row_was_read_decides_nothing_visible(
    tmp_path: Path, name: str, body: str
) -> None:
    root = git_repo(tmp_path, {**REQUIRED, name: body})
    assert contrary(root) == name


def test_a_dependency_given_as_its_own_table_has_its_row_at_the_header(tmp_path: Path) -> None:
    """Its version line names nothing, and the row has no pin, so it never installs the newest."""
    table = '[tool.poetry.dependencies.PyPDF2]\nversion = "^1.26"\n'
    assert contrary(git_repo(tmp_path, {**REQUIRED, "pyproject.toml": table})) == ""


def test_a_second_mention_with_no_row_is_found_beside_a_line_that_has_one(tmp_path: Path) -> None:
    one = 'dependencies = ["PyPDF2"]\n'
    other = '\n[tool.uv]\nconstraint-dependencies = ["PyPDF2"]\n'
    head = "[project]\nname = 'x'\n"
    both = git_repo(tmp_path / "a", {"pyproject.toml": head + one + other})
    assert contrary(both) == "pyproject.toml"
    alone = git_repo(tmp_path / "b", {"pyproject.toml": head + one})
    assert contrary(alone) == ""


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("pyproject.toml", '[tool.isort]\nknown_third_party = ["PyPDF2"]\n'),
        ("pyproject.toml", '[tool.ruff.lint.isort]\nknown-third-party = ["PyPDF2"]\n'),
        (
            "pyproject.toml",
            '[[tool.mypy.overrides]]\nmodule = ["PyPDF2.*"]\nignore_missing_imports = true\n',
        ),
        (
            "pyproject.toml",
            '[tool.pytest.ini_options]\nfilterwarnings = ["ignore::PyPDF2.DeprecationWarning"]\n',
        ),
        (
            "pyproject.toml",
            '[project]\nname = "x"\ndescription = "Splits PyPDF2 files"\nkeywords = ["PyPDF2"]\n',
        ),
        ("pyproject.toml", '[project.urls]\nUpstream = "https://github.com/py-pdf/PyPDF2"\n'),
        ("pyproject.toml", '[tool.poetry]\nname = "x"\ndescription = "Wraps PyPDF2"\n'),
        ("pyproject.toml", '[build-system]\nrequires = ["PyPDF2", "setuptools"]\n'),
        ("pyproject.toml", 'tool = { isort = { known_third_party = ["PyPDF2"] } }\n'),
        ("Pipfile", '[scripts]\nsplit = "python -m PyPDF2"\n'),
        ("Pipfile", '[requires]\npython_version = "3.12"\n[pipenv]\nnote = "PyPDF2"\n'),
    ],
    ids=[
        "isort",
        "ruff-isort",
        "mypy-override",
        "pytest-filter",
        "project-text",
        "project-urls",
        "poetry-text",
        "build-requires",
        "inline-table-of-a-tool",
        "pipfile-scripts",
        "pipfile-other-table",
    ],
)
def test_a_name_in_what_a_tool_that_installs_nothing_holds_is_not_evidence(
    tmp_path: Path, name: str, body: str
) -> None:
    """These name the distribution in many repositories that declare it in a manifest."""
    root = git_repo(tmp_path, {**REQUIRED, name: body})
    assert contrary(root) == ""


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("pyproject.toml", '[project]\ndependencies = ["PyPDF2>=3", "pypdf2[crypto]"]\n'),
        ("pyproject.toml", '[project.optional-dependencies]\npdf = ["PyPDF2"]\n'),
        ("pyproject.toml", '[dependency-groups]\ndev = ["PyPDF2", {include-group = "test"}]\n'),
        ("pyproject.toml", '[tool.poetry.dependencies]\nPyPDF2 = "^3"\n'),
        (
            "pyproject.toml",
            '[tool.poetry.dependencies]\nPyPDF2 = { version = "^3", extras = ["x"] }\n',
        ),
        ("pyproject.toml", '[tool.poetry.group.dev.dependencies]\nPyPDF2 = "^3"\n'),
        ("pyproject.toml", '[tool.poetry.dependencies.PyPDF2]\nversion = "^3"\n'),
        ("pyproject.toml", '[tool.uv]\ndev-dependencies = ["PyPDF2"]\n'),
        ("pyproject.toml", '[tool.pdm.dev-dependencies]\ntest = ["PyPDF2"]\n'),
        ("pyproject.toml", '[tool.hatch.envs.default]\ndependencies = ["PyPDF2"]\n'),
        ("Pipfile", '[packages]\nPyPDF2 = "*"\n[dev-packages]\npypdf2 = ">=3"\n'),
    ],
    ids=[
        "project",
        "optional",
        "group",
        "poetry",
        "poetry-inline",
        "poetry-group",
        "poetry-table",
        "uv-dev",
        "pdm-dev",
        "hatch-env",
        "pipfile",
    ],
)
def test_a_declaration_the_reader_reads_names_nothing_it_missed(
    tmp_path: Path, name: str, body: str
) -> None:
    """Each name is a row, so there is no more of them than rows and nothing is left unread."""
    root = git_repo(tmp_path, {"requirements.txt": "six\n", name: body})
    assert contrary(root) == ""


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("pyproject.toml", '[tool.uv]\noverride-dependencies = ["PyPDF2"]\n'),
        ("pyproject.toml", '[tool.uv]\nupgrade-package = ["PyPDF2"]\n'),
        ("pyproject.toml", '[tool.pdm.resolution.overrides]\nPyPDF2 = "<3"\n'),
        ("pyproject.toml", '[tool.hatch.envs.x]\nscripts = { run = "pip install -U PyPDF2" }\n'),
        (
            "pyproject.toml",
            '[tool.pixi.pypi-dependencies]\nPyPDF2 = { git = "https://host/repo" }\n',
        ),
        ("pyproject.toml", '[tool.rye]\ndev-dependencies = ["PyPDF2 @ git+https://host/repo"]\n'),
        (
            "pyproject.toml",
            '[tool.poetry.dependencies]\nPyPDF2 = { git = "https://host/PyPDF2.git" }\n',
        ),
        (
            "pyproject.toml",
            '[tool.poetry.dependencies]\nPyPDF2 = { path = "../PyPDF2-1.26.0.tar.gz" }\n',
        ),
        ("pyproject.toml", '[tool.poetry.extras]\npdf = ["PyPDF2"]\n'),
        ("Pipfile", '[packages]\nPyPDF2 = { git = "https://host/PyPDF2.git" }\n'),
        ("Pipfile", '[packages]\nflask = "*"\n[docs]\nPyPDF2 = "==1.26.0"\n'),
    ],
    ids=[
        "uv-override",
        "uv-upgrade-package",
        "pdm-override",
        "hatch-script",
        "pixi-git",
        "rye-git",
        "poetry-git",
        "poetry-path",
        "poetry-extras",
        "pipfile-git",
        "pipfile-category",
    ],
)
def test_a_name_where_a_dependency_can_be_declared_and_no_row_was_read_is_evidence(
    tmp_path: Path, name: str, body: str
) -> None:
    root = git_repo(tmp_path, {"requirements.txt": "PyPDF2\n", name: body})
    assert contrary(root) == name


def test_a_comment_names_nothing_and_a_longer_name_is_another_distribution(tmp_path: Path) -> None:
    body = (
        "PyPDF2  # PyPDF2 reads PDFs\n# pypdf2 was pinned here\n"
        "PyPDF2-extras\n-r requirements-b.txt\n"
    )
    root = git_repo(tmp_path, {"requirements.txt": body, "requirements-b.txt": "six\n"})
    assert contrary(root) == ""


def test_a_file_the_scan_cannot_read_whole_says_nothing_it_can_be_trusted_on(
    tmp_path: Path,
) -> None:
    refused = git_repo(tmp_path / "big", {**REQUIRED, "requirements-big.txt": "six\n" * 200})
    assert contrary(refused, config=Config(max_file_bytes=300)) == "requirements-big.txt"


def test_a_utf_16_manifest_reads_as_nothing_so_it_is_evidence(tmp_path: Path) -> None:
    """`pip freeze > requirements.txt` in a Windows shell: every line is NUL-separated."""
    body = "PyPDF2==1.26.0\n".encode("utf-16")
    root = git_repo(tmp_path, {**REQUIRED, "requirements-freeze.txt": body})
    assert contrary(root) == "requirements-freeze.txt"


@pytest.mark.parametrize(
    "option",
    [
        "-r requirements-b.txt",
        "--requirement requirements-b.txt",
        "--requirement=requirements-b.txt",
        "-c requirements-b.txt",
        "--constraint requirements-b.txt",
        "-r ./requirements-b.txt",
        "-e .",
        "--editable ./local/project[dev]",
        "--extra-index-url https://host/simple",
        "--extra-index-url=https://host/simple",
        "--trusted-host host",
    ],
)
def test_an_option_that_cannot_move_the_release_is_left_alone(tmp_path: Path, option: str) -> None:
    files = {"requirements.txt": f"PyPDF2\n{option}\n", "requirements-b.txt": "six\n"}
    assert contrary(git_repo(tmp_path, files)) == ""


@pytest.mark.parametrize(
    "option",
    [
        "-i https://host/simple",
        "--index-url=https://host/simple",
        "--index-url https://host/simple",
        "--find-links ./wheels",
        "-f ./wheels",
        "--no-index",
        "--pre",
        "--only-binary :all:",
        "-r missing.txt",
        "-r https://host/requirements.txt",
        "-r ../requirements.txt",
        "-rrequirements-b.txt",
        "-e git+https://host/repo#egg=thing",
        "-e git+git@host:org/thing.git",
        "-e file:///srv/thing",
        "--hash=sha256:aaaa",
        "-",
    ],
)
def test_an_option_that_can_move_the_release_is_evidence(tmp_path: Path, option: str) -> None:
    files = {"requirements.txt": f"PyPDF2\n{option}\n", "requirements-b.txt": "six\n"}
    assert contrary(git_repo(tmp_path, files)) == "requirements.txt"


def test_a_file_option_is_read_from_the_directory_of_the_file_that_holds_it(tmp_path: Path) -> None:
    files = {"requirements-b.txt": "six\n", "sub/requirements.txt": "-r ../requirements-b.txt\n"}
    assert contrary(git_repo(tmp_path / "a", {**REQUIRED, **files})) == ""
    files = {"requirements-b.txt": "six\n", "sub/requirements.txt": "-r requirements-b.txt\n"}
    assert contrary(git_repo(tmp_path / "b", {**REQUIRED, **files})) == "sub/requirements.txt"


def test_an_option_is_judged_only_in_a_requirements_file(tmp_path: Path) -> None:
    files = {**REQUIRED, "setup.cfg": "[metadata]\nname = x\n[flake8]\nexclude =\n  -skipped\n"}
    assert contrary(git_repo(tmp_path, files)) == ""


# What the resolver is told: a TOML file that holds a release back or moves the index.


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("pyproject.toml", '[tool.uv]\nexclude-newer = "2022-01-01T00:00:00Z"\n'),
        ("pyproject.toml", '[[tool.uv.index]]\nname = "x"\nurl = "https://host/simple"\n'),
        ("pyproject.toml", '[[tool.uv.index]]\nname = "x"\nexplicit = "yes"\n'),
        ("pyproject.toml", "[tool.uv]\nindex = ['https://host/simple']\n"),
        ("pyproject.toml", '[[tool.poetry.source]]\nname = "x"\nurl = "https://host/simple"\n'),
        ("Pipfile", '[[source]]\nurl = "https://host/simple"\nname = "private"\n'),
        ("Pipfile", '[[source]]\nname = "private"\n'),
        ("Pipfile", "source = ['https://host/simple']\n"),
        ("pyproject.toml", '[tool.uv]\nresolution = "lowest"\n'),
        ("pyproject.toml", '[tool.uv]\nindex-url = "https://host/simple"\n'),
        ("pyproject.toml", '[tool.uv]\nfind-links = ["./wheels"]\n'),
        ("pyproject.toml", "[tool.uv]\nno-index = true\n"),
        ("pyproject.toml", '[tool.uv.pip]\nindex-url = "https://host/simple"\n'),
        ("pyproject.toml", '[[tool.pdm.source]]\nname = "x"\nurl = "https://host/simple"\n'),
        ("pyproject.toml", "[project\n"),
        ("Pipfile", "[[source]\n"),
    ],
    ids=[
        "exclude-newer",
        "uv-index",
        "uv-index-explicit-not-a-bool",
        "uv-index-not-a-table",
        "poetry-source",
        "pipfile-private",
        "pipfile-no-url",
        "pipfile-source-not-a-table",
        "uv-resolution-lowest",
        "uv-index-url",
        "uv-find-links",
        "uv-no-index",
        "uv-pip-table",
        "pdm-source",
        "pyproject-not-toml",
        "pipfile-not-toml",
    ],
)
def test_a_resolver_setting_that_can_hold_a_release_back_or_move_it_is_evidence(
    tmp_path: Path, name: str, body: str
) -> None:
    root = git_repo(tmp_path, {**REQUIRED, name: body})
    assert contrary(root) == name


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("pyproject.toml", '[[tool.uv.index]]\nname = "x"\nurl = "https://h/s"\nexplicit = true\n'),
        ("pyproject.toml", "[tool.uv]\nindex = []\n"),
        ("pyproject.toml", "[tool.poetry]\nname = 'x'\n"),
        ("pyproject.toml", "tool = 'not a table'\n"),
        ("pyproject.toml", "[tool]\nuv = 5\n"),
        ("Pipfile", '[[source]]\nurl = "https://pypi.org/simple"\nname = "pypi"\n'),
        ("Pipfile", '[[source]]\nurl = "https://pypi.org/simple/"\nname = "pypi"\n'),
        ("Pipfile", "source = 'not a list'\n"),
        ("pyproject.toml", '[[source]]\nurl = "https://host/simple"\n'),
    ],
    ids=[
        "uv-index-explicit",
        "uv-no-index",
        "poetry-without-source",
        "tool-not-a-table",
        "uv-not-a-table",
        "pipfile-pypi",
        "pipfile-pypi-slash",
        "pipfile-source-not-a-list",
        "source-outside-a-pipfile",
    ],
)
def test_a_setting_that_leaves_the_index_and_the_release_alone_is_not_evidence(
    tmp_path: Path, name: str, body: str
) -> None:
    root = git_repo(tmp_path, {**REQUIRED, name: body})
    assert contrary(root) == ""


def test_a_resolver_file_that_is_not_utf_8_cannot_say(tmp_path: Path) -> None:
    root = git_repo(tmp_path, {**REQUIRED, "pyproject.toml": b"[project]\nname = '\xff'\n"})
    assert contrary(root) == "pyproject.toml"


def test_a_resolver_file_nobody_could_read_is_skipped_by_the_settings_check(
    tmp_path: Path,
) -> None:
    root = git_repo(tmp_path, {**REQUIRED, "pyproject.toml": "[tool.uv]\nexclude-newer = 'x'\n"})
    tree = runner.read(root, Config(), (SPEC,))
    assert installed._settings(tree.walk, lambda _path: (None, ())) == ""
    assert installed._settings(tree.walk, tree.contents) == "pyproject.toml"


# A manifest the user's `exclude` removed is read for no row, yet what it tells pip counts.


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("scripts/requirements-x.txt", "--index-url https://host/simple\n"),
        ("scripts/requirements-x.txt", "PyPDF2\n-e git+https://host/repo#egg=thing\n"),
        ("scripts/pyproject.toml", '[tool.uv]\nresolution = "lowest"\n'),
        ("scripts/pyproject.toml", "[project\n"),
        ("scripts/Pipfile", '[[source]]\nurl = "https://host/simple"\nname = "private"\n'),
    ],
    ids=["index-url", "editable-url", "uv-resolution", "pyproject-not-toml", "pipfile-private"],
)
def test_an_option_or_setting_in_an_excluded_manifest_is_evidence(
    tmp_path: Path, name: str, body: str
) -> None:
    root = git_repo(tmp_path, {**REQUIRED, name: body})
    assert contrary(root, config=Config(exclude=("scripts/**",))) == name
    assert contrary(root, config=Config(exclude=("elsewhere/**",))) == name


@pytest.mark.parametrize(
    ("name", "body"),
    [
        (
            "scripts/requirements-x.txt",
            "-r ../requirements.txt\n--extra-index-url https://host/s\n",
        ),
        ("scripts/requirements-x.txt", "PyPDF2>=3\nsix\n"),
        ("scripts/requirements-x.txt", "PyPDF2\n"),
        ("scripts/requirements-x.in", "PyPDF2\n"),
        ("scripts/requirements-x.txt", "-i https://host/simple\n".encode("utf-16")),
        ("scripts/pyproject.toml", '[project]\ndependencies = ["PyPDF2"]\n'),
        ("vendor/requirements.txt", "--index-url https://host/simple\n"),
        ("scripts/notes.txt", "--index-url https://host/simple\n"),
    ],
    ids=[
        "harmless-options",
        "newer-release",
        "bare-name",
        "bare-name-in-an-input",
        "utf-16",
        "declaration",
        "always-excluded",
        "not-a-manifest",
    ],
)
def test_an_excluded_manifest_is_judged_by_its_options_and_settings_alone(
    tmp_path: Path, name: str, body: str | bytes
) -> None:
    """What it names is for the search of every listed file, and no row was read from it."""
    root = git_repo(tmp_path, {**REQUIRED, "requirements-b.txt": "six\n", name: body})
    assert contrary(root, config=Config(exclude=("scripts/**",))) == ""


def test_an_excluded_manifest_nobody_can_read_is_not_evidence(tmp_path: Path) -> None:
    files = {**REQUIRED, "scripts/requirements-big.txt": "-i https://host/simple\n" + "x" * 400}
    root = git_repo(tmp_path, files)
    config = Config(exclude=("scripts/**",), max_file_bytes=300)
    assert contrary(root, config=config) == ""


# What is listed: a lock, an installer's settings; and the files read like manifests.


@pytest.mark.parametrize(
    "name",
    [
        "poetry.lock",
        "Pipfile.lock",
        "uv.lock",
        "pdm.lock",
        "pixi.lock",
        "conda-lock.yml",
        "pylock.toml",
        "pylock.docs.toml",
        "environment.yml",
        "environment.yaml",
        "pip.conf",
        "uv.toml",
        "requirements.lock",
        "requirements-dev.lock",
        "sub/poetry.lock",
    ],
)
def test_a_lock_in_the_listing_is_evidence(tmp_path: Path, name: str) -> None:
    root = git_repo(tmp_path, {**REQUIRED, name: "x\n"})
    assert contrary(root) == name


READ = [
    "dev-requirements.txt",
    "pip-requirements.txt",
    "requirements.in",
    "dev-requirements.in",
    "constraints.txt",
    "constraints-3.12.txt",
]


@pytest.mark.parametrize("name", READ)
def test_a_requirements_constraints_or_input_file_is_judged_by_what_it_says(
    tmp_path: Path, name: str
) -> None:
    """Listed, it is not evidence for being there: only a release it rules the newest out of is."""
    quiet = git_repo(tmp_path / "quiet", {**REQUIRED, name: "six\nflask>=2\n"})
    assert contrary(quiet) == ""
    newer = git_repo(tmp_path / "newer", {**REQUIRED, name: "PyPDF2>=3\n"})
    assert contrary(newer) == ""
    older = git_repo(tmp_path / "older", {**REQUIRED, name: "PyPDF2<3\n"})
    assert contrary(older) == name


@pytest.mark.parametrize("name", ["requirements.in", "constraints.txt"])
def test_a_bare_name_in_an_input_or_constraints_file_is_not_read_so_it_stays_evidence(
    tmp_path: Path, name: str
) -> None:
    assert contrary(git_repo(tmp_path, {**REQUIRED, name: "PyPDF2\n"})) == name


def test_an_option_in_a_constraints_file_is_judged_like_one_in_a_requirements_file(
    tmp_path: Path,
) -> None:
    index = {**REQUIRED, "constraints.txt": "-i https://host/simple\n"}
    assert contrary(git_repo(tmp_path / "a", index)) == "constraints.txt"
    files = {**REQUIRED, "requirements.in": "-c constraints.txt\n", "constraints.txt": "six\n"}
    assert contrary(git_repo(tmp_path / "b", files)) == ""


@pytest.mark.parametrize(
    "name",
    [".ci/constraints.txt", "vendor/requirements.in", "build/constraints-3.12.txt"],
)
def test_a_constraints_file_or_input_in_a_directory_the_scan_leaves_out_is_evidence(
    tmp_path: Path, name: str
) -> None:
    """Nothing reads it, and a `-c` to it from anywhere can hold a release back."""
    root = git_repo(tmp_path, {**REQUIRED, name: "six\n"})
    assert contrary(root) == name


@posix_only("a symbolic link is a POSIX file; Windows is tested through the junction refusal")
@pytest.mark.parametrize("name", ["constraints.txt", "requirements.in"])
def test_a_constraints_file_or_input_that_is_a_link_is_evidence(tmp_path: Path, name: str) -> None:
    root = git_repo(tmp_path / "repo", REQUIRED)
    outside = tmp_path / "outside.txt"
    outside.write_text("six\n", encoding="utf-8")
    link(root / name, outside)
    assert contrary(root, listed=(name,)) == name


@pytest.mark.parametrize(
    "name", ["yarn.lock", "package-lock.json", "Cargo.lock", "requirements-dev.txt", "notes.txt"]
)
def test_a_file_that_decides_no_python_release_is_not_evidence(tmp_path: Path, name: str) -> None:
    root = git_repo(tmp_path, {**REQUIRED, name: "x\n"})
    assert contrary(root) == ""


# A version written anywhere, in a file or in the name of one.


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("Dockerfile", "FROM python:3.9\nRUN pip install PyPDF2==1.26.0\n"),
        ("tox.ini", "[testenv]\ndeps =\n    PyPDF2>=1.26,<2\n"),
        (".github/workflows/ci.yml", "steps:\n  - run: pip install 'PyPDF2<3'\n"),
        ("setup.sh", "pip install pypdf2 == 1.26.0\n"),
        ("Makefile", "install:\n\tpip install PyPDF2[crypto]<3\n"),
        ("docs/notes.md", "Needs PyPDF2>=1.26.0,<3.0.0 or PyPDF2!=3.0.1.\n"),
        ("script.py", "SPEC = 'PyPDF2==2.1.1'\n"),
        ("odd.txt", "PyPDF2~=1\n"),
        ("odd2.txt", "PyPDF2>=1.*\n"),
        ("nb.ipynb", '{"source": ["!pip install PyPDF2==1.26.0"]}\n'),
    ],
    ids=[
        "dockerfile",
        "tox",
        "ci-in-a-dot-directory",
        "spaces-around-the-operator",
        "extras",
        "second-clause",
        "source-file",
        "invalid-compatible-release",
        "invalid-wildcard",
        "notebook",
    ],
)
def test_a_release_the_newest_is_not_in_is_evidence_wherever_it_is_written(
    tmp_path: Path, name: str, body: str
) -> None:
    root = git_repo(tmp_path, {**REQUIRED, name: body})
    assert contrary(root) == name


@pytest.mark.parametrize(
    "body",
    [
        "pip install PyPDF2==3.0.1\n",
        "pip install PyPDF2>=2.10 PyPDF2<4\n",
        "PyPDF2 >= 3, < 4\n",
        "PyPDF2[crypto]>=1\n",
        "PyPDF2.PdfReader(PyPDF2.__version__)\n",
        "PyPDF2 <https://pypi.org/project/PyPDF2/>`_\n",
        "uses PyPDF2\n> a quote\n",
        "PyPDF2\n>=1.26 on the next line\n",
        "pypdf2-extras==1.0 and mypypdf2==1.0 and pypdf22==1\n",
        "PyPDF2-3.0.1-py3-none-any.whl\n",
        "PyPDF2 is at 1.26\n",
    ],
)
def test_a_mention_that_admits_the_newest_or_names_no_release_is_not_evidence(
    tmp_path: Path, body: str
) -> None:
    root = git_repo(tmp_path, {**REQUIRED, "notes.txt": body})
    assert contrary(root) == ""


def test_a_mention_matches_in_any_case_and_with_separators_as_the_name_is_spelled(
    tmp_path: Path,
) -> None:
    spec = SPEC.model_copy(update={"legacy_distribution": "py-pdf-two"})
    quiet = git_repo(
        tmp_path / "quiet", {"requirements.txt": "py-pdf-two\n", "a.txt": "py-pdf-twos==1\n"}
    )
    assert contrary(quiet, spec=spec) == ""
    for index, text in enumerate(["PY_PDF.TWO==1.0", "py--pdf-two==1.0", "Py.Pdf_Two[x]<3"]):
        root = git_repo(
            tmp_path / f"loud{index}", {"requirements.txt": "py-pdf-two\n", "a.txt": text}
        )
        assert contrary(root, spec=spec) == "a.txt", text


@pytest.mark.parametrize(
    ("path", "evidence"),
    [
        ("wheels/PyPDF2-1.26.0-py3-none-any.whl", "wheels/PyPDF2-1.26.0-py3-none-any.whl"),
        ("dist/PyPDF2-1.26.0.tar.gz", "dist/PyPDF2-1.26.0.tar.gz"),
        ("venv/lib/python3.9/site-packages/PyPDF2-1.26.0.dist-info/METADATA", None),
        ("wheels/PyPDF2-3.0.1-py3-none-any.whl", ""),
        ("wheels/PyPDF2-3.0.1.tar.gz", ""),
        ("wheels/PyPDF2-extras-1.0.tar.gz", ""),
    ],
    ids=["wheel", "sdist", "committed-environment", "newest-wheel", "newest-sdist", "other-name"],
)
def test_a_file_named_for_another_release_is_evidence_without_being_read(
    tmp_path: Path, path: str, evidence: str | None
) -> None:
    root = git_repo(tmp_path, {**REQUIRED, path: "\0\0 not text"})
    assert contrary(root) == (path if evidence is None else evidence)


def test_a_binary_file_is_searched_without_trouble(tmp_path: Path) -> None:
    root = git_repo(tmp_path, {**REQUIRED, "logo.png": bytes(range(256)) * 40})
    assert contrary(root) == ""


def test_a_file_over_the_size_limit_is_searched_without_being_held_whole(tmp_path: Path) -> None:
    files = {**REQUIRED, "notes.txt": "pip install PyPDF2==1.26.0\n" + "x" * 400}
    root = git_repo(tmp_path, files)
    assert contrary(root, config=Config(max_file_bytes=200)) == "notes.txt"
    assert contrary(root) == "notes.txt"


@pytest.fixture
def small_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(installed, "_WINDOW", 32)
    monkeypatch.setattr(installed, "_OVERLAP", 16)


def searched(tmp_path: Path, body: str) -> bool:
    """Whether `_searched` takes a file that holds `body` as evidence against 3.0.1."""
    path = tmp_path / "notes.txt"
    path.write_text(body, encoding="utf-8", newline="\n")
    return installed._searched(path, installed._mention("PyPDF2", SPEC.legacy_lacks), "3.0.1")


@pytest.mark.usefixtures("small_windows")
@pytest.mark.parametrize("tail", ["\n" + "x" * 80, ""], ids=["inside", "at-the-end"])
@pytest.mark.parametrize("text", ["PyPDF2==1.26.0", "PdfFileReader", "PyPDF2.utils"])
def test_a_mention_across_the_edge_of_a_window_is_found_at_every_offset(
    tmp_path: Path, text: str, tail: str
) -> None:
    for offset in range(70):
        assert searched(tmp_path, "x" * offset + "\n" + text + tail), offset


@pytest.mark.usefixtures("small_windows")
@pytest.mark.parametrize(
    "text",
    [
        "PyPDF2==3.0.1",
        "PyPDF2<=3.0.1",
        "PyPDF2-3.0.1",
        "mypypdf2==1.26.0",
        "xPyPDF2-1.26.0",
        "xPdfFileReader",
        "xPyPDF2.utils",
    ],
)
def test_a_mention_across_the_edge_of_a_window_is_never_read_as_another_release(
    tmp_path: Path, text: str
) -> None:
    """Cut, `PyPDF2==3.0.1` reads `==3.0`, and a window that starts on `PyPDF2` of `mypypdf2` or on
    `PdfFileReader` of `xPdfFileReader` has lost the letter before it."""
    for offset in range(70):
        assert not searched(tmp_path, "x" * offset + "\n" + text + "\n" + "x" * 80), offset
        assert not searched(tmp_path, "x" * offset + "\n" + text), offset
    assert not searched(tmp_path, (text + "\n") * 40)


@pytest.mark.usefixtures("small_windows")
@pytest.mark.parametrize(
    "body",
    [
        "x" * 100,
        "x" * 100 + "\nPyPDF2>=3\n",
        "PyPDF2 reads PDFs" + "x" * 100,
        "PyPDF2\n" * 20,
        "PyPDF2==3.0.1\n" * 20,
    ],
)
def test_a_file_over_the_size_limit_that_names_no_other_release_is_not_evidence(
    tmp_path: Path, body: str
) -> None:
    root = git_repo(tmp_path, {**REQUIRED, "notes.txt": body})
    assert contrary(root, config=Config(max_file_bytes=10)) == ""


def test_a_file_over_the_search_limit_is_not_searched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = git_repo(tmp_path, {**REQUIRED, "notes.txt": "PyPDF2==1.26.0\n" + "x" * 300})
    config = Config(max_file_bytes=100)
    assert contrary(root, config=config) == "notes.txt"
    monkeypatch.setattr(installed, "_LIMIT", 200)
    assert contrary(root, config=config) == ""


def test_a_file_over_the_size_limit_that_cannot_be_opened_is_not_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_arguments: object) -> object:
        raise PermissionError(errno.EACCES, "denied")

    root = git_repo(tmp_path, {**REQUIRED, "notes.txt": "PyPDF2==1.26.0\n" + "x" * 300})
    monkeypatch.setattr(fsutil, "windows", refuse)
    assert contrary(root, config=Config(max_file_bytes=100)) == ""


def test_a_listed_name_that_is_gone_or_is_a_directory_is_not_opened(tmp_path: Path) -> None:
    root = git_repo(tmp_path, REQUIRED)
    (root / "folder").mkdir()
    assert contrary(root, listed=("ghost.txt", "folder")) == ""


@posix_only("a fifo and the symlink the scan never follows are POSIX files")
def test_a_fifo_and_a_symlink_in_the_listing_are_never_opened(tmp_path: Path) -> None:
    """Opening a fifo for reading blocks until something writes: the guard must come first."""
    root = git_repo(tmp_path / "repo", REQUIRED)
    outside = tmp_path / "outside.txt"
    outside.write_text("pip install PyPDF2==1.26.0\n", encoding="utf-8")
    subprocess.run(["mkfifo", str(root / "pipe")], check=True)
    link(root / "notes.txt", outside)
    assert contrary(root, listed=("pipe", "notes.txt")) == ""


# What git ignores, so the listing cannot show it.


def test_an_ignored_lock_beside_the_root_is_evidence(tmp_path: Path) -> None:
    root = git_repo(tmp_path, {**REQUIRED, "poetry.lock": "x\n"}, "poetry.lock\n")
    assert contrary(root) == "poetry.lock"


@pytest.mark.parametrize(
    "name",
    ["constraints.txt", "requirements.in", "dev-requirements.txt", "requirements-dev.txt"],
)
def test_an_ignored_requirements_constraints_or_input_file_beside_the_root_is_evidence(
    tmp_path: Path, name: str
) -> None:
    root = git_repo(tmp_path, {**REQUIRED, name: "x\n"}, f"{name}\n")
    assert contrary(root) == name


def test_an_ignored_requirements_file_beside_a_manifest_that_declares_is_evidence(
    tmp_path: Path,
) -> None:
    files = {"requirements.txt": "six\n", "app/requirements.txt": "PyPDF2\n"}
    ignored = {**files, "app/pip-requirements.txt": "x\n"}
    root = git_repo(tmp_path, ignored, "pip-requirements.txt\n")
    assert contrary(root) == "app/pip-requirements.txt"


def test_a_listed_constraints_file_is_read_and_not_looked_for_on_disk(tmp_path: Path) -> None:
    assert contrary(git_repo(tmp_path, {**REQUIRED, "constraints.txt": "six\n"})) == ""


def test_an_ignored_lock_beside_a_manifest_that_declares_is_evidence(tmp_path: Path) -> None:
    files = {"requirements.txt": "six\n", "app/requirements.txt": "PyPDF2\n", "app/uv.lock": "x\n"}
    root = git_repo(tmp_path, files, "uv.lock\n")
    assert contrary(root) == "app/uv.lock"


def test_an_ignored_lock_beside_a_manifest_that_does_not_declare_is_not_looked_for(
    tmp_path: Path,
) -> None:
    files = {**REQUIRED, "other/requirements.txt": "six\n", "other/uv.lock": "x\n"}
    assert contrary(git_repo(tmp_path, files, "uv.lock\n")) == ""


@pytest.mark.parametrize(
    ("environment", "packages", "name"),
    [
        (".venv", "lib/python3.9/site-packages", "PyPDF2-1.26.0.dist-info"),
        ("venv", "lib/python3.12/site-packages", "PyPDF2-2.12.1.dist-info"),
        ("env", "lib/python3.11/site-packages", "PyPDF2-1.26.0-py3.9.egg-info"),
        (".venv", "Lib/site-packages", "pypdf2-1.28.6.dist-info"),
    ],
    ids=["dot-venv", "venv", "env-egg", "windows-layout"],
)
def test_an_ignored_environment_that_holds_another_release_is_evidence(
    tmp_path: Path, environment: str, packages: str, name: str
) -> None:
    where = f"{environment}/{packages}/{name}"
    root = git_repo(tmp_path, {**REQUIRED, f"{where}/METADATA": "x\n"}, f"{environment}/\n")
    assert contrary(root) == where


@pytest.mark.parametrize(
    ("packages", "name"),
    [
        ("lib/python3.9/site-packages", "PyPDF2-3.0.1.dist-info"),
        ("lib/python3.9/site-packages", "PyPDF2-extras-1.0.dist-info"),
        ("lib/python3.9/site-packages", "pypdf-6.19.0.dist-info"),
        ("lib/python3.9/site-packages", "PyPDF2"),
        ("lib/notpython/site-packages", "PyPDF2-1.26.0.dist-info"),
        ("lib/python3.9/elsewhere", "PyPDF2-1.26.0.dist-info"),
    ],
    ids=[
        "newest",
        "other-name",
        "other-distribution",
        "no-metadata",
        "not-a-python",
        "not-packages",
    ],
)
def test_an_ignored_environment_that_holds_the_newest_or_nothing_of_ours_is_not_evidence(
    tmp_path: Path, packages: str, name: str
) -> None:
    root = git_repo(tmp_path, {**REQUIRED, f".venv/{packages}/{name}/METADATA": "x\n"}, ".venv/\n")
    assert contrary(root) == ""


def test_an_environment_that_cannot_be_listed_is_nothing(tmp_path: Path) -> None:
    root = git_repo(tmp_path, {**REQUIRED, ".venv": "a file, not a directory\n"}, ".venv\n")
    assert installed.names(root / ".venv") == []
    assert contrary(root) == ""


@pytest.mark.parametrize(
    ("beside", "environment"),
    [
        ("other/app.py", "other/.venv"),
        ("services/api/src/app.py", "services/api/src/venv"),
        ("docs/conf.py", "docs/env"),
    ],
)
def test_an_ignored_environment_beside_any_listed_file_is_evidence(
    tmp_path: Path, beside: str, environment: str
) -> None:
    where = f"{environment}/lib/python3.9/site-packages/PyPDF2-1.26.0.dist-info"
    files = {**REQUIRED, beside: "x = 1\n", f"{where}/METADATA": "x\n"}
    root = git_repo(tmp_path, files, ".venv/\nvenv/\nenv/\n")
    assert contrary(root) == where


def test_an_ignored_environment_is_not_looked_for_where_nothing_is_listed(tmp_path: Path) -> None:
    """A directory that holds no listed file is not probed: the cost is a stat per directory."""
    where = "other/.venv/lib/python3.9/site-packages/PyPDF2-1.26.0.dist-info"
    root = git_repo(tmp_path, {**REQUIRED, f"{where}/METADATA": "x\n"}, ".venv/\n")
    assert contrary(root) == ""


def test_an_ignored_environment_elsewhere_is_judged_like_one_at_the_root(tmp_path: Path) -> None:
    quiet = "other/.venv/lib/python3.9/site-packages/PyPDF2-3.0.1.dist-info"
    root = git_repo(
        tmp_path, {**REQUIRED, "other/app.py": "x\n", f"{quiet}/METADATA": "x\n"}, ".venv/\n"
    )
    assert contrary(root) == ""


# Which evidence comes first.


def test_the_checks_run_in_a_fixed_order(tmp_path: Path) -> None:
    files = {
        "requirements.txt": "PyPDF2\n-i https://host/simple\n",
        "pyproject.toml": "[tool.uv]\nexclude-newer = 'x'\n",
        "poetry.lock": "x\n",
        "Dockerfile": "RUN pip install PyPDF2==1.26.0\n",
        ".venv/lib/python3.9/site-packages/PyPDF2-1.26.0.dist-info/METADATA": "x\n",
    }
    root = git_repo(tmp_path, files, ".venv/\n")
    code = (usage("PyPDF2.PdfFileReader", path="app.py"),)
    assert contrary(root, findings=code) == "app.py"
    assert contrary(root) == "requirements.txt"
    (root / "requirements.txt").write_text("PyPDF2\n", encoding="utf-8")
    assert contrary(root) == "pyproject.toml"
    (root / "pyproject.toml").unlink()
    assert contrary(root) == "poetry.lock"
    (root / "poetry.lock").unlink()
    assert contrary(root) == "Dockerfile"
    (root / "Dockerfile").unlink()
    assert contrary(root) == ".venv/lib/python3.9/site-packages/PyPDF2-1.26.0.dist-info"


def test_an_ignored_lock_at_the_root_is_evidence_when_only_a_subdirectory_declares(
    tmp_path: Path,
) -> None:
    files = {"app/requirements.txt": "PyPDF2\n", "poetry.lock": "x\n"}
    assert contrary(git_repo(tmp_path, files, "poetry.lock\n")) == "poetry.lock"


@posix_only("a control character cannot be in a Windows file name")
def test_the_name_of_an_ignored_lock_is_spelled_out_wherever_it_is_shown(tmp_path: Path) -> None:
    name = "constraints\x1b[2J.txt"
    root = git_repo(tmp_path, {**REQUIRED, name: "x\n"}, "constraints*\n")
    assert contrary(root) == "constraints\\x1b[2J.txt"


def test_a_name_no_report_can_spell_hides_what_is_under_it(tmp_path: Path) -> None:
    root = git_repo(tmp_path, REQUIRED)
    tree = runner.read(root, Config(), (SPEC,))
    hidden = (Skipped(path="a\\x7cb/poetry.lock", reason="unusable_name", detail=""),)
    skipped = (*tree.walk.skipped, Skipped(path="big.bin", reason="unreadable", detail=""))
    walk = replace(tree.walk, skipped=(*hidden, *skipped))
    rows = tuple(manifests.read("requirements.txt", tree.contents).declarations)
    assert installed.contrary(tree.root, walk, tree.contents, rows, (), SPEC) == hidden[0].path
    walk = replace(tree.walk, skipped=skipped)
    assert installed.contrary(tree.root, walk, tree.contents, rows, (), SPEC) == ""


def test_a_resolver_file_too_deep_for_the_parser_cannot_say(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def too_deep(_text: str) -> dict[str, object]:
        raise RecursionError

    monkeypatch.setattr(tomllib, "loads", too_deep)
    assert contrary(git_repo(tmp_path, {**REQUIRED, "Pipfile": "[packages]\n"})) == "Pipfile"


@pytest.mark.parametrize(
    ("body", "evidence"),
    [
        ("PyPDF2==1.26.0\n", "freeze.txt"),
        ("PyPDF2==3.0.1\n", ""),
    ],
    ids=["another-release", "the-newest"],
)
@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-be"])
def test_a_utf_16_file_that_is_not_a_manifest_is_searched_after_its_byte_order_mark(
    tmp_path: Path, body: str, evidence: str, encoding: str
) -> None:
    data = (
        b"\xfe\xff" + body.encode("utf-16-be") if encoding == "utf-16-be" else body.encode(encoding)
    )
    assert contrary(git_repo(tmp_path, {**REQUIRED, "freeze.txt": data})) == evidence


@pytest.mark.parametrize("body", ["PyPDF2==" + "9" * 5000, "PyPDF2-" + "9" * 5000 + ".tar.gz"])
def test_a_version_of_more_digits_than_python_converts_is_evidence_not_a_crash(
    tmp_path: Path, body: str
) -> None:
    assert contrary(git_repo(tmp_path, {**REQUIRED, "notes.txt": body + "\n"})) == "notes.txt"


def test_a_line_of_opening_brackets_is_searched_in_linear_time(tmp_path: Path) -> None:
    root = git_repo(tmp_path, {**REQUIRED, "notes.txt": "PyPDF2[" * 20000 + "\n"})
    began = time.monotonic()
    assert contrary(root) == ""
    assert time.monotonic() - began < 5

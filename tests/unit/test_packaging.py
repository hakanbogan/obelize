"""Guards on packaging metadata that is easy to let drift."""

from __future__ import annotations

import email
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from email.message import Message
from importlib import metadata
from pathlib import Path
from typing import Any

import pytest
import yaml
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

import obelize

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"


@pytest.fixture(scope="module")
def pyproject() -> dict[str, Any]:
    with PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)


def test_the_dev_tools_are_a_dependency_group_and_nothing_else(pyproject: dict[str, Any]) -> None:
    """A `dev` extra would publish the dev tools to PyPI as something a user can install."""
    project = pyproject["project"]
    assert "optional-dependencies" not in project
    assert "dev" in pyproject["dependency-groups"]


def test_the_sdist_carries_no_tests(pyproject: dict[str, Any]) -> None:
    """The suite reads `docs/`, `examples/` and `bench/`, which the sdist does not ship."""
    include = pyproject["tool"]["hatch"]["build"]["targets"]["sdist"]["include"]
    assert "tests" not in include
    assert "src/obelize" in include


CONSTRAINTS = REPO_ROOT / ".github" / "build-constraints.txt"


@pytest.fixture(scope="module")
def built(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The sdist and the wheel built from this checkout the way a release builds them."""
    out = tmp_path_factory.mktemp("dist")
    subprocess.run(
        ["uv", "build", "--quiet", "--out-dir", str(out), str(REPO_ROOT)],
        env={**os.environ, "UV_BUILD_CONSTRAINT": str(CONSTRAINTS)},
        check=True,
    )
    return out


def test_the_pinned_backend_builds_the_wheel_in_metadata_pypi_accepts(built: Path) -> None:
    """PyPI takes Metadata-Version up to 2.5, so a newer hatchling is pinned only on purpose."""
    (pin,) = [
        line
        for line in CONSTRAINTS.read_text(encoding="utf-8").splitlines()
        if line.startswith("hatchling==")
    ]
    (wheel,) = built.glob("*.whl")
    with zipfile.ZipFile(wheel) as archive:
        (name,) = [name for name in archive.namelist() if name.endswith(".dist-info/WHEEL")]
        generator = email.message_from_bytes(archive.read(name))["Generator"]
    assert generator == pin.replace("==", " ")
    assert Version(_wheel_metadata(wheel)["Metadata-Version"]) <= Version("2.5")


def test_the_sdist_holds_the_package_and_the_root_documents_only(built: Path) -> None:
    """An include pattern without a leading `/` matches that name in every directory."""
    (sdist,) = built.glob("*.tar.gz")
    with tarfile.open(sdist) as archive:
        members = {member.name.partition("/")[2] for member in archive if member.isfile()}
    assert {member for member in members if not member.startswith("src/obelize/")} == {
        ".gitignore",
        "CHANGELOG.md",
        "LICENSE",
        "NOTICE",
        "PKG-INFO",
        "README.md",
        "pyproject.toml",
    }


def _wheel_metadata(wheel: Path) -> Message:
    with zipfile.ZipFile(wheel) as archive:
        (name,) = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        return email.message_from_bytes(archive.read(name))


def _sdist_metadata(sdist: Path) -> Message:
    with tarfile.open(sdist) as archive:
        (member,) = [m for m in archive if m.name.count("/") == 1 and m.name.endswith("/PKG-INFO")]
        handle = archive.extractfile(member)
        assert handle is not None
        return email.message_from_bytes(handle.read())


def _description(headers: Message) -> str:
    assert headers["Description-Content-Type"] == "text/markdown"
    description = headers.get_payload()
    assert isinstance(description, str)
    return description


# A link target in Markdown or HTML: inline links and images, reference definitions, and
# href or src attributes.
LINK_TARGET = re.compile(
    r"\]\((?P<inline>[^)\s]*)"
    r"|^ {0,3}\[[^\]]+\]:[ \t]*<?(?P<reference>[^\s>]*)"
    r"|\b(?:href|src)[ \t]*=[ \t]*[\"']?(?P<attribute>[^\"'\s>]*)",
    re.MULTILINE | re.IGNORECASE,
)
# A scheme, an in-page anchor or a protocol-relative URL.
ABSOLUTE = re.compile(r"[a-z][a-z0-9+.-]*:|#|//", re.IGNORECASE)


def test_the_pypi_page_holds_no_relative_link(built: Path) -> None:
    """PyPI resolves a relative link against the project page, where it is a 404."""
    (wheel,) = built.glob("*.whl")
    (sdist,) = built.glob("*.tar.gz")
    for headers in (_wheel_metadata(wheel), _sdist_metadata(sdist)):
        targets = [
            next(target for target in found.groups() if target is not None)
            for found in LINK_TARGET.finditer(_description(headers))
        ]
        assert targets
        assert [target for target in targets if not ABSOLUTE.match(target)] == []


# A fenced block, and a code span within one line.
FENCED = re.compile(r"^(`{3,}|~{3,}).*?^\1", re.MULTILINE | re.DOTALL)
SPAN = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)")


def code(markdown: str) -> list[str]:
    """Every fenced block, then every code span."""
    blocks = [found.group(0) for found in FENCED.finditer(markdown)]
    return blocks + [found.group(0) for found in SPAN.finditer(markdown)]


def test_the_pypi_page_shows_the_readmes_code_as_written(built: Path) -> None:
    """The link rule rewrites every `](` it meets, in code too, so README keeps it out of code."""
    readme = code((REPO_ROOT / "README.md").read_text(encoding="utf-8"))
    assert readme
    (wheel,) = built.glob("*.whl")
    (sdist,) = built.glob("*.tar.gz")
    for headers in (_wheel_metadata(wheel), _sdist_metadata(sdist)):
        assert code(_description(headers)) == readme


def test_the_pypi_page_links_each_file_at_the_release_tag(tmp_path: Path) -> None:
    """An image needs the raw file: a blob URL serves an HTML page."""
    for name in ("pyproject.toml", "LICENSE", "NOTICE"):
        shutil.copy(REPO_ROOT / name, tmp_path / name)
    # Not this checkout's version, so a version written into the rule fails.
    (tmp_path / "src/obelize").mkdir(parents=True)
    (tmp_path / "src/obelize/__init__.py").write_text(
        '__version__ = "2.3.4rc1"\n', encoding="utf-8"
    )
    readme = (
        "[a](docs/CLI.md#exit-codes) [b](#install) [c](https://x.test/c) [d](//x.test/d)\n"
        "![e](docs/e.gif) ![f](https://x.test/f.svg) ![g](//x.test/g.png) ![](k.png)\n"
        '[![h](/h.png)](/LICENSE "Licence") [i](mailto:i@x.test) [j](examples/j/)\n'
        "```\n[k](x)\n```\n"
        "`[m](y)`\n"
    )
    (tmp_path / "README.md").write_text(readme, encoding="utf-8")
    out = tmp_path / "dist"
    subprocess.run(
        ["uv", "build", "--quiet", "--wheel", "--out-dir", str(out), str(tmp_path)], check=True
    )
    (wheel,) = out.glob("*.whl")
    blob = "https://github.com/hakanbogan/obelize/blob/v2.3.4rc1/"
    raw = "https://raw.githubusercontent.com/hakanbogan/obelize/v2.3.4rc1/"
    description = _description(_wheel_metadata(wheel))
    assert description == (
        f"[a]({blob}docs/CLI.md#exit-codes) [b](#install) [c](https://x.test/c) [d](//x.test/d)\n"
        f"![e]({raw}docs/e.gif) ![f](https://x.test/f.svg) ![g](//x.test/g.png) ![]({raw}k.png)\n"
        f'[![h]({raw}h.png)]({blob}LICENSE "Licence") [i](mailto:i@x.test) [j]({blob}examples/j/)\n'
        f"```\n[k]({blob}x)\n```\n"
        f"`[m]({blob}y)`\n"
    )
    # The rule cannot tell code from prose, and the guard above sees both kinds of damage.
    assert code(readme) == ["```\n[k](x)\n```", "`[m](y)`"]
    assert code(description) == [f"```\n[k]({blob}x)\n```", f"`[m]({blob}y)`"]


# Stated once; every file that names the supported Pythons is compared with it.
SUPPORTED = ("3.12", "3.13", "3.14")


def _ci_jobs() -> dict[str, Any]:
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    jobs: dict[str, Any] = workflow["jobs"]
    return jobs


def _ci_matrix(job: str) -> list[str]:
    versions = _ci_jobs()[job]["strategy"]["matrix"]["python-version"]
    return [str(version) for version in versions]


def test_every_place_that_names_the_supported_pythons_names_the_same_ones(
    pyproject: dict[str, Any],
) -> None:
    project = pyproject["project"]
    floor = SpecifierSet(project["requires-python"])
    assert [v for v in ("3.10", "3.11", *SUPPORTED) if v in floor] == list(SUPPORTED)
    classified = [
        c.removeprefix("Programming Language :: Python :: ")
        for c in project["classifiers"]
        if c.startswith("Programming Language :: Python :: 3.")
    ]
    assert classified == list(SUPPORTED)
    assert pyproject["tool"]["ruff"]["target-version"] == "py" + SUPPORTED[0].replace(".", "")
    assert pyproject["tool"]["mypy"]["python_version"] == SUPPORTED[0]
    assert _ci_matrix("test") == list(SUPPORTED)
    # macOS and Windows run the ends only; the ubuntu matrix covers the middle.
    assert _ci_matrix("test-macos") == [SUPPORTED[0], SUPPORTED[-1]]
    assert _ci_matrix("test-windows") == [SUPPORTED[0], SUPPORTED[-1]]
    # pipx otherwise installs with its own default interpreter, which may be older.
    readme = " ".join((REPO_ROOT / "README.md").read_text(encoding="utf-8").split())
    assert f"needs Python {SUPPORTED[0]} or newer" in readme
    assert f"pipx install --python python{SUPPORTED[0]} obelize" in readme


# The runner label an "Operating System ::" classifier needs a job on that runs the suite. A
# classifier missing here matches no runner.
RUNNERS = {
    "Operating System :: MacOS": "macos-",
    "Operating System :: Microsoft :: Windows": "windows-",
    "Operating System :: POSIX :: Linux": "ubuntu-",
}


def test_every_operating_system_a_classifier_names_has_a_ci_job_that_runs_the_suite(
    pyproject: dict[str, Any],
) -> None:
    """A classifier tells PyPI obelize works on that system; only the suite run there shows it."""
    runners = [
        str(job["runs-on"])
        for job in _ci_jobs().values()
        if any("pytest" in step.get("run", "") for step in job["steps"])
    ]
    claimed = [
        c for c in pyproject["project"]["classifiers"] if c.startswith("Operating System ::")
    ]
    untested = [
        claim
        for claim in claimed
        if not any(runner.startswith(RUNNERS.get(claim, claim)) for runner in runners)
    ]
    assert untested == []


# What a reader calls each of those systems, in the README and in the bug form's list.
NAMES = {
    "Operating System :: MacOS": "macOS",
    "Operating System :: Microsoft :: Windows": "Windows",
    "Operating System :: POSIX :: Linux": "Linux",
}


def test_every_operating_system_a_classifier_names_is_one_the_readme_and_the_bug_form_name(
    pyproject: dict[str, Any],
) -> None:
    """A system PyPI lists must not be one the repository's own pages call untested."""
    claimed = [
        NAMES.get(c, c)
        for c in pyproject["project"]["classifiers"]
        if c.startswith("Operating System ::")
    ]
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    form = yaml.safe_load(
        (REPO_ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.yml").read_text(encoding="utf-8")
    )
    (options,) = [part["attributes"]["options"] for part in form["body"] if part.get("id") == "os"]
    assert [name for name in claimed if name not in readme] == []
    assert [name for name in claimed if name not in options] == []


# (sys_platform, platform_machine) of each machine a wheel install must serve.
MACHINES = {
    "Intel Mac": ("darwin", "x86_64"),
    "Apple silicon Mac": ("darwin", "arm64"),
    "Linux": ("linux", "x86_64"),
    "Linux on ARM": ("linux", "aarch64"),
    "Windows": ("win32", "AMD64"),
}


def test_only_libcst_depends_on_the_machine_and_only_an_intel_mac_keeps_1_8(
    pyproject: dict[str, Any],
) -> None:
    """A marker makes two machines run two different libraries; libcst 1.9 has no Intel macOS
    wheel, and 1.8 has one."""
    requirements = [Requirement(line) for line in pyproject["project"]["dependencies"]]
    marked = [(r, r.marker) for r in requirements if r.marker is not None]
    assert [r.name for r, _ in marked] == ["libcst", "libcst"]
    assert "libcst" not in [r.name for r in requirements if r.marker is None]
    for python in SUPPORTED:
        for machine, (platform, architecture) in MACHINES.items():
            environment = {
                "python_version": python,
                "sys_platform": platform,
                "platform_machine": architecture,
            }
            (chosen,) = [r for r, marker in marked if marker.evaluate(environment)]
            intel_mac = machine == "Intel Mac"
            assert (Version("1.8.6") in chosen.specifier) == intel_mac, (python, machine)
            assert (Version("1.9.0") in chosen.specifier) != intel_mac, (python, machine)


def test_version_is_single_sourced(pyproject: dict[str, Any]) -> None:
    """hatchling reads the version from obelize.__version__."""
    project = pyproject["project"]
    assert isinstance(project, dict)
    assert "version" not in project, (
        "version must stay dynamic, sourced from src/obelize/__init__.py"
    )
    assert project["dynamic"] == ["version", "readme"]
    assert metadata.version("obelize") == obelize.__version__


def test_runtime_dependency_count_is_bounded(pyproject: dict[str, Any]) -> None:
    """TM-7: adding a runtime dependency needs an ADR (ADR-005)."""
    project = pyproject["project"]
    assert isinstance(project, dict)
    dependencies = project["dependencies"]
    assert isinstance(dependencies, list)
    # The budget counts packages; libcst is one package on two marked lines.
    packages = sorted({Requirement(line).name for line in dependencies})
    assert len(packages) <= 7, f"runtime dependencies grew to {len(packages)}: {packages}"


def test_one_console_script_named_after_the_distribution(pyproject: dict[str, Any]) -> None:
    """One shared name lets `uvx obelize` run without `--from`; an alias script could only drift."""
    project = pyproject["project"]
    assert isinstance(project, dict)
    scripts = project["scripts"]
    assert isinstance(scripts, dict)
    assert scripts == {"obelize": "obelize.cli:main"}
    assert project["name"] == "obelize"


def test_package_is_importable_as_a_module() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "obelize.cli", "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        cwd=REPO_ROOT,
    )
    assert result.stdout.strip() == f"obelize {obelize.__version__}"

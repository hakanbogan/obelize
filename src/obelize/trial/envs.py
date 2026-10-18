"""The environments a trial tests in, made with uv, outside the repository and its copy.

One recipe installs what the repository declares: the lock file if it has one, else its project
file, else its requirements files. The environment for the release moved to is the same recipe
and then that release over the first. Installing runs the build scripts of whatever is installed
and reaches the index uv is configured for, which is why a trial needs the person's consent.
"""

from __future__ import annotations

import shlex
import shutil
import sys
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from obelize.verify import runner as verifier

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from pathlib import Path

Recipe = Literal["lock", "project", "requirements"]
# An install that has not finished in this long has not, and a trial should not wait for it.
INSTALL_TIMEOUT_S: Final = 1800
_TAIL: Final = 1200


class EnvError(Exception):
    """An environment that could not be made, with the tail of what the installer said."""


@dataclass(frozen=True, slots=True)
class Env:
    path: Path
    recipe: Recipe

    @property
    def bin(self) -> Path:
        return self.path / ("Scripts" if sys.platform == "win32" else "bin")

    @property
    def python(self) -> Path:
        return self.bin / ("python.exe" if sys.platform == "win32" else "python")


def program() -> str:
    found = shutil.which("uv")
    if found is None:
        raise EnvError(
            "uv is needed to make the environments of a trial, and it is not on PATH: "
            "https://docs.astral.sh/uv/getting-started/installation/"
        )
    return found


def recipe(work: Path) -> tuple[Recipe, tuple[str, ...]]:
    """How the repository's dependencies are installed, and the requirements files if that is it."""
    project = _has_project(work)
    if project and (work / "uv.lock").is_file():
        return "lock", ()
    if project:
        return "project", ()
    files = sorted(
        path.name
        for path in work.glob("requirements*.txt")
        if not path.name.startswith("constraints")
    )
    if files:
        return "requirements", tuple(files)
    raise EnvError(
        "no way to install the dependencies was found: no uv.lock or pyproject.toml with a "
        "[project] table, and no requirements*.txt at the top of the repository"
    )


def _has_project(work: Path) -> bool:
    try:
        return "project" in tomllib.loads((work / "pyproject.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False


def make(
    work: Path,
    path: Path,
    *,
    python: str | None,
    environ: Mapping[str, str],
    say: Callable[[str], None],
) -> Env:
    """The environment `path` for the repository copy `work`, with its dependencies and pytest."""
    kind, files = recipe(work)
    interpreter = python or _pinned(work)
    say(f"Installing the dependencies of the repository ({kind}) into {path.name}")
    if kind == "requirements":
        _step(
            ["venv", str(path), *(["--python", interpreter] if interpreter else [])], work, environ
        )
        found = Env(path, kind)
        _step(["pip", "install", "--python", str(found.python), *_files(files)], work, environ)
        if (work / "setup.py").is_file():
            _step(["pip", "install", "--python", str(found.python), "-e", "."], work, environ)
    else:
        sync = ["sync", *(["--frozen"] if kind == "lock" else [])]
        if interpreter:
            sync += ["--python", interpreter]
        _step(sync, work, {**environ, "UV_PROJECT_ENVIRONMENT": str(path)})
        found = Env(path, kind)
    install(found, "pytest", work=work, environ=environ)
    return found


def install(env: Env, requirement: str, *, work: Path, environ: Mapping[str, str]) -> None:
    """`requirement` in the environment, over what is there."""
    _step(["pip", "install", "--python", str(env.python), requirement], work, environ)


def uninstall(env: Env, name: str, *, work: Path, environ: Mapping[str, str]) -> None:
    """`name` out of the environment, as a move to another distribution leaves it."""
    _step(["pip", "uninstall", "--python", str(env.python), name], work, environ)


def freeze(env: Env, *, work: Path, environ: Mapping[str, str]) -> str:
    """What is installed, one requirement per line."""
    return _step(["pip", "freeze", "--python", str(env.python)], work, environ)


def _files(names: Sequence[str]) -> list[str]:
    return [word for name in names for word in ("-r", name)]


def _pinned(work: Path) -> str | None:
    """The interpreter a `.python-version` file asks for."""
    try:
        first = (work / ".python-version").read_text(encoding="utf-8").split()
    except OSError:
        return None
    return first[0] if first else None


def _step(arguments: list[str], work: Path, environ: Mapping[str, str]) -> str:
    """One uv command in `work`; its output on success, `EnvError` with its tail on failure."""
    argv = (program(), *arguments)
    done = verifier.execute(
        work,
        verifier.Command(" ".join(shlex.quote(word) for word in argv), "cli", argv),
        timeout_s=INSTALL_TIMEOUT_S,
        environ=environ,
    )
    if done.status != "pass":
        raise EnvError(f"uv {arguments[0]} failed: {done.output.strip()[-_TAIL:]}")
    return done.output

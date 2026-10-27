"""The maintained tools an `external_fixer` runs: a closed registry, and one run over one file.

A tool is found among the absolute entries of the person's `PATH`, never in the repository, and
never installed: obelize installs nothing. It is run as the agent is (ADR-003): an argv list and no
shell, a few environment variables, an empty directory, a deadline, and a size on what goes in and
comes out. Only a release the registry lists runs, since what a rule fixes changes between
releases (ADR-074).
"""

from __future__ import annotations

import functools
import os
import subprocess
import tempfile
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

from obelize.native import processes
from obelize.transforms.base import BailError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from obelize.models import FixerId

TIMEOUT_S: Final = 60.0
# The most a tool is given, and the most it may print.
LIMIT: Final = 1 << 22
# What a tool needs to start: none of its own settings (`RUFF_*` changes what it prints), no token.
_KEPT: Final = frozenset(
    {"PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL"}
)


@dataclass(frozen=True, slots=True)
class Fixer:
    """One tool run one way. `argv` follows the program and reads a file on stdin, writing it on
    stdout; `{name}` is the file's name. `releases` is a PEP 440 range of which every release was
    run over the bundled pack's fixtures and wrote the same bytes, and `install` what a person runs
    to have one."""

    tool: str
    releases: str
    argv: tuple[str, ...]
    install: str
    probe: tuple[str, ...] = ("--version",)


@dataclass(frozen=True, slots=True)
class Ran:
    """What a tool printed for a file, and the release that printed it."""

    version: str
    output: bytes


def _ruff(rule: str) -> Fixer:
    """`ruff check --fix-only` for one rule, with no configuration of the repository or the
    person (`--isolated`); its leftover findings are neither printed nor an exit code."""
    argv = ("check", "--isolated", "--select", rule, "--fix-only", "--stdin-filename={name}", "-")
    return Fixer("ruff", ">=0.6.2,<=0.17.2", argv, "ruff==0.17.2")


# Keyed by `models.FixerId`, which holds the same set (tested).
FIXERS: Final[dict[FixerId, Fixer]] = {"ruff:NPY201": _ruff("NPY201")}


def environment(environ: Mapping[str, str]) -> dict[str, str]:
    """The variables a tool starts with."""
    return {name: value for name, value in environ.items() if name in _KEPT}


def run(fixer: FixerId, name: str, data: bytes, environ: Mapping[str, str] = os.environ) -> Ran:
    """The tool's output for the file `name`, or `BailError` with the code that says why none."""
    if len(data) > LIMIT:
        raise BailError("external_tool_size_limit")
    program, version = ready(fixer, environ)
    argv = [program, *(word.replace("{name}", name) for word in FIXERS[fixer].argv)]
    done = _spawn(argv, data, environ)
    if done.returncode != 0:
        raise BailError("external_tool_failed")
    if len(done.stdout) > LIMIT:
        raise BailError("external_tool_size_limit")
    return Ran(version, done.stdout)


def ready(fixer: FixerId, environ: Mapping[str, str] = os.environ) -> tuple[str, str]:
    """Where the tool is and the release it is, or `BailError` if it is not here or not accepted."""
    spec = FIXERS[fixer]
    path = os.pathsep.join(
        entry for entry in environ.get("PATH", "").split(os.pathsep) if os.path.isabs(entry)
    )
    program = processes.locate(spec.tool, {"PATH": path})
    if program is None:
        raise BailError("external_tool_missing")
    version = _release(program, spec.probe, tuple(sorted(environment(environ).items())))
    try:
        accepted = Version(version) in SpecifierSet(spec.releases)
    except InvalidVersion:
        accepted = False
    if not accepted:
        raise BailError("external_tool_version_unsupported")
    return program, version


def problem(fixer: FixerId, environ: Mapping[str, str] = os.environ) -> str | None:
    """Why the tool cannot run here, with the command that fixes it, or `None`."""
    try:
        ready(fixer, environ)
    except BailError as bail:
        return f"{fixer}: {bail.reason}; install it with `uv tool install {FIXERS[fixer].install}`"
    return None


@functools.cache
def _release(program: str, probe: tuple[str, ...], environ: tuple[tuple[str, str], ...]) -> str:
    """The last word of the first line the tool prints for `probe` (`ruff 0.16.8`)."""
    done = _spawn([program, *probe], b"", dict(environ))
    words = done.stdout.decode("utf-8", "replace").split("\n", 1)[0].split()
    if done.returncode != 0 or not words:
        raise BailError("external_tool_failed")
    return words[-1]


def _spawn(
    argv: list[str], data: bytes, environ: Mapping[str, str]
) -> subprocess.CompletedProcess[bytes]:
    with tempfile.TemporaryDirectory(prefix="obelize-fixer-") as empty:
        try:
            return subprocess.run(
                argv,
                input=data,
                capture_output=True,
                cwd=empty,
                env=environment(environ),
                timeout=TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise BailError("external_tool_timeout") from error
        except OSError as error:
            raise BailError("external_tool_failed") from error


__all__ = ["FIXERS", "LIMIT", "TIMEOUT_S", "Fixer", "Ran", "environment", "problem", "ready", "run"]

"""One release's public API as data: what a name is, what it takes, what it derives from and
whether the library says it is deprecated.

The reading happens in a child process (`worker`), with a deadline and no environment but what
Python needs, over source that was unpacked and never run. What comes back is JSON, parsed here
into plain dataclasses.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from obelize.scan.inventory import packages

if TYPE_CHECKING:
    from collections.abc import Mapping

TIMEOUT_S: Final = 300.0
# What a source distribution ships beside the library, by the name of the top directory or file.
_NOT_MODULES: Final = frozenset({"tests", "test", "docs", "examples", "setup.py", "conftest.py"})
# The variables Python needs to start; the child sees none of the person's others.
_KEPT: Final = ("PATH", "SYSTEMROOT", "TEMP", "TMP", "LANG", "LC_ALL")


class SurfaceError(Exception):
    """A release whose API could not be read, and why."""


@dataclass(frozen=True, slots=True)
class Param:
    name: str
    kind: str
    default: str | None
    required: bool


@dataclass(frozen=True, slots=True)
class Obj:
    """A public name: its kind, and what the kind carries. `target` is where a re-exported name is
    defined; `deprecated` is the library's own message, `""` for a notice with none; `trivial` a
    function whose body is a stub."""

    path: str
    kind: str
    params: tuple[Param, ...] | None = None
    bases: tuple[str, ...] = ()
    deprecated: str | None = None
    target: str | None = None
    value: str | None = None
    trivial: bool = False


@dataclass(frozen=True, slots=True)
class Surface:
    module: str
    objects: Mapping[str, Obj] = field(default_factory=dict)
    truncated: bool = False

    def relative(self) -> dict[str, Obj]:
        """The objects by path below the module, so two releases of a module that moved compare."""
        prefix = f"{self.module}."
        return {
            path.removeprefix(prefix): one
            for path, one in self.objects.items()
            if path.startswith(prefix)
        }


def read(root: Path, module: str, *, timeout_s: float = TIMEOUT_S) -> Surface:
    """The public API of `module` under `root`. Raises `SurfaceError`."""
    environment = {name: os.environ[name] for name in _KEPT if name in os.environ}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    with tempfile.TemporaryDirectory(prefix="obelize-surface-") as empty:
        try:
            done = subprocess.run(
                [sys.executable, "-P", "-m", "obelize.apidiff", str(root), module],
                cwd=empty,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=timeout_s,
                env=environment,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise SurfaceError(f"reading {module} took more than {timeout_s:g} s") from error
    try:
        document = json.loads(done.stdout)
    except (ValueError, RecursionError) as error:
        tail = done.stderr.decode("utf-8", "replace").strip().splitlines()[-1:]
        raise SurfaceError(
            f"reading {module} failed ({done.returncode}): {' '.join(tail)}"
        ) from error
    if not isinstance(document, dict) or not isinstance(document.get("objects"), dict):
        reason = document.get("error") if isinstance(document, dict) else None
        raise SurfaceError(f"reading {module} failed: {reason or 'no document'}")
    return Surface(module, _objects(document["objects"]), bool(document.get("truncated")))


def _objects(raw: dict[str, dict[str, Any]]) -> dict[str, Obj]:
    found: dict[str, Obj] = {}
    for path, entry in raw.items():
        params = entry.get("params")
        found[path] = Obj(
            path=path,
            kind=entry.get("kind", "attribute"),
            params=None
            if params is None
            else tuple(
                Param(one["name"], one["kind"], one.get("default"), bool(one.get("required")))
                for one in params
            ),
            bases=tuple(entry.get("bases") or ()),
            deprecated=entry.get("deprecated"),
            target=entry.get("target"),
            value=entry.get("value"),
            trivial=bool(entry.get("trivial")),
        )
    return found


def modules(root: Path) -> tuple[str, ...]:
    """The top-level modules the unpacked source holds: packages and single files, below `root`
    or below its `src/`. What a release ships beside them (tests, docs, examples) is not one."""
    base = root / "src" if (root / "src").is_dir() else root
    names = [
        path.relative_to(base).as_posix()
        for path in base.rglob("*")
        if path.is_file() and path.suffix in {".py", ".pyi"}
    ]
    kept = [name for name in names if name.split("/")[0] not in _NOT_MODULES]
    return tuple(sorted(packages(kept)))


__all__ = ["Obj", "Param", "Surface", "SurfaceError", "modules", "read"]

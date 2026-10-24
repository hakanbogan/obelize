"""What `setuptools/pkg-resources-to-importlib` says of pkg_resources, read from setuptools 81.0.0,
the last release to ship it, beside the standard library; and that 82.0.0 does not.

Neither can share an environment with the setuptools the unit tests may import, so each runs in a
clean one, by hand. Standard library only, so nothing but setuptools is installed. It names each
claim that does not hold and exits 1 if there is one.

    uv run --isolated --no-project --python 3.12 --with setuptools==81.0.0 \
        python -I tests/packs/pkg_resources_check.py
    uv run --isolated --no-project --python 3.12 --with setuptools==82.0.0 \
        python -I tests/packs/pkg_resources_check.py
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.resources
import re
import sys
import warnings
from pathlib import Path
from typing import Any

PACK = (
    Path(__file__).resolve().parents[2] / "src/obelize/packs/setuptools/pkg-resources-to-importlib"
)
NAMES = re.findall(
    r"^    - pkg_resources\.(\w+)$", (PACK / "pack.yaml").read_text(encoding="utf-8"), re.MULTILINE
)
failures: list[str] = []


def claim(holds: bool, text: str) -> None:
    if not holds:
        failures.append(text)


def raised(call: Any, *args: str) -> type[BaseException] | None:
    try:
        call(*args)
    except Exception as error:
        return type(error)
    return None


try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pkg_resources: Any = importlib.import_module("pkg_resources")
except ModuleNotFoundError:
    # The release that removed it: the pack's `from.version` ends below this one.
    claim(importlib.metadata.version("setuptools").startswith("8"), "pkg_resources is missing")
    sys.exit(0 if not failures else 1)

claim(importlib.metadata.version("setuptools") == "81.0.0", "run this on setuptools 81.0.0")
claim(bool(NAMES), "no name was read from the pack")
for name in NAMES:
    claim(hasattr(pkg_resources, name), f"pkg_resources.{name} is not defined")

missing = "a-distribution-nobody-installed"
old, new = (
    raised(pkg_resources.get_distribution, missing),
    raised(importlib.metadata.version, missing),
)
claim(old is pkg_resources.DistributionNotFound, "get_distribution raises DistributionNotFound")
claim(new is importlib.metadata.PackageNotFoundError, "version raises PackageNotFoundError")
claim(not issubclass(importlib.metadata.PackageNotFoundError, old or object), "one error class")

# A requirement string is a name to one and not to the other.
claim(
    pkg_resources.get_distribution("setuptools>=1").version == "81.0.0",
    "get_distribution reads 'x>=1'",
)
claim(
    raised(importlib.metadata.version, "setuptools>=1") is importlib.metadata.PackageNotFoundError,
    "version does not read 'x>=1'",
)
claim(
    raised(pkg_resources.get_distribution, "setuptools>=1000") is pkg_resources.VersionConflict,
    "get_distribution checks the range",
)

# Entry points: the object the pack says is another.
(old_entry,) = list(pkg_resources.iter_entry_points("console_scripts"))[:1] or [None]
new_entry = next(iter(importlib.metadata.entry_points(group="console_scripts")), None)
if old_entry is not None and new_entry is not None:
    for member in ("require", "resolve", "dist"):
        claim(hasattr(old_entry, member), f"a pkg_resources entry point has {member}")
    for member in ("require", "resolve"):
        claim(not hasattr(new_entry, member), f"an importlib.metadata entry point lacks {member}")
    for member in ("dist", "value", "group", "name", "load"):
        claim(hasattr(new_entry, member), f"an importlib.metadata entry point has {member}")

# Resources: a path in the file system, against a Traversable.
path = pkg_resources.resource_filename("setuptools", "__init__.py")
traversable = importlib.resources.files("setuptools") / "__init__.py"
claim(isinstance(path, str), "resource_filename returns a str")
claim(not isinstance(traversable, str), "files() returns a Traversable")
claim(
    pkg_resources.resource_string("setuptools", "__init__.py") == traversable.read_bytes(),
    "resource_string is read_bytes",
)

for failure in failures:
    print(failure)
sys.exit(1 if failures else 0)

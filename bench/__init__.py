"""The measurement scripts; each runs from the repository root as a module."""

from pathlib import Path
from typing import Any

import yaml


def read_yaml(path: Path) -> Any:
    """What `yaml.safe_load` reads from `path`, through libyaml where the build has it."""
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    return yaml.load(path.read_text(encoding="utf-8"), Loader=loader)  # noqa: S506 - safe loader

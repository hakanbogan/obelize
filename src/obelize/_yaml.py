"""YAML reading for `.obelize.yml` and `pack.yaml`, neither of which obelize writes.

`SafeLoader` only, so a file cannot construct Python objects, and a duplicate key is an error
instead of the last one silently winning. Errors carry a line but no file name; the caller adds it.
"""

from __future__ import annotations

from typing import Any

import yaml


class DuplicateKeyError(ValueError):
    """A mapping that declares the same key twice, and where."""

    def __init__(self, key: str, line: int) -> None:
        super().__init__(f"duplicate key {key!r}")
        self.key = key
        # 1-based.
        self.line = line


class _Loader(yaml.SafeLoader):
    """`yaml.SafeLoader`, minus the rule that the last duplicate key wins."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: list[str] = []
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            # Non-string keys are left to the model, which reports them as unknown.
            if isinstance(key, str):
                if key in seen:
                    raise DuplicateKeyError(key, key_node.start_mark.line + 1)
                seen.append(key)
        return super().construct_mapping(node, deep)


def parse(text: str) -> Any:
    """Parse one YAML document. Raises `DuplicateKeyError` or `yaml.YAMLError`."""
    return yaml.load(text, Loader=_Loader)  # noqa: S506 -- _Loader derives from SafeLoader


def where(error: yaml.YAMLError) -> tuple[int, int, str] | None:
    """`(line, column, problem)`, 1-based, or None when the error carries no position."""
    mark = getattr(error, "problem_mark", None)
    problem = getattr(error, "problem", None)
    if mark is None or problem is None:
        return None
    return mark.line + 1, mark.column + 1, str(problem)


__all__ = ["DuplicateKeyError", "parse", "where"]

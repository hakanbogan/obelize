"""YAML reading for `.obelize.yml` and `pack.yaml`, neither of which obelize writes.

`SafeLoader` only, so a file cannot construct Python objects, and a duplicate key is an error
instead of the last one silently winning. A set is refused: it has no order. Errors carry a line but
no file name; the caller adds it.
"""

from __future__ import annotations

from typing import Any, NoReturn

import yaml

_STR = "tag:yaml.org,2002:str"

# Far above any real configuration or pack (the bundled packs are under 50 KiB). Readers take one
# byte more, which is how they tell a longer file.
MAX_BYTES = 1 << 20


class DuplicateKeyError(ValueError):
    """A mapping that declares the same key twice, and where."""

    def __init__(self, key: str, line: int) -> None:
        super().__init__(f"duplicate key {key!r}")
        self.key = key
        # 1-based.
        self.line = line


class _Loader(yaml.SafeLoader):
    """`yaml.SafeLoader`, minus the rule that the last duplicate key wins, and without sets."""

    def compose_mapping_node(self, anchor: Any) -> yaml.MappingNode:
        # Composed, not constructed, so a `<<` merge is still flattened and an explicit key that
        # overrides a merged one is no duplicate. Non-string keys are left to the model, which
        # reports them as unknown.
        node = super().compose_mapping_node(anchor)
        seen: set[str] = set()
        for key_node, _ in node.value:
            if isinstance(key_node, yaml.ScalarNode) and key_node.tag == _STR:
                if key_node.value in seen:
                    raise DuplicateKeyError(key_node.value, key_node.start_mark.line + 1)
                seen.add(key_node.value)
        return node

    def construct_object(self, node: yaml.Node, deep: bool = False) -> Any:
        try:
            return super().construct_object(node, deep=deep)
        except (ValueError, LookupError, AttributeError) as error:
            # A date the calendar refuses, an integer over the interpreter's digit limit, or an
            # explicit `!!bool`, `!!int`, `!!float` or `!!timestamp` on a scalar that is none of
            # them, which the constructors answer with a KeyError, IndexError or AttributeError.
            problem = (
                str(error)
                if isinstance(error, ValueError)
                else f"not a valid {node.tag.rpartition(':')[2]}"
            )
            raise yaml.constructor.ConstructorError(None, None, problem, node.start_mark) from error


def _set(loader: yaml.SafeLoader, node: yaml.Node) -> NoReturn:
    # Pydantic would read it in hash order, which changes between runs.
    raise yaml.constructor.ConstructorError(
        None, None, "a set has no order; write a list", node.start_mark
    )


_Loader.add_constructor("tag:yaml.org,2002:set", _set)


def parse(text: str) -> Any:
    """Parse one YAML document. Raises `DuplicateKeyError` or `yaml.YAMLError`."""
    try:
        return yaml.load(text, Loader=_Loader)  # noqa: S506 -- _Loader derives from SafeLoader
    except RecursionError as error:
        raise yaml.YAMLError("nested too deeply to read") from error


def where(error: yaml.YAMLError) -> tuple[int, int, str] | None:
    """`(line, column, problem)`, 1-based, or None when the error carries no position."""
    mark = getattr(error, "problem_mark", None)
    problem = getattr(error, "problem", None)
    if mark is None or problem is None:
        return None
    return mark.line + 1, mark.column + 1, str(problem)


__all__ = ["MAX_BYTES", "DuplicateKeyError", "parse", "where"]

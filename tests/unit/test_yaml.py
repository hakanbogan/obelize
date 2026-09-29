"""The YAML reader behind `.obelize.yml` and `pack.yaml`: duplicate keys and safe loading."""

from __future__ import annotations

import pytest
import yaml

from obelize import _yaml


def test_a_mapping_is_read_as_data() -> None:
    assert _yaml.parse("a: 1\nb: [2, 3]\n") == {"a": 1, "b": [2, 3]}
    assert _yaml.parse("") is None
    assert _yaml.parse("# only a comment\n") is None


def test_a_duplicate_key_is_an_error_and_says_where() -> None:
    """YAML keeps the second and discards the first without a word."""
    with pytest.raises(_yaml.DuplicateKeyError) as excinfo:
        _yaml.parse("a: 1\nb: 2\na: 3\n")
    assert excinfo.value.key == "a"
    assert excinfo.value.line == 3
    assert "duplicate key 'a'" in str(excinfo.value)


def test_a_duplicate_key_is_caught_inside_a_nested_mapping() -> None:
    with pytest.raises(_yaml.DuplicateKeyError) as excinfo:
        _yaml.parse("outer:\n  inner: 1\n  inner: 2\n")
    assert (excinfo.value.key, excinfo.value.line) == ("inner", 3)


def test_only_string_keys_are_tracked() -> None:
    """Tracking others would reimplement YAML's key equality; the model reports them as unknown."""
    assert _yaml.parse("1: one\n2.5: half\nnull: nothing\n") == {
        1: "one",
        2.5: "half",
        None: "nothing",
    }
    # The deliberate limit: a repeated non-string key is not caught, and YAML's answer stands.
    assert _yaml.parse("1: one\n1: two\n") == {1: "two"}


def test_a_python_object_tag_is_refused_rather_than_constructed() -> None:
    """`SafeLoader` is what keeps a configuration file from executing code."""
    with pytest.raises(yaml.YAMLError, match="could not determine a constructor"):
        _yaml.parse("!!python/object/apply:os.system ['echo hi']\n")


def test_a_parse_failure_is_located_when_the_parser_knows_where() -> None:
    with pytest.raises(yaml.YAMLError) as excinfo:
        _yaml.parse("a: [1, 2\n")
    located = _yaml.where(excinfo.value)
    assert located is not None
    line, column, problem = located
    assert (line, column) == (2, 1)
    assert "expected" in problem


def test_a_parse_failure_with_no_position_is_reported_as_having_none() -> None:
    """A reader error carries no mark; formatting one would print parser state, not the file's."""
    with pytest.raises(yaml.YAMLError) as excinfo:
        _yaml.parse("a: \x01\n")
    assert _yaml.where(excinfo.value) is None

"""The YAML reader behind `.obelize.yml` and `pack.yaml`: keys, merges, sets, safe loading."""

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


def test_a_merge_key_is_flattened_as_plain_yaml_does() -> None:
    assert _yaml.parse("base: &b {a: 1}\nx:\n  <<: *b\n  c: 2\n") == {
        "base": {"a": 1},
        "x": {"a": 1, "c": 2},
    }


def test_an_explicit_key_overriding_a_merged_one_is_no_duplicate() -> None:
    """The merge is legal YAML for exactly this."""
    assert _yaml.parse("base: &b {a: 1}\nx:\n  <<: *b\n  a: 9\n")["x"] == {"a": 9}


def test_a_duplicate_beside_a_merge_key_is_still_caught() -> None:
    with pytest.raises(_yaml.DuplicateKeyError) as excinfo:
        _yaml.parse("base: &b {a: 1}\nx:\n  <<: *b\n  c: 1\n  c: 2\n")
    assert (excinfo.value.key, excinfo.value.line) == ("c", 5)


def test_two_spellings_of_one_string_key_are_a_duplicate() -> None:
    """Compared as the strings they construct to, so quotes and an explicit tag change nothing."""
    with pytest.raises(_yaml.DuplicateKeyError, match="duplicate key 'a'"):
        _yaml.parse("a: 1\n'a': 2\n")
    with pytest.raises(_yaml.DuplicateKeyError, match="duplicate key '1'"):
        _yaml.parse("'1': 1\n!!str 1: 2\n")


def test_a_key_that_is_a_collection_is_left_to_the_constructor() -> None:
    with pytest.raises(yaml.YAMLError, match="unhashable"):
        _yaml.parse("? [a, b]\n: 1\n")


def test_a_set_is_refused_because_it_has_no_order() -> None:
    """Read as a Python set it would reach the model in hash order, which changes per process."""
    with pytest.raises(yaml.YAMLError, match="a set has no order; write a list") as excinfo:
        _yaml.parse("exclude: !!set {b, a}\n")
    assert _yaml.where(excinfo.value) == (1, 10, "a set has no order; write a list")


@pytest.mark.parametrize(
    ("text", "said"),
    [
        ("a: 2020-13-45\n", "month must be in 1..12"),
        ("a: !!int abc\n", "invalid literal for int"),
        ("a: !!bool maybe\n", "not a valid bool"),
        ("a: !!int ''\n", "not a valid int"),
        ("a: !!timestamp foo\n", "not a valid timestamp"),
    ],
    ids=["impossible-date", "bad-int", "bad-bool", "empty-int", "bad-timestamp"],
)
def test_a_scalar_the_constructor_refuses_is_a_yaml_error_at_its_position(
    text: str, said: str
) -> None:
    """The constructors answer with a ValueError, KeyError, IndexError or AttributeError."""
    with pytest.raises(yaml.YAMLError, match=said) as excinfo:
        _yaml.parse(text)
    located = _yaml.where(excinfo.value)
    assert located is not None
    assert located[:2] == (1, 4)


def test_a_document_nested_past_the_recursion_limit_is_a_yaml_error() -> None:
    with pytest.raises(yaml.YAMLError, match="nested too deeply to read") as excinfo:
        _yaml.parse("a: " + "[" * 5000)
    assert _yaml.where(excinfo.value) is None

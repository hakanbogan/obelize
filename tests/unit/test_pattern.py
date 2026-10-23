"""The templates of `rewrite_pattern`: what can be written, what a call is compared by, what is
built."""

from __future__ import annotations

import ast
import re

import libcst as cst
import pytest
from libcst.metadata import MetadataWrapper, ParentNodeProvider

from obelize import pattern

MODULE = cst.Module(body=[])


def code(node: cst.CSTNode) -> str:
    return MODULE.code_for_node(node)


def call(text: str) -> cst.Call:
    return cst.ensure_type(cst.parse_expression(text), cst.Call)


def bound(before: str, text: str, *, spelled: bool = False) -> dict[str, str] | None:
    found = pattern.match(pattern.parse(before), call(text), spelled=spelled)
    return None if found is None else {name: code(node) for name, node in found.items()}


@pytest.mark.parametrize(
    ("text", "says"),
    [
        ("x" * 2001, "over the 2000"),
        ("lib.f(obelize_meta_x)", "reserves"),
        ("lib.f(", "does not parse"),
        ("lambda: 1", "holds a Lambda"),
        ("lib.f(a + b)", "holds a BinaryOperation"),
        ("lib.f(f'{a}')", "holds a FormattedString"),
        ("lib.f(*$rest)", "`*` or `**` argument"),
        ("lib.f(**$rest)", "`*` or `**` argument"),
        ("lib.f($key=1)", "names a keyword with a metavariable"),
        ("lib.$name(1)", "names an attribute with a metavariable"),
        ("lib.f([*$a])", "holds a StarredElement"),
        ("lib.f({**$a})", "`**` entry"),
        ("lib.f(a if b else c)", "holds a IfExp"),
        ("lib.f($a)[1:2]", "not one index"),
        ("lib.f($a)[1, 2]", "not one index"),
        ("lib.f($a[*$b])", "starred index"),
        ("lib.f(n=$a, n=$b)", "names a keyword twice"),
        ("__import__('os').system($a)", "__import__, a name that reaches the interpreter"),
        ("lib.f($a).__class__", "__class__, a name that reaches the interpreter"),
        ("lib.f('$HOME')", "holds a $name inside a string"),
        ("lib.f('a' '$n')", "holds a ConcatenatedString"),
        (" lib.f(1)", "does not parse"),
        ("[" * 200 + "$n" + "]" * 200, "nested"),
        ("-" * 330 + "$n", "nested too deeply"),
        ("lib.f(" + "f(" * 500 + "$n" + ")" * 500 + ")", "nested"),
    ],
)
def test_a_template_that_cannot_be_read_is_refused_with_why(text: str, says: str) -> None:
    with pytest.raises(pattern.TemplateError, match=re.escape(says)):
        pattern.parse(text)


def test_a_template_nests_as_deep_as_the_limit_and_no_deeper() -> None:
    """Counted in `ast`'s tree: each operator is a level, with the name and its context below."""
    assert pattern.parse("-" * (pattern.DEPTH - 2) + "$n").names == {"n"}
    with pytest.raises(pattern.TemplateError, match="nested too deeply"):
        pattern.parse("-" * (pattern.DEPTH - 1) + "$n")


@pytest.mark.parametrize("error", [RecursionError, MemoryError])
def test_a_template_ast_cannot_build_a_tree_for_is_too_deep_to_read(
    monkeypatch: pytest.MonkeyPatch, error: type[Exception]
) -> None:
    """3.14 compiles a chain of terms that `ast` cannot turn into objects."""

    def overrun(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(ast, "parse", overrun)
    with pytest.raises(pattern.TemplateError, match="nested too deeply"):
        pattern.parse("lib.f(1)")


def test_a_template_is_the_expression_and_the_metavariables_in_it() -> None:
    found = pattern.parse("lib.f($a, key=[$b, 1], other={'k': -$c}, sub=$d[0], t=(1, $a))")
    assert found.names == {"a", "b", "c", "d"}
    assert dict(found.uses) == {"a": 2, "b": 1, "c": 1, "d": 1}
    assert pattern.parse("lib.f(1)").names == frozenset()


def test_a_template_says_which_attributes_it_reads_and_whether_it_holds_a_string() -> None:
    found = pattern.parse("$m.go(lib.New('x').size, 1)")
    assert (found.attributes, found.strings) == (frozenset({"go", "New", "size"}), True)
    plain = pattern.parse("lib.f($a, 2)")
    assert (plain.attributes, plain.strings) == (frozenset({"f"}), False)


@pytest.mark.parametrize(
    ("text", "symbol", "receiver", "where"),
    [
        ("lib.f($a)", "lib.f", None, {}),
        ("pkg.mod.f($a)", "pkg.mod.f", None, {}),
        ("$m.f($a)", "pkg.Model.f", "m", {"m": "pkg.Model"}),
    ],
)
def test_the_name_a_pattern_is_found_by_is_a_written_name_or_a_member_of_a_class(
    text: str, symbol: str, receiver: str | None, where: dict[str, str]
) -> None:
    assert pattern.anchor(pattern.parse(text), where) == pattern.Anchor(symbol, receiver)


@pytest.mark.parametrize(
    ("text", "where", "says"),
    [
        ("lib.f", {}, "is no call"),
        ("$m.f($a)", {}, "whose class `where` does not name"),
        ("f($a)", {}, "not a qualified name"),
        ("$m.sub.f($a)", {"m": "pkg.Model"}, "not a qualified name"),
        ("make($a).f($b)", {}, "not a qualified name"),
    ],
)
def test_a_pattern_that_is_found_by_nothing_is_refused(
    text: str, where: dict[str, str], says: str
) -> None:
    with pytest.raises(pattern.TemplateError, match=re.escape(says)):
        pattern.anchor(pattern.parse(text), where)


@pytest.mark.parametrize(
    ("text", "names"),
    [
        ("lib.New($a).go($b)", {"lib.New"}),
        ("$m.model_dump(exclude=$e)", set()),
        ("str($a)", set()),
        ("list(map(lib.f, $a))", {"lib.f"}),
        ("make($a).thing", {"make"}),
        ("table[lib.key]", {"table", "lib.key"}),
        (
            "($a, lib.x, [lib.y, 1], {lib.z: lib.w}, -lib.v)",
            {"lib.x", "lib.y", "lib.z", "lib.w", "lib.v"},
        ),
        ("f(1)(2)", {"f"}),
        ("$a[0]", set()),
        ("eval($a)", {"eval"}),
        ("open($a).read()", {"open"}),
        ("getattr($a, 'x')", {"getattr"}),
    ],
)
def test_the_names_a_template_spells_out_are_the_chains_whose_root_is_no_metavariable_or_builtin(
    text: str, names: set[str]
) -> None:
    assert pattern.new_names(pattern.parse(text)) == names


@pytest.mark.parametrize(
    ("before", "text", "found"),
    [
        ("lib.f($a, $b)", "lib.f(1, x)", {"a": "1", "b": "x"}),
        ("lib.f($a, $b)", "other.f(1, x)", {"a": "1", "b": "x"}),
        ("lib.f($a, key=$k)", "lib.f(x, key=y)", {"a": "x", "k": "y"}),
        ("lib.f(a=$a, b=$b)", "lib.f(b=2, a=1)", {"a": "1", "b": "2"}),
        ("lib.f($a, $a)", "lib.f(x,  x)", {"a": "x"}),
        ("lib.f(1, 2.5, 'x', name)", 'lib.f(1, 2.5, "x", name)', {}),
        ("lib.f(a.b.c)", "lib.f(a.b.c)", {}),
        ("lib.f(g($a, k=2))", "lib.f(g(1, k=2))", {"a": "1"}),
        (
            "lib.f(($a, 2), [$b], {'k': $c})",
            "lib.f((1, 2), [3], {'k': 4})",
            {"a": "1", "b": "3", "c": "4"},
        ),
        ("lib.f($a[0], -$b)", "lib.f(rows[0], -n)", {"a": "rows", "b": "n"}),
        ("lib.f($a)", "lib.f(x + 1)", {"a": "x + 1"}),
        ("lib.f()", "lib.f()", {}),
    ],
)
def test_a_call_has_the_shape_of_a_template_by_form_and_not_by_spelling(
    before: str, text: str, found: dict[str, str]
) -> None:
    assert bound(before, text) == found


@pytest.mark.parametrize(
    ("before", "text"),
    [
        ("lib.f($a, $b)", "lib.f(1)"),
        ("lib.f($a)", "lib.f(1, 2)"),
        ("lib.f($a)", "lib.f(*rest)"),
        ("lib.f($a)", "lib.f(**rest)"),
        ("lib.f($a, key=$k)", "lib.f(1)"),
        ("lib.f($a, key=$k)", "lib.f(1, other=2)"),
        ("lib.f($a, key=$k)", "lib.f(1, key=2, more=3)"),
        ("lib.f($a, $a)", "lib.f(x, y)"),
        ("lib.f(1)", "lib.f(2)"),
        ("lib.f(1.5)", "lib.f(2.5)"),
        ("lib.f('x')", "lib.f('y')"),
        ("lib.f(name)", "lib.f(other)"),
        ("lib.f(a.b)", "lib.f(a.c)"),
        ("lib.f(a.b)", "lib.f(a)"),
        ("lib.f(g($a))", "lib.f(h(1))"),
        ("lib.f(g($a))", "lib.f(g(1, 2))"),
        ("lib.f(($a, 2))", "lib.f((1, 3))"),
        ("lib.f(($a, 2))", "lib.f((1, 2, 3))"),
        ("lib.f(($a, 2))", "lib.f([1, 2])"),
        ("lib.f([$a])", "lib.f([*xs])"),
        ("lib.f({'k': $c})", "lib.f({'k': 1, 'j': 2})"),
        ("lib.f({'k': $c})", "lib.f({**spread})"),
        ("lib.f({'k': $c})", "lib.f({'j': 1})"),
        ("lib.f($a[0])", "lib.f(rows[1])"),
        ("lib.f($a[0])", "lib.f(rows[1:2])"),
        ("lib.f($a[0])", "lib.f(rows)"),
        ("lib.f(-$a)", "lib.f(+n)"),
        ("lib.f(-$a)", "lib.f(n)"),
    ],
)
def test_a_call_of_another_shape_is_none(before: str, text: str) -> None:
    assert bound(before, text) is None


@pytest.mark.parametrize(
    ("before", "text", "found"),
    [
        ("$m.dict($e)", "self.child.dict(1)", {"m": "self.child", "e": "1"}),
        ("$m.dict()", "(a + b).dict()", {"m": "(a + b)"}),
    ],
)
def test_a_member_call_binds_what_it_is_made_on(
    before: str, text: str, found: dict[str, str]
) -> None:
    assert bound(before, text, spelled=True) == found


@pytest.mark.parametrize("text", ["other()", "x.load(1)", "dict(1)"])
def test_a_member_call_of_another_member_or_no_member_is_none(text: str) -> None:
    assert bound("$m.dict($e)", text, spelled=True) is None


def built(after: str, before: str, text: str, spelled: dict[str, str] | None = None) -> str:
    found = pattern.match(pattern.parse(before), call(text), spelled=False)
    assert found is not None
    names = {name: cst.parse_expression(source) for name, source in (spelled or {}).items()}
    return code(pattern.build(pattern.parse(after), found, names))


def test_the_new_expression_is_built_over_what_was_bound() -> None:
    assert (
        built("lib.New($t).go($v, k=1)", "lib.f($t, $v)", "lib.f(A, b)") == "lib.New(A).go(b, k=1)"
    )


@pytest.mark.parametrize(
    ("text", "written"),
    [
        ("x.y", "x.y.model_dump()"),
        ("a + b", "(a + b).model_dump()"),
        ("(a + b)", "(a + b).model_dump()"),
        ("make()", "make().model_dump()"),
        ("rows[0]", "rows[0].model_dump()"),
        ("(1, 2)", "(1, 2).model_dump()"),
        ("-n", "(-n).model_dump()"),
        ("rows", "rows.model_dump()"),
    ],
)
def test_an_expression_put_before_a_dot_is_in_parentheses_unless_it_is_as_tight_as_a_name(
    text: str, written: str
) -> None:
    assert built("$m.model_dump()", "lib.f($m)", f"lib.f({text})") == written


def test_an_expression_put_where_a_call_or_a_subscript_is_read_gets_the_same_care() -> None:
    assert built("$f($a)", "lib.f($f, $a)", "lib.f(g, 1)") == "g(1)"
    assert built("$t[0]", "lib.f($t)", "lib.f(a + b)") == "(a + b)[0]"
    assert built("$f(1)", "lib.f($f)", "lib.f(g)") == "g(1)"


def test_a_name_spelled_beside_the_old_one_takes_the_files_own_spelling_of_where_it_lives() -> None:
    assert built("lib.New($a)", "lib.f($a)", "pd.f(1)", {"lib": "pd"}) == "pd.New(1)"
    assert built("pkg.sub.New($a)", "pkg.sub.f($a)", "p.f(1)", {"pkg.sub": "p"}) == "p.New(1)"
    assert built("lib.New($a).go()", "lib.f($a)", "x.y.f(1)", {"lib": "x.y"}) == "x.y.New(1).go()"


@pytest.mark.parametrize(
    ("text", "pure"),
    [
        ("x", True),
        ("x.y.z", True),
        ("1", True),
        ("2.5", True),
        ("'s'", True),
        ("-1", True),
        ("-x", False),
        ("f(x)", False),
        ("x.y()", False),
        ("[x]", False),
        ("a + b", False),
        ("next(it)", False),
    ],
)
def test_an_expression_is_pure_when_running_it_twice_is_running_it_once(
    text: str, pure: bool
) -> None:
    assert pattern.pure(cst.parse_expression(text)) is pure


def test_an_expression_written_twice_is_one_only_if_it_is_pure() -> None:
    assert bound("lib.f($a, $a)", "lib.f(x.y, x.y)") == {"a": "x.y"}
    assert bound("lib.f($a, $a)", "lib.f(next(it), next(it))") is None


@pytest.mark.parametrize(
    ("text", "held"),
    [
        ("i for i in z", "(i for i in z)"),
        ("(i for i in z)", "(i for i in z)"),
        ("y := 1", "(y := 1)"),
        ("a + b", "a + b"),
    ],
)
def test_an_expression_kept_for_another_place_keeps_what_held_it_together(
    text: str, held: str
) -> None:
    assert bound("lib.f($a)", f"lib.f({text})") == {"a": held}


def test_a_starred_index_is_no_index_a_template_matches() -> None:
    assert bound("lib.f($a[$i])", "lib.f(rows[0])") == {"a": "rows", "i": "0"}
    assert bound("lib.f($a[$i])", "lib.f(rows[*b])") is None


@pytest.mark.parametrize(
    ("after", "text", "written"),
    [
        ("-$n", "lib.f(a + b)", "-(a + b)"),
        ("not $n", "lib.f(a and b)", "not (a and b)"),
        ("-$n", "lib.f(a)", "-a"),
    ],
)
def test_the_operand_of_a_unary_operator_is_in_parentheses_unless_it_is_tight(
    after: str, text: str, written: str
) -> None:
    assert built(after, "lib.f($n)", text) == written


def put(parent: str, text: str) -> str:
    """The statement `parent` (`{}` is the call `lib.old(1)`) with the call replaced by what
    `pattern.place` makes of the expression `text` there."""
    module = cst.parse_module(parent.replace("{}", "lib.old(1)") + "\n")
    parents = MetadataWrapper(module, unsafe_skip_copy=True).resolve(ParentNodeProvider)
    call = next(
        node for node in parents if isinstance(node, cst.Call) and dotted_of(node) == "lib.old"
    )
    placed = pattern.place(cst.parse_expression(text), parents[call])
    return code(module.deep_replace(call, placed)).strip()


def dotted_of(call: cst.Call) -> str:
    return pattern.dotted(call.func)


@pytest.mark.parametrize(
    ("text", "parent", "written"),
    [
        ("a", "x.y = {}", "x.y = a"),
        ("a or b", "x = {}", "x = a or b"),
        ("a or b", "{}.strip()", "(a or b).strip()"),
        ("a + b", "y = 3 * {}", "y = 3 * (a + b)"),
        ("-n", "def f():\n    return {}", "def f():\n    return -n"),
        ("(a or b)", "{}.strip()", "(a or b).strip()"),
        ("a, 1", "f({})", "f((a, 1))"),
        ("a, 1", "x = {}", "x = a, 1"),
        ("a, 1", "x = [{}]", "x = [(a, 1)]"),
        ("lib.f(a)", "{}.real", "lib.f(a).real"),
    ],
)
def test_a_new_expression_is_in_parentheses_where_the_call_stood_unless_it_is_tight(
    text: str, parent: str, written: str
) -> None:
    assert put(parent, text) == written


def test_the_multi_line_new_expression_is_in_parentheses_even_where_one_line_would_not_be() -> None:
    wide = cst.parse_expression("(a\n + b)").with_changes(lpar=[], rpar=[])
    module = cst.parse_module("x = lib.old(1)\n")
    parents = MetadataWrapper(module, unsafe_skip_copy=True).resolve(ParentNodeProvider)
    call = next(node for node in parents if isinstance(node, cst.Call))
    assert code(pattern.place(wide, parents[call])).startswith("(")

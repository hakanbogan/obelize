"""`transforms/tree.py` asked directly, for contracts no rule's output would reveal."""

from __future__ import annotations

import acme
import libcst as cst

from obelize.impact import planner
from obelize.scan import analysis, parse
from obelize.transforms import base
from obelize.transforms.tree import Tree


def tree_over(source: str) -> tuple[Tree, cst.Module]:
    read = parse.gates("probe.py", source.encode("utf-8"))
    assert read.module is not None, read
    plan = planner.plan(analysis.analyse(read, acme.SPEC), acme.SPEC)
    context = base.RuleContext.build(plan, read.module, acme.SPEC)
    return Tree(context), read.module


def only_call(module: cst.Module) -> cst.Call:
    found: list[cst.Call] = []

    class Collect(cst.CSTVisitor):
        def visit_Call(self, node: cst.Call) -> None:  # noqa: N802 - libcst dispatch
            found.append(node)

    module.visit(Collect())
    assert len(found) == 1, found
    return found[0]


def test_a_call_the_author_already_split_has_no_line_to_measure() -> None:
    """Not a difference of columns on two lines, which would silently corrupt a caller's sums."""
    tree, module = tree_over("import acme.sdk as sdk\n\nsdk.configure(\n    key='k',\n)\n")
    assert tree.around(only_call(module)) == 0


def test_a_call_on_one_line_is_measured_with_everything_else_on_it() -> None:
    tree, module = tree_over(
        "import acme.sdk as sdk\n\n\ndef a():\n    return sdk.configure(key='k')  # note\n"
    )
    # The four spaces of indent are counted separately.
    assert tree.around(only_call(module)) == len("return ") + len("  # note")


def test_the_statement_a_call_belongs_to_may_be_a_compound_header() -> None:
    """`for x in <call>:` is not part of any small statement at all."""
    tree, module = tree_over(
        "import acme.sdk as sdk\n\n\ndef a():\n    for x in sdk.configure(key='k'):\n"
        "        yield x\n"
    )
    call = only_call(module)
    assert isinstance(tree.statement_of(call), cst.For)
    assert tree.line_of(call) is None
    assert tree.indent(call) == "    "
    assert tree.around(call) == len("for x in ") + len(":")


def test_the_innermost_call_that_starts_at_a_position_is_the_one_kept() -> None:
    """Two calls start at one line and column; the scanner found the inner one."""
    tree, module = tree_over("import acme.sdk as sdk\n\nsdk.configure(key='k')(1)\n")

    class Outer(cst.CSTVisitor):
        found: cst.Call | None = None

        def visit_Call(self, node: cst.Call) -> None:  # noqa: N802 - libcst dispatch
            if isinstance(node.func, cst.Call) and self.found is None:
                self.found = node

    outer = Outer()
    module.visit(outer)
    assert outer.found is not None
    inner = outer.found.func
    assert tree.call(tree.start(outer.found)) is inner

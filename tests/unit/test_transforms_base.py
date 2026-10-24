"""The rule protocol, the registry and the import plan, all resting on node identity.

`MetadataWrapper` deep-copies its module unless told not to, and a rule resolving metadata on a copy
reports its edits while silently writing nothing.
"""

from __future__ import annotations

import acme
import libcst as cst
from libcst.metadata import MetadataWrapper

from obelize.impact import planner
from obelize.packs import loader, schema
from obelize.scan import analysis, parse
from obelize.transforms import base, registry
from obelize.transforms.imports import ImportPlan, dotted, statement_for
from obelize.transforms.kinds.rename_import import RenameImport

SOURCE = "from acme.sdk.types import Config\n\nC = Config\n"


def context(source: str = SOURCE) -> base.RuleContext:
    read = parse.gates("probe.py", source.encode("utf-8"))
    assert read.module is not None
    plan = planner.plan(analysis.analyse(read, acme.SPEC), acme.SPEC)
    return base.RuleContext.build(plan, read.module, acme.SPEC)


def test_the_metadata_wrapper_is_built_over_the_module_and_not_over_a_copy() -> None:
    module = cst.parse_module(SOURCE)
    assert MetadataWrapper(module, unsafe_skip_copy=True).module is module
    assert MetadataWrapper(module).module is not module
    assert base.RuleContext.build(context().plan, module, acme.SPEC).wrapper.module is module


def test_a_copying_wrapper_reports_the_edits_and_writes_nothing() -> None:
    """Every edit is `auto`, but on nodes of a copied tree that `finish()` never sees."""
    read = parse.gates("probe.py", SOURCE.encode("utf-8"))
    assert read.module is not None
    copied = MetadataWrapper(read.module)
    wrong = base.RuleContext(
        path="probe.py",
        module=read.module,
        wrapper=copied,
        plan=planner.plan(analysis.analyse(read, acme.SPEC), acme.SPEC),
        spec=acme.SPEC,
        imports=ImportPlan(copied),
        rewrites=base.Rewrites(),
        layout=schema.Layout(),
        consumed=frozenset(),
        client_readers=frozenset(),
        client=base.ClientBinding(),
        imported_elsewhere=lambda name: False,
    )
    edits = RenameImport(acme.CHANGE).apply(wrong)
    assert [row.status for row in edits] == ["auto", "auto"]
    assert base.finish(wrong).code == SOURCE

    right = context()
    assert RenameImport(acme.CHANGE).apply(right)
    assert base.finish(right).code != SOURCE


def test_a_context_with_nothing_recorded_returns_the_file_it_was_given() -> None:
    built = context()
    assert base.finish(built).code == SOURCE


def test_rewrites_are_keyed_by_the_node_they_replace() -> None:
    rewrites = base.Rewrites()
    first, second = cst.Name("a"), cst.Name("a")
    replacement = cst.Name("b")
    rewrites.set(first, replacement)
    assert rewrites.get(first) is replacement
    assert rewrites.get(second) is None


def test_a_bail_carries_its_code_and_no_prose() -> None:
    error = base.BailError("alias_collision")
    assert error.reason == "alias_collision"
    assert str(error) == "alias_collision"


def test_a_name_is_handed_out_once_and_the_fallback_only_when_it_has_to_be() -> None:
    plan = context().imports
    assert plan.take("free") == "free"
    assert plan.take("free", "spare") == "spare"
    assert plan.take("free", "spare") is None


def test_a_released_name_is_free_again() -> None:
    plan = context().imports
    assert plan.take("Config") is None
    plan.release("Config")
    assert plan.take("Config") == "Config"


def test_a_binding_is_remembered_so_the_second_asker_gets_the_same_name() -> None:
    plan = context().imports
    assert plan.binding("acme.client.types") is None
    plan.bind("acme.client.types", "types")
    assert plan.binding("acme.client.types") == "types"


def test_an_unanchored_statement_is_left_alone() -> None:
    built = context()
    statement = built.module.body[0]
    assert isinstance(statement, cst.SimpleStatementLine)
    assert built.imports.lines_for(statement, statement) is None


def test_replace_says_what_a_statement_becomes_and_append_adds_to_it() -> None:
    built = context()
    statement = built.module.body[0]
    assert isinstance(statement, cst.SimpleStatementLine)
    built.imports.replace(statement, statement_for("acme.client", "client"))
    built.imports.replace(statement, statement_for("acme.client.types", "types"))
    built.imports.append(statement, statement_for("acme.client.wire", "wire"))
    lines = built.imports.lines_for(statement, statement)
    assert lines is not None
    assert [cst.Module(body=[line]).code for line in lines] == [
        "from acme.client import types\n",
        "from acme.client import wire\n",
    ]


def test_a_dotted_path_is_the_chain_libcst_wants() -> None:
    assert cst.Module(body=[]).code_for_node(dotted("a.b.c")) == "a.b.c"
    assert cst.Module(body=[]).code_for_node(dotted("a")) == "a"


def test_every_class_is_filed_under_the_kind_it_declares() -> None:
    """A kind in both tables would get a parsed file from one caller and a manifest from another."""
    assert all(kind == rule.kind for kind, rule in registry.RULES.items())
    assert all(kind == rule.kind for kind, rule in registry.MANIFEST_RULES.items())
    assert frozenset(registry.RULES) & frozenset(registry.MANIFEST_RULES) == frozenset()
    assert frozenset(registry.RULES) | frozenset(registry.MANIFEST_RULES) == registry.IMPLEMENTED
    assert registry.IMPLEMENTED == schema.CHANGE_KINDS


def test_a_kind_from_the_other_table_is_skipped_by_this_one() -> None:
    """`None` means "not a file's": a manifest is not parsed and its verdict is the repository's."""
    pack = loader.load("gemini/google-generativeai-to-google-genai").pack
    kinds = [change.kind for change in pack.changes]
    assert kinds.count("flag_only") > 1, "the pack no longer proves the split"
    assert [rule.kind for rule in registry.rules(pack)] == [
        "rename_import",
        "configure_to_client",
        "generative_model_calls",
        *["rewrite_call"] * 8,
        *["flag_only"] * 4,
    ]
    assert [rule.kind for rule in registry.manifest_rules(pack)] == ["manifest_dependency"]
    manifest = next(change for change in pack.changes if change.kind == "manifest_dependency")
    file_rule = next(change for change in pack.changes if change.kind == "flag_only")
    assert registry.rule_for(manifest) is None
    assert registry.manifest_rule_for(file_rule) is None


def test_the_import_rule_runs_before_the_client_rule_and_the_order_is_the_packs() -> None:
    """`configure_to_client` reads the name `rename_import` bound (else `alias_collision` on every
    file) and `generative_model_calls` reads both; nothing reads what the later rules write.
    """
    pack = loader.load("gemini/google-generativeai-to-google-genai").pack
    order = [rule.kind for rule in registry.rules(pack)]
    assert order[:3] == ["rename_import", "configure_to_client", "generative_model_calls"]
    assert set(order[3:]) == {"rewrite_call", "flag_only"}


def test_a_module_nobody_offered_a_name_for_cannot_be_introduced() -> None:
    """No name offered, or no replaced statement to anchor to: `None`, never an invented name."""
    read = parse.gates("probe.py", SOURCE.encode("utf-8"))
    assert read.module is not None
    plan = ImportPlan(MetadataWrapper(read.module, unsafe_skip_copy=True))
    assert plan.require("acme.client.types") is None
    plan.offer("acme.client.types", "types", "acme_types")
    assert plan.require("acme.client.types") is None


def test_a_required_import_is_reserved_once_and_anchored_to_the_first_statement() -> None:
    """The first ask reserves the name, so a second cannot take the fallback and add a line.

    The first statement anchors it, so it lands where the legacy imports begin, not after them.
    """
    read = parse.gates("probe.py", b"import acme.sdk\nimport acme.sdk.wire\n")
    assert read.module is not None
    plan = ImportPlan(MetadataWrapper(read.module, unsafe_skip_copy=True))
    first, second = read.module.body[0], read.module.body[1]
    assert isinstance(first, cst.SimpleStatementLine)
    assert isinstance(second, cst.SimpleStatementLine)
    plan.replace(first, statement_for("acme.client", "acme_client"))
    plan.replace(second, statement_for("acme.client.wire", "wire"))
    plan.offer("acme.client.types", "types", "acme_types")
    assert plan.require("acme.client.types") == "types"
    assert plan.require("acme.client.types") == "types"
    assert len(plan.lines_for(first, first) or []) == 2
    assert len(plan.lines_for(second, second) or []) == 1


def test_only_the_rules_that_will_run_can_make_another_one_drop_an_import() -> None:
    """`consumed` comes from the rules handed to the context, so the import rule alone keeps it."""
    source = 'from acme.sdk import configure\n\nconfigure(key="k")\n'
    alone, edits = acme.transform(source, acme.CHANGE)
    assert alone == source
    assert [(row.status, row.reason) for row in edits] == [
        ("needs_review", "from_import_unmigrated_symbol")
    ]


def test_a_module_reached_only_where_nothing_runs_has_no_runtime_name() -> None:
    """An import under `if TYPE_CHECKING:` binds nothing at runtime, nor would one beside it."""
    source = b"from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    import acme.sdk.types\n"
    read = parse.gates("probe.py", source)
    assert read.module is not None
    guard = read.module.body[1]
    assert isinstance(guard, cst.If)
    assert isinstance(guard.body, cst.IndentedBlock)
    guarded = guard.body.body[0]
    assert isinstance(guarded, cst.SimpleStatementLine)
    plan = ImportPlan(MetadataWrapper(read.module, unsafe_skip_copy=True))
    plan.replace(guarded, statement_for("acme.client.types", "types"))
    plan.bind("acme.client.types", "types")
    assert plan.require("acme.client.types") is None
    assert plan.refusal("acme.client.types") == "types_import_typing_only"
    plan.offer("acme.client.wire", "wire")
    assert plan.require("acme.client.wire") is None
    assert plan.refusal("acme.client.wire") == "types_import_typing_only"


def test_a_file_with_nothing_replaced_refuses_under_the_old_name() -> None:
    read = parse.gates("probe.py", b"import os\n")
    assert read.module is not None
    plan = ImportPlan(MetadataWrapper(read.module, unsafe_skip_copy=True))
    plan.offer("acme.client.types", "types", "acme_types")
    assert plan.require("acme.client.types") is None
    assert plan.refusal("acme.client.types") == "alias_collision"


def _statement(built: base.RuleContext, index: int) -> cst.SimpleStatementLine:
    line = built.module.body[index]
    assert isinstance(line, cst.SimpleStatementLine)
    return line


def test_lines_led_onto_a_statement_that_goes_too_go_on_to_the_next_that_stays() -> None:
    built = context("a = 1\nb = 2\nc = 3\nd = 4\n")
    first, second, third, last = (_statement(built, index) for index in range(4))
    for line in (second, third):
        built.rewrites.drop(line.body[0])
    built.rewrites.hand_on(second, third)
    built.rewrites.hand_on(third, last)
    note, other = (cst.EmptyLine(comment=cst.Comment(f"# {name}")) for name in "ab")
    built.rewrites.lead(third, (other,))
    built.rewrites.lead(second, (note,))
    assert built.rewrites.successor(second) is third
    assert built.rewrites.successor(first) is None
    assert base.finish(built).code == "a = 1\n# a\n# b\nd = 4\n"


def test_lines_led_onto_a_statement_that_goes_with_no_successor_named_go_with_it() -> None:
    built = context("a = 1\nb = 2\n")
    gone = _statement(built, 0)
    built.rewrites.drop(gone.body[0])
    built.rewrites.lead(gone, (cst.EmptyLine(comment=cst.Comment("# lost")),))
    assert base.finish(built).code == "b = 2\n"


def _plan(source: str) -> ImportPlan:
    read = parse.gates("probe.py", source.encode("utf-8"))
    assert read.module is not None
    return ImportPlan(MetadataWrapper(read.module, unsafe_skip_copy=True))


def test_a_top_level_import_names_a_path_the_way_the_file_spells_it() -> None:
    plan = _plan(
        "import acme.a\nimport acme.b as b\nimport plain\nfrom acme import c\n"
        "from acme import d as e\n\nx = 1\n"
    )
    line = 8
    assert plan.found("acme.a", line) == "acme.a"
    assert plan.found("acme.b", line) == "b"
    assert plan.found("plain", line) == "plain"
    assert plan.found("acme.c", line) == "c"
    assert plan.found("acme.d", line) == "e"
    assert plan.found("acme.f", line) is None


def test_a_relative_import_and_a_star_import_reach_no_path() -> None:
    plan = _plan("from . import sibling\nfrom acme import *\nimport os; import sys\n\nx = 1\n")
    assert [plan.found(path, 6) for path in ("sibling", "acme.sibling", "acme", "os", "sys")] == [
        None
    ] * 5


def test_only_an_import_above_the_line_can_be_used_there() -> None:
    plan = _plan("import first.a\nx = 1\nimport second.b\n")
    assert plan.found("first.a", 2) == "first.a"
    assert plan.found("second.b", 2) is None
    assert plan.found("second.b", 4) == "second.b"


def test_a_name_the_file_binds_twice_is_no_name_to_write_a_new_use_by() -> None:
    """A parameter, a local or a second import could stand in its place where the line is."""
    plan = _plan("from acme import c\nfrom other import c as d\n\n\ndef f(c):\n    return c\n")
    assert plan.found("acme.c", 8) is None
    assert plan.found("other.c", 8) == "d"
    assert _plan("import acme.a\nimport acme.b\n").found("acme.a", 3) is None


def test_fresh_imports_follow_the_last_top_level_import_above_the_first_use() -> None:
    read = parse.gates("probe.py", b"import os\nimport sys\n\n\ndef f():\n    pass\n")
    assert read.module is not None
    plan = ImportPlan(MetadataWrapper(read.module, unsafe_skip_copy=True))
    assert plan.anchor(5) is True
    plan.offer("acme.units", "units")
    assert plan.require("acme.units") == "units"
    sys_line = read.module.body[1]
    assert isinstance(sys_line, cst.SimpleStatementLine)
    assert len(plan.lines_for(sys_line, sys_line) or []) == 2
    first = read.module.body[0]
    assert isinstance(first, cst.SimpleStatementLine)
    assert plan.lines_for(first, first) is None
    assert plan.anchor(5) is True


def test_a_file_with_no_top_level_import_above_the_use_has_no_line_to_follow() -> None:
    assert _plan("def f():\n    import os\n\nx = f()\n").anchor(4) is False
    assert _plan("x = 1\nimport os\n").anchor(1) is False


def test_a_line_a_rule_replaced_already_anchors_fresh_imports() -> None:
    read = parse.gates("probe.py", b"import acme.sdk\nimport os\n\nx = 1\n")
    assert read.module is not None
    plan = ImportPlan(MetadataWrapper(read.module, unsafe_skip_copy=True))
    first = read.module.body[0]
    assert isinstance(first, cst.SimpleStatementLine)
    plan.replace(first, statement_for("acme.client", "client"))
    assert plan.anchor(4) is True
    plan.offer("acme.units", "units")
    assert plan.require("acme.units") == "units"
    assert len(plan.lines_for(first, first) or []) == 2

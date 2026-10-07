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

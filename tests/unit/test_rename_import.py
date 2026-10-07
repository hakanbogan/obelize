"""`rename_import` on the fake `acme` SDK, one shape at a time.

`acme.CHANGE`'s `default_alias` is not the new module's last segment and its `submodule_map` has a
submodule the Gemini pack lacks, so the rule must read its parameters rather than know Google's.
"""

from __future__ import annotations

from pathlib import Path

import acme
import libcst as cst
import pytest

from obelize.models import Edit
from obelize.transforms.imports import statement_for


def statuses(edits: list[Edit]) -> list[tuple[int, str, str | None]]:
    return [(row.line, row.status, row.reason) for row in edits]


def test_the_unaliased_import_introduces_the_packs_default_alias() -> None:
    code, edits = acme.transform("import acme.sdk\n\nacme.sdk.configure(key='k')\n")
    assert code.startswith("from acme import client as acme_client\n")
    assert statuses(edits) == [(1, "auto", None)]


def test_an_alias_the_author_wrote_survives_the_rewrite() -> None:
    code, _ = acme.transform("import acme.sdk as sdk\n\nsdk.configure(key='k')\n")
    assert code.startswith("from acme import client as sdk\n")


def test_the_module_own_spelling_does_not_survive_it() -> None:
    """`sdk` is the legacy module's own name, which is what changed."""
    code, _ = acme.transform("from acme import sdk\n\nsdk.configure(key='k')\n")
    assert code.startswith("from acme import client as acme_client\n")


def test_a_single_segment_target_module_is_a_plain_import() -> None:
    """`from  import x` is not a statement."""
    assert cst.Module(body=[cst.SimpleStatementLine([statement_for("acmeclient", "ac")])]).code == (
        "import acmeclient as ac\n"
    )
    assert cst.Module(
        body=[cst.SimpleStatementLine([statement_for("acmeclient", "acmeclient")])]
    ).code == ("import acmeclient\n")


def test_a_legacy_import_beside_another_keeps_the_other() -> None:
    code, _ = acme.transform("import os, acme.sdk\n\nacme.sdk.configure(key=os.sep)\n")
    assert code.startswith("import os\nfrom acme import client as acme_client\n")


def test_two_legacy_aliases_on_one_line_never_reach_the_rule() -> None:
    """Binding `acme` twice is `conditional_binding`, so the scan withholds the whole file."""
    source = "import acme.sdk, acme.sdk.types\n\nacme.sdk.configure(key=acme.sdk.types.Config)\n"
    code, edits = acme.transform(source)
    assert code == source
    assert edits == []


def test_a_from_package_import_beside_another_keeps_the_other() -> None:
    code, _ = acme.transform("from acme import helpers, sdk\n\nsdk.configure(key=helpers.K)\n")
    assert code.startswith("from acme import helpers\nfrom acme import client as acme_client\n")


def test_a_compound_line_is_split_and_the_other_statement_stays() -> None:
    """One statement per emitted line."""
    code, _ = acme.transform("import acme.sdk; KEY = 'k'\n\nacme.sdk.configure(key=KEY)\n")
    assert code.startswith("from acme import client as acme_client\nKEY = 'k'\n")


def test_a_kept_import_on_a_split_line_keeps_no_semicolon() -> None:
    code, _ = acme.transform("import os; import acme.sdk\n\nacme.sdk.configure(key=os.sep)\n")
    assert code.startswith("import os\nfrom acme import client as acme_client\n")
    assert ";" not in code


def test_a_read_through_the_module_alias_leaves_the_module_import_behind() -> None:
    """Neither `acme.sdk.types` (inside the chain) nor `.DEFAULT` (above it) counts as a use."""
    code, edits = acme.transform("import acme.sdk\n\nC = acme.sdk.types.Config.DEFAULT\n")
    assert code == "from acme.client import types\n\nC = types.RunConfig.DEFAULT\n"
    assert statuses(edits) == [(1, "auto", None), (3, "auto", None)]


def test_an_import_nothing_reaches_is_removed_rather_than_renamed() -> None:
    code, edits = acme.transform("import acme.sdk\n\nVALUE = 1\n")
    assert code == "\nVALUE = 1\n"
    assert statuses(edits) == [(1, "auto", None)]


def test_a_submodule_is_imported_under_its_own_last_segment() -> None:
    code, _ = acme.transform("import acme.sdk.wire\n\nFRAME = acme.sdk.wire.Frame\n")
    assert code.startswith("from acme.client import wire\n")


def test_a_submodule_import_keeps_the_alias_the_author_wrote() -> None:
    code, _ = acme.transform("import acme.sdk.wire as w\n\nFRAME = w.Frame\n")
    assert code.startswith("from acme.client import wire as w\n")


def test_a_submodule_reached_through_a_from_import_moves_the_same_way() -> None:
    code, _ = acme.transform("from acme.sdk import wire\n\nFRAME = wire.Frame\n")
    assert code.startswith("from acme.client import wire\n")


def test_a_from_import_of_a_name_that_is_not_a_submodule_bails() -> None:
    code, edits = acme.transform("from acme.sdk import configure\n\nconfigure(key='k')\n")
    assert code.startswith("from acme.sdk import configure\n")
    assert statuses(edits) == [(1, "needs_review", "from_import_unmigrated_symbol")]


def test_a_symbol_from_a_submodule_with_no_symbol_map_bails() -> None:
    """`wire` is mapped as a module; its contents are not."""
    code, edits = acme.transform("from acme.sdk.wire import Frame\n\nF = Frame\n")
    assert code.startswith("from acme.sdk.wire import Frame\n")
    assert statuses(edits) == [(1, "needs_review", "type_symbol_unmapped")]


def test_a_types_symbol_is_matched_on_the_segment_after_the_submodule() -> None:
    """`Config.Level` reads a mapped symbol; the map holds `Config`."""
    code, edits = acme.transform("from acme.sdk.types import Config\n\nL = Config.Level\n")
    assert code == "from acme.client import types\n\nL = types.RunConfig.Level\n"
    assert statuses(edits) == [(1, "auto", None), (3, "auto", None)]


def test_a_from_import_releases_the_names_it_bound() -> None:
    """`Config` is free again, so the submodule may bind it if it has to."""
    source = "from acme.sdk.types import Config\nfrom acme.sdk.types import Level\n\nC = Config\n"
    code, _ = acme.transform(source)
    assert code.count("from acme.client import types") == 1
    assert "C = types.RunConfig\n" in code


def test_a_types_symbol_is_read_through_the_submodule() -> None:
    code, edits = acme.transform("from acme.sdk.types import Config\n\nC = Config\n")
    assert code == "from acme.client import types\n\nC = types.RunConfig\n"
    assert statuses(edits) == [(1, "auto", None), (3, "auto", None)]


def test_a_symbol_renamed_on_the_way_in_is_still_read_through_the_submodule() -> None:
    """The `as` aliases the symbol, not the module."""
    code, _ = acme.transform("from acme.sdk.types import Config as C\n\nX = C\n")
    assert code == "from acme.client import types\n\nX = types.RunConfig\n"


def test_a_submodule_aliased_by_the_author_carries_its_symbols_too() -> None:
    code, _ = acme.transform("import acme.sdk.types as t\n\nX = t.Config\n")
    assert code == "from acme.client import types as t\n\nX = t.RunConfig\n"


def test_the_types_import_is_written_once_however_many_statements_ask() -> None:
    source = (
        "import acme.sdk.types\n"
        "from acme.sdk.types import Level\n"
        "\n"
        "A = acme.sdk.types.Config\n"
        "B = Level\n"
    )
    code, _ = acme.transform(source)
    assert code.count("from acme.client import types") == 1


def test_a_types_symbol_the_map_does_not_carry_bails_with_its_reads() -> None:
    source = "from acme.sdk.types import Config, Missing\n\nA = Config\nB = Missing\n"
    code, edits = acme.transform(source)
    assert code == source
    assert statuses(edits) == [
        (1, "needs_review", "type_symbol_unmapped"),
        (3, "needs_review", "type_symbol_unmapped"),
    ]


def test_the_module_alias_has_one_candidate_and_no_fallback() -> None:
    source = "import acme_client\nimport acme.sdk\n\nacme.sdk.configure(key=acme_client.K)\n"
    code, edits = acme.transform(source)
    assert code == source
    assert statuses(edits) == [(2, "needs_review", "alias_collision")]


def test_the_types_alias_falls_back_before_it_collides() -> None:
    source = "import types\nfrom acme.sdk.types import Config\n\nC = Config\nT = types\n"
    code, _ = acme.transform(source)
    assert "from acme.client import types as acme_types\n" in code
    assert "C = acme_types.RunConfig\n" in code


def test_the_types_alias_collides_when_the_fallback_is_taken_too() -> None:
    source = (
        "import types\n"
        "import acme_types\n"
        "from acme.sdk.types import Config\n"
        "\n"
        "C = Config\n"
        "T = (types, acme_types)\n"
    )
    code, edits = acme.transform(source)
    assert code == source
    assert statuses(edits) == [
        (3, "needs_review", "alias_collision"),
        (5, "needs_review", "alias_collision"),
    ]


def test_a_statement_the_scan_withheld_is_left_alone() -> None:
    """A bail anywhere withholds the whole file."""
    source = "import acme.sdk\n\nacme.sdk.protos.Thing()\n"
    code, edits = acme.transform(source)
    assert code == source
    assert edits == []


@pytest.mark.parametrize(
    "source",
    [
        "import os\n\nprint(os.sep)\n",
        "from acme import helpers\n\nprint(helpers.K)\n",
        "import acme.other\n\nacme.other.go()\n",
    ],
)
def test_a_file_with_no_legacy_import_is_untouched(source: str) -> None:
    code, edits = acme.transform(source)
    assert code == source
    assert edits == []


# A library with no client: `acme.old` to `acme.new`, module-level names and a `wire` submodule.
def old(source: str) -> tuple[str, list[Edit]]:
    return acme.transform(source, acme.OLD_RENAME, spec=acme.OLD_SPEC)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "import acme.old\n\nr = acme.old.Reader('x')\nacme.old.fetch(r)\n",
            "from acme import new as fresh\n\nr = fresh.Reader('x')\nfresh.get(r)\n",
        ),
        (
            "import acme.old as o\n\nr = o.Reader('x')\no.fetch(r)\n",
            "from acme import new as o\n\nr = o.Reader('x')\no.get(r)\n",
        ),
        (
            "from acme import old\n\nr = old.Reader('x')\nold.fetch(r)\n",
            "from acme import new as fresh\n\nr = fresh.Reader('x')\nfresh.get(r)\n",
        ),
    ],
    ids=["unaliased", "aliased", "from-package"],
)
def test_a_module_level_name_is_read_through_the_new_module(source: str, expected: str) -> None:
    """The legacy spelling goes, an author's alias stays, and a renamed name is renamed."""
    code, edits = old(source)
    assert code == expected
    assert {row.status for row in edits} == {"auto"}


def test_a_name_mapped_to_itself_stays_in_a_from_import_of_the_new_module() -> None:
    code, _ = old("from acme.old import Reader as R\n\nr = R('x')\n")
    assert code == "from acme.new import Reader as R\n\nr = R('x')\n"


def test_a_name_mapped_to_another_one_is_not_a_from_import_the_rule_can_keep() -> None:
    """Its reads would have to be renamed where they stand, which no rule does."""
    source = "from acme.old import fetch\n\nfetch(1)\n"
    code, edits = old(source)
    assert code == source
    assert {(row.status, row.reason) for row in edits} == {
        ("needs_review", "from_import_unmigrated_symbol")
    }


def test_a_symbol_of_a_submodule_is_read_through_the_new_submodule() -> None:
    code, _ = old("import acme.old\n\nf = acme.old.wire.Frame(1)\np = acme.old.wire.Pkt(2)\n")
    assert code == "from acme.new import wire\n\nf = wire.Frame(1)\np = wire.Packet(2)\n"


def test_symbols_imported_off_a_submodule_become_reads_of_it() -> None:
    code, _ = old("from acme.old.wire import Frame, Pkt\n\nf = Frame(1)\n")
    assert code == "from acme.new import wire\n\nf = wire.Frame(1)\n"


def test_a_symbol_imported_off_a_submodule_the_pack_does_not_map_is_refused() -> None:
    source = "from acme.old.wire import Other\n\nf = Other(1)\n"
    code, edits = old(source)
    assert code == source
    assert statuses(edits) == [(1, "needs_review", "type_symbol_unmapped")]


def test_a_symbol_imported_off_a_submodule_the_pack_does_not_move_is_refused() -> None:
    """No rule claims that import alone; only a line shared with a claimed one gets here."""
    source = "import acme.old; from acme.old.extra import Other\n\nOther(1)\n"
    code, edits = old(source)
    assert code == source
    assert statuses(edits) == [(1, "needs_review", "type_symbol_unmapped")]


@pytest.mark.parametrize(
    "source",
    [
        "from acme.old.wire import Frame\n__all__ = ['Frame']\n\nf = Frame(1)\n",
        "from acme.old.wire import Frame\n__all__ = ('Frame',)\n\nf = Frame(1)\n",
        "from acme.old.wire import Frame\n__all__ = []\n__all__ += ['Frame']\n\nf = Frame(1)\n",
        "from acme.old.wire import Frame\nf = Frame(1)\ndel Frame\n",
        "from acme.old.wire import Frame\nf = Frame(1)\ndel f, Frame\n",
        "import acme.old\n__all__ = ['acme']\n\nacme.old.Reader(1)\n",
    ],
    ids=["all-list", "all-tuple", "all-extended", "del", "del-several", "module-in-all"],
)
def test_a_name_the_rewrite_drops_and_the_file_exports_or_deletes_is_refused(source: str) -> None:
    """A string in `__all__` and a `del` read the name without naming it as a read."""
    _code, edits = old(source)
    assert {row.reason for row in edits} == {"from_import_unmigrated_symbol"}


def test_a_name_the_rewrite_keeps_may_be_exported() -> None:
    code, edits = old("from acme.old import Reader\n__all__ = ['Reader']\n\nr = Reader(1)\n")
    assert code == "from acme.new import Reader\n__all__ = ['Reader']\n\nr = Reader(1)\n"
    assert {row.status for row in edits} == {"auto"}


def test_an_export_or_a_delete_the_rewrite_cannot_read_is_not_taken_for_one_of_its_names() -> None:
    """Counters, attribute and subscript deletes, a computed `__all__` and a name inside one."""
    source = (
        "from acme.old import Reader\n\ncount = 1\ncount += 1\nitems = [Reader]\n"
        "del items[0]\ndel Reader.attribute\n__all__ = [Reader.__name__]\n__all__ += compute()\n"
        "__all__ = compute()\n"
    )
    code, edits = old(source)
    assert code.startswith("from acme.new import Reader\n")
    assert {row.status for row in edits} == {"auto"}


def test_an_import_in_one_branch_does_not_bind_a_name_in_the_other() -> None:
    source = (
        "import sys\nif sys.platform == 'x':\n    from acme.old.wire import Frame\n"
        "    f = Frame(1)\nelse:\n    from acme.old.wire import Pkt\n    f = Pkt(1)\n"
    )
    code, _ = old(source)
    assert code == (
        "import sys\nif sys.platform == 'x':\n    from acme.new import wire\n"
        "    f = wire.Frame(1)\nelse:\n    from acme.new import wire as fresh_wire\n"
        "    f = fresh_wire.Packet(1)\n"
    )


def test_an_import_under_type_checking_does_not_bind_the_name_a_module_level_read_needs() -> None:
    source = (
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n"
        "    from acme.old.wire import Frame\nfrom acme.old.wire import Pkt\n\nx = Pkt(1)\n"
    )
    code, _ = old(source)
    assert code.endswith("from acme.new import wire as fresh_wire\n\nx = fresh_wire.Packet(1)\n")


def test_the_submodules_fallback_alias_is_taken_when_its_own_name_is_bound() -> None:
    code, _ = old("import acme.old\n\nwire = 1\nf = acme.old.wire.Frame(wire)\n")
    assert (
        code == "from acme.new import wire as fresh_wire\n\nwire = 1\nf = fresh_wire.Frame(wire)\n"
    )


def test_a_module_alias_that_is_bound_is_a_refusal_not_a_collision_written() -> None:
    source = "import acme.old\n\nfresh = 1\nacme.old.Reader(fresh)\n"
    code, edits = old(source)
    assert code == source
    assert {row.reason for row in edits} == {"alias_collision"}


def test_importing_a_submodule_and_reading_the_module_binds_both() -> None:
    """`import acme.old.wire` binds `acme`, so a read of the module needs its own import."""
    code, _ = old("import acme.old.wire\n\nx = acme.old.Reader(acme.old.wire.Frame(1))\n")
    assert code == (
        "from acme.new import wire\nfrom acme import new as fresh\n\n"
        "x = fresh.Reader(wire.Frame(1))\n"
    )


def test_a_name_no_rule_maps_is_left_for_the_driver_to_withhold(tmp_path: Path) -> None:
    run = acme.repository(
        tmp_path,
        {"app.py": "import acme.old\n\nacme.old.Thing()\n"},
        spec=acme.OLD_SPEC,
        pack=acme.OLD_PACK,
    )
    assert run.written == ()
    assert [(row.line, row.bail) for row in run.plans[0].findings] == [
        (1, "file_not_fully_migrated"),
        (3, "usage_unmapped"),
    ]

"""`rename_import` on the fake `acme` SDK, one shape at a time.

`acme.CHANGE`'s `default_alias` is not the new module's last segment and its `submodule_map` has a
submodule the Gemini pack lacks, so the rule must read its parameters rather than know Google's.
"""

from __future__ import annotations

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

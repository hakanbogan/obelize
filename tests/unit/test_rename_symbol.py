"""`rename_symbol` on an invented shared module: 2.x of `acme.kit` exports its error classes.

`acme.kit.faults.Busy` is `acme.kit.Busy` and `Denied` is `Forbidden`, both derived from `Fault`,
which their old classes were not; `Failure` has no counterpart. `acme.kit` is invented, so nothing
here reads the openai pack's spellings.
"""

from __future__ import annotations

from pathlib import Path

import acme
import acme_kept as kit
import pytest

from obelize.models import Edit

HEADER = "import acme.kit\n\n"
TRY = "try:\n    run()\n"


def tidy(body: str, header: str = HEADER) -> tuple[str, list[Edit]]:
    code, edits = acme.transform(f"{header}{body}", kit.ERRORS, spec=kit.SPEC)
    return code.removeprefix(header), edits


def reasons(edits: list[Edit]) -> list[str | None]:
    return [row.reason for row in edits]


@pytest.mark.parametrize(
    ("body", "written"),
    [
        (
            f"{TRY}except acme.kit.faults.Busy:\n    pass\n",
            f"{TRY}except acme.kit.Busy:\n    pass\n",
        ),
        (
            f"{TRY}except acme.kit.faults.Denied:\n    pass\n",
            f"{TRY}except acme.kit.Forbidden:\n    pass\n",
        ),
        (
            f"{TRY}except (acme.kit.faults.Busy, ValueError) as error:\n    print(error)\n",
            f"{TRY}except (acme.kit.Busy, ValueError) as error:\n    print(error)\n",
        ),
        (
            f"{TRY}except (OSError, (acme.kit.faults.Denied,)):\n    pass\n",
            f"{TRY}except (OSError, (acme.kit.Forbidden,)):\n    pass\n",
        ),
        (
            f"{TRY}except acme.kit.faults.Busy as error:\n    raise\n",
            f"{TRY}except acme.kit.Busy as error:\n    raise\n",
        ),
        ("retry(acme.kit.faults.Busy, max=3)\n", "retry(acme.kit.Busy, max=3)\n"),
        ("retry(on=acme.kit.faults.Busy)\n", "retry(on=acme.kit.Busy)\n"),
        ("ok = isinstance(e, acme.kit.faults.Busy)\n", "ok = isinstance(e, acme.kit.Busy)\n"),
        (
            "CAUGHT = (acme.kit.faults.Busy, acme.kit.faults.Denied)\n",
            "CAUGHT = (acme.kit.Busy, acme.kit.Forbidden)\n",
        ),
        ("x = acme.kit.faults.Busy  # why\n", "x = acme.kit.Busy  # why\n"),
        ("x = (acme.kit\n     .faults\n     .Busy)\n", "x = (acme.kit\n     .Busy)\n"),
        ("def f(e: acme.kit.faults.Busy): ...\n", "def f(e: acme.kit.Busy): ...\n"),
    ],
)
def test_a_reference_drops_the_submodule_and_takes_the_new_name(body: str, written: str) -> None:
    code, edits = tidy(body)
    assert code == written
    assert set(reasons(edits)) == {None}
    assert {row.status for row in edits} == {"auto"}


@pytest.mark.parametrize(
    ("header", "body", "after", "written"),
    [
        (
            "import acme.kit as kit\n\n",
            "x = kit.faults.Busy\n",
            "import acme.kit as kit\n\n",
            "x = kit.Busy\n",
        ),
        (
            "import acme.kit.faults\n\n",
            "x = acme.kit.faults.Busy\n",
            "import acme.kit\n\n",
            "x = acme.kit.Busy\n",
        ),
        (
            "import acme.kit.faults  # keep\n\n",
            "x = acme.kit.faults.Busy\n",
            "import acme.kit  # keep\n\n",
            "x = acme.kit.Busy\n",
        ),
        (
            "import os, acme.kit.faults\n\n",
            "x = acme.kit.faults.Busy\n",
            "import os, acme.kit\n\n",
            "x = acme.kit.Busy\n",
        ),
        (
            "import acme.kit.faults as oops\n\n",
            "x = oops.Busy\n",
            "import acme.kit as oops\n\n",
            "x = oops.Busy\n",
        ),
        (
            "import acme.kit.faults as oops\n\n",
            "x = oops.Denied\n",
            "import acme.kit as oops\n\n",
            "x = oops.Forbidden\n",
        ),
        ("import acme.kit.faults; y = 1\n\n", "x = 2\n", "import acme.kit\ny = 1\n\n", "x = 2\n"),
        (
            "import acme.kit.faults; import os\n\n",
            "x = 2\n",
            "import acme.kit\nimport os\n\n",
            "x = 2\n",
        ),
        (
            "from acme.kit import faults\n\n",
            "x = faults.Busy\n",
            "from acme.kit import faults\n\n",
            "x = faults.Busy\n",
        ),
    ],
)
def test_the_import_that_bound_the_submodule_binds_the_package_in_its_place(
    header: str, body: str, after: str, written: str
) -> None:
    code, edits = acme.transform(f"{header}{body}", kit.ERRORS, spec=kit.SPEC)
    if header.startswith("from acme.kit import faults"):
        # No spelling to move to: the statement is refused and the name left as it was.
        assert code == f"{header}{body}"
        assert "from_import_unmigrated_symbol" in reasons(edits)
        return
    assert code == f"{after}{written}"
    assert {row.status for row in edits} == {"auto"}


@pytest.mark.parametrize(
    ("header", "body", "written_header", "written"),
    [
        (
            "from acme.kit.faults import Busy\n\n",
            f"{TRY}except Busy:\n    pass\n",
            "from acme.kit import Busy\n\n",
            f"{TRY}except Busy:\n    pass\n",
        ),
        (
            "from acme.kit.faults import Busy as Overloaded\n\n",
            f"{TRY}except Overloaded:\n    pass\n",
            "from acme.kit import Busy as Overloaded\n\n",
            f"{TRY}except Overloaded:\n    pass\n",
        ),
        (
            "from acme.kit.faults import Denied\n\n",
            f"{TRY}except Denied as error:\n    print(error)\n",
            "from acme.kit import Forbidden\n\n",
            f"{TRY}except Forbidden as error:\n    print(error)\n",
        ),
        (
            "from acme.kit.faults import Denied as No\n\n",
            f"{TRY}except No:\n    pass\n",
            "from acme.kit import Forbidden as No\n\n",
            f"{TRY}except No:\n    pass\n",
        ),
        (
            "from acme.kit.faults import (\n    Busy,\n    Denied,  # why\n)\n\n",
            f"{TRY}except (Busy, Denied):\n    pass\n",
            "from acme.kit import (\n    Busy,\n    Forbidden,  # why\n)\n\n",
            f"{TRY}except (Busy, Forbidden):\n    pass\n",
        ),
        (
            "from acme.kit.faults import Busy; from acme.kit import Client\n\n",
            "x = Busy, Client\n",
            "from acme.kit import Busy\nfrom acme.kit import Client\n\n",
            "x = Busy, Client\n",
        ),
        (
            "from acme.kit.faults import Busy\n\n",
            "x = Busy\ndef f(Busy):\n    return Busy\n",
            "from acme.kit import Busy\n\n",
            "x = Busy\ndef f(Busy):\n    return Busy\n",
        ),
    ],
)
def test_a_name_imported_from_the_submodule_is_imported_from_the_package(
    header: str, body: str, written_header: str, written: str
) -> None:
    code, edits = acme.transform(f"{header}{body}", kit.ERRORS, spec=kit.SPEC)
    assert code == f"{written_header}{written}"
    assert {row.status for row in edits} == {"auto"}


@pytest.mark.parametrize(
    "source",
    [
        "from acme.kit.faults import Busy, Failure\n",
        "from acme.kit.faults import Failure\n",
        "from acme.kit import faults\n",
        "from acme.kit import Client, faults as oops\n",
        "if ready: import acme.kit.faults\n",
        "if ready: from acme.kit.faults import Busy\n",
    ],
)
def test_an_import_that_cannot_be_moved_whole_is_refused(source: str) -> None:
    code, edits = acme.transform(source, kit.ERRORS, spec=kit.SPEC)
    assert code == source
    assert "from_import_unmigrated_symbol" in reasons(edits)


def test_a_name_the_file_already_binds_is_not_taken_for_a_renamed_import() -> None:
    _, edits = tidy("Forbidden = 1\nprint(Denied)\n", "from acme.kit.faults import Denied\n\n")
    assert reasons(edits) == ["alias_collision", None]


@pytest.mark.parametrize(
    "body",
    [
        "raise acme.kit.faults.Busy('x')\n",
        "raise acme.kit.faults.Busy\n",
        "raise acme.kit.faults.Denied('x', 3) from error\n",
        "mocked = Mock(side_effect=acme.kit.faults.Busy('x'))\n",
        "class Mine(acme.kit.faults.Busy):\n    pass\n",
        "class Mine(acme.kit.faults.Busy, metaclass=Meta):\n    pass\n",
    ],
)
def test_a_class_that_is_called_raised_or_derived_from_is_refused(body: str) -> None:
    """The new class takes other constructor arguments, so each of these would raise a TypeError."""
    code, edits = tidy(body)
    assert code == body
    assert reasons(edits) == ["error_class_changed"]


@pytest.mark.parametrize(
    "body",
    [
        f"{TRY}except acme.kit.faults.Busy as error:\n    print(error.status)\n",
        f"{TRY}except acme.kit.faults.Busy as error:\n    x = f'{{error.status}}'\n",
        f"{TRY}except acme.kit.faults.Busy as error:\n    g = lambda: error.args\n",
        f"{TRY}except (OSError, acme.kit.faults.Denied) as error:\n    if ok:\n        error.x()\n",
    ],
)
def test_a_handler_that_reads_an_attribute_of_the_error_is_refused(body: str) -> None:
    """The old class had `status`, `http_status` and the rest; the new one has other names."""
    code, edits = tidy(body)
    assert code == body
    assert "attribute_removed" in reasons(edits)


@pytest.mark.parametrize(
    "body",
    [
        f"{TRY}except acme.kit.faults.Busy as error:\n    log(str(error), error)\n",
        f"{TRY}except acme.kit.faults.Busy as error:\n    raise Wrapper(error) from error\n",
        f"{TRY}except acme.kit.faults.Busy:\n    print(error.status)\n",
    ],
)
def test_an_error_used_as_a_value_is_no_read_of_an_attribute(body: str) -> None:
    code, edits = tidy(body)
    assert "acme.kit.Busy" in code
    assert reasons(edits) == [None]


@pytest.mark.parametrize(
    "earlier",
    [
        "acme.kit.Fault",
        "(ValueError, acme.kit.Fault)",
        "(OSError, (acme.kit.Fault, KeyError))",
        "errors",
        "get_errors()",
        "self.errors",
        "Mine",
    ],
)
def test_a_handler_ahead_that_may_catch_the_new_class_and_did_not_catch_the_old_is_refused(
    earlier: str,
) -> None:
    body = (
        "class Mine(Exception):\n    pass\n\n"
        f"{TRY}except {earlier}:\n    pass\nexcept acme.kit.faults.Busy:\n    pass\n"
    )
    code, edits = tidy(body)
    assert code == body
    assert reasons(edits) == ["error_class_changed"]


def test_a_handler_ahead_through_an_alias_of_the_base_is_still_the_base() -> None:
    body = f"{TRY}except Base:\n    pass\nexcept acme.kit.faults.Busy:\n    pass\n"
    code, edits = tidy(body, "import acme.kit\nfrom acme.kit import Fault as Base\n\n")
    assert code == body
    assert reasons(edits) == ["error_class_changed"]


@pytest.mark.parametrize(
    "earlier",
    [
        "ValueError",
        "(KeyError, OSError)",
        "Exception",
        "os.error",
        "acme.kit.faults.Denied",
        "(acme.kit.faults.Denied, ValueError)",
    ],
)
def test_a_handler_ahead_that_could_not_catch_it_before_or_now_leaves_it_alone(
    earlier: str,
) -> None:
    body = f"{TRY}except {earlier}:\n    pass\nexcept acme.kit.faults.Busy:\n    pass\n"
    code, edits = tidy(body, "import os\nimport acme.kit\n\n")
    assert "except acme.kit.Busy:" in code
    assert {row.reason for row in edits} == {None}


def test_a_handler_after_the_renamed_class_is_no_obstacle() -> None:
    body = f"{TRY}except acme.kit.faults.Busy:\n    pass\nexcept acme.kit.Fault:\n    pass\n"
    code, edits = tidy(body)
    assert code == body.replace("faults.", "")
    assert reasons(edits) == [None]


def test_the_handlers_of_another_try_are_not_the_ones_ahead() -> None:
    body = f"{TRY}except acme.kit.Fault:\n    pass\n{TRY}except acme.kit.faults.Busy:\n    pass\n"
    code, edits = tidy(body)
    assert code.endswith("except acme.kit.Busy:\n    pass\n")
    assert reasons(edits) == [None]


@pytest.mark.parametrize(
    ("earlier", "withheld"),
    [("acme.kit.Fault", True), ("ValueError", False)],
)
def test_an_except_star_clause_is_held_to_the_same_rules(earlier: str, withheld: bool) -> None:
    body = f"{TRY}except* {earlier}:\n    pass\nexcept* acme.kit.faults.Busy as e:\n    log(e)\n"
    code, edits = tidy(body)
    assert reasons(edits) == (["error_class_changed"] if withheld else [None])
    assert ("acme.kit.faults.Busy" in code) is withheld


def test_an_except_star_clause_that_reads_an_attribute_of_its_error_is_refused() -> None:
    code, edits = tidy(f"{TRY}except* acme.kit.faults.Busy as error:\n    print(error.status)\n")
    assert "acme.kit.faults.Busy" in code
    assert reasons(edits) == ["attribute_removed"]


def test_a_refused_class_beside_a_renamed_one_is_left_to_the_flag() -> None:
    """`Failure` is not this rule's: the scan flags it, and the file is withheld as a whole."""
    body = f"{TRY}except (acme.kit.faults.Busy, acme.kit.faults.Failure):\n    pass\n"
    result = acme.scan(f"{HEADER}{body}", kit.SPEC)
    assert [(f.symbol, f.scan_status, f.bail) for f in result.findings] == [
        ("acme.kit.faults.Busy", "eligible", None),
        ("acme.kit.faults.Failure", "needs_review", "flag_only_surface"),
    ]


def test_a_second_run_finds_nothing_to_change() -> None:
    once, _ = tidy(f"{TRY}except acme.kit.faults.Busy:\n    pass\n", "import acme.kit.faults\n\n")
    again, edits = acme.transform(f"import acme.kit\n\n{once}", kit.ERRORS, spec=kit.SPEC)
    assert again.endswith(once)
    assert edits == []


def test_a_file_is_written_only_when_every_reference_in_it_is(tmp_path: Path) -> None:
    ok = "import acme.kit.faults\n\n\ndef f():\n    try:\n        run()\n"
    ok += "    except acme.kit.faults.Busy:\n        return 0\n"
    mixed = "import acme.kit\n\n\ndef f():\n    try:\n        run()\n"
    mixed += "    except (acme.kit.faults.Busy, acme.kit.faults.Failure):\n        return 0\n"
    called = "import acme.kit\n\n\ndef f():\n    raise acme.kit.faults.Busy('x')\n"
    alone = acme.repository(tmp_path / "alone", {"ok.py": ok}, spec=kit.SPEC, pack=kit.PACK)
    assert [outcome.path for outcome in alone.written] == ["ok.py"]
    written = alone.written[0].after.decode()
    assert written.startswith("import acme.kit\n\n")
    assert "except acme.kit.Busy:" in written
    # One distribution holds both APIs, so a file left behind keeps every other one as it was.
    files = {"ok.py": ok, "mixed.py": mixed, "called.py": called}
    run = acme.repository(tmp_path / "all", files, spec=kit.SPEC, pack=kit.PACK)
    assert run.written == ()
    held = {(edit.rule_id, edit.reason) for edit in run.edits if edit.status != "auto"}
    assert ("errors", "error_class_changed") in held
    assert ("flag-failure", "flag_only_surface") in held


def test_the_scan_reports_the_class_and_the_submodule_import_as_eligible() -> None:
    result = acme.scan(
        "import acme.kit.faults\n\nx = acme.kit.faults.Busy\ny = acme.kit.faults.Failure\n",
        kit.SPEC,
    )
    assert [(f.line, f.kind, f.symbol, f.scan_status) for f in result.findings] == [
        (1, "import", "acme.kit.faults", "eligible"),
        (3, "attribute", "acme.kit.faults.Busy", "eligible"),
        (4, "attribute", "acme.kit.faults.Failure", "needs_review"),
    ]

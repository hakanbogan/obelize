"""`upgrade` writes a file at a time where one distribution holds both APIs.

Without the option a pack like that writes a repository whole or not at all (`fix`, `scan` and
`--pack`, which have no referee); with it, a file is left as it was exactly when it holds a place of
its own that is left, the others are written, and the pins follow them. The packs are invented:
`acme.kit` keeps its module name and its distribution across the move, and `acme.sdk` has a
`configure` that other modules run on.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import acme
import acme_kept as kit
import fakefixer
import pytest
from fakefixer import FIXED
from fakefixer import SOURCE as OLD_NAMES

from obelize.models import WITHHELD, ManifestPlan
from obelize.packs import loader
from obelize.packs.schema import ManifestDependencyChange, ManifestDependencyParams
from obelize.scan import manifests
from obelize.transforms import codemod
from support import migrate

if TYPE_CHECKING:
    from pathlib import Path

    from obelize.models import ScanSpec
    from obelize.packs.schema import PackDocument

CLEAN = "import acme.kit\n\nreply = acme.kit.Greeter.say(name='a')\nprint(reply.reply.text)\n"
MOVED = CLEAN.replace("acme.kit.Greeter.say(name='a')", "acme.kit.talk.say(who='a')")
FLAGGED = "import acme.kit\nacme.kit.proxy = 'p'\n"
BROKEN = "import acme.kit\n\nreply = acme.kit.Greeter.say(name='b')\nprint(reply['reply'])\n"
PINNED = "acme-kit==1.5\n"
MOVED_PIN = "acme-kit>=2,<3\n"
# A source and a manifest at once: the rules edit its code and the pin check its requirement.
SETUP = "from setuptools import setup\nsetup(name='x', install_requires=['acme-kit==1.5'])\n"


def run(
    root: Path, files: dict[str, str], *, by_file: bool, sources: dict[str, bytes] | None = None
) -> codemod.Run:
    return acme.repository(
        root, files, spec=kit.SPEC, pack=kit.PACK, by_file=by_file, sources=sources
    )


def after(done: codemod.Run, files: dict[str, str]) -> dict[str, str]:
    return {**files, **{row.path: row.after.decode() for row in done.outcomes if row.written}}


def withheld(done: codemod.Run, path: str) -> list[str]:
    return [
        str(row.bail)
        for row in done.findings
        if str(row.path) == path and row.scan_status in WITHHELD
    ]


# Repositories where something is left, each a file or more that holds a place of its own.
REPOSITORIES: dict[str, dict[str, str]] = {
    "a flagged place": {"a.py": CLEAN, "b.py": FLAGGED, "requirements.txt": PINNED},
    "a response read that changed": {"a.py": CLEAN, "b.py": BROKEN, "requirements.txt": PINNED},
    "two files and one left": {
        "a.py": CLEAN,
        "pkg/c.py": CLEAN,
        "pkg/b.py": FLAGGED,
        "requirements.txt": PINNED,
    },
    "a pin in two manifests": {
        "a.py": CLEAN,
        "b.py": FLAGGED,
        "requirements.txt": PINNED,
        "dev/requirements.txt": "acme-kit>=1.3\n",
    },
}


@pytest.mark.parametrize("name", REPOSITORIES)
def test_a_written_file_holds_no_place_and_a_held_file_is_the_bytes_it_was(
    tmp_path: Path, name: str
) -> None:
    files = REPOSITORIES[name]
    done = run(tmp_path, files, by_file=True)
    assert done.apart
    for outcome in done.outcomes:
        if outcome.path in done.apart:
            assert (outcome.after, outcome.written) == (outcome.before, False), outcome.path
            assert all(row.status != "auto" for row in outcome.edits)
            assert withheld(done, outcome.path)
        elif outcome.written:
            assert not withheld(done, outcome.path), outcome.path
            assert all(row.status == "auto" for row in outcome.edits), outcome.path
    written = [outcome.path for outcome in done.written]
    assert written
    assert not set(written) & set(done.apart)
    assert all(row.scan_status not in WITHHELD for row in done.manifest_plan.findings)
    assert done.manifest_plan.blocking == ()


@pytest.mark.parametrize("name", REPOSITORIES)
def test_without_the_option_the_same_repository_is_written_as_it_always_was(
    tmp_path: Path, name: str
) -> None:
    """The golden is today's: every file as it was, each ready row held for the repository."""
    files = REPOSITORIES[name]
    done = run(tmp_path, files, by_file=False)
    assert (done.written, done.apart) == ((), ())
    assert after(done, files) == files
    assert {
        row.reason for row in done.edits if row.status == "needs_review" and row.path == "a.py"
    } == {"repo_not_fully_migrated"}
    assert all(row.bail != "file_not_fully_migrated" for row in done.findings if row.path == "a.py")
    assert done.manifest_plan.blocking == tuple(sorted(done.manifest_plan.blocking))
    assert {row.bail for row in done.manifest_plan.findings} == {"repo_not_fully_migrated"}
    assert run(tmp_path / "again", files, by_file=False) == done


def test_a_clean_file_is_written_and_a_flagged_one_left_and_the_pin_moves(tmp_path: Path) -> None:
    files = REPOSITORIES["a flagged place"]
    done = run(tmp_path, files, by_file=True)
    assert after(done, files) == {**files, "a.py": MOVED, "requirements.txt": MOVED_PIN}
    assert done.apart == ("b.py",)
    rows = [(row.path, row.line, row.status, row.reason) for row in done.edits]
    assert rows == [
        ("a.py", 3, "auto", None),
        ("b.py", 2, "needs_review", "flag_only_surface"),
        ("requirements.txt", 1, "auto", None),
    ]
    assert withheld(done, "b.py") == ["flag_only_surface"]


def test_a_file_with_a_place_of_its_own_and_a_ready_row_holds_that_row_for_the_file(
    tmp_path: Path,
) -> None:
    """A file is the unit: its ready row is held by the file's code and not the repository's."""
    mixed = CLEAN + "acme.kit.proxy = 'p'\n"
    files = {"a.py": CLEAN, "b.py": mixed, "requirements.txt": PINNED}
    done = run(tmp_path, files, by_file=True)
    held = next(outcome for outcome in done.files if outcome.path == "b.py")
    assert (held.after, held.written) == (mixed.encode(), False)
    rows = [(row.line, row.bail, row.caused_by) for row in done.findings if row.path == "b.py"]
    assert rows == [
        (3, "file_not_fully_migrated", ("flag_only_surface",)),
        (5, "flag_only_surface", None),
    ]
    assert done.apart == ("b.py",)


def test_a_pin_that_cannot_be_written_holds_the_whole_repository_as_it_did(tmp_path: Path) -> None:
    for index, extra in enumerate(
        [
            {"requirements.txt": "acme-kit[x]==1.5\n"},
            {
                "requirements.txt": "-c constraints.txt\nacme-kit==1.5\n",
                "constraints.txt": "acme-kit<2\n",
            },
        ]
    ):
        files = {"a.py": CLEAN, "b.py": FLAGGED, **extra}
        always = run(tmp_path / f"always{index}", files, by_file=False)
        now = run(tmp_path / f"now{index}", files, by_file=True)
        assert now == always
        assert (now.written, now.apart) == ((), ())
        assert "manifest_pin_shape_unsupported" in {row.bail for row in now.manifest_plan.findings}


def test_a_repository_where_no_file_can_be_written_is_what_it_was(tmp_path: Path) -> None:
    files = {"b.py": FLAGGED, "c.py": BROKEN, "requirements.txt": PINNED}
    now = run(tmp_path / "now", files, by_file=True)
    assert now == run(tmp_path / "always", files, by_file=False)
    assert (now.written, now.apart) == ((), ())
    assert {row.bail for row in now.manifest_plan.findings} == {"repo_not_fully_migrated"}
    assert now.manifest_plan.blocking == ("b.py", "c.py")


def test_a_result_another_module_reads_holds_the_file_that_made_it_and_no_other(
    tmp_path: Path,
) -> None:
    """`reach.read_elsewhere` withholds the call whose result `pkg/b.py` reads as a dictionary."""
    files = {
        "pkg/__init__.py": "",
        "pkg/a.py": CLEAN,
        "pkg/b.py": "from pkg.a import reply\n\nprint(reply['reply'])\n",
        "c.py": CLEAN,
        "requirements.txt": PINNED,
    }
    now = run(tmp_path / "now", files, by_file=True)
    assert now.apart == ("pkg/a.py",)
    assert withheld(now, "pkg/a.py") == ["response_shape_changed"]
    assert after(now, files) == {**files, "c.py": MOVED, "requirements.txt": MOVED_PIN}
    assert run(tmp_path / "always", files, by_file=False).written == ()


def test_a_notebook_that_calls_the_old_api_still_holds_the_pin_and_with_it_every_file(
    tmp_path: Path,
) -> None:
    book = (
        '{"cells": [{"cell_type": "code", "source": ["import acme.kit\\n", "acme.kit.Greeter()"]}]}'
    )
    files = {"a.py": CLEAN, "b.py": FLAGGED, "n.ipynb": book, "requirements.txt": PINNED}
    named = {name: text.encode() for name, text in files.items() if name != "n.ipynb"}
    now = run(tmp_path / "now", files, by_file=True, sources=named)
    assert now == run(tmp_path / "always", files, by_file=False, sources=named)
    assert (now.written, now.apart) == ((), ())
    assert now.manifest_plan.blocking == ("b.py", "n.ipynb")


def test_a_file_the_rules_and_the_manifest_pass_both_edit_is_one_outcome_and_one_write(
    tmp_path: Path,
) -> None:
    setup = CLEAN + SETUP
    files = {"setup.py": setup, "b.py": FLAGGED}
    done = run(tmp_path, files, by_file=True)
    assert [outcome.path for outcome in done.outcomes] == ["b.py", "setup.py"]
    assert done.apart == ("b.py",)
    (joined,) = done.written
    assert joined.after.decode() == setup.replace(
        "acme.kit.Greeter.say(name='a')", "acme.kit.talk.say(who='a')"
    ).replace("acme-kit==1.5", "acme-kit>=2,<3")
    assert [row.status for row in joined.edits] == ["auto", "auto"]


def test_a_pin_inside_a_file_that_is_left_holds_the_repository_as_it_did(tmp_path: Path) -> None:
    """`setup.py` holds a place of its own, so it stays as it was, and the pin is a line of it."""
    setup = FLAGGED + SETUP
    files = {"setup.py": setup, "a.py": CLEAN}
    now = run(tmp_path / "now", files, by_file=True)
    assert now == run(tmp_path / "always", files, by_file=False)
    assert (now.written, now.apart) == ((), ())


# `configure` sets a process-wide default: a module left on the legacy SDK with no `configure` of
# its own runs on another module's, so the one that holds the `configure` is held too.

PIN = ManifestDependencyChange(
    id="pin",
    kind="manifest_dependency",
    citation="Acme migration notes, 'Installing'",
    fixtures=("fixtures/negative/none.txt", "fixtures/positive/one.before.txt"),
    params=ManifestDependencyParams(from_name="acme-sdk", to_name="acme-sdk", to_spec=">=2"),
)
COUPLED_PACK: PackDocument = acme.PACK.model_copy(
    update={
        "to": acme.PACK.to.model_copy(update={"package": "acme-sdk"}),
        "changes": tuple(PIN if change.id == "pin" else change for change in acme.PACK.changes),
    }
)
COUPLED: ScanSpec = acme.SPEC.model_copy(update={"new_distribution": "acme-sdk"})

CONFIGURES = 'import acme.sdk as sdk\n\nsdk.configure(key="k")\n'
USES = 'M = sdk.Model("m")\n\n\ndef go(text):\n    return M.run(text).words\n'
RELIES = "import acme.sdk as sdk\n\n" + USES
BARE = '"""An import and nothing else."""\n\nimport acme.sdk as sdk\n'


def sdk(root: Path, files: dict[str, str], *, by_file: bool) -> codemod.Run:
    return acme.repository(root, files, spec=COUPLED, pack=COUPLED_PACK, by_file=by_file)


def test_a_file_a_configure_keeps_from_moving_is_a_file_that_is_left(tmp_path: Path) -> None:
    files = {
        "settings.py": CONFIGURES,
        "use.py": RELIES,
        "bare.py": BARE,
        "requirements.txt": "acme-sdk==0.1.0\n",
    }
    assert manifests.coupled(COUPLED)
    always = sdk(tmp_path / "always", files, by_file=False)
    assert always.written == ()
    done = sdk(tmp_path / "now", files, by_file=True)
    assert [outcome.path for outcome in done.written] == ["bare.py", "requirements.txt"]
    assert done.apart == ("settings.py", "use.py")
    held = next(outcome for outcome in done.files if outcome.path == "settings.py")
    assert held.after == held.before
    assert [(row.line, row.status, row.reason, row.caused_by) for row in held.edits] == [
        (1, "needs_review", "file_not_fully_migrated", ("configure_consumed_elsewhere",)),
        (3, "needs_review", "configure_consumed_elsewhere", None),
    ]
    assert done.manifest_plan.blocking == ()
    assert next(o for o in done.manifests if o.path == "requirements.txt").after == b"acme-sdk>=2\n"


def test_a_module_the_run_takes_off_the_old_sdk_does_not_keep_the_configure(tmp_path: Path) -> None:
    clean = CONFIGURES + "\n" + USES
    done = sdk(
        tmp_path,
        {"app.py": clean, "bare.py": BARE, "requirements.txt": "acme-sdk==0.1.0\n"},
        by_file=True,
    )
    assert done.apart == ()
    assert sorted(outcome.path for outcome in done.written) == [
        "app.py",
        "bare.py",
        "requirements.txt",
    ]


# A maintained tool writes a file only where the rules left no place in it.


def test_a_tool_is_run_on_the_files_that_are_written_and_never_on_one_that_is_left(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fakefixer.tool(monkeypatch)
    held = "import acme.kit as kit\n\nA = kit.old_a(1)\nkit.gone()\n"
    (tmp_path / "a.py").write_bytes(OLD_NAMES.encode())
    (tmp_path / "b.py").write_bytes(held.encode())
    always = migrate(tmp_path, fakefixer.SPEC, fakefixer.PACK)
    done = migrate(tmp_path, fakefixer.SPEC, fakefixer.PACK, by_file=True)
    assert always.written == ()
    assert [(outcome.path, outcome.after.decode()) for outcome in done.written] == [("a.py", FIXED)]
    assert done.apart == ("b.py",)
    assert [row.path for row in done.fixes] == ["a.py"]
    assert next(outcome for outcome in done.files if outcome.path == "b.py").after == held.encode()


def test_the_numpy_pack_writes_the_files_with_no_place_left_under_upgrade_and_none_under_fix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`upgrade numpy` reaches the bundled pack with the rule; `fix --pack` runs it without."""
    fakefixer.tool(monkeypatch, fakefixer.made("out = data.replace(b'np.float_', b'np.float64')"))
    loaded = loader.load("numpy/numpy-1-to-2")
    spec = loader.to_scan_spec(loaded)
    files = {
        "app.py": "import numpy as np\n\nSCALAR = np.float_(1)\n",
        "other.py": "import numpy as np\n\nX = np.asfarray([1])\n",
        "requirements.txt": "numpy==1.26.4\n",
    }
    for name, text in files.items():
        (tmp_path / name).write_bytes(text.encode())
    always = migrate(tmp_path, spec, loaded.pack)
    done = migrate(tmp_path, spec, loaded.pack, by_file=True)
    assert always.written == ()
    assert {outcome.path: outcome.after for outcome in done.written} == {
        "app.py": b"import numpy as np\n\nSCALAR = np.float64(1)\n",
        "requirements.txt": b"numpy>=2\n",
    }
    assert done.apart == ("other.py",)


# Several packs: a file left by one that another wrote is not left.


def test_the_files_left_by_each_pack_of_a_run_are_one_list_and_a_file_another_wrote_is_not_in_it(
    tmp_path: Path,
) -> None:
    files = REPOSITORIES["a flagged place"]
    first = run(tmp_path, files, by_file=True)
    other = codemod.Run(
        files=(codemod.Outcome("c.py", b"x\n", b"y\n", ()),),
        manifests=(),
        plans=(),
        manifest_plan=ManifestPlan(),
    )
    assert codemod.chained([("kit", first), ("other", other)]).apart == ("b.py",)
    rewrites = codemod.Run(
        files=(codemod.Outcome("b.py", b"x\n", b"y\n", ()),),
        manifests=(),
        plans=(),
        manifest_plan=ManifestPlan(),
    )
    assert codemod.chained([("kit", first), ("other", rewrites)]).apart == ()
    assert codemod.chained([("kit", replace(first, apart=("z.py", "b.py")))]).apart == (
        "b.py",
        "z.py",
    )


# The pin check: what a file left for a place of its own does and does not hold.


def test_a_file_that_is_left_blocks_no_pin_and_a_file_that_cannot_be_read_still_does(
    tmp_path: Path,
) -> None:
    done = run(tmp_path, REPOSITORIES["a flagged place"], by_file=True)
    plans = done.plans
    migration = manifests.survey(plans, paired=True)
    assert migration.blocking == ("b.py",)
    freed = manifests.survey(plans, paired=True, left=("b.py",))
    assert (freed.blocking, freed.migrated) == ((), ("a.py",))
    unread = manifests.survey(plans, ["x.py"], ["y.py"], paired=True, left=("b.py",))
    assert unread.blocking == ("y.py",)
    nothing = manifests.survey([p for p in plans if p.path != "a.py"], paired=True, left=("b.py",))
    assert (nothing.blocking, nothing.migrated) == ((), ())

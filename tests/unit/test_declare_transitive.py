"""`declare_transitive`: the pin moves by declaring what the legacy distribution installed.

openai 0.28.1 installed `requests`, `aiohttp` and `tqdm` for an app that imports one without
declaring it, and 1.109.1 and 3.26.0 do not. The pack asks the pin to wait until a manifest of the
app declares each; with the flag the run declares it, unpinned, on a line below the legacy
requirement of a requirements file, and in any other layout the pin still waits.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from obelize.cli import app
from obelize.models import Finding, ManifestPlan, ScanSpec
from obelize.packs import loader
from obelize.scan import manifests
from obelize.transforms import manifest as manifest_rules
from obelize.transforms.registry import manifest_rule_for
from platforms import PYTHON
from support import committed

BUNDLED = loader.load("openai/openai-0-to-1")
OPENAI = loader.to_scan_spec(BUNDLED)
SHARED = OPENAI.model_copy(update={"declare_transitive": False})

# The pack's own rule, so what is written is what a run writes.
CHANGE = next(change for change in BUNDLED.pack.changes if change.kind == "manifest_dependency")
RULE = manifest_rule_for(CHANGE)
assert RULE is not None


def planned(
    files: Mapping[str, str],
    *,
    migrated: tuple[str, ...] = ("app.py",),
    blocking: tuple[str, ...] = (),
    needs: tuple[tuple[str, str], ...] = (),
    spec: ScanSpec = OPENAI,
) -> ManifestPlan:
    found = [
        row for name, text in files.items() for row in manifests.declarations(name, text.encode())
    ]
    migration = manifests.Migration(
        migrated=migrated, blocking=blocking, transitive=tuple(sorted(set(needs)))
    )
    return manifests.plan(found, migration, spec)


def rows(plan: ManifestPlan) -> list[tuple[str, int, str, str, str | None]]:
    return [
        (row.path, row.line, row.symbol or "", row.scan_status, row.bail) for row in plan.findings
    ]


def written(name: str, text: str, plan: ManifestPlan) -> tuple[str, list[tuple[int, str]]]:
    """What the pack's rule makes of one manifest, and the status of each edit."""
    assert RULE is not None
    context = manifest_rules.ManifestContext.build(name, text.encode(), plan)
    edits = RULE.apply(context)
    return manifest_rules.finish(context).decode(), [(row.line, row.status) for row in edits]


NEEDS = (("app.py", "requests"), ("app.py", "tqdm"))
PINNED = {"requirements.txt": "flask==3.0\nopenai==0.28.1  # chat\nrich\n"}


def test_the_pin_moves_and_each_distribution_the_code_imports_is_declared_below_it() -> None:
    plan = planned(PINNED, needs=NEEDS)
    assert rows(plan) == [
        ("requirements.txt", 2, "openai", "eligible", None),
        ("requirements.txt", 2, "requests", "eligible", None),
        ("requirements.txt", 2, "tqdm", "eligible", None),
    ]
    assert plan.transitive == ()
    text, edits = written("requirements.txt", PINNED["requirements.txt"], plan)
    assert text == "flask==3.0\nopenai>=1.109.1  # chat\nrequests\ntqdm\nrich\n"
    assert edits == [(2, "auto"), (2, "auto"), (2, "auto")]


def test_without_the_flag_the_pin_waits_as_it_did() -> None:
    plan = planned(PINNED, needs=NEEDS, spec=SHARED)
    assert rows(plan) == [
        ("requirements.txt", 2, "openai", "needs_review", "transitive_dependency_in_use")
    ]
    assert plan.transitive == ("app.py",)


def test_a_distribution_a_manifest_of_the_same_app_declares_is_not_written_again() -> None:
    files = {**PINNED, "requirements-dev.txt": "requests>=2\n"}
    plan = planned(files, needs=NEEDS)
    assert [row[2] for row in rows(plan)] == ["openai", "tqdm"]
    assert planned(files, needs=(("app.py", "requests"),)).findings[0].scan_status == "eligible"


def test_a_constraints_file_declares_nothing_so_the_distribution_is_still_written() -> None:
    files = {**PINNED, "constraints.txt": "requests>=2\n"}
    assert [row[2] for row in rows(planned(files, needs=NEEDS))] == ["openai", "requests", "tqdm"]


def test_each_app_is_declared_below_the_requirement_nearest_its_files() -> None:
    files = {
        "requirements.txt": "openai==0.28.1\n",
        "web/requirements.txt": "openai==0.28.1\n",
        "jobs/requirements/base.txt": "openai==0.28.1\n",
    }
    needs = (
        ("web/app.py", "requests"),
        ("jobs/run.py", "aiohttp"),
        ("tools/run.py", "tqdm"),
        ("web/deep/view.py", "requests"),
    )
    plan = planned(files, migrated=("web/app.py",), needs=needs)
    assert rows(plan) == [
        ("jobs/requirements/base.txt", 1, "aiohttp", "eligible", None),
        ("jobs/requirements/base.txt", 1, "openai", "eligible", None),
        ("requirements.txt", 1, "openai", "eligible", None),
        ("requirements.txt", 1, "tqdm", "eligible", None),
        ("web/requirements.txt", 1, "openai", "eligible", None),
        ("web/requirements.txt", 1, "requests", "eligible", None),
    ]


def test_a_distribution_the_files_of_two_apps_import_is_written_once_for_each_app() -> None:
    files = {"a/requirements.txt": "openai==0.28.1\n", "b/requirements.txt": "openai==0.28.1\n"}
    needs = (("a/x.py", "requests"), ("b/x.py", "requests"), ("a/y.py", "requests"))
    plan = planned(files, migrated=("a/x.py",), needs=needs)
    assert [(row[0], row[2]) for row in rows(plan)] == [
        ("a/requirements.txt", "openai"),
        ("a/requirements.txt", "requests"),
        ("b/requirements.txt", "openai"),
        ("b/requirements.txt", "requests"),
    ]


def test_the_distribution_is_named_as_pip_would_fold_it() -> None:
    plan = planned(PINNED, needs=(("app.py", "Charset_Normalizer"),))
    assert [row[2] for row in rows(plan)] == ["charset-normalizer", "openai"]


@pytest.mark.parametrize(
    "files",
    [
        {"pyproject.toml": '[tool.poetry.dependencies]\nopenai = "0.28.1"\n'},
        {"Pipfile": '[packages]\nopenai = "==0.28.1"\n'},
        {"setup.cfg": "[options]\ninstall_requires =\n    openai==0.28.1\n"},
        {"setup.py": "from setuptools import setup\nsetup(install_requires=['openai==0.28.1'])\n"},
    ],
    ids=["poetry", "pipfile", "setup-cfg", "setup-py"],
)
def test_a_pin_in_any_other_layout_still_waits_for_a_manifest_to_declare_the_module(
    files: dict[str, str],
) -> None:
    plan = planned(files, needs=NEEDS)
    assert {(row[3], row[4]) for row in rows(plan)} == {
        ("needs_review", "transitive_dependency_in_use")
    }
    assert plan.transitive == ("app.py",)


def test_one_file_nothing_can_declare_for_keeps_the_pin_waiting_everywhere() -> None:
    """The requirement that could host the other file's imports would move without the pin."""
    files = {
        "web/requirements.txt": "openai==0.28.1\n",
        "jobs/requirements.txt": "openai==0.28.1\n",
    }
    plan = planned(
        files, migrated=("web/x.py",), needs=(("web/x.py", "requests"), ("tools/x.py", "tqdm"))
    )
    assert {(row[3], row[4]) for row in rows(plan)} == {
        ("needs_review", "transitive_dependency_in_use")
    }
    assert plan.transitive == ("tools/x.py", "web/x.py")


def test_a_requirement_that_cannot_be_copied_is_no_place_to_declare_below() -> None:
    plan = planned({"requirements.txt": "openai[datalib]==0.28.1\n"}, needs=NEEDS)
    assert rows(plan) == [
        ("requirements.txt", 1, "openai", "needs_review", "manifest_pin_shape_unsupported")
    ]


def test_a_requirement_with_extras_the_release_provides_is_no_place_to_declare_below_either() -> (
    None
):
    spec = OPENAI.model_copy(update={"new_extras": ("datalib",)})
    files = {"requirements.txt": "openai[datalib]==0.28.1\n"}
    assert rows(planned(files, spec=spec)) == [("requirements.txt", 1, "openai", "eligible", None)]
    assert rows(planned(files, needs=NEEDS, spec=spec)) == [
        ("requirements.txt", 1, "openai", "needs_review", "transitive_dependency_in_use")
    ]


def test_a_requirement_that_has_arrived_is_no_place_either() -> None:
    files = {"requirements.txt": "openai>=1.109.1\n", "constraints.txt": "openai==0.28.1\n"}
    plan = planned(files, needs=NEEDS)
    assert [(row[0], row[3], row[4]) for row in rows(plan)] == [
        ("constraints.txt", "needs_review", "manifest_pin_shape_unsupported")
    ]


def test_a_file_that_still_imports_the_legacy_module_holds_the_pin_and_declares_nothing() -> None:
    plan = planned(PINNED, blocking=("old.py",), needs=NEEDS)
    assert rows(plan) == [
        ("requirements.txt", 2, "openai", "needs_review", "repo_not_fully_migrated")
    ]
    assert plan.transitive == ("app.py",)


def test_nothing_is_declared_where_nothing_needs_it() -> None:
    plan = planned(PINNED)
    assert rows(plan) == [("requirements.txt", 2, "openai", "eligible", None)]


def test_two_distributions_with_the_flag_replace_the_pin_and_declare_below_it() -> None:
    """The flag is not only for one distribution: the legacy line is the new one, then the rest."""
    spec = OPENAI.model_copy(
        update={"new_distribution": "openai-next", "new_range": None, "legacy_range": ">=0.27.0,<1"}
    )
    plan = planned(PINNED, needs=NEEDS, spec=spec)
    assert [(row[2], row[3]) for row in rows(plan)] == [
        ("openai", "eligible"),
        ("requests", "eligible"),
        ("tqdm", "eligible"),
    ]


# What the rule writes.


def test_a_declaration_takes_the_indent_and_the_line_ending_of_the_requirement_it_follows() -> None:
    source = "  openai==0.28.1\r\nrich\r\n"
    plan = planned({"requirements.txt": source}, needs=NEEDS)
    text, _edits = written("requirements.txt", source, plan)
    assert text == "  openai>=1.109.1\r\n  requests\r\n  tqdm\r\nrich\r\n"


def test_a_requirement_on_the_last_line_with_no_newline_is_followed_by_the_others() -> None:
    plan = planned({"requirements.txt": "openai==0.28.1"}, needs=NEEDS)
    text, _edits = written("requirements.txt", "openai==0.28.1", plan)
    assert text == "openai>=1.109.1\nrequests\ntqdm"


def test_a_marker_or_a_comment_is_left_on_the_line_it_was_written_on() -> None:
    source = 'openai==0.28.1 ; python_version < "3.13"  # chat\n'
    plan = planned({"requirements.txt": source}, needs=NEEDS)
    text, _edits = written("requirements.txt", source, plan)
    assert text == 'openai>=1.109.1 ; python_version < "3.13"  # chat\nrequests\ntqdm\n'


def test_the_rule_writes_nothing_where_the_scan_planned_nothing_below_the_pin() -> None:
    plan = planned(PINNED)
    text, edits = written("requirements.txt", PINNED["requirements.txt"], plan)
    assert text == "flask==3.0\nopenai>=1.109.1  # chat\nrich\n"
    assert edits == [(2, "auto")]


def test_a_row_for_another_distribution_is_the_rules_only_where_it_declares_them() -> None:
    row = Finding.model_validate(
        {
            "path": "requirements.txt",
            "line": 1,
            "column": 0,
            "kind": "manifest",
            "confidence_reason": "manifest_dependency",
            "symbol": "requests",
            "scan_status": "eligible",
        }
    )
    other = Finding.model_validate({**row.model_dump(), "symbol": "openai"})
    assert RULE is not None
    assert RULE.claims(row) is True
    assert RULE.claims(other) is True
    code = {**row.model_dump(), "kind": "import", "confidence_reason": "direct_import_resolved"}
    assert RULE.claims(Finding.model_validate(code)) is False


def test_a_row_for_a_line_the_pin_check_cannot_write_is_refused_where_it_is() -> None:
    """The plan never asks for it, so the rule's own refusal is the second line of defence."""
    source = "openai[datalib]==0.28.1\n"
    row = Finding.model_validate(
        {
            "path": "requirements.txt",
            "line": 1,
            "column": 0,
            "kind": "manifest",
            "confidence_reason": "manifest_dependency",
            "symbol": "requests",
            "scan_status": "eligible",
        }
    )
    text, edits = written("requirements.txt", source, ManifestPlan(findings=(row,)))
    assert text == source
    assert edits == [(1, "needs_review")]


def test_the_other_pack_that_declares_nothing_claims_only_its_own_two_distributions() -> None:
    from obelize.packs.schema import ManifestDependencyChange

    gemini = loader.load("gemini/google-generativeai-to-google-genai").pack
    change = next(
        change for change in gemini.changes if isinstance(change, ManifestDependencyChange)
    )
    rule = manifest_rule_for(change)
    assert rule is not None
    other = Finding.model_validate(
        {
            "path": "requirements.txt",
            "line": 1,
            "column": 0,
            "kind": "manifest",
            "confidence_reason": "manifest_dependency",
            "symbol": "requests",
            "scan_status": "eligible",
        }
    )
    assert rule.claims(other) is False


# From a repository to a run, and back.

runner_ = CliRunner()
QUIET = f"{PYTHON} -c pass"


def command(tree: Path, *arguments: str) -> Any:
    return runner_.invoke(app, [*arguments, "--repo", str(tree)])


APP = (
    "import openai\nimport requests\nfrom tqdm import tqdm\n\n"
    "response = openai.ChatCompletion.create(model='m', messages=[])\n"
    "requests.get('https://example.invalid')\n"
)


def test_an_apply_declares_what_the_app_imports_and_an_undo_restores_every_byte(
    tmp_path: Path,
) -> None:
    files = {"app.py": APP, "requirements.txt": "flask==3.0\r\nopenai==0.28.1  # chat\r\nrich\r\n"}
    tree = committed(tmp_path / "repo", files)
    result = command(tree, "fix", "--apply", "--allow-dirty", "--verify", QUIET)
    assert result.exit_code == 0, result.output
    assert (tree / "requirements.txt").read_bytes() == (
        b"flask==3.0\r\nopenai>=1.109.1  # chat\r\nrequests\r\ntqdm\r\nrich\r\n"
    )
    assert "openai.chat.completions.create" in (tree / "app.py").read_text(encoding="utf-8")
    name = (tree / ".obelize" / "latest").read_text(encoding="utf-8").strip()
    undone = command(tree, "undo", "--run", name)
    assert undone.exit_code == 0, undone.output
    for path, text in files.items():
        assert (tree / path).read_bytes() == text.encode(), path


def test_a_pin_in_a_pyproject_still_waits_and_nothing_is_written(tmp_path: Path) -> None:
    files = {
        "app.py": APP,
        "pyproject.toml": '[project]\nname = "x"\ndependencies = ["openai==0.28.1"]\n',
    }
    tree = committed(tmp_path / "repo", files)
    result = command(tree, "fix", "--apply", "--allow-dirty", "--verify", QUIET)
    assert result.exit_code == 4, result.output
    assert "transitive_dependency_in_use" in result.output
    for path, text in files.items():
        assert (tree / path).read_text(encoding="utf-8") == text, path

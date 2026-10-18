"""`obelize scan --library`: a library with no pack, listed and never rewritten."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner, Result

from obelize.cli import app
from obelize.models import Config, ScanSpec
from obelize.packs import loader
from obelize.scan import inventory
from obelize.scan import runner as scanner
from support import write_tree

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

APP = """import requests
from requests.adapters import HTTPAdapter
import yaml

session = requests.Session()
session.mount("https://", HTTPAdapter(max_retries=3))


def fetch(url):
    return requests.get(url, timeout=5).json()
"""

PLAIN = "def add(left: int, right: int) -> int:\n    return left + right\n"


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    return write_tree(
        tmp_path / "repo",
        {"app.py": APP, "plain.py": PLAIN, "requirements.txt": "requests==2.31.0\nflask>=2\n"},
    )


def _scan(tree: Path, *extra: str) -> Result:
    return runner.invoke(app, ["scan", "--repo", str(tree), *extra])


def _record(tree: Path) -> dict[str, Any]:
    latest = (tree / ".obelize" / "latest").read_text(encoding="utf-8").strip()
    folder = tree / ".obelize" / "runs" / latest
    loaded: dict[str, Any] = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    return loaded


def _environment(tree: Path, distribution: str, files: list[str], **extra: str) -> Path:
    """An environment kept in the repository, whose distribution installed `files`."""
    packages = tree / ".venv" / "lib" / "python3.12" / "site-packages"
    info = packages / f"{distribution}-1.0.dist-info"
    write_tree(info, {"RECORD": "".join(f"{name},sha256=x,1\n" for name in files), **extra})
    return packages


# The scan.


def test_every_place_of_the_library_is_listed_and_withheld_for_want_of_a_pack(
    tree: Path,
) -> None:
    result = _scan(tree, "--library", "requests", "--json")
    assert result.exit_code == 0, result.output
    rows = json.loads(result.stdout)["findings"]
    code = [row for row in rows if row["kind"] != "manifest"]
    assert [row["symbol"] for row in code] == [
        "requests",
        "requests.adapters",
        "requests.Session",
        "requests.adapters.HTTPAdapter",
        "requests.get.json",
    ]
    assert {(row["scan_status"], row["bail"]) for row in code} == {
        ("needs_review", "no_pack_for_usage")
    }


def test_the_libraries_lines_in_a_manifest_are_context_and_no_other_library_is_listed(
    tree: Path,
) -> None:
    rows = json.loads(_scan(tree, "--library", "requests", "--json").stdout)["findings"]
    manifest = [row for row in rows if row["kind"] == "manifest"]
    assert [(row["path"], row["symbol"], row["scan_status"]) for row in manifest] == [
        ("requirements.txt", "requests", "not_a_usage")
    ]
    assert not [row for row in rows if "yaml" in (row["symbol"] or "")]


def test_the_table_says_nothing_is_rewritten_and_offers_no_fix(tree: Path) -> None:
    result = _scan(tree, "--library", "requests")
    assert result.exit_code == 0
    assert "obelize scan  inventory/requests" in result.stdout
    assert "no_pack_for_usage" in result.stdout
    assert "rewrites nothing" in result.stdout
    assert "Next: obelize fix" not in result.stdout
    assert "No pack applies" not in result.stdout


def test_the_run_folder_records_an_inventory_with_no_copy_of_a_pack(tree: Path) -> None:
    _scan(tree, "--library", "requests")
    (pack,) = _record(tree)["packs"]
    assert pack["id"] == "inventory/requests"
    assert pack["source"] == "inventory"
    folder = tree / ".obelize" / "runs" / (tree / ".obelize" / "latest").read_text().strip()
    assert not (folder / "packs").exists()
    findings = json.loads((folder / "findings.json").read_text(encoding="utf-8"))
    assert findings["packs"][0]["sha256"] == pack["sha256"]


def test_no_file_of_the_repository_changes(tree: Path) -> None:
    before = {p.name: p.read_bytes() for p in tree.iterdir() if p.is_file()}
    _scan(tree, "--library", "requests")
    assert {p.name: p.read_bytes() for p in tree.iterdir() if p.is_file()} == before


def test_two_inventories_of_one_input_print_the_same_bytes(tree: Path) -> None:
    first = _scan(tree, "--library", "requests", "--json").stdout
    assert first == _scan(tree, "--library", "requests", "--json").stdout


def test_an_inventory_can_fail_a_job_like_any_scan(tree: Path) -> None:
    assert _scan(tree, "--library", "requests", "--fail-on", "needs_review").exit_code == 4
    assert _scan(tree, "--library", "requests", "--fail-on", "eligible").exit_code == 0


def test_an_inventory_prints_as_sarif(tree: Path) -> None:
    (run,) = json.loads(_scan(tree, "--library", "requests", "--sarif").stdout)["runs"]
    assert {rule["id"] for rule in run["tool"]["driver"]["rules"]} == {"no_pack_for_usage"}
    assert {result["level"] for result in run["results"]} == {"warning"}


def test_a_library_the_repository_does_not_use_lists_nothing(tree: Path) -> None:
    result = _scan(tree, "--library", "numpy", "--json")
    assert result.exit_code == 0
    assert json.loads(result.stdout)["findings"] == []


# Where the modules come from.


def test_the_modules_say_where_they_came_from(tree: Path) -> None:
    named = _scan(tree, "--library", "PyYAML", "--module", "yaml")
    assert "yaml (named with --module)" in named.stderr
    assumed = _scan(tree, "--library", "requests")
    assert "requests (taken from its name" in assumed.stderr


def test_a_module_named_with_module_is_the_one_listed(tree: Path) -> None:
    rows = json.loads(_scan(tree, "--library", "PyYAML", "--module", "yaml", "--json").stdout)[
        "findings"
    ]
    assert [row["symbol"] for row in rows] == ["yaml"]


def test_the_modules_a_distribution_installed_in_the_repository_are_the_ones_listed(
    tree: Path,
) -> None:
    _environment(tree, "PyYAML", ["yaml/__init__.py", "yaml/loader.py", "_yaml/__init__.py"])
    result = _scan(tree, "--library", "PyYAML", "--json")
    assert "(installed in an environment in the repository)" in result.stderr
    symbols = [row["symbol"] for row in json.loads(result.stdout)["findings"]]
    assert symbols == ["yaml"]


def test_a_distribution_is_found_under_any_spelling_of_its_name(tmp_path: Path) -> None:
    _environment(tmp_path, "typing_extensions", ["typing_extensions.py"])
    assert inventory.modules(tmp_path, "typing-extensions") == ("typing_extensions",)


def test_a_namespace_package_gives_the_package_under_it_and_not_the_namespace(
    tmp_path: Path,
) -> None:
    _environment(
        tmp_path,
        "google_generativeai",
        [
            "google/generativeai/__init__.py",
            "google/generativeai/types/__init__.py",
            "google/generativeai/types/content.py",
            "../../../bin/tool",
        ],
    )
    assert inventory.modules(tmp_path, "google-generativeai") == ("google.generativeai",)


def test_top_level_txt_answers_where_the_record_is_gone(tmp_path: Path) -> None:
    packages = _environment(
        tmp_path, "Pillow", [], **{"top_level.txt": "PIL\n__pycache__\nnot ok\n"}
    )
    (packages / "Pillow-1.0.dist-info" / "RECORD").unlink()
    assert inventory.modules(tmp_path, "Pillow") == ("PIL",)


def test_a_distribution_with_neither_a_record_nor_a_top_level_list_has_no_modules(
    tmp_path: Path,
) -> None:
    packages = _environment(tmp_path, "bare", [])
    (packages / "bare-1.0.dist-info" / "RECORD").unlink()
    assert inventory.modules(tmp_path, "bare") == ()


def test_another_distribution_beside_it_is_not_read(tmp_path: Path) -> None:
    _environment(tmp_path, "other", ["other/__init__.py"])
    packages = _environment(tmp_path, "wanted", ["wanted/__init__.py"])
    (packages / "not-a-distribution").mkdir()
    assert inventory.modules(tmp_path, "wanted") == ("wanted",)


def test_a_distribution_that_is_not_installed_has_no_modules(tmp_path: Path) -> None:
    assert inventory.modules(tmp_path, "requests") == ()


def test_a_single_file_module_is_a_module(tmp_path: Path) -> None:
    _environment(tmp_path, "six", ["six.py", "six-1.0.dist-info/RECORD"])
    assert inventory.modules(tmp_path, "six") == ("six",)


# The spec.


def test_the_spec_of_an_inventory_names_the_modules_and_tokens_it_looks_for() -> None:
    spec = inventory.spec("google-generativeai", ("google.generativeai", "google.generativeai"))
    assert spec.legacy_modules == ("google.generativeai",)
    assert spec.prefilter_tokens == ("generativeai",)
    assert spec.inventory
    assert spec.pack_id == "inventory/google-generativeai"


def test_the_hash_of_an_inventory_is_of_the_library_and_its_modules() -> None:
    first = inventory.spec("requests", ("requests",)).pack_sha256
    assert first == inventory.spec("requests", ("requests",)).pack_sha256
    assert first != inventory.spec("requests", ("requests", "urllib3")).pack_sha256
    assert first != inventory.spec("urllib3", ("requests",)).pack_sha256


def test_a_spec_that_is_no_inventory_digests_as_it_did_before_the_field_existed() -> None:
    spec = loader.to_scan_spec(loader.load("py-pdf/pypdf2-to-pypdf"))
    assert not spec.inventory
    assert "inventory" not in str(sorted(spec.model_dump(mode="json", exclude_defaults=True)))
    plain = ScanSpec.model_validate({**spec.model_dump(), "inventory": False})
    assert loader.spec_digest(plain) == loader.spec_digest(spec)
    assert loader.spec_digest(plain) != loader.spec_digest(
        ScanSpec.model_validate({**spec.model_dump(), "inventory": True})
    )


def test_a_scan_of_a_pack_never_grades_a_place_no_pack_for_usage(tree: Path) -> None:
    spec = loader.to_scan_spec(loader.load("py-pdf/pypdf2-to-pypdf"))
    scan = scanner.scan(tree, Config(), spec, jobs=1)
    assert "no_pack_for_usage" not in {row.bail for row in scan.findings}


# The usage errors.


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--library", "requests", "--pack", "py-pdf/pypdf2-to-pypdf"], "--pack names one"),
        (["--module", "requests"], "pass --library too"),
        (["--library", "requests", "--module", "not a module"], "dotted module names"),
        (["--library", "not a distribution", "--module", "x"], "takes a distribution name"),
    ],
    ids=["with-pack", "module-alone", "bad-module", "bad-distribution"],
)
def test_a_flag_that_does_not_fit_is_a_usage_error(
    tree: Path, argv: list[str], message: str
) -> None:
    result = _scan(tree, *argv)
    assert result.exit_code == 2
    assert message in result.output
    assert not (tree / ".obelize" / "runs").exists()


# The pointer when no pack applies.


def test_when_no_pack_applies_the_scan_names_what_the_repository_imports_most(tree: Path) -> None:
    result = _scan(tree)
    assert "The repository imports these most: requests (1 file), yaml (1 file)." in result.stdout
    assert f"Next: obelize scan --library requests --module requests --repo {tree}" in (
        result.stdout
    )


def test_what_is_imported_leaves_out_the_standard_library_and_the_repositorys_own_modules(
    tmp_path: Path,
) -> None:
    root = write_tree(
        tmp_path,
        {
            "main.py": "import os, sys\nimport helpers\nimport requests, numpy.linalg as la\n",
            "helpers.py": "from requests import get\nfrom . import sibling\nimport __future__\n",
            "pkg/inner.py": "import pkg.other\nimport numpy\n",
        },
    )
    tree = scanner.read(root, Config(), ())
    assert inventory.imported(tree) == (("numpy", 2), ("requests", 2))
    assert inventory.imported(tree, limit=1) == (("numpy", 2),)


def test_a_repository_that_imports_nothing_outside_itself_names_nothing(tmp_path: Path) -> None:
    root = write_tree(tmp_path, {"main.py": "import os\n", "empty.py": ""})
    assert inventory.imported(scanner.read(root, Config(), ())) == ()
    result = runner.invoke(app, ["scan", "--repo", str(root)])
    assert "The repository imports" not in result.stdout


def test_a_file_that_cannot_be_read_imports_nothing(tmp_path: Path) -> None:
    root = write_tree(tmp_path, {"main.py": "import requests\n"})
    tree = scanner.read(root, Config(max_file_bytes=4), ())
    assert inventory.imported(tree) == ()

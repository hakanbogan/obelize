"""A requirement that names extras keeps them when its one distribution moves to a release that
provides every one (ADR-077), and in no other case: each form where the edit is not a replacement
of the version alone stays as it was. Nothing is assumed: a pack that states none behaves as before.
"""

from __future__ import annotations

from pathlib import Path

import acme
import acme_kept as kit
import pytest

from obelize.models import ScanSpec
from obelize.packs import loader
from obelize.packs.schema import (
    ManifestDependencyChange,
    ManifestDependencyParams,
    PackDocument,
)
from obelize.scan import manifests
from obelize.scan.manifests import Migration

CLEAR = Migration(migrated=("app.py",))
BLOCKED = Migration(migrated=("app.py",), blocking=("legacy.py",))
WITHHELD = (1, "needs_review", "manifest_pin_shape_unsupported")


def pin(*extras: str) -> ManifestDependencyChange:
    return ManifestDependencyChange(
        id="pin",
        kind="manifest_dependency",
        citation="Acme Kit 2 metadata, 'Provides-Extra'",
        fixtures=("fixtures/negative/none.txt", "fixtures/positive/one.before.txt"),
        params=ManifestDependencyParams(
            from_name="acme-kit", to_name="acme-kit", to_spec=">=2,<3", provides_extras=extras
        ),
    )


def stated(*extras: str) -> tuple[PackDocument, ScanSpec, ManifestDependencyChange]:
    """The pack of `acme_kept` with the dependency rule stating `extras`, and its scan spec."""
    change = pin(*extras)
    made = kit.PACK.model_copy(update={"changes": (*kit.PACK.changes[:-1], change)})
    loaded = loader.LoadedPack(
        pack=made, sha256="0" * 64, data=b"", reference=made.id, bundled=False, path=Path("p.yaml")
    )
    return made, loader.to_scan_spec(loaded), change


PACK, SPEC, CHANGE = stated("cli", "grpc")
PLAIN_PACK, PLAIN_SPEC, PLAIN_CHANGE = stated()


def declared(
    name: str, source: str, migration: Migration = CLEAR, *, states: bool = True
) -> tuple[str, list[tuple[int, str, str | None]]]:
    spec, change = (SPEC, CHANGE) if states else (PLAIN_SPEC, PLAIN_CHANGE)
    produced, edits = acme.declared(name, source, migration, spec=spec, change=change)
    return produced, [(row.line, row.status, row.reason) for row in edits]


def test_a_pack_that_states_the_extras_the_release_provides_is_projected_into_the_spec() -> None:
    assert SPEC.new_extras == ("cli", "grpc")
    assert PLAIN_SPEC.new_extras == ()


@pytest.mark.parametrize(
    ("line", "moved"),
    [
        ("acme-kit[cli]==1.5\n", "acme-kit[cli]>=2,<3\n"),
        ("acme-kit[cli,grpc]>=1.2,<2\n", "acme-kit[cli,grpc]>=2,<3\n"),
        ("acme-kit [ grpc , cli ] >= 1.2\n", "acme-kit [ grpc , cli ]>=2,<3\n"),
        ("Acme_Kit[CLI]==1.5  # the cli\n", "acme-kit[CLI]>=2,<3  # the cli\n"),
        (
            "acme-kit[cli]==1.5 ; python_version >= '3.9'\n",
            "acme-kit[cli]>=2,<3 ; python_version >= '3.9'\n",
        ),
        ("acme-kit[cli]\n", "acme-kit[cli]>=2,<3\n"),
        (
            "acme-kit[cli]==1.5 --config-settings x=y\n",
            "acme-kit[cli]>=2,<3 --config-settings x=y\n",
        ),
        ("acme-kit[c_li]==1.5\n", None),
    ],
)
def test_the_version_after_the_extras_is_all_a_requirements_file_edit_replaces(
    line: str, moved: str | None
) -> None:
    produced, edits = declared("requirements.txt", line)
    if moved is None:
        assert (produced, edits) == (line, [WITHHELD])
    else:
        assert (produced, edits) == (moved, [(1, "auto", None)])


def test_an_extra_in_another_spelling_is_the_extra_the_release_provides() -> None:
    """PEP 685 folds case and `-_.`: `Cli` and `c.li` are one name."""
    _pack, spec, change = stated("c-li")
    produced, edits = acme.declared(
        "requirements.txt",
        "acme-kit[C_LI]==1.5\nacme-kit[c.li]==1.5\n",
        CLEAR,
        spec=spec,
        change=change,
    )
    assert produced == "acme-kit[C_LI]>=2,<3\nacme-kit[c.li]>=2,<3\n"
    assert [row.status for row in edits] == ["auto", "auto"]


@pytest.mark.parametrize(
    "line",
    [
        "acme-kit[cli,other]==1.5\n",
        "acme-kit[other]==1.5\n",
        "acme-kit[CLI,Other]==1.5\n",
    ],
)
def test_one_extra_the_release_does_not_provide_leaves_the_line_as_it_was(line: str) -> None:
    produced, edits = declared("requirements.txt", line)
    assert (produced, edits) == (line, [WITHHELD])


@pytest.mark.parametrize("line", ["acme-kit[cli]==1.5\n", "acme-kit[cli,grpc]==1.5\n"])
def test_a_pack_that_states_no_extras_leaves_every_line_with_extras_as_it_was(line: str) -> None:
    produced, edits = declared("requirements.txt", line, states=False)
    assert (produced, edits) == (line, [WITHHELD])


@pytest.mark.parametrize(
    "line",
    [
        "acme-kit[cli]==1.5 --hash=sha256:aaaa\n",
        "acme-kit[cli]==1.5 \\\n    --hash=sha256:aaaa\n",
        "acme-kit[cli] \\\n    ==1.5\n",
        "-e git+https://example.invalid/kit.git#egg=acme-kit[cli]\n",
        "acme-kit[cli] @ https://example.invalid/kit.whl\n",
    ],
)
def test_a_requirement_with_extras_that_says_more_than_a_version_stays_as_it_was(line: str) -> None:
    produced, edits = declared("requirements.txt", line)
    assert produced == line
    assert [(row[1], row[2]) for row in edits] == [WITHHELD[1:]]


@pytest.mark.parametrize("line", ["acme-kit[cli]>=2.1\n", "acme-kit[nobody]~=2.0\n"])
def test_a_requirement_with_extras_that_already_names_the_new_release_has_nothing_to_move(
    line: str,
) -> None:
    """It is judged by its version alone, so an extra the release lacks is not a reason to hold."""
    assert declared("requirements.txt", line) == (line, [])


@pytest.mark.parametrize("name", ["requirements.in", "constraints.txt", "dev-constraints.txt"])
def test_a_constraints_file_and_a_pip_tools_input_are_never_written(name: str) -> None:
    produced, edits = declared(name, "acme-kit[cli]==1.5\n")
    assert (produced, edits) == ("acme-kit[cli]==1.5\n", [WITHHELD])


def test_extras_are_kept_in_a_pep_621_array_and_the_rest_of_the_file_is_untouched() -> None:
    source = (
        '[project]\nname = "app"\ndependencies = [\n  "httpx>=0.27",\n  "acme-kit[cli]==1.5",\n]\n'
        '[project.optional-dependencies]\ndev = ["acme-kit[grpc]>=1.2,<2", "pytest"]\n'
    )
    produced, edits = declared("pyproject.toml", source)
    assert produced == source.replace("[cli]==1.5", "[cli]>=2,<3").replace(
        "[grpc]>=1.2,<2", "[grpc]>=2,<3"
    )
    assert edits == [(5, "auto", None), (8, "auto", None)]


def test_a_blocked_removal_copies_nothing_for_a_move_of_one_distribution() -> None:
    """One distribution on both sides: the pin is replaced in place, and no second line is added."""
    produced, edits = declared("requirements.txt", "acme-kit[cli]==1.5\n", BLOCKED)
    assert produced == "acme-kit[cli]==1.5\n"
    assert edits == [(1, "needs_review", "repo_not_fully_migrated")]


def test_extras_are_kept_in_a_setup_cfg_value() -> None:
    source = "[options]\ninstall_requires =\n    acme-kit[cli]==1.5\n    httpx\n"
    produced, edits = declared("setup.cfg", source)
    assert produced == source.replace("[cli]==1.5", "[cli]>=2,<3")
    assert edits == [(3, "auto", None)]


def test_a_setup_cfg_line_with_a_trailing_comment_is_left_as_it_was() -> None:
    source = "[options]\ninstall_requires =\n    acme-kit[cli]==1.5  # the cli\n"
    produced, edits = declared("setup.cfg", source)
    assert (produced, [row[1:] for row in edits]) == (source, [WITHHELD[1:]])


def test_extras_are_kept_in_a_plain_setup_py_literal() -> None:
    source = 'from setuptools import setup\n\nsetup(install_requires=["acme-kit[cli]==1.5"])\n'
    produced, edits = declared("setup.py", source)
    assert produced == source.replace("[cli]==1.5", "[cli]>=2,<3")
    assert edits == [(3, "auto", None)]


@pytest.mark.parametrize(
    "requires",
    [
        '["acme-kit[cli]" ">=1"]',
        '["acme-kit[cli]==" + V]',
        '["acme-kit\\u005bcli]==1.5"]',
    ],
    ids=["concatenated", "added", "escaped"],
)
def test_a_setup_py_requirement_built_from_code_is_left_as_it_was(requires: str) -> None:
    source = f'from setuptools import setup\n\nV = "1"\nsetup(install_requires={requires})\n'
    produced, edits = declared("setup.py", source)
    assert produced == source
    assert [row[1:] for row in edits] == [("needs_review", "manifest_pin_shape_unsupported")]


@pytest.mark.parametrize(
    ("path", "table", "old"),
    [("pyproject.toml", "tool.poetry.dependencies", "^1.5"), ("Pipfile", "packages", "==1.5")],
)
@pytest.mark.parametrize(
    "form",
    [
        '{{version = "{old}", extras = ["cli"]}}',
        '{{ extras = ["cli", "grpc"] , version = \'{old}\' }}',
        '{{version = "{old}", extras = ["cli"],}}',
    ],
)
def test_an_inline_table_of_a_version_and_extras_has_its_version_replaced(
    path: str, table: str, old: str, form: str
) -> None:
    value = form.format(old=old)
    produced, edits = declared(path, f"[{table}]\nacme-kit = {value}\n")
    assert produced == f"[{table}]\nacme-kit = {value.replace(old, '>=2,<3')}\n"
    assert edits == [(2, "auto", None)]


@pytest.mark.parametrize(
    "value",
    [
        '{version = "^1.5", extras = ["cli", "other"]}',
        '{version = "^1.5", extras = []}',
        '{version = "^1.5", extras = ["cli"], markers = "sys_platform == \'linux\'"}',
        '{version = "^1.5", extras = ["cli"], python = "^3.9"}',
        '{extras = ["cli"], git = "https://example.invalid/kit.git"}',
        '{version = "^1.5", extras = ["cli", 3]}',
        '{version = "^1.5", extras = ["cli"',
        '{version = "^1.5", extras = [\n"cli"]}',
        '{version = "^1.5", extras = ["cli"]}, {version = "^1.5"}',
    ],
)
def test_an_inline_table_that_holds_more_or_other_than_a_version_and_extras_is_left_as_it_was(
    value: str,
) -> None:
    source = f"[tool.poetry.dependencies]\nacme-kit = {value}\n"
    produced, edits = declared("pyproject.toml", source)
    assert produced == source
    assert edits == [(2, "needs_review", "manifest_pin_shape_unsupported")]


def test_a_dependency_given_as_a_table_of_its_own_is_left_as_it_was() -> None:
    source = '[tool.poetry.dependencies.acme-kit]\nversion = "^1.5"\nextras = ["cli"]\n'
    produced, edits = declared("pyproject.toml", source)
    assert (produced, edits) == (source, [(1, "needs_review", "manifest_pin_shape_unsupported")])


def test_a_table_value_of_extras_is_left_as_it_was_where_the_pack_states_none() -> None:
    source = '[packages]\nacme-kit = {version = "==1.5", extras = ["cli"]}\n'
    produced, edits = declared("Pipfile", source, states=False)
    assert (produced, edits) == (source, [(2, "needs_review", "manifest_pin_shape_unsupported")])


# The scan grades the same line the rule writes, so a repository is held for neither or for both.


def test_the_scan_grades_what_the_rule_writes_eligible_and_what_it_would_not_needs_review() -> None:
    def graded(line: str, spec: ScanSpec) -> list[tuple[str, str | None]]:
        plan = manifests.plan(
            manifests.declarations("requirements.txt", line.encode()), CLEAR, spec
        )
        return [(row.scan_status, row.bail) for row in plan.findings]

    assert graded("acme-kit[cli]==1.5\n", SPEC) == [("eligible", None)]
    assert graded("acme-kit[cli,x]==1.5\n", SPEC) == [("needs_review", WITHHELD[2])]
    assert graded("acme-kit[cli]==1.5\n", PLAIN_SPEC) == [("needs_review", WITHHELD[2])]


def test_a_repository_is_written_whole_with_extras_kept_or_not_at_all(tmp_path: Path) -> None:
    source = "import acme.kit\n\nreply = acme.kit.Greeter.say(name='a')\nprint(reply.reply.text)\n"
    files = {"app.py": source, "requirements.txt": "acme-kit[cli]==1.5\n"}
    run = acme.repository(tmp_path / "kept", files, spec=SPEC, pack=PACK)
    after = {row.path: row.after.decode() for row in run.outcomes}
    assert after["requirements.txt"] == "acme-kit[cli]>=2,<3\n"
    assert "talk.say" in after["app.py"]
    held = acme.repository(tmp_path / "held", files, spec=PLAIN_SPEC, pack=PLAIN_PACK)
    assert {row.path: row.after.decode() for row in held.outcomes} == {
        row.path: row.before.decode() for row in held.outcomes
    }
    assert ("requirements.txt", 1, "needs_review", "manifest_pin_shape_unsupported") in [
        (row.path, row.line, row.status, row.reason) for row in held.edits
    ]


# What the reader records.


def read(name: str, text: str) -> list[manifests.Declaration]:
    return list(manifests.declarations(name, text.encode()))


def test_the_reader_records_the_extras_and_where_the_version_after_them_is() -> None:
    line = "acme-kit[Cli, grpc] >= 1.2 ; os_name == 'nt'"
    (row,) = read("requirements.txt", line + "\n")
    assert row.pin is None
    assert row.extras == manifests.Extras(("cli", "grpc"), (19, 26))
    assert line[19:26] == " >= 1.2"
    assert row.spec == ">=1.2"


def test_a_form_the_edit_cannot_use_has_no_extras_to_judge() -> None:
    for name, text in (
        ("requirements.txt", "acme-kit[cli]==1.5 --hash=sha256:aa\n"),
        ("requirements.txt", "-e acme-kit[cli]\n"),
        ("requirements.in", "acme-kit[cli]==1.5\n"),
        ("requirements.txt", "acme-kit[cli] @ https://example.invalid/kit.whl\n"),
        (
            "pyproject.toml",
            '[tool.poetry.dependencies]\nacme-kit = {version = "1", python = "3"}\n',
        ),
    ):
        (row,) = read(name, text)
        assert (row.pin, row.extras) == (None, None), text


def test_a_plain_requirement_has_a_pin_and_no_extras() -> None:
    (row,) = read("requirements.txt", "acme-kit==1.5\n")
    assert row.pin == (8, 13)
    assert row.extras is None


@pytest.mark.parametrize(
    ("provided", "kept"),
    [(("cli",), True), (("cli", "grpc"), True), ((), False), (("grpc",), False)],
)
def test_the_edit_span_is_the_one_after_the_extras_only_if_all_are_provided(
    provided: tuple[str, ...], kept: bool
) -> None:
    (row,) = read("requirements.txt", "acme-kit[cli]==1.5\n")
    assert manifests.editable_pin(row, provided) == ((13, 18) if kept else None)
    (plain,) = read("requirements.txt", "acme-kit==1.5\n")
    assert manifests.editable_pin(plain, ()) == (8, 13)

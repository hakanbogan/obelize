"""Plugins: a rule kind the user's own distribution provides, found by entry point and run only when
the user has allowed it.

Each plugin here is a folder on `sys.path` with a `.dist-info`, as `pip` leaves one.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import TYPE_CHECKING

import fakeplugin
import pytest
import yaml
from typer.testing import CliRunner

from obelize.cli import app
from obelize.config import ConfigError
from obelize.models import Config
from obelize.packs import loader
from obelize.packs.schema import PackDocument, PluginChange
from obelize.packtools import check
from obelize.transforms import codemod, plugins, registry
from obelize.verify.runner import UserConfig

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

runner = CliRunner()
ALLOW = [plugins.Permit("acme-fixer", "fixer")]
RECORD = fakeplugin.RECORD
PACK = {
    "id": "acme/old-to-new",
    "pack_version": "0.1.0",
    "provider": "acme",
    "language": "python",
    "source": {
        "type": "official_guide",
        "url": "https://example.invalid/guide",
        "retrieved_at": dt.date(2026, 10, 21),
    },
    "from": {"package": "acme", "version": "<2"},
    "to": {"package": "acme", "version": ">=2", "requires_python": ">=3.9"},
    "match": {
        "imports": ["acme"],
        "shared": True,
        "symbols": ["acme.old"],
        "prefilter_tokens": ["acme"],
    },
    "changes": [
        {
            "id": "fix",
            "kind": "plugin",
            "plugin": "fixer",
            "citation": "Acme notes",
            "params": {"word": "new_call"},
            "fixtures": ["fixtures/negative/a.py", "fixtures/positive/b.before.py"],
        }
    ],
    "requires_plugins": [{"name": "fixer", "version": ">=1,<2"}],
    "limitations": ["Only the calls of one name."],
}


def document(**changes: object) -> dict[str, object]:
    return {**PACK, **changes}


def pack(**changes: object) -> PackDocument:
    return PackDocument.model_validate(document(**changes))


@pytest.fixture(autouse=True)
def nothing_loaded() -> Iterator[None]:
    plugins.clear()
    yield
    plugins.clear()


@pytest.fixture
def installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    return fakeplugin.install(tmp_path / "site", monkeypatch, record=RECORD)


def test_an_allowed_plugin_in_the_release_a_pack_names_is_loaded_and_recorded(
    installed: Path,
) -> None:
    [found] = plugins.activate([pack()], ALLOW).used
    assert (found.name, found.distribution, found.version) == ("fixer", "acme-fixer", "1.0")
    assert found.record_sha256 == hashlib.sha256(RECORD.encode()).hexdigest()
    assert plugins.used(pack()) == (found,)


def test_a_distribution_the_installer_left_no_record_of_is_recorded_without_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakeplugin.install(tmp_path / "site", monkeypatch, record=None)
    [found] = plugins.activate([pack()], ALLOW).used
    assert found.record_sha256 is None


def test_a_distribution_name_is_read_the_way_pip_reads_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakeplugin.install(tmp_path / "site", monkeypatch, distribution="Acme_Fixer")
    assert plugins.activate([pack()], ALLOW).used[0].distribution == "Acme_Fixer"


def test_a_pack_that_requires_nothing_loads_nothing_and_forgets_what_was_loaded(
    installed: Path,
) -> None:
    plugins.activate([pack()], ALLOW)
    other = PackDocument.model_validate({**PACK, "changes": _flag(), "requires_plugins": []})
    assert plugins.activate([other], []) == plugins.Activated()
    assert plugins.used(pack()) == ()


def _flag() -> list[dict[str, object]]:
    return [
        {
            "id": "gone",
            "kind": "flag_only",
            "citation": "Acme notes",
            "params": {"symbols": ["acme.old"], "message": "Gone.", "suggestion": "Use new."},
            "fixtures": ["fixtures/negative/a.py", "fixtures/positive/b.before.py"],
        }
    ]


def test_a_plugin_nobody_provides_is_refused_before_anything_runs() -> None:
    with pytest.raises(plugins.PluginError, match="no installed distribution provides"):
        plugins.activate([pack()], ALLOW)


def test_a_plugin_the_user_has_not_allowed_is_never_imported(
    installed: Path, tmp_path: Path
) -> None:
    marker = tmp_path / "ran"
    fakeplugin.install(
        tmp_path / "other",
        pytest.MonkeyPatch(),
        distribution="acme-evil",
        name="fixer",
        module="acme_evil",
        source=f"open({str(marker)!r}, 'w').close()\nKIND = None\n",
    )
    with pytest.raises(plugins.PluginError, match="allowed"):
        plugins.activate([pack()], [])
    assert not marker.exists()


def test_two_distributions_that_provide_a_name_need_one_to_be_allowed(
    installed: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakeplugin.install(
        tmp_path / "second", monkeypatch, distribution="acme-other", module="acme_other"
    )
    with pytest.raises(plugins.PluginError, match="more than one is allowed"):
        plugins.activate([pack()], [*ALLOW, plugins.Permit("acme-other", "fixer")])
    assert plugins.activate([pack()], ALLOW).used[0].distribution == "acme-fixer"
    with pytest.raises(plugins.PluginError, match="none of them is allowed"):
        plugins.activate([pack()], [plugins.Permit("acme-fixer", "other")])


def test_a_release_the_pack_does_not_name_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakeplugin.install(tmp_path / "site", monkeypatch, version="2.0")
    with pytest.raises(plugins.PluginError, match=r"requires 'fixer' in >=1,<2.*2\.0"):
        plugins.activate([pack()], ALLOW)


def test_a_version_that_is_no_version_fits_no_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakeplugin.install(tmp_path / "site", monkeypatch, version="not-a-version")
    with pytest.raises(plugins.PluginError, match="is installed"):
        plugins.activate([pack()], ALLOW)


def test_a_plugin_that_does_not_import_is_named_by_its_error_class_and_never_its_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fakeplugin.install(
        tmp_path / "site", monkeypatch, source="raise RuntimeError('token sk-123')\n"
    )
    with pytest.raises(plugins.PluginError, match="RuntimeError") as caught:
        plugins.activate([pack()], ALLOW)
    assert "sk-123" not in str(caught.value)


@pytest.mark.parametrize(
    "source",
    [
        fakeplugin.SOURCE.replace("api = API", "api = 99"),
        fakeplugin.SOURCE.replace("    api = API\n", ""),
        fakeplugin.SOURCE.replace("params = Settings", "params = dict"),
        fakeplugin.SOURCE.replace("    params = Settings\n", ""),
        fakeplugin.SOURCE.replace("def rule(", "def other("),
    ],
)
def test_a_kind_that_does_not_speak_the_interface_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    fakeplugin.install(tmp_path / "site", monkeypatch, source=source)
    with pytest.raises(plugins.PluginError, match="does not speak plugin interface 1"):
        plugins.activate([pack()], ALLOW)


@pytest.mark.parametrize(
    ("params", "says"),
    [
        ({}, "word: Field required"),
        ({"word": "x", "extra": 1}, "extra: Extra inputs are not permitted"),
        ({"word": 3}, "word: Input should be a valid string"),
    ],
)
def test_the_params_of_a_change_are_read_by_the_plugins_own_model_when_it_loads(
    installed: Path, params: dict[str, object], says: str
) -> None:
    changes = [{**PACK["changes"][0], "params": params}]  # type: ignore[index]
    with pytest.raises(plugins.PluginError, match=says):
        plugins.activate([pack(changes=changes)], ALLOW)


def test_a_change_whose_plugin_was_not_loaded_cannot_make_a_rule(installed: Path) -> None:
    [change] = (one for one in pack().changes if isinstance(one, PluginChange))
    with pytest.raises(plugins.PluginError, match="was not loaded"):
        registry.rule_for(change)


def test_a_loaded_plugins_rule_is_the_rule_of_its_change_in_a_run(
    installed: Path, tmp_path: Path
) -> None:
    plugins.activate([pack()], ALLOW)
    path = tmp_path / "pack.yaml"
    path.write_text(yaml.safe_dump(document()), encoding="utf-8")
    loaded = loader.load(str(path))
    work = tmp_path / "repo"
    work.mkdir()
    (work / "app.py").write_text("import acme\n\nacme.old(1)\n", encoding="utf-8", newline="\n")
    run = check.migrate(loaded, work)
    assert run.files[0].after.decode() == "import acme\n\nacme.new_call(1)\n"
    assert [(edit.status, edit.rule_id) for edit in run.edits] == [("auto", "fix")]
    rule = registry.rule_for(loaded.pack.changes[0])
    assert rule is not None
    assert (rule.consumes, rule.client_readers) == (frozenset(), frozenset())
    assert getattr(rule, "renames", None) == frozenset()


@pytest.mark.parametrize(
    ("changes", "requires", "says"),
    [
        (None, [{"name": "other", "version": ">=1"}], "which requires_plugins does not list"),
        (
            None,
            [{"name": "b", "version": ">=1"}, {"name": "a", "version": ">=1"}],
            "sorted and de-duplicated",
        ),
        ([], None, "at least one change"),
        (_flag(), [{"name": "fixer", "version": ">=1"}], "which no change uses"),
    ],
)
def test_the_plugins_a_pack_names_are_the_plugins_it_requires(
    changes: object, requires: object, says: str
) -> None:
    fields = {}
    if changes is not None:
        fields["changes"] = changes
    if requires is not None:
        fields["requires_plugins"] = requires
    with pytest.raises(ValueError, match=says):
        pack(**fields)


def test_a_change_that_names_a_plugin_the_pack_does_not_require_is_refused() -> None:
    with pytest.raises(ValueError, match="which requires_plugins does not list"):
        pack(requires_plugins=[])


def test_a_bundled_pack_never_asks_for_a_plugin(tmp_path: Path) -> None:
    folder = tmp_path / "acme" / "old-to-new"
    folder.mkdir(parents=True)
    (folder / "pack.yaml").write_text(yaml.safe_dump(document()), encoding="utf-8")
    with pytest.raises(loader.PackInvalidError, match="asks for none") as caught:
        loader.load("acme/old-to-new", root=tmp_path)
    assert caught.value.bundled is True
    assert loader.load(str(folder / "pack.yaml")).bundled is False


def test_the_user_may_allow_plugins_and_a_repository_may_not(tmp_path: Path) -> None:
    user = UserConfig.model_validate({"plugins": [{"distribution": "acme-fixer", "name": "fixer"}]})
    assert [(one.distribution, one.name) for one in user.plugins] == [("acme-fixer", "fixer")]
    for bad in (
        {"distribution": "not a name", "name": "fixer"},
        {"distribution": "a", "name": "x y"},
    ):
        with pytest.raises(ValueError, match=r"distribution|name"):
            UserConfig.model_validate({"plugins": [bad]})
    (tmp_path / ".obelize.yml").write_text(
        "plugins:\n  - distribution: acme-fixer\n    name: fixer\n", encoding="utf-8"
    )
    from obelize import config

    with pytest.raises(ConfigError, match="plugins are not read from a repository"):
        config.load(tmp_path)
    assert Config().include


def write_user_config(home: Path, plugins_block: str) -> None:
    folder = home / "obelize"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.yml").write_text(plugins_block, encoding="utf-8")


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, installed: Path) -> Path:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "app.py").write_text("import acme\n\nacme.old(1)\n", encoding="utf-8")
    (tmp_path / "pack.yaml").write_text(yaml.safe_dump(document()), encoding="utf-8")
    return repo


def test_a_run_that_needs_a_plugin_the_user_has_not_allowed_exits_seven(
    project: Path, tmp_path: Path
) -> None:
    result = runner.invoke(
        app, ["scan", "--repo", str(project), "--pack", str(tmp_path / "pack.yaml")]
    )
    assert result.exit_code == 7
    assert "allow one in ~/.config/obelize/config.yml" in result.output


def test_a_run_with_an_allowed_plugin_records_it_in_the_run_folder(
    project: Path, tmp_path: Path
) -> None:
    write_user_config(
        tmp_path / "config",
        "plugins:\n  - distribution: acme-fixer\n    name: fixer\n",
    )
    result = runner.invoke(
        app, ["fix", "--repo", str(project), "--pack", str(tmp_path / "pack.yaml")]
    )
    assert result.exit_code == 0, result.output
    [folder] = sorted((project / ".obelize" / "runs").iterdir())
    record = json.loads((folder / "run.json").read_text())
    [found] = record["packs"][0]["plugins"]
    assert (found["name"], found["distribution"], found["version"]) == (
        "fixer",
        "acme-fixer",
        "1.0",
    )
    assert found["record_sha256"] == hashlib.sha256(RECORD.encode()).hexdigest()


def test_pack_validate_says_a_plugin_is_not_loaded_and_pack_test_loads_it(
    project: Path, tmp_path: Path
) -> None:
    named = str(tmp_path / "pack.yaml")
    shown = runner.invoke(app, ["pack", "validate", named])
    assert shown.exit_code == 0
    assert "plugins      fixer (not loaded by this command" in shown.output
    tried = runner.invoke(app, ["pack", "test", named])
    assert tried.exit_code == 7
    assert "allow one" in tried.output


def test_a_distribution_in_the_working_directory_does_not_stand_in_for_the_allowed_one(
    installed: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`python -m obelize` puts the working directory first on the path, where a repository could
    hold a `.dist-info` of the allowed name, or a module of the allowed plugin's."""
    import sys

    marker = tmp_path / "ran"
    rogue = tmp_path / "repo-with-a-plugin"
    source = f"open({str(marker)!r}, 'w').close()\nKIND = None\n"
    fakeplugin.install(rogue, monkeypatch, module="evil", source=source)
    (rogue / "acme_fixer.py").write_text(source, encoding="utf-8")
    monkeypatch.chdir(rogue)
    monkeypatch.syspath_prepend(str(rogue))
    sys.path.insert(0, "")
    before = list(sys.path)
    assert plugins.activate([pack()], ALLOW).used[0].distribution == "acme-fixer"
    assert not marker.exists()
    assert sys.path == before


def test_the_path_is_put_back_when_a_plugin_cannot_be_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    fakeplugin.install(tmp_path / "site", monkeypatch, source="raise RuntimeError\n")
    before = list(sys.path)
    with pytest.raises(plugins.PluginError):
        plugins.activate([pack()], ALLOW)
    assert sys.path == before


EDITS = """
from obelize.plugin import API, Edit, Params


class Settings(Params):
    word: str = ""


class Rewriter:
    kind = "plugin"
    consumes = frozenset()
    client_readers = frozenset()

    def __init__(self, change_id):
        self.id = change_id

    def claims(self, finding):
        return finding.kind == "call" and finding.symbol == "acme.old"

    def apply(self, context):
        rows = [
            one for one in context.plan.findings
            if one.scan_status == "eligible" and self.claims(one)
        ]
{body}


class Kind:
    api = API
    params = Settings

    def rule(self, change_id, params):
        return Rewriter(change_id)


KIND = Kind()
"""
TWICE = "import acme\n\nacme.old(1)\nacme.old(2)\n"


def migrated(
    body: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str = TWICE
) -> codemod.Run:
    fakeplugin.install(tmp_path / "site", monkeypatch, source=EDITS.format(body=body))
    plugins.activate([pack()], ALLOW)
    path = tmp_path / "pack.yaml"
    path.write_text(yaml.safe_dump(document()), encoding="utf-8")
    work = tmp_path / "repo"
    work.mkdir()
    (work / "app.py").write_text(source, encoding="utf-8")
    return check.migrate(loader.load(str(path)), work)


def test_a_plugin_that_hands_back_a_generator_keeps_its_refusals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = (
        "        for number, one in enumerate(rows):\n"
        "            yield Edit(\n"
        "                path=context.path,\n"
        "                line=one.line,\n"
        '                status="auto" if number == 0 else "needs_review",\n'
        "                rule_id=self.id,\n"
        '                reason=None if number == 0 else "pattern_unmatched",\n'
        "            )"
    )
    run = migrated(body, tmp_path, monkeypatch)
    assert [(row.status, row.reason) for row in run.edits] == [
        ("needs_review", "file_not_fully_migrated"),
        ("needs_review", "pattern_unmatched"),
    ]
    assert run.files[0].written is False


def test_a_row_a_plugin_names_for_itself_is_the_rows_of_its_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = (
        "        return tuple(\n"
        '            Edit(path=context.path, line=one.line, status="auto", rule_id="acme-fixer")\n'
        "            for one in rows\n"
        "        )"
    )
    run = migrated(body, tmp_path, monkeypatch)
    assert {row.rule_id for row in run.edits} == {"fix"}


def test_a_plugin_that_returns_something_that_is_no_row_is_contained_as_an_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = migrated("        return [1]", tmp_path, monkeypatch)
    assert [(row.status, row.reason) for row in run.edits] == [
        ("needs_review", "internal_error"),
        ("needs_review", "internal_error"),
    ]


@pytest.mark.parametrize(
    ("record", "digest"),
    [
        (b"acme_fixer.py,sha256=x,1\n", None),
        (b"\xff\xfe\x00,,\n", None),
        (
            b"acme_fixer-1.0.dist-info/RECORD,,\n",
            hashlib.sha256(b"acme_fixer-1.0.dist-info/RECORD,,\n"),
        ),
    ],
)
def test_the_record_is_hashed_as_the_bytes_the_installer_wrote_or_not_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record: bytes, digest: object
) -> None:
    fakeplugin.install(tmp_path / "site", monkeypatch, record=record)
    [found] = plugins.activate([pack()], ALLOW).used
    assert found.record_sha256 == (digest.hexdigest() if digest is not None else None)  # type: ignore[attr-defined]


def test_a_key_in_the_params_that_moves_a_terminal_is_spelled_out_in_the_error(
    installed: Path,
) -> None:
    changes = [{**PACK["changes"][0], "params": {"word": "x", "\x1b]0;PWNED\x07": 1}}]  # type: ignore[index]
    with pytest.raises(plugins.PluginError) as caught:
        plugins.activate([pack(changes=changes)], ALLOW)
    message = str(caught.value)
    assert "\x1b" not in message
    assert "\\x1b]0;PWNED\\x07" in message


def test_a_plugin_whose_params_model_raises_is_named_by_the_class_of_the_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = fakeplugin.SOURCE.replace(
        "class Settings(Params):\n    word: str\n",
        "from pydantic import field_validator\n\n\nclass Settings(Params):\n    word: str\n\n"
        "    @field_validator('word')\n    @classmethod\n"
        "    def _check(cls, value):\n        return value + 1\n",
    )
    fakeplugin.install(tmp_path / "site", monkeypatch, source=source)
    with pytest.raises(
        plugins.PluginError, match=r"failed reading the params.*TypeError"
    ) as caught:
        plugins.activate([pack()], ALLOW)
    assert "concatenate" not in str(caught.value)


def test_a_distribution_with_no_name_that_registers_the_same_entry_point_is_ignored(
    installed: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken = tmp_path / "broken" / "nameless-1.0.dist-info"
    broken.mkdir(parents=True)
    (broken / "METADATA").write_text("Metadata-Version: 2.1\nVersion: 1.0\n", encoding="utf-8")
    (broken / "entry_points.txt").write_text(
        "[obelize.kinds]\nfixer = nothing:KIND\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path / "broken"))
    assert plugins.activate([pack()], ALLOW).used[0].distribution == "acme-fixer"


def write_pack_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "packs" / "acme" / "old-to-new"
    folder.mkdir(parents=True)
    (folder / "pack.yaml").write_text(yaml.safe_dump(document()), encoding="utf-8")
    return tmp_path / "packs"


def test_a_run_for_every_known_pack_leaves_out_one_whose_plugin_is_not_allowed(
    project: Path, tmp_path: Path
) -> None:
    packs = write_pack_dir(tmp_path)
    write_user_config(tmp_path / "config", f"pack_dirs:\n  - {packs}\n")
    unnamed = runner.invoke(app, ["scan", "--repo", str(project)])
    assert unnamed.exit_code == 0, unnamed.output
    assert "acme/old-to-new was left out" in unnamed.output
    named = runner.invoke(app, ["scan", "--repo", str(project), "--pack", "acme/old-to-new"])
    assert named.exit_code == 7


def test_a_run_for_every_known_pack_uses_one_whose_plugin_is_allowed(
    project: Path, tmp_path: Path
) -> None:
    packs = write_pack_dir(tmp_path)
    write_user_config(
        tmp_path / "config",
        f"pack_dirs:\n  - {packs}\nplugins:\n  - distribution: acme-fixer\n    name: fixer\n",
    )
    result = runner.invoke(app, ["scan", "--repo", str(project)])
    assert result.exit_code == 0, result.output
    assert "was left out" not in result.output
    assert "acme.old" in result.output

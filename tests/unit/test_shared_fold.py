"""A pack that keeps its module's name, folded with a client-based one in one run.

`acme.kit` (acme_kept.py) is one distribution on both sides, so its files and its pin are written
together or not at all. `acme.sdk` (acme.py) moves to a client in another distribution and holds
back only its own files. The last tests run the bundled OpenAI and Gemini packs over one repository.
"""

from __future__ import annotations

from pathlib import Path

import acme
import acme_kept as kept
import pytest
from test_several_packs import GEMINI, OPENAI, document, latest, repository, run, sources

from obelize.commands import CommandError
from obelize.commands import fix as fixer
from obelize.models import Config, ModelConfig
from obelize.packs import loader
from obelize.packs.schema import PackDocument
from obelize.verify.runner import Mode
from platforms import PYTHON

QUIET = f"{PYTHON} -c pass"
HELD = "repo_not_fully_migrated"


def loaded(pack: PackDocument) -> loader.LoadedPack:
    return loader.LoadedPack(
        pack=pack,
        sha256="0" * 64,
        data=b"",
        reference=pack.id,
        bundled=False,
        path=Path("pack.yaml"),
    )


SDK = loaded(acme.PACK)
KIT = loaded(kept.PACK)

# Declares a module only the legacy distribution installed, as the OpenAI pack does for `requests`.
WIRED = loaded(
    kept.PACK.model_copy(
        update={"match": kept.PACK.match.model_copy(update={"transitive": {"wirelib": "wirelib"}})}
    )
)

# The same pack asking for a Python newer than any other pack here does.
NEWER = loaded(
    kept.PACK.model_copy(
        update={"to": kept.PACK.to.model_copy(update={"requires_python": ">=3.11"})}
    )
)

KIT_CLEAN = """import acme.kit as kit


def hello(name):
    return kit.Greeter.say(name, loud=True).reply.text
"""

KIT_MIGRATED = """import acme.kit as kit


def hello(name):
    return kit.talk.say(who=name, loud=True).reply.text
"""

# A key read that stops short of a leaf of what 2.x returns as an object.
KIT_DICT = KIT_CLEAN.replace(".reply.text", '["reply"]')

SDK_CLEAN = """import acme.sdk as sdk

sdk.configure(key="k")

M = sdk.Model("m")


def go(text):
    return M.run(text).words
"""

SDK_MIGRATED = """from acme import client as sdk

handle = sdk.Client(key="k")


def go(text):
    return handle.models.run(target="m", body=text).words
"""

BOTH = """import acme.kit as kit
import acme.sdk as sdk

sdk.configure(key="k")

M = sdk.Model("m")


def go(text):
    return M.run(text).words


def hello(name):
    return kit.Greeter.say(name, loud=True).reply.text
"""

BOTH_MIGRATED = """import acme.kit as kit
from acme import client as sdk

handle = sdk.Client(key="k")


def go(text):
    return handle.models.run(target="m", body=text).words


def hello(name):
    return kit.talk.say(who=name, loud=True).reply.text
"""

# Names 2.x kept: nothing to migrate, whichever version is installed.
KEPT_ONLY = """import acme.kit as kit

CLIENT = kit.Client()
TOKEN = kit.token
"""

PINS = "acme-kit==1.5\nacme-sdk==0.1.0\n"


def fold(
    tree: Path,
    *packs: loader.LoadedPack,
    apply: bool = True,
    model: ModelConfig | None = None,
    flagged: bool = False,
) -> fixer.Outcome:
    return fixer.run(
        fixer.Request(
            root=tree,
            packs=packs,
            named=False,
            config=Config(allow_dirty=True),
            source="defaults",
            cli_commands=(QUIET,),
            mode=Mode(),
            config_dir=tree.parent / "config",
            environ={},
            argv=("fix",),
            apply=apply,
            model=model or ModelConfig(),
            model_flagged=flagged,
        )
    )


def rows(outcome: fixer.Outcome) -> set[tuple[str, str, str | None]]:
    return {(row.path, row.status, row.reason) for row in outcome.plan.edits}


def test_a_file_using_both_sdks_is_migrated_for_both_and_a_second_run_changes_nothing(
    tmp_path: Path,
) -> None:
    tree = repository(tmp_path / "repo", {"app.py": BOTH, "requirements.txt": PINS})
    outcome = fold(tree, SDK, KIT)
    assert outcome.exit_code == 0
    assert [pack.id for pack in outcome.record.packs] == [kept.PACK.id, acme.PACK.id]
    assert sources(tree) == {
        "app.py": BOTH_MIGRATED,
        "requirements.txt": "acme-kit>=2,<3\nacme-client>=2\n",
    }
    assert {row.status for row in outcome.plan.edits} == {"auto"}

    migrated = sources(tree)
    again = fold(tree, SDK, KIT)
    assert again.exit_code == 0
    assert again.record.packs == ()
    assert again.notes == (f"No pack applies. Checked: {kept.PACK.id}, {acme.PACK.id}.",)
    assert sources(tree) == migrated


def test_a_dict_style_read_holds_all_the_shared_pack_would_write_and_nothing_of_the_other(
    tmp_path: Path,
) -> None:
    files = {
        "app.py": SDK_CLEAN,
        "greet.py": KIT_CLEAN,
        "bad.py": KIT_DICT,
        "requirements.txt": PINS,
    }
    tree = repository(tmp_path / "repo", files)
    outcome = fold(tree, SDK, KIT)
    assert outcome.exit_code == 4
    assert sources(tree) == {
        **files,
        "app.py": SDK_MIGRATED,
        "requirements.txt": "acme-kit==1.5\nacme-client>=2\n",
    }
    assert rows(outcome) == {
        ("app.py", "auto", None),
        ("bad.py", "needs_review", "response_shape_changed"),
        ("greet.py", "needs_review", HELD),
        # The kit pin is held, and the sdk pin beside it is written.
        ("requirements.txt", "needs_review", HELD),
        ("requirements.txt", "auto", None),
    }


@pytest.mark.parametrize(
    ("source", "cause"),
    [
        pytest.param(KIT_DICT, "response_shape_changed", id="dict_read"),
        pytest.param(
            KIT_CLEAN.replace("loud=True", "nonsense=1"), "unsupported_kwarg", id="keyword"
        ),
        pytest.param(
            "import acme.kit as kit\n\nkit.legacy.run()\n", "flag_only_surface", id="flagged"
        ),
        pytest.param(
            "from acme.kit import Greeter\n\nx = Greeter.say('bob').reply.text\n",
            "from_import_unmigrated_symbol",
            id="from_import",
        ),
    ],
)
def test_one_withheld_row_of_the_shared_pack_holds_every_file_and_the_pin(
    tmp_path: Path, source: str, cause: str
) -> None:
    files = {"good.py": KIT_CLEAN, "bad.py": source, "requirements.txt": "acme-kit==1.5\n"}
    tree = repository(tmp_path / "repo", files)
    outcome = fold(tree, KIT)
    assert outcome.exit_code == 4
    assert sources(tree) == files
    assert {row.status for row in outcome.plan.edits} == {"needs_review"}
    expected = {("bad.py", cause), ("good.py", HELD), ("requirements.txt", HELD)}
    assert {(row.path, row.reason) for row in outcome.plan.edits} >= expected

    assert {
        (row["path"], row["bail"]) for row in document(tree, "run.json")["withheld"]
    } >= expected
    report = (latest(tree) / "REPORT.md").read_text(encoding="utf-8").splitlines()
    for name in ("good.py", "requirements.txt"):
        assert any(f"`{name}`" in line and f"`{HELD}`" in line for line in report), name


def test_a_module_only_the_legacy_distribution_installs_holds_the_shared_pack_until_declared(
    tmp_path: Path,
) -> None:
    files = {
        "good.py": KIT_CLEAN,
        "net.py": "import wirelib\n\nwirelib.send()\n",
        "requirements.txt": "acme-kit==1.5\n",
    }
    tree = repository(tmp_path / "repo", files)
    held = fold(tree, WIRED)
    assert held.exit_code == 4
    assert sources(tree) == files
    assert rows(held) == {
        ("good.py", "needs_review", HELD),
        ("requirements.txt", "needs_review", "transitive_dependency_in_use"),
    }

    (tree / "requirements.txt").write_text("acme-kit==1.5\nwirelib>=1\n", encoding="utf-8")
    released = fold(tree, WIRED)
    assert released.exit_code == 0
    assert sources(tree) == {
        **files,
        "good.py": KIT_MIGRATED,
        "requirements.txt": "acme-kit>=2,<3\nwirelib>=1\n",
    }


@pytest.mark.parametrize(
    ("blocked", "extra", "pins", "reason"),
    [
        pytest.param(
            KIT, {}, "acme-kit==1.1\nacme-sdk==0.1.0\n", "legacy_version_unsupported", id="legacy"
        ),
        pytest.param(
            NEWER,
            {"pyproject.toml": '[project]\nrequires-python = ">=3.9"\n'},
            PINS,
            "runtime_unsupported",
            id="python",
        ),
    ],
)
def test_a_pack_blocked_beside_one_that_writes_still_leaves_the_run_unfinished(
    tmp_path: Path,
    blocked: loader.LoadedPack,
    extra: dict[str, str],
    pins: str,
    reason: str,
) -> None:
    files = {"app.py": SDK_CLEAN, "greet.py": KIT_CLEAN, "requirements.txt": pins, **extra}
    tree = repository(tmp_path / "repo", files)
    outcome = fold(tree, SDK, blocked)
    assert outcome.exit_code == 4
    assert {pack.id: pack.blocked for pack in outcome.record.packs} == {
        kept.PACK.id: reason,
        acme.PACK.id: None,
    }
    assert sources(tree) == {
        **files,
        "app.py": SDK_MIGRATED,
        "requirements.txt": pins.replace("acme-sdk==0.1.0", "acme-client>=2"),
    }
    assert {row.bail for row in outcome.record.withheld} == {reason}
    assert outcome.record.counts.auto > 0


def test_a_repository_using_only_the_names_a_shared_pack_kept_selects_no_pack(
    tmp_path: Path,
) -> None:
    tree = repository(
        tmp_path / "repo", {"kept.py": KEPT_ONLY, "requirements.txt": "acme-kit==1.5\n"}
    )
    outcome = fold(tree, SDK, KIT, apply=False)
    assert outcome.exit_code == 0
    assert outcome.record.packs == ()
    assert outcome.notes == (f"No pack applies. Checked: {kept.PACK.id}, {acme.PACK.id}.",)
    assert document(tree, "findings.json")["packs"] == []


def test_a_dropped_name_beside_kept_ones_selects_the_shared_pack(tmp_path: Path) -> None:
    source = KEPT_ONLY + "\nSAY = kit.Greeter.say\n"
    tree = repository(tmp_path / "repo", {"kept.py": source, "requirements.txt": "acme-kit==1.5\n"})
    outcome = fold(tree, SDK, KIT, apply=False)
    assert [pack.id for pack in outcome.record.packs] == [kept.PACK.id]
    assert outcome.notes == ()


# The bundled packs, over one repository, through the command a user types.


def positive(pack: str, name: str) -> str:
    return (loader.BUNDLED / pack / "fixtures" / "positive" / name).read_text(encoding="utf-8")


CHAT = positive(OPENAI, "chat_completion.before.py")
ANSWER = positive(GEMINI, "configure_module_level.before.py")
LEGACY = {
    "chat.py": CHAT,
    "answer.py": ANSWER,
    "requirements.txt": "openai==0.28.1\ngoogle-generativeai==0.8.6\n",
}
NEW = {
    "chat.py": positive(OPENAI, "chat_completion.after.py"),
    "answer.py": positive(GEMINI, "configure_module_level.after.py"),
    "requirements.txt": "openai>=1.109.1\ngoogle-genai>=1\n",
}


@pytest.fixture
def migrated(tmp_path: Path) -> Path:
    tree = repository(tmp_path / "repo", LEGACY)
    result = run(tree, "fix", "--apply", "--verify", QUIET)
    assert result.exit_code == 0, result.output
    return tree


def test_the_openai_and_gemini_packs_migrate_one_repository_in_one_run(migrated: Path) -> None:
    assert sources(migrated) == NEW
    assert [pack["id"] for pack in document(migrated, "run.json")["packs"]] == [GEMINI, OPENAI]
    edits = document(migrated, "plan.json")["edits"]
    assert {edit["rule_id"].partition(":")[0] for edit in edits if edit["rule_id"]} == {
        GEMINI,
        OPENAI,
    }


def test_a_second_run_over_the_migrated_repository_finds_nothing(migrated: Path) -> None:
    again = run(migrated, "fix", "--apply", "--allow-dirty")
    assert again.exit_code == 0, again.output
    assert "No pack applies" in again.output
    assert sources(migrated) == NEW


def test_undo_puts_back_the_bytes_both_packs_wrote(migrated: Path) -> None:
    undone = run(migrated, "undo", "--run", latest(migrated).name)
    assert undone.exit_code == 0, undone.output
    assert sources(migrated) == LEGACY


def test_an_openai_pin_held_by_requests_leaves_gemini_to_write(tmp_path: Path) -> None:
    """`requests` came with openai 0.x and does not with 1.x, so nothing declares it until told."""
    files = {**LEGACY, "fetch.py": "import requests\n\nPAGE = requests.get('http://x').text\n"}
    tree = repository(tmp_path / "repo", files)
    held = run(tree, "fix", "--apply", "--verify", QUIET)
    assert held.exit_code == 4, held.output
    assert sources(tree) == {
        **files,
        "answer.py": NEW["answer.py"],
        "requirements.txt": "openai==0.28.1\ngoogle-genai>=1\n",
    }
    withheld = {row["bail"] for row in document(tree, "run.json")["withheld"]}
    assert withheld == {HELD, "transitive_dependency_in_use"}

    (tree / "requirements.txt").write_text(
        "openai==0.28.1\ngoogle-genai>=1\nrequests>=2.31\n", encoding="utf-8"
    )
    released = run(tree, "fix", "--apply", "--allow-dirty", "--verify", QUIET)
    assert released.exit_code == 0, released.output
    assert sources(tree)["chat.py"] == NEW["chat.py"]
    assert sources(tree)["requirements.txt"] == "openai>=1.109.1\ngoogle-genai>=1\nrequests>=2.31\n"


# What the all-or-nothing pack changes about the rest of the run.

MODEL = ModelConfig(provider="openai_compat", base_url="http://127.0.0.1:9", model="m")


def test_a_model_is_not_asked_about_a_pack_that_moves_a_whole_repository(tmp_path: Path) -> None:
    files = {"bad.py": KIT_DICT, "requirements.txt": "acme-kit==1.5\n"}
    tree = repository(tmp_path / "repo", files)
    outcome = fold(tree, KIT, model=MODEL)
    assert outcome.notes == (
        f"The configured model was not asked: {kept.PACK.id} moves a whole repository.",
    )
    assert outcome.record.model is None
    assert sources(tree) == files


def test_a_model_a_flag_asked_for_is_refused_with_a_pack_that_moves_a_whole_repository(
    tmp_path: Path,
) -> None:
    tree = repository(
        tmp_path / "repo", {"bad.py": KIT_DICT, "requirements.txt": "acme-kit==1.5\n"}
    )
    with pytest.raises(CommandError, match="moves a whole repository or none of it") as refused:
        fold(tree, KIT, model=MODEL, flagged=True)
    assert refused.value.code == 2


def test_a_pin_the_rule_cannot_write_holds_the_files_the_shared_pack_would_write(
    tmp_path: Path,
) -> None:
    files = {"good.py": KIT_CLEAN, "requirements.txt": "acme-kit[extra]==1.5\n"}
    tree = repository(tmp_path / "repo", files)
    outcome = fold(tree, KIT)
    assert outcome.exit_code == 4
    assert sources(tree) == files
    assert rows(outcome) == {
        ("good.py", "needs_review", HELD),
        ("requirements.txt", "needs_review", "manifest_pin_shape_unsupported"),
    }


def test_a_setup_py_naming_both_distributions_is_one_row_of_the_plan(tmp_path: Path) -> None:
    """It is read as a source and as a manifest, by two packs that each write its requirement."""
    setup = (
        "from setuptools import setup\n\n"
        'setup(install_requires=["acme-kit==1.5", "acme-sdk==0.1.0"])\n'
    )
    tree = repository(tmp_path / "repo", {"app.py": BOTH, "setup.py": setup})
    outcome = fold(tree, SDK, KIT)
    assert outcome.exit_code == 0
    assert sources(tree)["setup.py"] == setup.replace("acme-kit==1.5", "acme-kit>=2,<3").replace(
        "acme-sdk==0.1.0", "acme-client>=2"
    )
    assert sorted(row.path for row in outcome.plan.edits).count("setup.py") == 2


def test_show_context_is_refused_for_a_pack_that_moves_a_whole_repository(tmp_path: Path) -> None:
    tree = repository(
        tmp_path / "repo", {"bad.py": KIT_DICT, "requirements.txt": "acme-kit==1.5\n"}
    )
    request = fixer.Request(
        root=tree,
        packs=(KIT,),
        named=False,
        config=Config(allow_dirty=True),
        source="defaults",
        cli_commands=(QUIET,),
        mode=Mode(),
        config_dir=tree.parent / "config",
        environ={},
        argv=("fix", "--show-context"),
        model=MODEL,
        model_flagged=True,
    )
    with pytest.raises(CommandError, match="no model is asked about it") as refused:
        fixer.context(request)
    assert refused.value.code == 2


def test_a_file_another_pack_wrote_as_a_manifest_is_one_row_from_first_bytes_to_last(
    tmp_path: Path,
) -> None:
    """The kit pack edits `setup.py` as a manifest in pass one, the sdk pack reads it as a source in
    pass two: the row runs from the original bytes to the last, not from the first pack's output."""
    setup = (
        "from setuptools import setup\n\n"
        'setup(install_requires=["acme-kit==1.5", "acme-sdk==0.1.0"])\n'
    )
    tree = repository(tmp_path / "repo", {"setup.py": setup, "app.py": BOTH})
    outcome = fold(tree, SDK, KIT)
    rows = [row for row in outcome.plan.edits if row.path == "setup.py"]
    assert len(rows) == 2
    patch = outcome.patch.decode()
    assert "-from setuptools" not in patch
    assert patch.count("-setup(install_requires") == 1

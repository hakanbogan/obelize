"""`from.since`: code that uses a name only the source range defines stands for a bare pin.

A bare `openai` installs 3.x today, where `openai.ChatCompletion` is a stub that raises, so code
that calls it was written for a release in `>=0.27.0,<1`. The gate passes such a declaration, as
ADR-056 passes one that installs the newest release, and fails closed on the same evidence.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import acme
import pytest
from packaging.specifiers import SpecifierSet
from pdf_repo import git_repo
from typer.testing import CliRunner

from obelize.cli import app
from obelize.evidence import report
from obelize.models import Config, Finding, ScanSpec
from obelize.packs import loader
from obelize.scan import manifests, runner, runtime
from platforms import PYTHON
from support import committed

OPENAI = loader.to_scan_spec(loader.load("openai/openai-0-to-1"))
RANGE = ">=0.27.0,<1"
CALL = "import openai\n\nresponse = openai.ChatCompletion.create(model='m', messages=[])\n"

# A name that exists below the floor too, so it proves nothing.
OLDER = "import openai\n\nvector = openai.Embedding.create(model='m', input='x')\n"

SINCE = acme.OLD_SPEC.model_copy(update={"legacy_since": ("acme.old.Registry",)})


def plain(spec: str | None = "", path: str = "requirements.txt", **fields: Any) -> Any:
    """A requirement a rewrite can carry: the pin span is set."""
    row = manifests.Declaration(
        path=path, line=1, column=0, name="acme-old", raw="acme-old", end=8, pin=(8, 8), spec=spec
    )
    return replace(row, **fields)


def use(symbol: str, *, kind: str = "call", status: str = "eligible") -> Finding:
    reasons = {"text_mention": "string_or_comment_mention", "manifest": "manifest_dependency"}
    return Finding.model_validate(
        {
            "path": "main.py",
            "line": 3,
            "column": 0,
            "kind": kind,
            "confidence_reason": reasons.get(kind, "direct_import_resolved"),
            "symbol": symbol,
            "scan_status": status,
            "bail": None if status in {"eligible", "not_a_usage"} else "flag_only_surface",
        }
    )


# `acme.old`'s range is `>=2,<3`.


@pytest.mark.parametrize(
    "pinned",
    ["", "*", ">=1", "<3", "!=2.0", ">=2,<3", "==2.4.1", "~=2.1", "<=2.5", ">=1,<2.1", "^2.0"],
    ids=repr,
)
def test_a_plain_requirement_that_may_install_a_release_of_the_range_is_within_it(
    pinned: str,
) -> None:
    assert runtime.within(plain(pinned), SINCE) is True


@pytest.mark.parametrize(
    "pinned",
    ["<2", ">=3", "==3.1", "==1.9", ">=3,<4", "<1.9", "~=3.0", ">=0.5,<2", "^1.0"],
    ids=repr,
)
def test_a_requirement_that_admits_no_release_of_the_range_is_not_within_it(pinned: str) -> None:
    assert runtime.within(plain(pinned), SINCE) is False


@pytest.mark.parametrize(
    "fields",
    [{"pin": None}, {"marked": True}, {"spec": None}, {"spec": ">=2rc1"}, {"spec": "nonsense"}],
    ids=["no-pin-span", "marker", "unreadable", "pre-release", "not-a-specifier"],
)
def test_a_requirement_a_rewrite_cannot_carry_or_that_may_pick_a_pre_release_is_not_within(
    fields: dict[str, Any],
) -> None:
    assert runtime.within(plain(**{"spec": "", **fields}), SINCE) is False


def test_two_sets_meet_where_one_release_is_in_both() -> None:
    target = SpecifierSet(">=2,<3")
    assert manifests.meets([SpecifierSet(">=3"), SpecifierSet("<2.5")], target) is True
    assert manifests.meets([SpecifierSet(">=3"), SpecifierSet("==1.9")], target) is False
    assert manifests.meets([], target) is False


@pytest.mark.parametrize(
    ("findings", "taken"),
    [
        ([use("acme.old.Registry")], ">=2,<3"),
        ([use("acme.old.Registry.get")], ">=2,<3"),
        ([use("acme.old.Registry", kind="import", status="needs_review")], ">=2,<3"),
        ([use("acme.old.Other"), use("acme.old.Registry")], ">=2,<3"),
        ([], None),
        ([use("acme.old.Other")], None),
        ([use("acme.old.RegistryX")], None),
        ([use("acme.old")], None),
        ([use("acme.old.Registry", kind="manifest")], None),
        ([use("acme.old.Registry", kind="text_mention", status="not_a_usage")], None),
    ],
    ids=[
        "the-name",
        "under-the-name",
        "an-import-the-rule-withholds",
        "one-of-two",
        "no-code",
        "another-name",
        "a-name-that-only-starts-the-same",
        "the-module",
        "a-manifest-row",
        "a-mention",
    ],
)
def test_code_that_uses_a_name_only_the_range_defines_is_what_takes_the_declaration(
    findings: list[Finding], taken: str | None
) -> None:
    assert runtime.taken_for([plain("")], findings, SINCE) == taken


@pytest.mark.parametrize("pinned", ["==1.9", ">=3", "<2", "==3.1"])
def test_a_declaration_the_range_rules_out_is_never_taken_whatever_the_code_uses(
    pinned: str,
) -> None:
    assert runtime.taken_for([plain(pinned)], [use("acme.old.Registry")], SINCE) is None


def test_a_declaration_at_or_above_the_floor_needs_nothing_taken() -> None:
    assert runtime.taken_for([plain(">=2")], [use("acme.old.Registry")], SINCE) is None


def test_a_pack_that_names_no_since_takes_nothing_from_the_code() -> None:
    assert runtime.taken_for([plain("")], [use("acme.old.Registry")], acme.OLD_SPEC) is None
    open_range = SINCE.model_copy(update={"legacy_floor": None})
    assert runtime.taken_for([plain("")], [use("acme.old.Registry")], open_range) is None


def test_a_declaration_of_another_distribution_takes_nothing() -> None:
    other = plain("", name="acme-new")
    assert runtime.taken_for([other], [use("acme.old.Registry")], SINCE) is None


def test_a_pack_that_names_a_newest_release_takes_that_and_not_the_code() -> None:
    newest = acme.OLD_SPEC.model_copy(update={"legacy_newest": "2.4.1"})
    assert runtime.taken_for([plain("")], [], newest) == "2.4.1"
    assert runtime.taken_for([plain("<2.4")], [use("acme.old.Registry")], newest) is None


@pytest.mark.parametrize("pinned", ["", "*", ">=1", "<3", "^1.0 || ^2.0"], ids=repr)
def test_a_declaration_within_the_range_passes_the_floor_once_taken(pinned: str) -> None:
    assert runtime.legacy([plain(pinned)], SINCE, used=True, taken=">=2,<3") is None
    assert runtime.legacy([plain(pinned)], SINCE, used=True) is not None


@pytest.mark.parametrize("pinned", ["==1.9", "<2", None], ids=repr)
def test_a_declaration_the_range_does_not_reach_blocks_as_before(pinned: str | None) -> None:
    found = runtime.legacy([plain(pinned)], SINCE, used=True, taken=">=2,<3")
    assert found is not None
    assert found == runtime.legacy([plain(pinned)], SINCE, used=True)
    assert found.evidence == ""


def test_the_evidence_that_takes_the_range_back_is_the_blocks_and_says_which_range() -> None:
    found = runtime.legacy([plain("")], SINCE, used=True, taken=">=2,<3", contrary="poetry.lock")
    assert found == runtime.Blocked(
        "legacy_version_unsupported",
        "acme-old",
        "requirements.txt",
        "",
        ">=2",
        "poetry.lock",
        taken=">=2,<3",
    )


def test_a_block_without_a_range_taken_does_not_name_one() -> None:
    assert runtime.legacy([plain("")], SINCE, used=True) == runtime.Blocked(
        "legacy_version_unsupported", "acme-old", "requirements.txt", "", ">=2"
    )
    newest = SINCE.model_copy(update={"legacy_newest": "2.4.1"})
    held = runtime.legacy([plain("")], newest, used=True, taken="2.4.1", contrary="poetry.lock")
    assert held is not None
    assert held.taken == ""


# A repository of the bundled openai pack, read as a scan reads it.


def gated(root: Path, spec: ScanSpec = OPENAI, config: Config | None = None) -> runner.Scan:
    return runner.scan(root, config or Config(), spec, jobs=1)


def repository(root: Path, files: Mapping[str, str | bytes], ignore: str = "") -> Path:
    return git_repo(root, {"main.py": CALL, **files}, ignore)


STANDS_IN: dict[str, dict[str, str | bytes]] = {
    "bare": {"requirements.txt": "openai\n"},
    "below-one": {"requirements.txt": "openai<1\n"},
    "a-low-floor": {"requirements.txt": "openai>=0.20\n"},
    "not-the-last": {"requirements.txt": "openai!=0.28.1\n"},
    "a-requirements-folder": {"requirements/base.txt": "openai\n"},
    "pipfile": {"Pipfile": '[packages]\nopenai = "*"\n'},
    "poetry": {"pyproject.toml": '[tool.poetry.dependencies]\nopenai = "*"\n'},
    "a-range-that-reaches-it": {"requirements.txt": "openai>=0.10,<0.28\n"},
}


@pytest.mark.parametrize("name", STANDS_IN)
def test_a_declaration_that_may_install_a_legacy_release_stands_for_that_range_beside_the_code(
    tmp_path: Path, name: str
) -> None:
    scan = gated(repository(tmp_path, STANDS_IN[name]))
    assert scan.blocked == ()
    assert scan.assumed == (("openai", RANGE),)


@pytest.mark.parametrize("name", STANDS_IN)
def test_the_same_repository_is_blocked_by_a_pack_that_names_no_since(
    tmp_path: Path, name: str
) -> None:
    """The field is the pack's claim: without it the gate is the one ADR-050 describes."""
    spec = OPENAI.model_copy(update={"legacy_since": ()})
    scan = gated(repository(tmp_path, STANDS_IN[name]), spec)
    assert [(row.reason, row.evidence, row.taken) for row in scan.blocked] == [
        ("legacy_version_unsupported", "", "")
    ]
    assert scan.assumed == ()


REFUSED: dict[str, dict[str, str | bytes]] = {
    "a-pin-below-the-range": {"requirements.txt": "openai==0.18.0\n"},
    "a-range-below-it": {"requirements.txt": "openai<0.27\n"},
    "a-range-that-skips-it": {"requirements.txt": "openai>=0.10,<0.27\n"},
    "a-marker": {"requirements.txt": 'openai; python_version < "3.12"\n'},
    "extras": {"requirements.txt": "openai[embeddings]\n"},
    "a-pre-release": {"requirements.txt": "openai>=0.27.0rc1\n"},
    "a-url": {"requirements.txt": "openai @ https://host/openai.whl\n"},
    "nothing-declares-it": {},
    "another-distribution": {"requirements.txt": "requests\n"},
}


@pytest.mark.parametrize("name", REFUSED)
def test_a_declaration_the_range_cannot_stand_for_blocks_with_nothing_assumed(
    tmp_path: Path, name: str
) -> None:
    scan = gated(repository(tmp_path, REFUSED[name]))
    assert [(row.reason, row.evidence, row.taken) for row in scan.blocked] == [
        ("legacy_version_unsupported", "", "")
    ]
    assert scan.assumed == ()


def test_a_name_older_releases_define_too_proves_nothing(tmp_path: Path) -> None:
    root = git_repo(tmp_path, {"main.py": OLDER, "requirements.txt": "openai\n"})
    scan = gated(root)
    assert [row.reason for row in scan.blocked] == ["legacy_version_unsupported"]
    assert scan.assumed == ()


def test_a_name_in_a_comment_or_a_string_proves_nothing(tmp_path: Path) -> None:
    code = "# openai.ChatCompletion.create was removed\nimport openai\n"
    root = git_repo(tmp_path, {"main.py": code, "requirements.txt": "openai\n"})
    scan = gated(root)
    assert scan.assumed == ()
    assert [row.reason for row in scan.blocked] == []  # nothing uses the library: not blocked


def test_the_other_name_the_pack_lists_proves_it_too(tmp_path: Path) -> None:
    audio = "import openai\n\nopenai.Audio.transcribe('whisper-1', open('a.wav', 'rb'))\n"
    scan = gated(git_repo(tmp_path, {"main.py": audio, "requirements.txt": "openai\n"}))
    assert (scan.blocked, scan.assumed) == ((), (("openai", RANGE),))


def test_a_pin_inside_the_range_is_not_an_assumption(tmp_path: Path) -> None:
    for index, pin in enumerate(["openai==0.28.1", "openai>=0.27.0,<1", "openai>=1.109.1"]):
        scan = gated(repository(tmp_path / str(index), {"requirements.txt": f"{pin}\n"}))
        assert (scan.blocked, scan.assumed) == ((), ()), pin


def test_a_directory_that_is_not_a_repository_takes_nothing_and_does_not_say_newest(
    tmp_path: Path,
) -> None:
    root = git_repo(tmp_path, {"main.py": CALL, "requirements.txt": "openai\n"}, init=False)
    scan = gated(root)
    assert scan.source == "walk"
    assert [(row.reason, row.path, row.evidence) for row in scan.blocked] == [
        ("legacy_version_unsupported", "requirements.txt", "")
    ]
    assert scan.blocked[0].unlisted is False
    assert scan.assumed == ()


EVIDENCE: dict[str, tuple[dict[str, str | bytes], str, str]] = {
    "a-lock": ({"requirements.txt": "openai\n", "poetry.lock": "# generated\n"}, "", "poetry.lock"),
    "an-index": (
        {"requirements.txt": "-i https://private.example/simple\nopenai\n"},
        "",
        "requirements.txt",
    ),
    "a-constraint-that-skips-the-range": (
        {"requirements.txt": "-c constraints.txt\nopenai\n", "constraints.txt": "openai>=1\n"},
        "",
        "constraints.txt",
    ),
    "a-dockerfile-on-the-new-release": (
        {"requirements.txt": "openai\n", "Dockerfile": "RUN pip install 'openai>=1.109.1'\n"},
        "",
        "Dockerfile",
    ),
    "a-ci-pin-below": (
        {
            "requirements.txt": "openai\n",
            ".github/workflows/ci.yml": "- run: pip install openai==0.18.0\n",
        },
        "",
        ".github/workflows/ci.yml",
    ),
    "a-dist-info-of-the-new-release": (
        {
            "requirements.txt": "openai\n",
            ".venv/lib/python3.12/site-packages/openai-1.45.0.dist-info/M": "x\n",
        },
        ".venv/\n",
        ".venv/lib/python3.12/site-packages/openai-1.45.0.dist-info",
    ),
    "a-dist-info-below": (
        {
            "requirements.txt": "openai\n",
            "env/lib/python3.9/site-packages/openai-0.18.0.dist-info/M": "x\n",
        },
        "env/\n",
        "env/lib/python3.9/site-packages/openai-0.18.0.dist-info",
    ),
    "a-file-named-for-it": (
        {"requirements.txt": "openai\n", "wheels/openai-1.0.0.tar.gz": "x\n"},
        "",
        "wheels/openai-1.0.0.tar.gz",
    ),
}


@pytest.mark.parametrize("name", EVIDENCE)
def test_a_repository_that_shows_a_release_outside_the_range_is_blocked_and_names_the_path(
    tmp_path: Path, name: str
) -> None:
    files, ignore, path = EVIDENCE[name]
    scan = gated(repository(tmp_path, files, ignore))
    assert [(row.reason, row.evidence, row.taken) for row in scan.blocked] == [
        ("legacy_version_unsupported", path, RANGE)
    ]
    assert scan.assumed == ()


QUIET: dict[str, tuple[dict[str, str | bytes], str]] = {
    "a-pin-in-the-range": (
        {"requirements.txt": "openai\n", "Dockerfile": "RUN pip install openai==0.28.1\n"},
        "",
    ),
    "a-range-in-it": (
        {"requirements.txt": "openai\n", "tox.ini": "deps = openai>=0.27,<0.29\n"},
        "",
    ),
    "a-dist-info-in-it": (
        {
            "requirements.txt": "openai\n",
            ".venv/lib/python3.12/site-packages/openai-0.28.1.dist-info/M": "x\n",
        },
        ".venv/\n",
    ),
}


@pytest.mark.parametrize("name", QUIET)
def test_a_release_inside_the_range_written_elsewhere_is_no_evidence_against_taking_it(
    tmp_path: Path, name: str
) -> None:
    files, ignore = QUIET[name]
    scan = gated(repository(tmp_path, files, ignore))
    assert (scan.blocked, scan.assumed) == ((), (("openai", RANGE),))


def test_a_manifest_the_scan_cannot_read_whole_is_evidence_here_too(tmp_path: Path) -> None:
    files = {"requirements.txt": "openai\n", "requirements-big.txt": "six\n" * 100}
    scan = gated(repository(tmp_path, files), config=Config(max_file_bytes=200))
    assert [row.evidence for row in scan.blocked] == ["requirements-big.txt"]


def test_a_mention_in_a_file_over_the_limit_is_searched_against_the_range(tmp_path: Path) -> None:
    for index, (mention, evidence) in enumerate(
        [("openai==0.28.1", ""), ("openai>=1.109.1", "notes.txt")]
    ):
        files = {
            "requirements.txt": "openai\n",
            "notes.txt": f"pip install {mention}\n" + "x" * 400,
        }
        scan = gated(repository(tmp_path / str(index), files), config=Config(max_file_bytes=200))
        assert [row.evidence for row in scan.blocked] == ([evidence] if evidence else []), mention


def test_a_range_that_reads_nothing_is_taken_back_not_guessed(tmp_path: Path) -> None:
    """A clause the specifier grammar refuses is `ruled out`, as it is for the newest release."""
    files = {"requirements.txt": "openai\n", "notes.txt": "pip install openai==1.*.*\n"}
    assert [row.evidence for row in gated(repository(tmp_path, files)).blocked] == ["notes.txt"]


# What the report says.


def test_a_range_taken_for_a_version_nobody_wrote_down_is_said_as_a_range() -> None:
    lines = report._assumed((("openai", RANGE),), report._code)
    assert lines == [
        "`openai` is declared with no version that rules out a release in "
        f"`{RANGE}`, and the code uses a name only those releases define, so this "
        "migration takes it as one of them. A repository that installs another needs that "
        "pinned in a manifest obelize reads.",
        "",
    ]


def test_a_range_stopped_by_evidence_is_named_in_the_block() -> None:
    blocked = runtime.Blocked(
        "legacy_version_unsupported",
        "openai",
        "requirements.txt",
        "",
        ">=0.27.0",
        "poetry.lock",
        taken=RANGE,
    )
    assert report._blocked(blocked, report._bare).startswith(
        f"requirements.txt declares openai with no version, which this migration would take as "
        f"a release in {RANGE}, but poetry.lock suggests another release is in use, so it "
        f"reports its findings and plans no change. To migrate, pin openai to >=0.27.0 in "
        f"requirements.txt and run again."
    )


# From a bare declaration to a rewritten repository, and back.

runner_ = CliRunner()


def command(tree: Path, *arguments: str) -> Any:
    return runner_.invoke(app, [*arguments, "--repo", str(tree)])


def recorded(tree: Path) -> Any:
    name = (tree / ".obelize" / "latest").read_text(encoding="utf-8").strip()
    return json.loads((tree / ".obelize" / "runs" / name / "run.json").read_text(encoding="utf-8"))


def test_a_bare_openai_beside_chat_completion_code_is_migrated_with_the_pin_and_undone(
    tmp_path: Path,
) -> None:
    files = {
        "app.py": CALL + "print(response.choices[0].message.content)\n",
        "requirements.txt": "openai\n",
    }
    tree = committed(tmp_path / "repo", files)
    result = command(tree, "fix", "--apply", "--allow-dirty", "--verify", f"{PYTHON} -c pass")
    assert result.exit_code == 0, result.output
    assert (
        f"a release in {RANGE}, and the code uses a name only those releases define"
        in result.output
    )
    assert (tree / "requirements.txt").read_text(encoding="utf-8") == "openai>=1.109.1\n"
    assert "openai.chat.completions.create" in (tree / "app.py").read_text(encoding="utf-8")
    record = recorded(tree)
    assert [(pack["blocked"], pack["assumed"]) for pack in record["packs"]] == [(None, RANGE)]
    undone = command(tree, "undo", "--run", record["run_id"])
    assert undone.exit_code == 0, undone.output
    for name, text in files.items():
        assert (tree / name).read_text(encoding="utf-8") == text

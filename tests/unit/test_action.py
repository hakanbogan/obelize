"""The GitHub Action and the pre-commit hook: what they pin, what they pass, what they print."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
ACTION = ROOT / "action.yml"
SCRIPT = ROOT / "action" / "scan.sh"
NEEDS_BASH = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None,
    reason="GitHub runs these steps under bash on ubuntu",
)

SARIF: dict[str, Any] = {
    "version": "2.1.0",
    "runs": [
        {
            "results": [
                {
                    "ruleId": "eligible",
                    "level": "note",
                    "message": {"text": "obelize can migrate this place."},
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {"uri": "src/app.py"},
                                "region": {"startLine": 7, "startColumn": 5},
                            }
                        }
                    ],
                },
                {
                    "ruleId": "usage_unmapped",
                    "level": "warning",
                    "message": {"text": "Migrate it by hand.\nSecond line, with 100% of: colons."},
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {"uri": "odd,name:with\n%.py"},
                                "region": {"startLine": 1, "startColumn": 1},
                            }
                        }
                    ],
                },
                {
                    "ruleId": "attribute_removed",
                    "level": "error",
                    "message": {"text": "Gone."},
                    "locations": [
                        {
                            "physicalLocation": {
                                "artifactLocation": {"uri": "a.py"},
                                "region": {"startLine": 2, "startColumn": 1},
                            }
                        }
                    ],
                },
            ]
        }
    ],
}


def _action() -> dict[str, Any]:
    loaded = yaml.safe_load(ACTION.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _load_annotate() -> Any:
    spec = importlib.util.spec_from_file_location(
        "obelize_action_annotate", ROOT / "action" / "annotate.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


annotate = _load_annotate()


# The action.


def test_the_action_is_a_composite_that_names_what_it_takes_and_gives() -> None:
    action = _action()
    assert action["runs"]["using"] == "composite"
    assert set(action["inputs"]) == {
        "version",
        "mode",
        "packs",
        "library",
        "modules",
        "fail-on",
        "sarif",
        "distributions",
        "from",
        "fail-on-unproven",
        "artifact-name",
        "working-directory",
    }
    for name, one in action["inputs"].items():
        assert one["description"], name
    assert action["inputs"]["version"]["required"] is True
    assert action["inputs"]["mode"]["default"] == "scan"
    # A step that did not run has an empty output, so the two are told apart by joining them.
    assert action["outputs"]["exit-code"]["value"] == (
        "${{ format('{0}{1}', steps.scan.outputs.exit-code, steps.upgrade.outputs.exit-code) }}"
    )
    assert set(action["outputs"]) == {
        "exit-code",
        "sarif-file",
        "bundle-file",
        "report-file",
        "changed",
    }


def test_every_step_the_action_uses_is_held_to_a_commit() -> None:
    steps = _action()["runs"]["steps"]
    uses = [step["uses"] for step in steps if "uses" in step]
    assert len(uses) == 3
    for name in uses:
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", name), name
    text = ACTION.read_text(encoding="utf-8")
    assert all(re.search(rf"{re.escape(name)} # v\d+\.\d+\.\d+", text) for name in uses)


def test_the_action_installs_the_uv_the_workflows_install() -> None:
    steps = _action()["runs"]["steps"]
    (setup,) = [step for step in steps if step.get("uses", "").startswith("astral-sh/setup-uv@")]
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    ours = next(
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if step.get("uses", "").startswith("astral-sh/setup-uv@")
    )
    assert setup["uses"] == ours["uses"]
    assert setup["with"]["version"] == ours["with"]["version"]
    assert setup["with"]["enable-cache"] is False


def test_no_script_of_the_action_expands_an_input_into_its_own_source() -> None:
    """A value reaches a script through the environment, where the shell cannot run it."""
    for step in _action()["runs"]["steps"]:
        run = step.get("run", "")
        assert "${{" not in run, step["name"]
        if run:
            assert step["shell"] == "bash", step["name"]


def test_the_job_fails_after_the_annotations_and_the_upload_not_before() -> None:
    names = [step["name"] for step in _action()["runs"]["steps"]]
    assert names == [
        "Install uv",
        "Check the mode",
        "Scan",
        "Annotate",
        "Upload to code scanning",
        "Fail on what was found",
        "Upgrade",
        "Upload the upgrade",
        "Fail on an upgrade that was not proven",
    ]
    upload = _action()["runs"]["steps"][4]
    assert "inputs.sarif == 'true'" in upload["if"]
    assert "exit-code == '4'" in upload["if"]


# The scan script.


def _run(tmp_path: Path, env: dict[str, str], *, code: int = 0) -> subprocess.CompletedProcess[str]:
    """`action/scan.sh` with a `uvx` that records its arguments and exits `code`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    uvx = bin_dir / "uvx"
    uvx.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$RECORD"\npwd >> "$RECORD"\n'
        f"printf '{{\"runs\":[]}}'\nexit {code}\n",
        encoding="utf-8",
    )
    uvx.chmod(uvx.stat().st_mode | stat.S_IXUSR)
    (tmp_path / "work").mkdir(exist_ok=True)
    environment = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "RECORD": str(tmp_path / "record"),
        "GITHUB_OUTPUT": str(tmp_path / "output"),
        "OBELIZE_SARIF_FILE": str(tmp_path / "out.sarif"),
        "OBELIZE_VERSION": "0.7.0",
        "OBELIZE_WORKDIR": str(tmp_path / "work"),
        **env,
    }
    return subprocess.run(
        ["bash", str(SCRIPT)], env=environment, capture_output=True, text=True, check=False
    )


def _record(tmp_path: Path) -> list[str]:
    return (tmp_path / "record").read_text(encoding="utf-8").splitlines()


@NEEDS_BASH
def test_the_scan_runs_the_pinned_release_and_fails_on_the_statuses_named(tmp_path: Path) -> None:
    done = _run(tmp_path, {"OBELIZE_FAIL_ON": "eligible needs_review"})
    assert done.returncode == 0, done.stdout
    assert _record(tmp_path)[:-1] == [
        "obelize==0.7.0",
        "scan",
        "--sarif",
        "--fail-on",
        "eligible",
        "--fail-on",
        "needs_review",
    ]
    assert _record(tmp_path)[-1].endswith("/work")
    assert (tmp_path / "out.sarif").read_text(encoding="utf-8") == '{"runs":[]}'


@NEEDS_BASH
def test_the_exit_code_goes_to_the_output_and_the_script_itself_exits_zero(tmp_path: Path) -> None:
    done = _run(tmp_path, {}, code=4)
    assert done.returncode == 0
    output = (tmp_path / "output").read_text(encoding="utf-8").splitlines()
    assert output == ["exit-code=4", f"sarif-file={tmp_path / 'out.sarif'}"]


@NEEDS_BASH
def test_packs_a_library_and_its_modules_become_flags(tmp_path: Path) -> None:
    done = _run(tmp_path, {"OBELIZE_PACKS": "py-pdf/pypdf2-to-pypdf openai/openai-0-to-1"})
    assert done.returncode == 0
    assert _record(tmp_path)[1:7] == [
        "scan",
        "--sarif",
        "--pack",
        "py-pdf/pypdf2-to-pypdf",
        "--pack",
        "openai/openai-0-to-1",
    ]
    _run(tmp_path, {"OBELIZE_LIBRARY": "PyYAML", "OBELIZE_MODULES": "yaml _yaml"})
    assert _record(tmp_path)[1:9] == [
        "scan",
        "--sarif",
        "--library",
        "PyYAML",
        "--module",
        "yaml",
        "--module",
        "_yaml",
    ]


@NEEDS_BASH
@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"OBELIZE_VERSION": ""}, "version takes a release"),
        ({"OBELIZE_VERSION": "latest"}, "version takes a release"),
        ({"OBELIZE_VERSION": "0.7.0 --index-url=https://x"}, "version takes a release"),
        ({"OBELIZE_PACKS": "--pack"}, "packs takes pack ids"),
        ({"OBELIZE_PACKS": "../etc"}, "packs takes pack ids"),
        ({"OBELIZE_LIBRARY": "-x"}, "library takes a distribution name"),
        ({"OBELIZE_LIBRARY": "a b;c"}, "library takes a distribution name"),
        ({"OBELIZE_MODULES": "yaml"}, "modules goes with library"),
        ({"OBELIZE_LIBRARY": "requests", "OBELIZE_MODULES": "a-b"}, "modules takes module names"),
        ({"OBELIZE_LIBRARY": "requests", "OBELIZE_PACKS": "py-pdf/pypdf2-to-pypdf"}, "has no pack"),
        ({"OBELIZE_FAIL_ON": "not_a_usage"}, "fail-on takes eligible"),
        ({"OBELIZE_FAIL_ON": "eligible; rm -rf ."}, "fail-on takes eligible"),
        ({"OBELIZE_WORKDIR": "/nonexistent-obelize"}, "is not a directory"),
    ],
)
def test_a_value_that_could_become_a_flag_or_a_command_stops_the_scan(
    tmp_path: Path, env: dict[str, str], message: str
) -> None:
    done = _run(tmp_path, env)
    assert done.returncode == 2
    assert f"::error::{message}" in done.stdout or message in done.stdout
    assert not (tmp_path / "record").exists()


@NEEDS_BASH
def test_a_glob_in_a_value_is_not_expanded(tmp_path: Path) -> None:
    (tmp_path / "work" / "py-pdf").mkdir(parents=True)
    done = _run(tmp_path, {"OBELIZE_PACKS": "*"})
    assert done.returncode == 2


# The annotations.


def test_a_result_becomes_an_annotation_at_its_file_and_line() -> None:
    assert annotate.annotation(SARIF["runs"][0]["results"][0]) == (
        "::notice file=src/app.py,line=7,col=5,title=obelize eligible::"
        "obelize can migrate this place."
    )
    assert annotate.annotation(SARIF["runs"][0]["results"][2]).startswith("::error file=a.py,")


def test_what_comes_from_the_repository_cannot_end_a_command() -> None:
    line = annotate.annotation(SARIF["runs"][0]["results"][1])
    assert line.count("\n") == 0
    assert "file=odd%2Cname%3Awith%0A%25.py" in line
    assert line.endswith("::Migrate it by hand.%0ASecond line, with 100%25 of: colons.")


def test_a_level_it_does_not_know_is_a_warning() -> None:
    result = {**SARIF["runs"][0]["results"][0], "level": "none"}
    assert annotate.annotation(result).startswith("::warning ")


def test_the_summary_counts_the_places_by_reason() -> None:
    text = annotate.summary(SARIF["runs"][0]["results"])
    assert "3 place(s) left." in text
    assert "| `attribute_removed` | 1 |" in text
    assert "| `usage_unmapped` | 1 |" in text
    assert annotate.summary([]).endswith("0 place(s) left.\n")


def test_the_script_prints_the_annotations_and_appends_the_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sarif = tmp_path / "out.sarif"
    sarif.write_text(json.dumps(SARIF), encoding="utf-8")
    summary = tmp_path / "summary.md"
    summary.write_text("earlier\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    assert annotate.main(str(sarif)) == 0
    assert capsys.readouterr().out.count("\n::") + 1 == 3
    assert summary.read_text(encoding="utf-8").startswith("earlier\n## obelize")


def test_without_a_summary_file_only_the_annotations_are_printed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sarif = tmp_path / "out.sarif"
    sarif.write_text(json.dumps(SARIF), encoding="utf-8")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert annotate.main(str(sarif)) == 0
    assert capsys.readouterr().out.startswith("::notice ")


@pytest.mark.parametrize("content", [None, "", "not json", "{}", '{"runs": []}'])
def test_a_scan_that_printed_no_findings_is_said_and_does_not_fail_the_step(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], content: str | None
) -> None:
    path = tmp_path / "out.sarif"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    assert annotate.main(str(path)) == 0
    assert "::error::obelize printed no findings" in capsys.readouterr().out


# The pre-commit hook.


def test_the_hook_runs_obelize_scan_and_fails_on_what_is_left() -> None:
    hooks = yaml.safe_load((ROOT / ".pre-commit-hooks.yaml").read_text(encoding="utf-8"))
    (hook,) = hooks
    assert hook["id"] == "obelize-scan"
    assert hook["entry"] == "obelize scan"
    assert hook["pass_filenames"] is False
    assert hook["language"] == "python"
    assert hook["args"].count("--fail-on") == 3
    assert {hook["args"][i + 1] for i, one in enumerate(hook["args"]) if one == "--fail-on"} == {
        "eligible",
        "needs_review",
        "unsupported",
    }


def test_the_hook_manifest_is_valid_to_pre_commit() -> None:
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "pre_commit",
            "validate-manifest",
            str(ROOT / ".pre-commit-hooks.yaml"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_command_the_hook_runs_is_one_the_package_installs() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^obelize = "obelize\.cli:main"$', pyproject, re.MULTILINE)


# The upgrade mode: the action's half, and the example of the other.

EXAMPLE = ROOT / "examples" / "ci" / "upgrade-pull-request.yml"
PIN = re.compile(r"[\w./-]+@[0-9a-f]{40}")


def _example() -> dict[str, Any]:
    loaded = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _triggers(document: dict[str, Any]) -> dict[str, Any]:
    """PyYAML reads the key `on` as a boolean."""
    triggers: dict[str, Any] = document.get("on") or dict(document)[True]  # type: ignore[index]
    return triggers


def test_every_scan_step_waits_for_the_scan_mode_and_every_upgrade_step_for_the_other() -> None:
    steps = {step["name"]: step for step in _action()["runs"]["steps"]}
    for name in ("Scan", "Annotate", "Upload to code scanning", "Fail on what was found"):
        assert "inputs.mode == 'scan'" in steps[name]["if"], name
    for name in ("Upgrade", "Upload the upgrade", "Fail on an upgrade that was not proven"):
        assert "inputs.mode == 'upgrade'" in steps[name]["if"], name
    assert "Install uv" in steps
    assert "if" not in steps["Install uv"]
    assert "mode takes scan or upgrade" in steps["Check the mode"]["run"]


def test_the_scan_mode_runs_the_script_it_always_ran() -> None:
    scan = next(step for step in _action()["runs"]["steps"] if step["name"] == "Scan")
    assert scan["run"] == '"$ACTION_PATH/action/scan.sh"'
    assert set(scan["env"]) == {
        "ACTION_PATH",
        "OBELIZE_VERSION",
        "OBELIZE_PACKS",
        "OBELIZE_LIBRARY",
        "OBELIZE_MODULES",
        "OBELIZE_FAIL_ON",
        "OBELIZE_WORKDIR",
        "OBELIZE_SARIF_FILE",
    }


def test_the_upgrade_mode_holds_no_token_and_hands_each_input_over_in_the_environment() -> None:
    steps = json.dumps(_action()["runs"]["steps"])
    for token in ("secrets.", "github.token", "GITHUB_TOKEN", "GH_TOKEN", "pull_request_target"):
        assert token not in steps, token
    step = next(step for step in _action()["runs"]["steps"] if step["name"] == "Upgrade")
    assert step["run"] == 'python3 "$ACTION_PATH/action/upgrade.py" run'
    assert set(step["env"]) == {
        "ACTION_PATH",
        "OBELIZE_VERSION",
        "OBELIZE_DISTRIBUTIONS",
        "OBELIZE_FROM",
        "OBELIZE_ARTIFACT_NAME",
        "OBELIZE_WORKDIR",
        "OBELIZE_OUT",
    }


def test_the_artifact_is_kept_a_week_and_holds_nothing_hidden() -> None:
    step = next(s for s in _action()["runs"]["steps"] if s["name"] == "Upload the upgrade")
    assert step["with"]["retention-days"] == 7
    assert step["with"]["if-no-files-found"] == "error"
    assert "include-hidden-files" not in step["with"]
    assert step["with"]["name"] == "${{ inputs.artifact-name }}"
    assert "${{ runner.temp }}" not in step["with"]["path"]


def test_the_defaults_pass_a_move_nothing_proved_and_name_the_artifact_the_example_downloads() -> (
    None
):
    inputs = _action()["inputs"]
    assert inputs["fail-on-unproven"]["default"] == "false"
    assert inputs["artifact-name"]["default"] == "obelize-upgrade"
    downloads = [
        step["with"]["name"]
        for job in _example()["jobs"].values()
        for step in job["steps"]
        if step.get("uses", "").startswith("actions/download-artifact@")
    ]
    assert downloads == [inputs["artifact-name"]["default"]]


def test_the_example_runs_the_tests_in_a_job_with_nothing_to_write_with() -> None:
    document = _example()
    assert document["permissions"] == {}
    first, second = document["jobs"]["upgrade"], document["jobs"]["pull-request"]
    assert first["permissions"] == {"contents": "read"}
    assert second["permissions"] == {"contents": "write", "pull-requests": "write"}
    assert second["needs"] == "upgrade"
    assert second["if"] == "needs.upgrade.outputs.changed == 'true'"
    assert first["outputs"] == {"changed": "${{ steps.obelize.outputs.changed }}"}
    assert "env" not in first
    assert not any("env" in step for step in first["steps"])
    assert set(_triggers(document)) == {"schedule", "workflow_dispatch"}


def test_the_job_that_writes_runs_none_of_the_repositorys_code() -> None:
    steps = _example()["jobs"]["pull-request"]["steps"]
    assert [step.get("run") for step in steps if "run" in step] == [
        "gh auth setup-git",
        'python3 obelize/action/upgrade.py publish --artifacts "$ARTIFACTS" --repo repo '
        '--base "$BASE" --base-branch "$BASE_BRANCH" --distributions "$NAMES"',
    ]
    assert not any(step.get("uses", "").startswith("hakanbogan/obelize@") for step in steps)
    checkouts = [
        step["with"] for step in steps if step.get("uses", "").startswith("actions/checkout@")
    ]
    assert [one["path"] for one in checkouts] == ["repo", "obelize"]
    assert checkouts[1]["repository"] == "hakanbogan/obelize"


def test_the_dependencies_to_upgrade_are_listed_once_and_both_jobs_read_that_list() -> None:
    document = _example()
    assert set(document["env"]) == {"DISTRIBUTIONS"}
    steps = document["jobs"]["upgrade"]["steps"]
    action = next(step for step in steps if step.get("uses", "").startswith("hakanbogan/obelize@"))
    assert action["with"]["distributions"] == "${{ env.DISTRIBUTIONS }}"
    publish = document["jobs"]["pull-request"]["steps"][-1]
    assert publish["env"]["NAMES"] == "${{ env.DISTRIBUTIONS }}"


def test_the_example_pins_every_action_to_a_commit_and_no_credential_is_kept() -> None:
    placeholders = []
    for job in _example()["jobs"].values():
        for step in job["steps"]:
            name = step.get("uses")
            if name is None:
                continue
            if name.startswith("hakanbogan/obelize@"):
                placeholders.append(name)
            else:
                assert PIN.fullmatch(name), name
            if name.startswith("actions/checkout@"):
                assert step["with"]["persist-credentials"] is False
    text = EXAMPLE.read_text(encoding="utf-8")
    assert placeholders == ["hakanbogan/obelize@<commit>"]
    assert text.count("<commit>") == 3
    assert "pull_request" not in text.replace("pull-requests", "").replace("pull-request", "")
    assert "secrets." not in text
    assert "${{" not in "".join(
        step["run"] for job in _example()["jobs"].values() for step in job["steps"] if "run" in step
    )


def test_the_example_pins_are_the_commits_the_repository_pins_the_same_actions_to() -> None:
    ours = ACTION.read_text(encoding="utf-8") + "".join(
        path.read_text(encoding="utf-8") for path in (ROOT / ".github" / "workflows").glob("*.yml")
    )
    for job in _example()["jobs"].values():
        for step in job["steps"]:
            name = step.get("uses", "")
            if PIN.fullmatch(name) and not name.startswith("actions/download-artifact@"):
                assert name in ours, name


def test_the_documentation_shows_the_example_it_ships() -> None:
    page = (ROOT / "docs" / "UPGRADING_IN_CI.md").read_text(encoding="utf-8")
    block = re.search(r"```yaml\n(.*?)```", page, re.DOTALL)
    assert block is not None
    assert block.group(1) == EXAMPLE.read_text(encoding="utf-8")


@pytest.mark.skipif(
    not (Path(sys.executable).parent / "zizmor").exists(), reason="zizmor is in the workflows group"
)
def test_the_example_passes_zizmor_with_a_commit_in_place_of_the_placeholder(
    tmp_path: Path,
) -> None:
    folder = tmp_path / ".github" / "workflows"
    folder.mkdir(parents=True)
    text = EXAMPLE.read_text(encoding="utf-8").replace(
        "<commit>", "0123456789abcdef" * 2 + "01234567"
    )
    (folder / "upgrade.yml").write_text(text, encoding="utf-8")
    persona = ["--persona", "pedantic", str(tmp_path)]
    done = subprocess.run(
        [str(Path(sys.executable).parent / "zizmor"), "--offline", "--no-progress", *persona],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr

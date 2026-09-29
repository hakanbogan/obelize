"""Verify decisions over twenty-four cases, each a real program in `tests/fixtures/verify/tools/`.

TM-5, TM-9 and TM-10 are about what a real process does; a fake `subprocess` proves only the fake.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

from obelize.models import CommandResult, VerifyPhase, VerifyResult
from obelize.verify import runner, status
from platforms import PYTHON, alive, quoted

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "verify"
TOOLS = ROOT / "tools"
KEY: dict[str, Any] = yaml.safe_load((ROOT / "answers.yaml").read_text(encoding="utf-8"))
CASES: dict[str, dict[str, Any]] = {case["case"]: case for case in KEY["cases"]}

# Two literals each, so no committed line matches a secret scanner. `tools/leak.py` reads them
# from the environment, so the needle asserted is exactly the one it printed.
GOOGLE_KEY = "AIza" + "NotARealGoogleApiKeyForTestsOnly123"
NAMED_SECRET = "swordfish-" + "not-a-real-token"

# Generous: the assertion is that a killed group becomes gone, not how fast.
REAPED_S = 10.0


def spell(text: str, marker: Path) -> str:
    """The two things a command in the key cannot know: this interpreter, and tmp."""
    return text.format(python=PYTHON, marker=quoted(marker))


class Prompt:
    """A scripted `y`/`n` that records whether it was reached."""

    def __init__(self, answer: bool | None) -> None:
        self.answer = answer
        self.asked: list[str] = []

    def __call__(self, command: str) -> bool:
        self.asked.append(command)
        return bool(self.answer)


def environment(case: dict[str, Any]) -> dict[str, str]:
    """The ambient environment minus `CI`, so a local-mode case stays local when run in CI."""
    env = {name: value for name, value in os.environ.items() if name != "CI"}
    env["OBELIZE_SAMPLE_PLAIN"] = GOOGLE_KEY
    env["OBELIZE_TEST_TOKEN"] = NAMED_SECRET
    env.update(case.get("env") or {})
    return env


def _exited(actual: int | None, graded: int | str | None) -> bool:
    """`killed` is the key's word for "the program did not choose its code".

    On POSIX a signal ended it, which is a negative status. On Windows its job was terminated
    with `STATUS_CONTROL_C_EXIT`, which `GetExitCodeProcess` gives unsigned.
    """
    if graded != "killed":
        return actual == graded
    if sys.platform == "win32":
        return actual == 0xC000013A
    else:
        return actual is not None and actual < 0


def verify(case: dict[str, Any], work: Path, config_dir: Path, marker: Path) -> dict[str, Any]:
    """`fix --apply`'s order minus the apply and compile check: resolve, baseline, gate, after."""
    allowed = [spell(text, marker) for text in case.get("allowlist") or []]
    if allowed:
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / runner.ALLOWLIST_FILENAME).write_text(
            yaml.safe_dump({"verify": {"allow": allowed}}), encoding="utf-8"
        )
    for text in case.get("approved") or []:
        runner.remember(config_dir, str(work.resolve()), spell(text, marker))
    prompt = Prompt(case.get("answer"))
    plan = runner.resolve(
        work,
        mode=runner.Mode(**case["mode"]),
        config_dir=config_dir,
        cli_commands=[spell(text, marker) for text in case["cli"]],
        repo_commands=[spell(text, marker) for text in case["repo"]],
        ask=prompt,
    )
    outcome = {"plan": plan, "prompt": prompt, "config_dir": config_dir}
    environ = environment(case)
    if isinstance(plan, runner.Refused):
        return {**outcome, "result": VerifyResult(status="not_run", reason="policy_refused")}
    if not plan.commands:
        return {**outcome, "result": VerifyResult(status="not_run", reason="no_verify_commands")}
    before: VerifyPhase | None = None
    if case.get("baseline"):
        before = status.phase(
            runner.run(
                work,
                [runner.Command.of(spell(text, marker), "cli") for text in case["baseline"]],
                timeout_s=case["timeout_s"],
                environ=environ,
            )
        )
    settled = status.gate(before)
    if settled is not None:
        return {**outcome, "result": settled}
    after = status.phase(
        runner.run(work, plan.commands, timeout_s=case["timeout_s"], environ=environ)
    )
    return {**outcome, "result": status.decide(after, baseline=before)}


@pytest.fixture(scope="module")
def corpora(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, Any]]:
    """Every case, run once, each in its own tree and its own configuration home."""
    built: dict[str, dict[str, Any]] = {}
    for name in sorted(CASES):
        work = tmp_path_factory.mktemp(name)
        (work / "tools").mkdir()
        for tool in sorted(TOOLS.glob("*.py")):
            (work / "tools" / tool.name).write_bytes(tool.read_bytes())
        home = tmp_path_factory.mktemp(f"{name}-home")
        built[name] = verify(CASES[name], work, home / "obelize", work / "survived")
        built[name]["root"] = work
    return built


def test_every_tool_the_corpus_ships_is_used_by_some_case() -> None:
    """The four exceptions are timing mechanisms the unit tests grade with shortened waits."""
    written = " ".join(
        " ".join(case.get("cli", []) + case.get("repo", []) + (case.get("baseline") or []))
        for case in CASES.values()
    )
    unused = {tool.name for tool in TOOLS.glob("*.py") if tool.name not in written}
    assert unused == {"escapee.py", "leaves_a_child.py", "obeys_term.py", "stubborn.py"}, sorted(
        unused
    )


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_ladder_placed_every_command_where_the_key_says(
    name: str, corpora: dict[str, dict[str, Any]]
) -> None:
    case, built = CASES[name], corpora[name]
    marker = built["root"] / "survived"
    plan = built["plan"]
    if "refused" in case:
        assert isinstance(plan, runner.Refused), plan
        assert plan.command == spell(case["refused"], marker)
        return
    assert isinstance(plan, runner.Allowed), plan
    assert [(command.text, command.source) for command in plan.commands] == [
        (spell(row["command"], marker), row["source"]) for row in case["resolution"]
    ]


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_prompt_was_reached_exactly_when_the_key_says(
    name: str, corpora: dict[str, dict[str, Any]]
) -> None:
    """The difference between an approval that was read and one that was asked for."""
    prompt: Prompt = corpora[name]["prompt"]
    assert bool(prompt.asked) is CASES[name]["asked"]


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_store_holds_what_the_key_says_it_holds(
    name: str, corpora: dict[str, dict[str, Any]]
) -> None:
    case, built = CASES[name], corpora[name]
    if "stored" not in case:
        return
    marker = built["root"] / "survived"
    repository = str(built["root"].resolve())
    stored = runner.approvals(built["config_dir"])
    assert stored == {(repository, runner.digest(spell(text, marker))) for text in case["stored"]}


@pytest.mark.parametrize("name", sorted(CASES))
def test_each_command_ended_the_way_the_key_says(
    name: str, corpora: dict[str, dict[str, Any]]
) -> None:
    case = CASES[name]
    rows: tuple[CommandResult, ...] = corpora[name]["result"].commands
    assert [(row.status, row.reason) for row in rows] == [
        (row["status"], row["reason"]) for row in case["commands"]
    ]
    for row, expected in zip(rows, case["commands"], strict=True):
        assert _exited(row.exit_code, expected["exit_code"]), (row.exit_code, expected)


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_run_concluded_what_the_key_says(name: str, corpora: dict[str, dict[str, Any]]) -> None:
    case = CASES[name]
    result: VerifyResult = corpora[name]["result"]
    assert (result.status, result.reason) == (case["status"], case["reason"])
    assert status.exit_code(result) == case["exit"]
    expected = case.get("baseline_result")
    if expected is None:
        assert result.baseline is None
        return
    assert result.baseline is not None
    assert (result.baseline.status, result.baseline.reason) == (
        expected["status"],
        expected["reason"],
    )
    assert [(row.status, row.reason) for row in result.baseline.commands] == [
        (row["status"], row["reason"]) for row in expected["commands"]
    ]
    for row, graded in zip(result.baseline.commands, expected["commands"], strict=True):
        assert _exited(row.exit_code, graded["exit_code"]), (row.exit_code, graded)


@pytest.mark.parametrize("name", sorted(CASES))
def test_the_output_holds_what_the_key_says_and_not_what_it_does_not(
    name: str, corpora: dict[str, dict[str, Any]]
) -> None:
    case, built = CASES[name], corpora[name]
    expected = case.get("output")
    if expected is None:
        return
    recorded = "\n".join(row.output for row in built["result"].commands)
    for needle in expected["present"]:
        assert needle in recorded, needle
    for needle in expected["absent"]:
        assert needle not in recorded, needle
    if case.get("truncated"):
        assert [row.truncated for row in built["result"].commands] == [True]
    if case.get("cwd_is_root"):
        # Resolved on both sides: Windows runners hand out 8.3 temporary paths.
        (cwd,) = [
            line.removeprefix("CWD=") for line in recorded.splitlines() if line.startswith("CWD=")
        ]
        assert Path(cwd).resolve() == built["root"].resolve()


def test_the_secrets_were_in_the_raw_output_before_they_were_not_in_the_recorded_one(
    corpora: dict[str, dict[str, Any]],
) -> None:
    """TM-9 with its control: without the raw run, absence would pass over an empty capture."""
    (name,) = [name for name, case in CASES.items() if case.get("secrets_removed")]
    case, built = CASES[name], corpora[name]
    raw = subprocess.run(
        [sys.executable, "tools/leak.py"],
        cwd=built["root"],
        env=environment(case),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    assert GOOGLE_KEY in raw, "the control printed no key, so absence proves nothing"
    assert NAMED_SECRET in raw, "the control printed no token"
    recorded = "\n".join(row.output for row in built["result"].commands)
    assert GOOGLE_KEY not in recorded
    assert NAMED_SECRET not in recorded


def test_the_runaway_took_its_child_with_it(corpora: dict[str, dict[str, Any]]) -> None:
    """TM-10's sharp half: the kill reached the group and not only the command."""
    (name,) = [name for name, case in CASES.items() if case.get("group_is_gone")]
    built = corpora[name]
    recorded = built["result"].commands[0].output
    child = int(recorded.split()[1])
    deadline = time.monotonic() + REAPED_S
    while time.monotonic() < deadline:
        if not alive(child):
            break
        time.sleep(0.05)
    else:  # pragma: no cover - only reached when the group kill did not work
        pytest.fail(f"pid {child} outlived the process group it was killed with")
    assert not (built["root"] / "survived").exists(), "the child finished its sleep"

"""Twelve CLI runs against one scripted endpoint, graded by `tests/fixtures/providers/runs.yaml`.

The case is the route and the handler reads the file and line from each message, so one script
answers five questions five ways. Nothing patches `urlopen`: ADR-038 D7's transport is under test.
"""

from __future__ import annotations

import hashlib
import http.server
import json
import re
import shutil
import socket
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml
from typer.testing import CliRunner

from obelize.cli import app
from obelize.providers import openai_compat as adapter
from platforms import PYTHON

if TYPE_CHECKING:
    from collections.abc import Iterator

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "providers"
KEY: dict[str, Any] = yaml.safe_load((FIXTURES / "runs.yaml").read_text(encoding="utf-8"))
REQUESTS: dict[str, Any] = yaml.safe_load((FIXTURES / "requests.yaml").read_text(encoding="utf-8"))
CASES: dict[str, dict[str, Any]] = {case["case"]: case for case in KEY["cases"]}
NAMES = [case["case"] for case in KEY["cases"]]
SCRIPTS: dict[str, dict[str, Any]] = KEY["scripts"]
PROPOSALS: dict[str, dict[str, Any]] = KEY["proposals"]

runner = CliRunner()

# Read off the cases, so a case with no script reaches a server with nothing to say to it.
SCRIPT_OF = {name: CASES[name].get("script") for name in NAMES}

# `openai_compat.question`'s header lines: if they change, routing fails loudly rather than
# answering every question with the first case's reply.
FILE_LINE = re.compile(r"^file: (?P<path>.+)$", re.MULTILINE)
CHANGE_LINE = re.compile(r"^line to change: (?P<line>\d+)$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class Arrived:
    case: str
    site: str
    body: bytes


SEEN: list[Arrived] = []


def _site(body: bytes) -> str:
    """The `path:line` of the question a request carries."""
    message = json.loads(body)["messages"][1]["content"]
    path = FILE_LINE.search(message)
    line = CHANGE_LINE.search(message)
    assert path is not None, message[:200]
    assert line is not None, message[:200]
    return f"{path.group('path')}:{line.group('line')}"


def _answer(site: str, script: dict[str, Any]) -> tuple[int, bytes]:
    one = script["answers"][site]
    if "status" in one:
        return int(one["status"]), str(one["body"]).encode("utf-8")
    name = one["proposal"]
    envelope: dict[str, Any] = {
        "proposal": None if name is None else dict(PROPOSALS[name]),
    }
    body: dict[str, Any] = {
        "choices": [{"index": 0, "message": {"role": "assistant", "content": json.dumps(envelope)}}]
    }
    tokens = one.get("tokens")
    if tokens:
        body["usage"] = {"prompt_tokens": tokens[0], "completion_tokens": tokens[1]}
    return 200, json.dumps(body).encode("utf-8")


class Endpoint(http.server.BaseHTTPRequestHandler):
    """Every case behind one port, chosen by the first path segment."""

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        case = self.path.strip("/").split("/")[0]
        site = _site(body)
        SEEN.append(Arrived(case=case, site=site, body=body))
        name = SCRIPT_OF.get(case)
        assert name is not None, f"no script for {case}"
        status, payload = _answer(site, SCRIPTS[name])
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - the base signature
        """Silence the per-request log."""


@pytest.fixture(scope="module")
def server() -> Iterator[str]:
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Endpoint)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{int(httpd.server_address[1])}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _closed_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), "-c", "commit.gpgsign=false", *arguments],
        check=True,
        capture_output=True,
    )


def prepare(work: Path, case: dict[str, Any], base_url: str, config_home: Path) -> None:
    """One working copy, configured and committed as its case declares.

    The model block goes in the user's config (`config_home` is `XDG_CONFIG_HOME`);
    `repository_model` puts it in the checkout instead, which a repository may not do.
    """
    shutil.copytree(FIXTURES / "deep", work)
    settings = {
        "model": {
            "provider": KEY["provider"],
            "base_url": base_url,
            "model": KEY["model"],
            "api_key_env": KEY["api_key_env"],
            "log_prompts": bool(case.get("log_prompts")),
        }
    }
    if case.get("configured"):
        (config_home / "obelize").mkdir(parents=True)
        (config_home / "obelize" / "config.yml").write_text(
            yaml.safe_dump(settings), encoding="utf-8"
        )
    if case.get("repository_model"):
        (work / ".obelize.yml").write_text(yaml.safe_dump(settings), encoding="utf-8")
    spec = case.get("git") or {}
    if spec.get("init"):
        git(work, "init", "-q", "-b", "work")
        git(work, "config", "user.name", "obelize tests")
        git(work, "config", "user.email", "tests@obelize.invalid")
        git(work, "add", "-A")
        git(work, "commit", "-q", "-m", "the tree before obelize saw it")
    if spec.get("dirty"):
        with (work / "long.py").open("a", encoding="utf-8") as handle:
            handle.write("# edited by hand, and not committed\n")


def digests(folder: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(folder)): path.read_bytes()
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


@dataclass(frozen=True, slots=True)
class State:
    """One invocation, as the corpus left it."""

    case: dict[str, Any]
    work: Path
    folder: Path | None
    exit_code: int
    stdout: str
    files: dict[str, bytes]
    requests: list[Arrived]
    changed: list[str]

    @property
    def written(self) -> Path:
        assert self.folder is not None
        return self.folder

    def document(self, *parts: str) -> dict[str, Any]:
        loaded: dict[str, Any] = json.loads(
            self.written.joinpath(*parts).read_text(encoding="utf-8")
        )
        return loaded

    @property
    def run(self) -> dict[str, Any]:
        return self.document("run.json")

    @property
    def index(self) -> dict[str, Any]:
        return self.document("model", "model.json")

    def proposal(self, number: int) -> dict[str, Any]:
        return self.document("model", f"proposals-{number}.json")


def drive(name: str, work: Path, server: str, patch: pytest.MonkeyPatch) -> State:
    case = CASES[name]
    script = SCRIPTS.get(case.get("script") or "", {})
    host = f"http://127.0.0.1:{_closed_port()}" if script.get("closed_port") else server
    config_home = work.parent / f"{name}-config"
    config_home.mkdir()
    patch.setenv("XDG_CONFIG_HOME", str(config_home))
    prepare(work, case, f"{host}/{name}/v1", config_home)
    # Taken after `prepare`'s deliberate edits: `tree_changed` is only what the run changed.
    original = {
        path.name: (work / path.name).read_bytes()
        for path in (FIXTURES / "deep").iterdir()
        if path.is_file()
    }
    arguments = [
        *(word.format(python=PYTHON) for word in case["argv"]),
        "--repo",
        str(work),
        "--pack",
        KEY["pack"],
    ]
    patch.setenv(KEY["api_key_env"], KEY["api_key"])
    patch.setattr(sys, "argv", ["obelize", *arguments])
    result = runner.invoke(app, arguments, catch_exceptions=False)
    runs = work / ".obelize" / "runs"
    folders = sorted(runs.iterdir()) if runs.is_dir() else []
    return State(
        case=case,
        work=work,
        folder=folders[0] if folders else None,
        exit_code=result.exit_code,
        stdout=result.output,
        files=digests(folders[0]) if folders else {},
        requests=[one for one in SEEN if one.case == name],
        changed=sorted(
            name for name, data in original.items() if (work / name).read_bytes() != data
        ),
    )


@pytest.fixture(scope="module")
def driven(tmp_path_factory: pytest.TempPathFactory, server: str) -> dict[str, State]:
    root = tmp_path_factory.mktemp("model-runs")
    captured: dict[str, State] = {}
    with pytest.MonkeyPatch.context() as patch:
        for name in NAMES:
            captured[name] = drive(name, root / name, server, patch)
    return captured


@pytest.fixture
def state(request: pytest.FixtureRequest, driven: dict[str, State]) -> State:
    return driven[request.param]


def parametrised(function: Any) -> Any:
    return pytest.mark.parametrize("state", NAMES, ids=NAMES, indirect=True)(function)


@parametrised
def test_the_process_exits_with_the_code_the_key_gives_it(state: State) -> None:
    assert state.exit_code == state.case["exit_code"], state.stdout


@parametrised
def test_exactly_the_requests_the_key_allows_were_made(state: State) -> None:
    """Three cases send nothing; in `dirty_tree` that is a decision."""
    assert len(state.requests) == state.case["requests"]


@parametrised
def test_a_run_folder_exists_only_where_a_run_happened(state: State) -> None:
    assert (state.folder is not None) is state.case.get("run_folder", False)


@parametrised
def test_the_record_carries_the_model_object_the_key_writes(state: State) -> None:
    if not state.case.get("run_folder"):
        return
    record = state.run
    assert record["mode"] == state.case["mode"]
    assert record["model"] == state.case.get("model")
    assert (record["timings"]["model_ms"] is not None) is (record["model"] is not None)
    assert [row["code"] for row in record["refused"]] == state.case.get("refused", [])


@parametrised
def test_the_model_directory_holds_one_file_per_consultation(state: State) -> None:
    """Per consultation, not per proposal, which the failing case shows."""
    if not state.case.get("run_folder"):
        return
    names = sorted(name for name in state.files if name.startswith("model/"))
    if not state.case.get("model_dir"):
        assert names == []
        return
    expected = ["model/model.json"] + [
        f"model/proposals-{one['index']}.json" for one in KEY["consultations"]
    ]
    assert names == sorted(expected)
    assert state.index["consulted"] == len(KEY["consultations"])
    assert len(state.index["skipped"]) == KEY["skipped"]
    assert state.index["summary"] == state.case["model"]


@parametrised
def test_every_proposal_records_the_outcome_the_key_decides(state: State) -> None:
    for one in state.case.get("outcomes", []):
        record = state.proposal(one["index"])
        word = record["failure"] or record["refusal"]
        assert (record["outcome"], word) == (one["outcome"], one["word"]), record


@parametrised
def test_the_plan_and_the_disk_say_what_the_key_says(state: State) -> None:
    if "plan_files" not in state.case:
        return
    plan = state.document("plan.json")
    assert [row["path"] for row in plan["files"]] == state.case["plan_files"]
    record = state.run
    assert [row["path"] for row in record["file_edits"]] == state.case["file_edits"]
    if "edit_proposals" in state.case:
        assert [row["proposals"] for row in record["file_edits"]] == state.case["edit_proposals"]
    if "idempotent" in state.case:
        assert record["idempotent"] is state.case["idempotent"]


@parametrised
def test_the_tree_changed_where_the_key_says_and_nowhere_else(state: State) -> None:
    """Separate from the plan test: two cases that plan nothing still pin the disk afterwards."""
    if "tree_changed" not in state.case:
        return
    assert state.changed == state.case["tree_changed"]


@parametrised
def test_a_configured_run_says_where_the_code_is_about_to_go(state: State) -> None:
    """One line before the scan, and none under `provider: none` (ADR-039 D10).

    It names the host, not the URL, because a query string can carry a credential.
    """
    if "prints_endpoint" not in state.case:
        return
    heading = f"Model: {KEY['model']} at {KEY['host']} ({KEY['provider']})."
    assert (heading in state.stdout) is state.case["prints_endpoint"], state.stdout


@parametrised
def test_the_summary_says_what_the_model_cost_and_what_it_bought(state: State) -> None:
    model = state.case.get("model")
    if model is None or not state.case.get("run_folder"):
        return
    assert (
        f"Model: {model['model']} at {model['host']}, {model['proposals']} proposal(s), "
        f"{model['accepted']} written, {model['tokens_in']}+{model['tokens_out']} tokens"
        in state.stdout
    ), state.stdout


@parametrised
def test_the_report_says_what_became_of_every_consultation(state: State) -> None:
    """A row per consultation, so a misconfigured endpoint shows without opening `model/`."""
    if not state.case.get("model_dir"):
        return
    document = state.written.joinpath("REPORT.md").read_text(encoding="utf-8")
    assert "## Model" in document
    for one in state.case["outcomes"]:
        record = state.proposal(one["index"])
        assert f"| {one['index']} | `{record['path']}:{record['line']}` " in document
        assert f"`{one['outcome']}`" in document
        if one["word"]:
            assert f"`{one['word']}`" in document


@parametrised
def test_the_verification_ran_where_the_key_says_it_did(state: State) -> None:
    """The only case with a command: the model's files go through the verify order too."""
    wanted = state.case.get("verify")
    if wanted is None:
        return
    verify = state.run["verify"]
    assert verify["status"] == wanted["status"]
    assert verify["baseline"] is not None
    assert verify["baseline"]["status"] == wanted["baseline"]
    assert state.run["timings"]["verify_ms"] is not None


@parametrised
def test_a_written_proposal_is_still_a_review_item(state: State) -> None:
    """ADR-039 D6: the guard proves an edit safe to apply, not correct."""
    if not state.case.get("withheld_unchanged"):
        return
    record = state.run
    assert record["withheld"], "the repository has withheld rows and they are still withheld"
    assert record["exit_code"] == 4
    edits = state.document("plan.json")["edits"]
    proposed = [row for row in edits if row["status"] == "model_proposed"]
    assert [(row["path"], row["line"]) for row in proposed] == [
        ("nested.py", 31),
        ("spread.py", 25),
    ]
    assert all(row["reason"] == "generation_config_not_static" for row in proposed)
    assert all(row["rule_id"] is None for row in proposed)


@parametrised
def test_the_refusals_name_both_flags(state: State) -> None:
    for word in state.case.get("stderr_holds", []):
        assert word in state.stdout


@parametrised
def test_show_context_prints_every_string_the_payload_carries(state: State) -> None:
    shown = state.case.get("shows")
    if shown is None:
        return
    assert adapter.SYSTEM_PROMPT in state.stdout
    assert REQUESTS["message"] in state.stdout
    consultations, skipped = shown["counts"]
    assert (
        f"{consultations} question(s); {skipped} finding(s) left for review are not asked about"
        in state.stdout
    )
    assert ("Model: " in state.stdout) is shown["endpoint"]
    assert (KEY["host"] in state.stdout) is shown["endpoint"]


@parametrised
def test_the_prompt_is_stored_only_when_it_was_asked_for(state: State) -> None:
    if not state.case.get("model_dir"):
        return
    wanted = bool(state.case.get("prompts_stored"))
    for one in KEY["consultations"]:
        record = state.proposal(one["index"])
        assert (record["prompt"] is not None) is wanted
        if not wanted:
            continue
        digest = hashlib.sha256(record["prompt"].encode("utf-8")).hexdigest()
        assert digest == record["prompt_sha256"]
        # The bytes the server received, not a re-serialisation that agrees (ADR-039 D8).
        site = f"{one['path']}:{one['line']}"
        arrived = next(row for row in state.requests if row.site == site)
        assert record["prompt"].encode("utf-8") == arrived.body


@parametrised
def test_every_record_names_the_consultation_the_key_names(state: State) -> None:
    if not state.case.get("model_dir"):
        return
    for one in KEY["consultations"]:
        record = state.proposal(one["index"])
        assert (record["path"], record["line"]) == (one["path"], one["line"])
        assert [record["context_start_line"], record["context_end_line"]] == one["context"]
        assert record["provider"] == KEY["provider"]
        assert record["model"] == KEY["model"]


@parametrised
def test_the_credential_reaches_neither_a_payload_nor_the_model_evidence(state: State) -> None:
    """TM-3 covers what reaches a model, which `model/` records, not the whole run folder.

    `patch.diff` and `snapshots/` carry whole files, credentials included (`docs/PRIVACY.md`).
    """
    for secret in KEY["must_not_appear"]:
        assert secret not in state.stdout
        for one in state.requests:
            assert secret.encode("utf-8") not in one.body
        for name, data in state.files.items():
            if not name.startswith("model/"):
                continue
            assert secret.encode("utf-8") not in data, name


def test_the_patch_is_the_users_own_file_and_is_not_redacted(
    driven: dict[str, State],
) -> None:
    """`patch.diff` is deliberately unredacted: the `nested.py` hunk keeps the line-30 comment."""
    state = driven[KEY["also_in_the_patch"]]
    patch = state.written.joinpath("patch.diff").read_bytes()
    for secret in KEY["must_not_appear"]:
        assert secret.encode("utf-8") in patch


def test_the_key_names_the_consultations_the_corpus_makes(driven: dict[str, State]) -> None:
    """The key restates `answers.yaml`; this keeps the restatement safe."""
    sites = [f"{one['path']}:{one['line']}" for one in KEY["consultations"]]
    assert [one.site for one in driven["dry_run"].requests] == sites


def test_the_tokens_are_the_sum_of_the_answers_that_carried_any(
    driven: dict[str, State],
) -> None:
    for name, script in SCRIPTS.items():
        for case in NAMES:
            if SCRIPT_OF[case] != name or driven[case].case.get("model") is None:
                continue
            model = driven[case].run["model"]
            assert (model["tokens_in"], model["tokens_out"]) == (
                script["tokens_in"],
                script["tokens_out"],
            )

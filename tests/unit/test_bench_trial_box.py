"""The pure half of the trial box: what a container may be given, the Python a repository gets, how
a run's output is read and classified, how the self-test is judged, and the record's shape."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest
import trialrecords as records

from bench import trial_box as box
from bench.trial import probe, proxy
from platforms import BENCH

pytestmark = BENCH

ROOT = Path(__file__).resolve().parents[2]
LIMITS = box.Limits()
IMAGE = f"{box.IMAGE}:0123456789ab"


# The Docker command lines.


def create(*extra: str) -> list[str]:
    """A `docker create` that passes, with `extra` flags put before the image."""
    return ["create", "--name", f"{box.PREFIX}x", *extra, IMAGE, "true"]


def test_a_trial_container_is_made_with_exactly_these_arguments() -> None:
    assert box.trial_args(f"{box.PREFIX}r-1", IMAGE, ["sh", "-c", "true"], LIMITS, {}) == [
        "create",
        "--name",
        "obelize-trial-r-1",
        "--label",
        "obelize-trial=1",
        "--pull",
        "never",
        "--network",
        "obelize-trial-net",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--memory",
        "2g",
        "--memory-swap",
        "2g",
        "--cpus",
        "2",
        "--pids-limit",
        "1024",
        "--user",
        "10001:10001",
        "--init",
        "--log-driver",
        "none",
        "--ulimit",
        "core=0",
        IMAGE,
        "sh",
        "-c",
        "true",
    ]


def test_the_proxy_is_made_with_exactly_these_arguments() -> None:
    assert box.proxy_args(IMAGE) == [
        "create",
        "--name",
        "obelize-trial-proxy",
        "--label",
        "obelize-trial=1",
        "--pull",
        "never",
        "--network",
        "obelize-trial-net",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--memory",
        "256m",
        "--memory-swap",
        "256m",
        "--pids-limit",
        "256",
        "--user",
        "10001:10001",
        "--init",
        "--log-driver",
        "local",
        "--log-opt",
        "max-size=5m",
        "--log-opt",
        "max-file=2",
        IMAGE,
        "python",
        "/opt/box/proxy.py",
    ]


def test_the_networks_are_the_internal_one_and_the_proxys_own() -> None:
    assert box.network_args(box.NETWORK) == ["network", "create", "--internal", "obelize-trial-net"]
    assert box.network_args(box.EGRESS) == ["network", "create", "obelize-trial-out"]
    assert box.connect_args() == ["network", "connect", "obelize-trial-out", "obelize-trial-proxy"]
    with pytest.raises(box.UnsafeError, match="not a network of the box"):
        box.network_args("bridge")


def test_a_trial_is_given_the_proxy_and_a_timeout_and_nothing_of_the_machine() -> None:
    env = box.trial_env(LIMITS._replace(http_s=90))
    assert env == {
        "HTTP_PROXY": "http://obelize-trial-proxy:3128",
        "HTTPS_PROXY": "http://obelize-trial-proxy:3128",
        "http_proxy": "http://obelize-trial-proxy:3128",
        "https_proxy": "http://obelize-trial-proxy:3128",
        "NO_PROXY": "localhost,127.0.0.1,::1",
        "no_proxy": "localhost,127.0.0.1,::1",
        "UV_HTTP_TIMEOUT": "90",
    }
    argv = box.trial_args(f"{box.PREFIX}x", IMAGE, ["true"], LIMITS, {**env, "CI": "1"})
    given = [argv[at + 1] for at, word in enumerate(argv) if word == "-e"]
    assert given == sorted(f"{key}={value}" for key, value in {**env, "CI": "1"}.items())
    assert all("=" in one for one in given)


@pytest.mark.parametrize(
    ("env", "named"),
    [
        ({"HOME": "/Users/someone"}, "HOME"),
        ({"AWS_SECRET_ACCESS_KEY": "x"}, "AWS_SECRET_ACCESS_KEY"),
        ({"PATH": "/usr/bin"}, "PATH"),
        ({"HTTP_PROXY": "http://elsewhere:3128"}, "HTTP_PROXY"),
        ({"UV_HTTP_TIMEOUT": "0"}, "UV_HTTP_TIMEOUT"),
        ({"UV_HTTP_TIMEOUT": "9; id"}, "UV_HTTP_TIMEOUT"),
        ({"CI": "yes please"}, "CI"),
    ],
    ids=["home", "secret", "path", "proxy", "zero", "shell", "ci"],
)
def test_a_variable_off_the_allowlist_or_with_another_value_cannot_be_given(
    env: dict[str, str], named: str
) -> None:
    with pytest.raises(box.UnsafeError, match=named):
        box.trial_args(f"{box.PREFIX}x", IMAGE, ["true"], LIMITS, env)


FORBIDDEN = [
    (["--privileged"], "--privileged is not allowed"),
    (["--privileged=true"], "--privileged is not allowed"),
    (["--cap-add", "SYS_ADMIN"], "--cap-add is not allowed"),
    (["--cap-add=ALL"], "--cap-add is not allowed"),
    (["--network", "host"], "--network host is not an allowed value"),
    (["--network=host"], "--network host is not an allowed value"),
    (["--network", "bridge"], "--network bridge is not an allowed value"),
    (["--network", "obelize-trial-out"], "--network obelize-trial-out is not an allowed value"),
    (["-v", "/:/host"], "-v is not allowed"),
    (["--volume", "/Users:/Users:ro"], "--volume is not allowed"),
    (["--mount", "type=bind,src=/,dst=/h"], "--mount is not allowed"),
    (["-v", "/var/run/docker.sock:/var/run/docker.sock"], "-v is not allowed"),
    (["--volumes-from", "other"], "--volumes-from is not allowed"),
    (["-p", "8080:80"], "-p is not allowed"),
    (["--publish", "80"], "--publish is not allowed"),
    (["-P"], "-P is not allowed"),
    (["--pid", "host"], "--pid is not allowed"),
    (["--ipc", "host"], "--ipc is not allowed"),
    (["--userns", "host"], "--userns is not allowed"),
    (["--device", "/dev/kmsg"], "--device is not allowed"),
    (["--user", "root"], "--user root is not an allowed value"),
    (["--user", "0:0"], "--user 0:0 is not an allowed value"),
    (["--security-opt", "seccomp=unconfined"], "is not an allowed value"),
    (["--security-opt", "apparmor=unconfined"], "is not an allowed value"),
    (["--env-file", "/Users/me/.env"], "--env-file is not allowed"),
    (["-e", "CI"], "CI is not an allowed variable"),
    (["--env", "HOME"], "HOME is not an allowed variable"),
    (["-e", "SECRET=1"], "SECRET is not an allowed variable"),
    (["--add-host", "x:1.2.3.4"], "--add-host is not allowed"),
    (["--dns", "8.8.8.8"], "--dns is not allowed"),
    (["--ulimit", "nofile=1"], "--ulimit nofile=1 is not an allowed value"),
    (["--memory", "0"], "--memory 0 is not an allowed value"),
    (["--cpus", "0"], "--cpus 0 is not an allowed value"),
    (["--pids-limit", "-1"], "--pids-limit -1 is not an allowed value"),
    (["--pull", "always"], "--pull always is not an allowed value"),
    (["--name", "someone-elses"], "is not an allowed value"),
    (["--label", "x=1"], "--label x=1 is not an allowed value"),
    (["--log-driver", "syslog"], "--log-driver syslog is not an allowed value"),
    (["-it"], "-it is not allowed"),
]


@pytest.mark.parametrize(
    ("extra", "problem"), FORBIDDEN, ids=[" ".join(extra)[:24] for extra, _ in FORBIDDEN]
)
def test_a_forbidden_flag_is_refused_whatever_its_spelling(extra: list[str], problem: str) -> None:
    assert any(problem in found for found in box.check(create(*extra))), box.check(create(*extra))


def test_a_flag_with_no_value_is_refused() -> None:
    assert "--memory has no value" in box.check(["create", "--memory"])


def test_a_list_with_nothing_forbidden_passes() -> None:
    assert box.check(create()) == []
    assert box.check(create("--init", "-e", "CI=1", "--env=NO_PROXY=localhost,127.0.0.1,::1")) == []


@pytest.mark.parametrize(
    ("argv", "problem"),
    [
        (["run", "--name", f"{box.PREFIX}x", IMAGE], "not a `docker create`"),
        ([], "not a `docker create`"),
        (["create", "--name", f"{box.PREFIX}x"], "the image is not the box's own"),
        (["create", "--name", f"{box.PREFIX}x", "python:3.12"], "the image is not the box's own"),
        (["create", "--name", f"{box.PREFIX}x", "obelize-trial:proto"], "the image"),
        ([*create(), "cat", "/var/run/docker.sock"], "the Docker socket is named"),
    ],
    ids=["run", "empty", "no-image", "stock", "prototype", "socket"],
)
def test_what_is_not_a_create_of_the_box_is_refused(argv: list[str], problem: str) -> None:
    assert problem in box.check(argv)[-1] or problem in box.check(argv)


def test_the_builder_refuses_a_command_that_names_the_docker_socket() -> None:
    with pytest.raises(box.UnsafeError, match="Docker socket"):
        box.trial_args(f"{box.PREFIX}x", IMAGE, ["ls", "/var/run/docker.sock"], LIMITS, {})


@pytest.mark.parametrize("name", ["x", "other-prefix-x", f"{box.PREFIX}", f"{box.PREFIX}A"])
def test_a_container_outside_the_prefix_cannot_be_made(name: str) -> None:
    with pytest.raises(box.UnsafeError, match="--name"):
        box.trial_args(name, IMAGE, ["true"], LIMITS, {})


def test_every_container_the_builder_makes_passes_the_check_whatever_the_limits() -> None:
    for limits in (LIMITS, LIMITS._replace(memory_gb=4, cpus=8, pids=64, http_s=600)):
        argv = box.trial_args(f"{box.PREFIX}y", IMAGE, ["true"], limits, box.trial_env(limits))
        assert box.check(argv) == []
        flags = {word for word in argv if word.startswith("-")}
        assert not flags & {"--privileged", "--cap-add", "-v", "--volume", "--mount", "-p"}
        assert argv[argv.index("--network") + 1] == box.NETWORK


def test_the_collector_names_no_flag_the_builder_cannot_make() -> None:
    """The one place that runs `docker` has no privilege, mount, port or network of its own."""
    source = (ROOT / "bench" / "trial_collect.py").read_text(encoding="utf-8")
    for flag in (
        "--privileged",
        "--cap-add",
        "--volume",
        "--mount",
        "--publish",
        "--network",
        "--device",
        "--pid",
        "--env-file",
        "--add-host",
        "--userns",
        "-v",
        "-p",
        "-e",
        "shell=True",
        "docker.sock",
        "system prune",
    ):
        assert f'"{flag}"' not in source, flag
        assert f"'{flag}'" not in source, flag
    assert "docker(*trial_box.trial_args(" in source
    assert "docker(*trial_box.proxy_args(" in source


@pytest.mark.parametrize(
    ("old", "timeout", "new"),
    [("1.10.26", None, "2.12.5"), (None, None, None), ("2.0", 60, None), ("1.0", None, None)],
    ids=["from-to", "no-from", "timeout", "no-to"],
)
def test_the_trial_command_is_obelizes_with_the_python_and_without_a_prompt(
    old: str | None, timeout: int | None, new: str | None
) -> None:
    command = box.run_command("pydantic", old, "3.11", timeout, new)
    assert command[:5] == ["sh", "-c", command[2], "sh", "obelize"]
    assert "cp /work/repo/.obelize/trials/*/trial.json /work/out/" in command[2]
    assert command[2].startswith('"$@"; code=$?;')
    assert command[2].endswith("exit $code")
    assert command[5:] == [
        "upgrade",
        "pydantic",
        *(["--from", old] if old else []),
        *(["--to", new] if new else []),
        "--apply",
        "--yes",
        "--repo",
        "/work/repo",
        "--python",
        "3.11",
        *(["--timeout", str(timeout)] if timeout else []),
    ]


@pytest.mark.parametrize(
    ("distribution", "old", "python", "new"),
    [
        ("x; id", "1.0", "3.12", None),
        ("$(id)", "1.0", "3.12", None),
        ("pydantic", "1.0; id", "3.12", None),
        ("pydantic", "1.0", "3.12", "2.0 && id"),
        ("p", "1", "3", None),
    ],
    ids=["semicolon", "substitution", "release", "target", "python"],
)
def test_a_word_a_shell_could_read_is_refused(
    distribution: str, old: str, python: str, new: str | None
) -> None:
    with pytest.raises(box.UnsafeError):
        box.run_command(distribution, old, python, new=new)


# Which Python.

INSTALLED = {
    "3.9": "3.9.25",
    "3.10": "3.10.21",
    "3.11": "3.11.16",
    "3.12": "3.12.14",
    "3.13": "3.13.15",
    "3.14": "3.14.7",
}


def declared(spec: str) -> str:
    return f'[project]\nname = "p"\nrequires-python = "{spec}"\n'


@pytest.mark.parametrize(
    ("pyproject", "version", "expected"),
    [
        (declared(">=3.9"), None, "3.13"),
        (declared(">=3.8,<3.12"), None, "3.11"),
        (declared("==3.10.*"), None, "3.10"),
        (declared("~=3.9.0"), None, "3.9"),
        (declared(">=3.10.4"), None, "3.13"),
        (declared(">=3.10.22,<3.11"), None, "3.12"),
        (declared("<3.9"), None, "3.12"),
        (declared(">=3.14"), "3.14\n", "3.14"),
        (declared(">=3.14"), None, "3.12"),
        (declared(">=3.11"), "3.9", "3.13"),
        (declared("not a specifier"), "3.10", "3.10"),
        ('[project]\nname = "p"\n', "3.11.4\n", "3.11"),
        ("[project\n", "3.10\n", "3.10"),
        ("[tool.poetry]\nname = 'p'\n", None, "3.12"),
        ("[project]\nrequires-python = 3\n", None, "3.12"),
        (None, "cpython-3.10.2\n", "3.10"),
        (None, "# a comment\n\n 3.9 # old\n", "3.9"),
        (None, "pypy3.9\n", "3.12"),
        (None, "3.99\n", "3.12"),
        (None, "3.1\n", "3.12"),
        (None, "\n\n", "3.12"),
        (None, None, "3.12"),
    ],
    ids=[
        "any",
        "range",
        "wild",
        "compatible",
        "patch-floor",
        "patch-floor-over",
        "too-old",
        "future-pinned",
        "future-unpinned",
        "requires-beats-pin",
        "invalid-spec",
        "no-requires",
        "bad-toml",
        "other-table",
        "not-a-string",
        "cpython-pin",
        "comment",
        "pypy",
        "missing",
        "short",
        "blank",
        "nothing",
    ],
)
def test_the_python_is_the_newest_the_declaration_admits_else_the_pin_else_3_12(
    pyproject: str | None, version: str | None, expected: str
) -> None:
    assert box.choose_python(pyproject, version, INSTALLED) == expected


# What a run printed.

OK_LINE = (
    "Trial of pypdf2 3.0.1 to pypdf>=6.19: pass; 2 test(s) passed before, 0 broke, "
    "0 failed once and passed again. Evidence: <repo>/.obelize/trials/20261027T174143Z-ee125e49"
)
FAIL_LINE = (
    "Trial of pydantic 1.10.26 to pydantic>=2,<3: fail (tests_broke); 40 test(s) passed before, "
    "3 broke, 1 failed once and passed again. Evidence: .obelize/trials/20261027T000000Z-aa"
)
INCONCLUSIVE_LINE = (
    "Trial of urllib3 1.26.20 to urllib3>=2,<3: inconclusive (no_junit). Evidence: .obelize/t/x"
)
PASS_OUTPUT = f"""obelize contacts pypi.org
Moving pypdf2 3.0.1 to pypdf>=6.19. Using the pack py-pdf/pypdf2-to-pypdf.
Running the tests on the release in use
{OK_LINE}
obelize fix  py-pdf/pypdf2-to-pypdf 0.4.1

Mode apply: 2 file(s) written.

  app.py  (1 hunk(s))  written
"""


def test_the_trial_line_gives_the_verdict_and_the_counts() -> None:
    assert box.parse_trial_line(PASS_OUTPUT) == box.TrialLine("pass", None, 2, 0, 0)
    assert box.parse_trial_line(FAIL_LINE) == box.TrialLine("fail", "tests_broke", 40, 3, 1)
    assert box.parse_trial_line(INCONCLUSIVE_LINE) == box.TrialLine(
        "inconclusive", "no_junit", 0, 0, 0
    )


def test_the_last_trial_line_counts_and_a_line_that_is_not_one_does_not() -> None:
    both = f"{FAIL_LINE}\n{OK_LINE}\n"
    assert box.parse_trial_line(both) == box.TrialLine("pass", None, 2, 0, 0)
    assert box.parse_trial_line("Trial of x: maybe") is None
    assert box.parse_trial_line("") is None


def test_the_files_written_and_left_are_read_from_the_lines_the_engine_prints() -> None:
    partial = (
        "Part of the move: 3 file(s) written, 2 left as they were because a place in each is left "
        "for you (a.py, b.py). The dependency line follows the files written."
    )
    notice = "The move is partial: 2 file(s) were left as they were because a place in each is left"
    assert box.parse_files(PASS_OUTPUT) == (2, None, 0)
    assert box.parse_files(f"Mode apply: 3 file(s) written.\n{partial}") == (3, 2, 0)
    assert box.parse_files(notice) == (None, 2, 0)
    assert box.parse_files("Mode plan: a dry run.") == (None, None, 0)


PLACES_OUTPUT = f"""{OK_LINE}
obelize fix  py-pdf/pypdf2-to-pypdf 0.4.1

Mode apply: 2 file(s) written.

  app.py  (1 hunk(s))  written
  requirements.txt  (1 hunk(s))  written

4 finding(s) left for you. Most common reasons: flag_only_surface (3).
  legacy.py:5  PyPDF2.PdfFileMerger  flag_only_surface
"""


def test_the_places_a_write_left_are_counted_where_no_whole_file_was() -> None:
    assert box.parse_files(PLACES_OUTPUT) == (2, None, 4)


def test_a_stream_is_kept_by_its_head_and_its_tail() -> None:
    small = box.Capture(head=8, tail=8)
    small.feed(b"abc")
    assert small.text() == "abc"
    long = box.Capture(head=4, tail=6)
    for piece in (b"ab", b"cdef", b"ghij", b"klmn", b"op\xff"):
        long.feed(piece)
    assert long.text() == "abcd\n[7 byte(s) cut]\nlmnop\ufffd"
    assert box.parse_trial_line(box.Capture().text()) is None
    big = box.Capture(head=10, tail=len(PASS_OUTPUT) + 100)
    big.feed(b"x" * 5000 + PASS_OUTPUT.encode())
    assert box.parse_trial_line(big.text()) == box.TrialLine("pass", None, 2, 0, 0)
    assert box.parse_files(big.text()) == (2, None, 0)


GOOD = {
    "distribution": "pypdf2",
    "from": "3.0.1",
    "to": "pypdf>=6.19",
    "command": ["python", "-m", "pytest"],
    "status": "pass",
    "reason": None,
    "compared": 2,
    "broken": [],
    "fixed": [],
    "flaky": [],
    "written": ["app.py", "requirements.txt"],
    "held": [],
    "model": None,
}


def trial_json(**changes: Any) -> str:
    return json.dumps({**GOOD, **changes})


def test_trial_json_is_read_with_its_lists_and_a_missing_held_is_none_held() -> None:
    parsed = box.parse_trial_json(trial_json())
    assert parsed is not None
    assert parsed["written"] == ["app.py", "requirements.txt"]
    older = {key: value for key, value in GOOD.items() if key != "held"}
    assert box.parse_trial_json(json.dumps(older)) == {**older, "held": []}
    flaky = box.parse_trial_json(trial_json(flaky=["t::a"], broken=["t::b"], status="fail"))
    assert flaky is not None
    assert flaky["flaky"] == ["t::a"]


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "not json",
        "[]",
        "1",
        trial_json(status="maybe"),
        trial_json(status=None),
        trial_json(reason=3),
        trial_json(compared="2"),
        trial_json(compared=True),
        trial_json(broken="t"),
        trial_json(broken=[1]),
        trial_json(written=None),
        trial_json(held="x"),
        trial_json(held=[3]),
    ],
    ids=lambda text: str(text)[:20],
)
def test_a_file_that_is_not_the_engines_trial_json_is_not_read(text: str | None) -> None:
    assert box.parse_trial_json(text) is None


def outcome(
    output: str = "", code: int | None = 0, trial: str | None = None, **kept: Any
) -> box.Outcome:
    fields: dict[str, Any] = {"timed_out": False, "oom": False, "disk": False, **kept}
    return box.Outcome(
        code,
        fields["timed_out"],
        fields["oom"],
        fields["disk"],
        output,
        box.parse_trial_json(trial),
    )


@pytest.mark.parametrize(
    ("done", "expected"),
    [
        (outcome(PASS_OUTPUT, 0, trial_json()), ("pass", None)),
        (outcome(PASS_OUTPUT, 4, trial_json()), ("pass", None)),
        (outcome("", 0, trial_json()), ("pass", None)),
        (
            outcome(FAIL_LINE, 3, trial_json(status="fail", reason="tests_broke")),
            ("fail", "tests_broke"),
        ),
        (
            outcome(INCONCLUSIVE_LINE, 6, trial_json(status="inconclusive", reason="no_junit")),
            ("inconclusive", "no_junit"),
        ),
        (outcome(PASS_OUTPUT, 5, trial_json()), ("error", "write_failed")),
        (outcome(PASS_OUTPUT, 137, trial_json()), ("error", "write_failed")),
        (
            outcome(FAIL_LINE, 0, trial_json(status="fail", reason="tests_broke")),
            ("error", "exit_mismatch"),
        ),
        (
            outcome(PASS_OUTPUT, 0, trial_json(status="fail", reason="tests_broke")),
            ("error", "verdict_mismatch"),
        ),
        (outcome(PASS_OUTPUT, 0, trial_json(compared=9)), ("pass", None)),
        (outcome(PASS_OUTPUT, 0, timed_out=True), ("timeout", "wall_clock")),
        (outcome(PASS_OUTPUT, 0, trial_json(), timed_out=True), ("timeout", "wall_clock")),
        (outcome("", 137, disk=True), ("error", "disk")),
        (outcome("", 137, oom=True), ("error", "oom")),
        (outcome("uv sync failed: no matching distribution", 6), ("error", "environment")),
        (outcome("no way to install the dependencies was found", 6), ("error", "environment")),
        (outcome("x is larger than a trial copies: 200000 files", 6), ("error", "copy")),
        (outcome("The tree has uncommitted changes.", 5), ("error", "not_started")),
        (outcome("Pass --yes to agree.", 2), ("error", "not_started")),
        (outcome("a library error", 1), ("error", "not_started")),
        (outcome("something else", 6), ("error", "no_verdict")),
        (outcome("", None), ("error", "no_verdict")),
        (outcome("uv sync failed: Killed", 6, oom=True), ("error", "oom")),
    ],
    ids=[
        "pass",
        "pass-places-left",
        "pass-no-line",
        "fail",
        "inconclusive",
        "write-failed",
        "killed-after-verdict",
        "fail-exit",
        "line-disagrees",
        "pass-compared",
        "timeout",
        "timeout-with-verdict",
        "disk",
        "oom",
        "environment",
        "no-recipe",
        "copy",
        "dirty",
        "consent",
        "library",
        "no-verdict",
        "no-code",
        "oom-beats-text",
    ],
)
def test_a_run_is_classified_by_its_verdict_and_the_exit_code_only_checks_it(
    done: box.Outcome, expected: tuple[str, str | None]
) -> None:
    assert box.classify(done) == expected


def test_every_status_and_reason_classify_can_return_is_in_the_vocabulary() -> None:
    assert set(box.EXITS) | {"error", "timeout"} == set(box.STATUSES)
    assert set(box.REASONS) == set(box.STATUSES)
    for status, reason in (("error", "write_failed"), ("timeout", "wall_clock")):
        assert reason in box.REASONS[status]


# What the proxy counted.

TOTALS = {
    "totals": {
        "allow": {"pypi.org:443": 7, "files.pythonhosted.org:443": 31},
        "deny": {"example.com:443": 2, "evil host": 1, "(other)": 4},
        "error": {},
    }
}


def test_the_last_totals_line_is_the_count_and_a_name_the_proxy_could_not_print_is_set_aside() -> (
    None
):
    logs = "\n".join(
        [
            "proxy up",
            json.dumps({"verdict": "allow", "target": "pypi.org:443"}),
            json.dumps({"totals": {"allow": {"pypi.org:443": 1}, "deny": {}, "error": {}}}),
            "not json",
            json.dumps(TOTALS),
            "[1]",
        ]
    )
    assert box.parse_totals(logs) == {
        "allow": {"pypi.org:443": 7, "files.pythonhosted.org:443": 31},
        "deny": {"example.com:443": 2, "(invalid)": 1, "(other)": 4},
        "error": {},
    }


@pytest.mark.parametrize(
    "logs",
    [
        "",
        "proxy up",
        json.dumps({"totals": 3}),
        json.dumps({"totals": {"allow": 3}}),
        "[1, 2]",
        "7",
    ],
    ids=["empty", "up", "scalar", "not-a-count-table", "list", "number"],
)
def test_logs_with_no_totals_have_no_counts(logs: str) -> None:
    assert box.parse_totals(logs) is None


def test_a_count_that_is_not_a_number_and_a_verdict_that_is_not_one_are_dropped() -> None:
    logs = json.dumps(
        {"totals": {"allow": {"pypi.org:443": "x", "a.org:443": 2}, "other": {"a": 1}}}
    )
    assert box.parse_totals(logs) == {"allow": {"a.org:443": 2}}


# What the self-test judges.

EXPECT = box.expect(LIMITS, ["PATH", "LANG", "HOME", "UV_PYTHON_DOWNLOADS"])


def attempt(label: str, reached: bool = False) -> dict[str, Any]:
    return {"label": label, "reached": reached, "detail": "Network is unreachable"}


def good_report() -> dict[str, Any]:
    return {
        "uid": [10001, 10001, 10001, 10001],
        "gid": [10001, 10001, 10001, 10001],
        "groups": [10001],
        "status": {
            "CapInh": "0000000000000000",
            "CapPrm": "0000000000000000",
            "CapEff": "0000000000000000",
            "CapBnd": "0000000000000000",
            "CapAmb": "0000000000000000",
            "NoNewPrivs": "1",
            "Seccomp": "2",
        },
        "pid1": "/sbin/docker-init -- python /opt/box/probe.py",
        "mounts": [
            "/",
            "/proc",
            "/dev/pts",
            "/sys/fs/cgroup",
            "/etc/hosts",
            "/usr/sbin/docker-init",
        ],
        "host_paths": [],
        "env": ["HOME", "HOSTNAME", "HTTP_PROXY", "LANG", "PATH", "UV_HTTP_TIMEOUT"],
        "cgroup": {
            "memory.max": "2147483648",
            "memory.swap.max": "0",
            "pids.max": "1024",
            "cpu.max": "200000 100000",
        },
        "pythons": dict(INSTALLED),
        "direct": [attempt("tcp 1.1.1.1:443"), attempt("dns example.com")],
        "denied": [
            {"target": "example.com:443", "status": 403, "http": None, "detail": ""},
            {"target": "example.com:80", "status": 403, "http": None, "detail": ""},
        ],
        "allowed": [
            {"target": "pypi.org:443", "status": 200, "http": 200, "detail": ""},
            {"target": "files.pythonhosted.org:443", "status": 200, "http": 404, "detail": ""},
        ],
    }


def test_a_container_that_holds_everything_passes() -> None:
    assert box.judge_probe(good_report(), EXPECT) == []
    assert box.judge_probe({**good_report(), "groups": []}, EXPECT) == []


def broken(path: str, value: Any) -> dict[str, Any]:
    report = good_report()
    node = report
    *parents, last = path.split("/")
    for part in parents:
        node = node[part]
    if value is KeyError:
        del node[last]
    else:
        node[last] = value
    return report


@pytest.mark.parametrize(
    ("path", "value", "fragment"),
    [
        ("uid", [0, 0, 0, 0], "uid is [0, 0, 0, 0], not 10001"),
        ("uid", [10001, 10001, 0, 10001], "uid is [10001, 10001, 0, 10001]"),
        ("gid", [0], "gid is [0], not 10001"),
        ("uid", KeyError, "uid is None"),
        ("gid", [], "gid is [], not 10001"),
        ("groups", [10001, 0], "supplementary groups"),
        ("groups", KeyError, "supplementary groups"),
        ("status/CapEff", "00000000a80425fb", "capabilities are not empty"),
        ("status/CapBnd", KeyError, "capabilities are not empty"),
        ("status/NoNewPrivs", "0", "no-new-privileges"),
        ("pid1", "systemd", "process namespace"),
        ("mounts", ["/", "/Users"], "mounts beyond the container's own: ['/Users']"),
        ("mounts", ["/", "/etc/passwd"], "mounts beyond"),
        ("mounts", [], "mounts beyond the container's own: none read"),
        ("host_paths", ["/Users"], "host paths exist"),
        ("host_paths", KeyError, "host paths exist"),
        ("env", ["HOME", "AWS_SECRET_ACCESS_KEY", "USER"], "['AWS_SECRET_ACCESS_KEY', 'USER']"),
        ("cgroup/memory.max", "max", "memory.max is max"),
        ("cgroup/memory.max", KeyError, "memory.max is None"),
        ("cgroup/memory.swap.max", "max", "memory.swap.max is max"),
        ("cgroup/pids.max", "max", "pids.max is max"),
        ("cgroup/cpu.max", "max 100000", "cpu.max is max 100000"),
        ("direct", [attempt("tcp 1.1.1.1:443", True)], "reached tcp 1.1.1.1:443"),
        ("direct", [], "no direct attempt was made"),
        ("pythons", {"3.12": "3.12.1"}, "the box holds no Python 3.13"),
        ("denied", [], "no request to the proxy was denied or tried"),
        ("denied", [{"target": "github.com:443", "status": 200}], "answered 200 to github.com:443"),
        ("denied", [{"target": "github.com:443", "status": None}], "answered None to github.com"),
        ("allowed", [], "the index hosts tried were []"),
        ("allowed", [{"target": "pypi.org:443", "status": 200, "http": 200}], "index hosts tried"),
    ],
    ids=lambda value: str(value)[:28],
)
def test_each_property_the_probe_does_not_show_is_a_failure(
    path: str, value: Any, fragment: str
) -> None:
    found = box.judge_probe(broken(path, value), EXPECT)
    assert any(fragment in one for one in found), found


@pytest.mark.parametrize(
    "allowed",
    [
        [
            {"target": "pypi.org:443", "status": 403},
            {"target": "files.pythonhosted.org:443", "status": 200, "http": 200},
        ],
        [
            {"target": "pypi.org:443", "status": 200, "http": None},
            {"target": "files.pythonhosted.org:443", "status": 200, "http": 200},
        ],
        [
            {"target": "pypi.org:443", "status": 200, "http": 502},
            {"target": "files.pythonhosted.org:443", "status": 200, "http": 200},
        ],
    ],
    ids=["refused", "no-reply", "bad-gateway"],
)
def test_an_index_host_the_proxy_does_not_carry_is_a_failure(allowed: list[dict[str, Any]]) -> None:
    found = box.judge_probe(broken("allowed", allowed), EXPECT)
    assert any("the proxy did not carry pypi.org:443" in one for one in found), found


def test_a_document_with_nothing_in_it_fails_everything() -> None:
    assert len(box.judge_probe({}, EXPECT)) >= 10


def good_inspect() -> tuple[dict[str, Any], dict[str, Any]]:
    container = {
        "HostConfig": {
            "Privileged": False,
            "CapAdd": None,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges"],
            "NetworkMode": "obelize-trial-net",
            "Memory": 2147483648,
            "MemorySwap": 2147483648,
            "NanoCpus": 2000000000,
            "PidsLimit": 1024,
            "PidMode": "",
            "UsernsMode": "",
            "Binds": None,
            "PortBindings": {},
            "Devices": [],
            "ExtraHosts": None,
            "Dns": None,
            "VolumesFrom": None,
        },
        "Config": {
            "User": "10001:10001",
            "Env": ["HTTP_PROXY=http://obelize-trial-proxy:3128", "PATH=/bin"],
        },
        "Mounts": [],
        "NetworkSettings": {"Networks": {"obelize-trial-net": {}}},
    }
    return container, {"Internal": True}


def test_the_daemons_own_view_of_a_container_made_as_a_trial_is_passes() -> None:
    container, network = good_inspect()
    assert box.judge_inspect(container, network, EXPECT) == []


@pytest.mark.parametrize(
    ("where", "key", "value", "fragment"),
    [
        ("HostConfig", "Privileged", True, "Privileged is True"),
        ("HostConfig", "CapAdd", ["SYS_ADMIN"], "CapAdd is ['SYS_ADMIN']"),
        ("HostConfig", "CapDrop", None, "CapDrop is None"),
        ("HostConfig", "SecurityOpt", [], "SecurityOpt is []"),
        ("HostConfig", "NetworkMode", "bridge", "NetworkMode is 'bridge'"),
        ("HostConfig", "Memory", 0, "Memory is 0"),
        ("HostConfig", "MemorySwap", -1, "MemorySwap is -1"),
        ("HostConfig", "NanoCpus", 0, "NanoCpus is 0"),
        ("HostConfig", "PidsLimit", None, "PidsLimit is None"),
        ("HostConfig", "PidMode", "host", "PidMode is 'host'"),
        ("HostConfig", "UsernsMode", "host", "UsernsMode is 'host'"),
        ("HostConfig", "Binds", ["/:/h"], "Binds is not empty"),
        ("HostConfig", "PortBindings", {"80/tcp": [{}]}, "PortBindings is not empty"),
        ("HostConfig", "Devices", [{"PathOnHost": "/dev/kmsg"}], "Devices is not empty"),
        ("HostConfig", "ExtraHosts", ["a:1.1.1.1"], "ExtraHosts is not empty"),
        ("HostConfig", "Dns", ["8.8.8.8"], "Dns is not empty"),
        ("HostConfig", "VolumesFrom", ["x"], "VolumesFrom is not empty"),
        (None, "Mounts", [{"Source": "/Users"}], "the container has mounts"),
        ("Config", "User", "root", "Config.User is 'root'"),
        ("Config", "User", None, "Config.User is None"),
        ("Config", "Env", ["AWS_SECRET_ACCESS_KEY=x"], "['AWS_SECRET_ACCESS_KEY']"),
        (
            None,
            "NetworkSettings",
            {"Networks": {"obelize-trial-net": {}, "bridge": {}}},
            "not only",
        ),
        (None, "NetworkSettings", {}, "the container is on []"),
    ],
    ids=lambda value: str(value)[:24],
)
def test_each_flag_that_did_not_reach_the_daemon_shows_in_its_inspect(
    where: str | None, key: str, value: Any, fragment: str
) -> None:
    container, network = good_inspect()
    (container[where] if where else container)[key] = value
    found = box.judge_inspect(container, network, EXPECT)
    assert any(fragment in one for one in found), found


def test_a_network_that_is_not_internal_or_that_cannot_be_read_fails() -> None:
    container, _ = good_inspect()
    assert (
        "is not an internal network" in box.judge_inspect(container, {"Internal": False}, EXPECT)[0]
    )
    assert box.judge_inspect(container, {}, EXPECT)
    assert box.judge_inspect({}, {}, EXPECT)


def test_the_expected_names_are_the_images_the_allowlists_and_the_two_docker_adds() -> None:
    assert EXPECT.env == {
        "PATH",
        "LANG",
        "HOME",
        "UV_PYTHON_DOWNLOADS",
        "HOSTNAME",
        *box.ENV_ALLOWED,
    }
    assert not {"AWS_SECRET_ACCESS_KEY", "USER", "SSH_AUTH_SOCK"} & EXPECT.env


# A record.

ENTRY = {"full_name": "o/r", "sha": "a" * 40, "band": "size:<1000"}
FRAME = {"distribution": "pydantic", "from": "1.10.26"}


def make(done: box.Outcome, work: str = "/scratch/w") -> dict[str, Any]:
    return box.repository_record(ENTRY, FRAME, "3.11", done, 12.34, work)


def test_a_passing_trial_is_a_record_with_what_it_compared_and_wrote() -> None:
    record = make(outcome(PASS_OUTPUT, 0, trial_json()))
    assert record == {
        "full_name": "o/r",
        "sha": "a" * 40,
        "band": "size:<1000",
        "distribution": "pydantic",
        "from": "1.10.26",
        "python": "3.11",
        "status": "pass",
        "reason": None,
        "compared": 2,
        "broken": [],
        "broken_count": 0,
        "flaky": 0,
        "written": 2,
        "held": 0,
        "places": 0,
        "partial": False,
        "exit_code": 0,
        "oom": False,
        "seconds": 12.3,
        "tail": None,
    }


def test_a_pass_that_left_files_is_partial_and_names_the_count_the_write_gave() -> None:
    text = (
        f"{OK_LINE}\nMode apply: 3 file(s) written.\n"
        "Part of the move: 3 file(s) written, 2 left as they were because a place in each\n"
    )
    record = make(outcome(text, 4, trial_json(held=["a.py", "b.py"], written=["x", "y", "z"])))
    assert (record["status"], record["written"], record["held"], record["partial"]) == (
        "pass",
        3,
        2,
        True,
    )
    assert record["exit_code"] == 4


def test_a_pass_that_ends_with_places_left_is_partial_though_no_file_was_held() -> None:
    record = make(outcome(PLACES_OUTPUT, 4, trial_json()))
    assert (record["status"], record["held"], record["places"], record["partial"]) == (
        "pass",
        0,
        4,
        True,
    )
    assert make(outcome(PLACES_OUTPUT, 0, trial_json()))["partial"] is False


def test_a_failing_trial_keeps_the_count_and_a_short_list_of_the_tests_that_broke() -> None:
    names = [f"tests.test_a::test_{number}" for number in range(30)]
    record = make(
        outcome(
            FAIL_LINE,
            3,
            trial_json(
                status="fail", reason="tests_broke", compared=40, broken=names, flaky=["t::f"]
            ),
        )
    )
    assert (record["status"], record["reason"], record["compared"]) == ("fail", "tests_broke", 40)
    assert record["broken"] == names[: box.BROKEN_NAMES]
    assert record["broken_count"] == 30
    assert (record["flaky"], record["partial"], record["tail"]) == (1, None, None)


def test_a_run_with_no_verdict_keeps_the_end_of_its_output_with_no_path_of_this_machine() -> None:
    lines = [
        f"line {number} in /scratch/w/repos/o__r and /work/repo/x and /home/trial/.cache"
        for number in range(60)
    ]
    record = make(outcome("\n".join(lines), 6))
    assert (record["status"], record["reason"], record["compared"]) == ("error", "no_verdict", 0)
    tail = record["tail"]
    assert tail.count("\n") == box.TAIL_LINES - 1
    assert "line 59" in tail
    assert "line 29" not in tail
    assert "/scratch/w" not in tail
    assert "<work>/repos/o__r and <repo>/x and <home>/.cache" in tail
    assert len(make(outcome("x" * 9000, 6))["tail"]) == box.TAIL_CHARS


def test_a_timeout_records_what_the_trial_line_said_before_it() -> None:
    record = make(outcome(f"{OK_LINE[:30]}", None, timed_out=True, oom=True))
    assert (record["status"], record["reason"], record["exit_code"], record["oom"]) == (
        "timeout",
        "wall_clock",
        None,
        True,
    )
    assert record["tail"]


def test_without_a_trial_json_the_held_files_are_the_ones_the_write_said() -> None:
    held = "Part of the move: 1 file(s) written, 2 left as they were because"
    assert make(outcome(held, 1))["held"] == 2
    assert make(outcome("", 1))["held"] == 0
    assert make(outcome(OK_LINE, 6))["compared"] == 2


def test_the_trial_json_wins_over_the_line_for_what_was_compared() -> None:
    assert make(outcome(OK_LINE, 0, trial_json(compared=5)))["compared"] == 5


def test_a_test_name_that_holds_a_path_of_this_machine_is_scrubbed() -> None:
    record = make(
        outcome(
            FAIL_LINE,
            3,
            trial_json(status="fail", reason="tests_broke", broken=["/scratch/w/x::t"]),
        ),
    )
    assert record["broken"] == ["<work>/x::t"]


def test_the_repositories_tried_are_those_whose_dry_run_writes_a_file_whichever_rule_wrote_it() -> (
    None
):
    dry = {
        "upgrade": [
            {"full_name": "a/whole", "files": 3},
            {"full_name": "b/none", "files": 0},
            {"full_name": "c/error", "error": "RuntimeError: x", "files": 4},
            {"full_name": "d/old", "files": 1},
            {"full_name": "e/unplanned"},
        ]
    }
    assert box.select(dry) == ["a/whole", "d/old"]
    assert box.select({"upgrade": []}) == []


def good_record() -> dict[str, Any]:
    return records.record(
        [
            make(outcome(PASS_OUTPUT, 0, trial_json())),
            make(outcome(FAIL_LINE, 3, trial_json(status="fail", reason="tests_broke"))),
            make(outcome("", 6)),
        ]
    )


def test_a_well_formed_record_has_nothing_wrong() -> None:
    assert box.validate_record(good_record()) == []


def mutated(change: Any) -> dict[str, Any]:
    record = copy.deepcopy(good_record())
    change(record)
    return record


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        (lambda r: r.pop("image"), "missing image"),
        (lambda r: r.pop("selftest"), "missing selftest"),
        (lambda r: r.pop("dry_run"), "missing dry_run"),
        (lambda r: r["selftest"].pop("attempts"), "the self-test has no attempts"),
        (lambda r: r["selftest"].pop("at"), "the self-test has no attempts or no date"),
        (lambda r: r.__setitem__("trial", []), "no repository was tried"),
        (lambda r: r.__setitem__("selftest", {"passed": False}), "the self-test did not pass"),
        (lambda r: r["trial"][0].__setitem__("status", "great"), "status 'great'"),
        (
            lambda r: r["trial"][0].__setitem__("reason", "tests_broke"),
            "reason 'tests_broke' for pass",
        ),
        (lambda r: r["trial"][1].__setitem__("reason", None), "reason None for fail"),
        (lambda r: r["trial"][0].__setitem__("compared", "2"), "compared is not a count"),
        (lambda r: r["trial"][0].__setitem__("held", True), "held is not a count"),
        (lambda r: r["trial"][0].__setitem__("broken", ["a"] * 21), "broken is not a short list"),
        (lambda r: r["trial"][0].__setitem__("broken", "a"), "broken is not a short list"),
        (lambda r: r["trial"][0].__setitem__("partial", None), "partial is for a pass"),
        (lambda r: r["trial"][1].__setitem__("partial", False), "partial is for a pass"),
        (
            lambda r: r["trial"][2].__setitem__("tail", "/Users/me/x failed"),
            "a path of the machine: /Users/",
        ),
        (lambda r: r["trial"][2].__setitem__("tail", "/private/tmp/x"), "/private/"),
        (lambda r: r["trial"][2].__setitem__("tail", "C:\\\\work"), "C:"),
    ],
    ids=[
        "image",
        "selftest",
        "dry-run",
        "no-attempts",
        "no-date",
        "no-trial",
        "selftest-failed",
        "status",
        "pass-reason",
        "fail-reason",
        "count",
        "bool-count",
        "long-list",
        "string-list",
        "pass-partial",
        "fail-partial",
        "users",
        "private",
        "windows",
    ],
)
def test_each_way_a_record_can_be_wrong_is_named(change: Any, fragment: str) -> None:
    assert any(fragment in one for one in box.validate_record(mutated(change))), (
        box.validate_record(mutated(change))
    )


def test_a_wheels_version_is_in_its_name() -> None:
    assert box.wheel_version("obelize-0.9.0-py3-none-any.whl") == "0.9.0"
    assert box.wheel_version("obelize-1.0.0rc1-py3-none-any.whl") == "1.0.0rc1"
    for name in ("obelize.whl", "obelize-x.y-py3-none-any.whl"):
        with pytest.raises(ValueError, match="not a wheel's name"):
            box.wheel_version(name)


# The files of the box agree with the constants here.


def test_the_proxy_carries_the_index_hosts_the_record_says_it_does() -> None:
    assert {f"{host}:{port}" for host, port in proxy.INDEX} == set(box.INDEX_HOSTS)
    assert proxy.PORT == box.PROXY_PORT
    assert probe.PROXY == (box.PROXY, box.PROXY_PORT)
    assert set(probe.ALLOWED) == {host.partition(":")[0] for host in box.INDEX_HOSTS}


def test_the_image_is_one_base_held_to_a_digest_with_the_user_the_box_runs_as() -> None:
    text = (ROOT / "bench" / "trial" / "Dockerfile").read_text(encoding="utf-8")
    assert re.search(r"^FROM python:3\.12-slim@sha256:[0-9a-f]{64}$", text, re.MULTILINE)
    assert f"useradd -m -u {box.USER.partition(':')[0]} trial" in text
    assert "USER trial" in text
    assert "COPY proxy.py probe.py /opt/box/" in text
    assert f"HOME={box.HOME}" in text
    assert "UV_PYTHON_DOWNLOADS=never" in text
    assert "--privileged" not in text
    assert "docker.sock" not in text
    versions = set(re.findall(r"uv python install ([0-9. ]+)", text))
    assert {tuple(one.split()) for one in versions} == {
        ("3.9", "3.10", "3.11", "3.12", "3.13", "3.14")
    }
    assert set(box.CANDIDATES) <= set(next(iter(versions)).split())

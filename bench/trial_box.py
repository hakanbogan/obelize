"""The parts of the box that measures a trial that need no Docker: what a container may be given,
which Python a repository gets, how a run's outputs are read and classified, how the self-test's
facts are judged, and the shape of a record.

`bench/trial_collect.py` runs the box; every property it relies on is stated here and tested here.
A container is made only through `trial_args` and `proxy_args`, whose parameters cannot express a
privilege, a mount, a published port or a host variable, and whose result is checked again against
an allowlist of flags (`check`), so a change that adds one fails a test instead of reaching a
repository's tests.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Mapping, Sequence
from typing import Any, Final, NamedTuple

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

PREFIX: Final = "obelize-trial-"
IMAGE: Final = "obelize-trial-box"
NETWORK: Final = PREFIX + "net"
EGRESS: Final = PREFIX + "out"
PROXY: Final = PREFIX + "proxy"
PROXY_PORT: Final = 3128
PROXY_URL: Final = f"http://{PROXY}:{PROXY_PORT}"
LABEL: Final = "obelize-trial=1"
USER: Final = "10001:10001"
INDEX_HOSTS: Final = ("pypi.org:443", "files.pythonhosted.org:443")
LOOPBACK: Final = "localhost,127.0.0.1,::1"
REPOSITORY: Final = "/work/repo"
HOME: Final = "/home/trial"

# The only variables a container is given, and the only values each may have.
ENV_ALLOWED: Final[Mapping[str, str]] = {
    "HTTP_PROXY": re.escape(PROXY_URL),
    "HTTPS_PROXY": re.escape(PROXY_URL),
    "http_proxy": re.escape(PROXY_URL),
    "https_proxy": re.escape(PROXY_URL),
    "NO_PROXY": re.escape(LOOPBACK),
    "no_proxy": re.escape(LOOPBACK),
    "UV_HTTP_TIMEOUT": r"[1-9][0-9]{0,3}",
    "CI": r"1|true",
}

STATUSES: Final = ("pass", "fail", "inconclusive", "error", "timeout")
INCONCLUSIVE: Final = ("no_tests", "no_junit", "timeout", "nothing_to_compare", "unresolved")
ERRORS: Final = (
    "environment",
    "copy",
    "not_started",
    "write_failed",
    "verdict_mismatch",
    "exit_mismatch",
    "oom",
    "disk",
    "container",
    "fetch",
    "no_verdict",
)
REASONS: Final[Mapping[str, tuple[str | None, ...]]] = {
    "pass": (None,),
    "fail": ("tests_broke",),
    "inconclusive": INCONCLUSIVE,
    "error": ERRORS,
    "timeout": ("wall_clock",),
}
# The exit codes `upgrade --apply --yes` ends with after each verdict (docs/CLI.md): `4` is a pass
# that leaves places for a person.
EXITS: Final = {"pass": (0, 4), "fail": (3,), "inconclusive": (6,)}


class Limits(NamedTuple):
    """What one container may use; the wall clock and the disk are held by the collector."""

    memory_gb: int = 2
    cpus: int = 2
    pids: int = 1024
    wall_s: int = 5400
    disk_gb: int = 8
    http_s: int = 120

    @property
    def memory(self) -> str:
        return f"{self.memory_gb}g"


class UnsafeError(ValueError):
    """A `docker` argument list that would give a container more than the box allows."""


# The Docker command lines.

_NAME = re.compile(rf"{re.escape(PREFIX)}[a-z0-9][a-z0-9_.-]{{0,80}}")
_IMAGE = re.compile(rf"{re.escape(IMAGE)}:[A-Za-z0-9_.-]{{1,40}}")
_COUNT = r"[1-9][0-9]{0,5}"
_VALUES: Final[Mapping[str, str]] = {
    "--name": _NAME.pattern,
    "--label": re.escape(LABEL),
    "--pull": "never",
    "--network": re.escape(NETWORK),
    "--cap-drop": "ALL",
    "--security-opt": "no-new-privileges",
    "--memory": rf"{_COUNT}[gm]",
    "--memory-swap": rf"{_COUNT}[gm]",
    "--cpus": _COUNT,
    "--pids-limit": _COUNT,
    "--user": re.escape(USER),
    "--log-driver": "none|local",
    "--log-opt": r"max-size=[0-9]{1,3}m|max-file=[0-9]",
    "--ulimit": "core=0",
}
_BARE: Final = frozenset({"--init"})
_ENVIRONMENT: Final = frozenset({"-e", "--env"})


def check(argv: Sequence[str]) -> list[str]:
    """Why `argv` (a `docker create`, without the program) is not one the box makes; none if it is.

    Every flag must be on the list above with a value of the shape given, an environment value
    must be `NAME=value` for a name in `ENV_ALLOWED`, and the image must be the box's own. A flag
    in any other spelling, such as `--network=host`, is read as its name and refused the same way.
    """
    problems: list[str] = []
    words = list(argv)
    if words[:1] != ["create"]:
        return ["not a `docker create`"]
    index = 1
    while index < len(words) and words[index].startswith("-"):
        flag, equals, inline = words[index].partition("=")
        index += 1
        if flag in _BARE and not equals:
            continue
        if flag not in _VALUES and flag not in _ENVIRONMENT:
            problems.append(f"{flag} is not allowed")
            continue
        if not equals:
            if index >= len(words):
                problems.append(f"{flag} has no value")
                continue
            inline, index = words[index], index + 1
        if flag in _ENVIRONMENT:
            name, _, value = inline.partition("=")
            pattern = ENV_ALLOWED.get(name)
            if pattern is None or "=" not in inline or not re.fullmatch(pattern, value):
                problems.append(f"{flag} {name} is not an allowed variable and value")
        elif not re.fullmatch(_VALUES[flag], inline):
            problems.append(f"{flag} {inline} is not an allowed value")
    if index >= len(words) or not _IMAGE.fullmatch(words[index]):
        problems.append("the image is not the box's own")
    if any("docker.sock" in word for word in words):
        problems.append("the Docker socket is named")
    return problems


def _create(
    name: str,
    image: str,
    command: Sequence[str],
    *,
    memory: str,
    cpus: int | None,
    pids: int,
    logs: Sequence[str],
    env: Mapping[str, str],
) -> list[str]:
    cpu = ["--cpus", str(cpus)] if cpus else []
    argv = [
        "create",
        "--name",
        name,
        "--label",
        LABEL,
        "--pull",
        "never",
        "--network",
        NETWORK,
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--memory",
        memory,
        "--memory-swap",
        memory,
        *cpu,
        "--pids-limit",
        str(pids),
        "--user",
        USER,
        "--init",
        *logs,
        *(word for key, value in sorted(env.items()) for word in ("-e", f"{key}={value}")),
        image,
        *command,
    ]
    if problems := check(argv):
        raise UnsafeError("; ".join(problems))
    return argv


def trial_args(
    name: str, image: str, command: Sequence[str], limits: Limits, env: Mapping[str, str]
) -> list[str]:
    """`docker create` for a container that runs a repository's trial, or the probe: on the
    internal network only, no capability, no new privilege, a user with no name on the host, its
    memory, processes and CPUs capped, its output not kept by the daemon, and only the variables
    on the allowlist, each given its value here, never taken from the host."""
    return _create(
        name,
        image,
        command,
        memory=limits.memory,
        cpus=limits.cpus,
        pids=limits.pids,
        logs=["--log-driver", "none", "--ulimit", "core=0"],
        env=env,
    )


def proxy_args(image: str) -> list[str]:
    """`docker create` for the proxy: the same container, with a small share of memory, and a log
    the daemon rotates. It joins the network with a route out afterwards (`connect_args`)."""
    return _create(
        PROXY,
        image,
        ["python", "/opt/box/proxy.py"],
        memory="256m",
        cpus=None,
        pids=256,
        logs=["--log-driver", "local", "--log-opt", "max-size=5m", "--log-opt", "max-file=2"],
        env={},
    )


def network_args(name: str) -> list[str]:
    """`docker network create`: the internal one has no route out, the other is the proxy's."""
    if name == NETWORK:
        return ["network", "create", "--internal", name]
    if name == EGRESS:
        return ["network", "create", name]
    raise UnsafeError(f"{name} is not a network of the box")


def connect_args() -> list[str]:
    return ["network", "connect", EGRESS, PROXY]


def trial_env(limits: Limits) -> dict[str, str]:
    """What a trial is given: the proxy for every tool that reads one, a name list that keeps a
    test's own local server off it, and uv's timeout."""
    proxied = dict.fromkeys(("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"), PROXY_URL)
    return {
        **proxied,
        "NO_PROXY": LOOPBACK,
        "no_proxy": LOOPBACK,
        "UV_HTTP_TIMEOUT": str(limits.http_s),
    }


_SAFE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_RELEASE = re.compile(r"[0-9][A-Za-z0-9.+!_-]*")


def run_command(
    distribution: str,
    old: str | None,
    python: str,
    test_timeout_s: int | None = None,
    new: str | None = None,
) -> list[str]:
    """The trial as the container runs it, to the release the dry run was made for: without `new`
    it would move to the newest and be another pack. The shell only copies `trial.json` to a fixed
    place afterwards and keeps obelize's exit code; the repository's files are never given to it."""
    releases = (old, new)
    if not _SAFE.fullmatch(distribution) or not all(
        release is None or _RELEASE.fullmatch(release) for release in releases
    ):
        raise UnsafeError(f"{distribution} {old} {new} is not a distribution and two releases")
    if not re.fullmatch(r"3\.[0-9]{1,2}", python):
        raise UnsafeError(f"{python} is not a Python of the box")
    wrapper = (
        '"$@"; code=$?; mkdir -p /work/out; '
        "cp /work/repo/.obelize/trials/*/trial.json /work/out/ 2>/dev/null; exit $code"
    )
    return [
        "sh",
        "-c",
        wrapper,
        "sh",
        "obelize",
        "upgrade",
        distribution,
        *(["--from", old] if old else []),
        *(["--to", new] if new else []),
        "--apply",
        "--yes",
        "--repo",
        REPOSITORY,
        "--python",
        python,
        *(["--timeout", str(test_timeout_s)] if test_timeout_s else []),
    ]


# The Python a repository gets.

# Newest first: a `requires-python` that admits several takes the newest the box holds.
CANDIDATES: Final = ("3.13", "3.12", "3.11", "3.10", "3.9")
FALLBACK: Final = "3.12"


def choose_python(
    pyproject: str | None, python_version: str | None, installed: Mapping[str, str]
) -> str:
    """The newest of `CANDIDATES` that the repository's `requires-python` admits, else the Python
    its `.python-version` names if the box holds it, else 3.12. `installed` maps a minor release
    to the full version of the interpreter the box holds, so `>=3.10.4` is judged on a real one."""
    admits = _requires(pyproject)
    if admits is not None:
        for minor in CANDIDATES:
            if minor in installed and admits.contains(Version(installed[minor]), prereleases=True):
                return minor
    named = _pinned(python_version) or FALLBACK
    return named if named in installed else FALLBACK


def _requires(pyproject: str | None) -> SpecifierSet | None:
    try:
        declared = tomllib.loads(pyproject or "").get("project", {}).get("requires-python")
        return SpecifierSet(declared) if isinstance(declared, str) else None
    except (tomllib.TOMLDecodeError, InvalidSpecifier):
        return None


def _pinned(text: str | None) -> str | None:
    for line in (text or "").splitlines():
        words = line.split("#")[0].split()
        if words:
            found = re.match(r"(?:cpython-)?(3\.[0-9]+)(?![0-9])", words[0])
            return found.group(1) if found else None
    return None


# A run's outputs.


class Capture:
    """The first and the last bytes of a stream, so an output that never ends is bounded and the
    line near its end, which `upgrade` prints last, is kept."""

    def __init__(self, head: int = 1 << 17, tail: int = 1 << 18) -> None:
        self.head, self.tail = bytearray(), bytearray()
        self.limits, self.cut = (head, tail), 0

    def feed(self, data: bytes) -> None:
        room = self.limits[0] - len(self.head)
        self.head += data[:room]
        self.tail += data[room:]
        if len(self.tail) > self.limits[1]:
            self.cut += len(self.tail) - self.limits[1]
            del self.tail[: -self.limits[1]]

    def text(self) -> str:
        middle = f"\n[{self.cut} byte(s) cut]\n" if self.cut else ""
        return (bytes(self.head) + middle.encode() + bytes(self.tail)).decode("utf-8", "replace")


class TrialLine(NamedTuple):
    status: str
    reason: str | None
    compared: int
    broken: int
    flaky: int


_TRIAL = re.compile(
    r"^Trial of \S+ \S+ to .+?: (?P<status>pass|fail|inconclusive)(?: \((?P<reason>[a-z_]+)\))?"
    r"(?:; (?P<compared>\d+) test\(s\) passed before, (?P<broken>\d+) broke, "
    r"(?P<flaky>\d+) failed once and passed again)?\. Evidence: ",
    re.MULTILINE,
)
_WRITTEN = re.compile(r"^Mode apply: (\d+) file\(s\) written\.$", re.MULTILINE)
_PLACES = re.compile(r"^(\d+) finding\(s\) left for you", re.MULTILINE)
_HELD = re.compile(
    r"^(?:Part of the move: \d+ file\(s\) written, |The move is partial: )(\d+) "
    r"(?:file\(s\) )?(?:left|were left) as they were",
    re.MULTILINE,
)


def parse_trial_line(text: str) -> TrialLine | None:
    """The last `Trial of X to Y: <status> ...` line of the output."""
    found = list(_TRIAL.finditer(text))
    if not found:
        return None
    one = found[-1]
    return TrialLine(
        one["status"],
        one["reason"],
        int(one["compared"] or 0),
        int(one["broken"] or 0),
        int(one["flaky"] or 0),
    )


def parse_files(text: str) -> tuple[int | None, int | None, int]:
    """The files the write said it wrote and, where it said so, the files it left; and the places
    it left for a person, which a whole file or a place in a file written both are."""
    wrote, left, places = _WRITTEN.search(text), _HELD.search(text), _PLACES.search(text)
    return (
        int(wrote.group(1)) if wrote else None,
        int(left.group(1)) if left else None,
        int(places.group(1)) if places else 0,
    )


def _strings(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(one, str) for one in value)


def parse_trial_json(text: str | None) -> dict[str, Any] | None:
    """`trial.json` as the engine writes it, or none for a file that is not one."""
    try:
        document = json.loads(text or "")
    except ValueError:
        return None
    if not isinstance(document, dict) or document.get("status") not in EXITS:
        return None
    reason = document.get("reason")
    compared = document.get("compared")
    lists = ("broken", "fixed", "flaky", "written")
    if (
        not (reason is None or isinstance(reason, str))
        or not isinstance(compared, int)
        or isinstance(compared, bool)
        or not all(_strings(document.get(name)) for name in lists)
        or not _strings(document.get("held", []))
    ):
        return None
    return {**document, "held": document.get("held", [])}


class Outcome(NamedTuple):
    """Everything a container left that says how its trial ended."""

    exit_code: int | None
    timed_out: bool
    oom: bool
    disk: bool
    output: str
    trial: dict[str, Any] | None


def classify(outcome: Outcome) -> tuple[str, str | None]:
    """The status and reason of a run: by `trial.json` and the trial line, and the exit code as a
    check on them. A run that never reached a verdict is an `error`, with the reason its output
    gives."""
    if outcome.timed_out:
        return "timeout", "wall_clock"
    if outcome.disk:
        return "error", "disk"
    trial, line = outcome.trial, parse_trial_line(outcome.output)
    if trial is not None:
        if line is not None and (line.status, line.reason) != (trial["status"], trial["reason"]):
            return "error", "verdict_mismatch"
        if outcome.exit_code not in EXITS[trial["status"]]:
            return "error", "write_failed" if trial["status"] == "pass" else "exit_mismatch"
        return trial["status"], trial["reason"]
    if outcome.oom:
        return "error", "oom"
    if re.search(r"uv \w+ failed:|no way to install the dependencies", outcome.output):
        return "error", "environment"
    if "is larger than a trial copies" in outcome.output:
        return "error", "copy"
    if outcome.exit_code in (1, 2, 5):
        return "error", "not_started"
    return "error", "no_verdict"


# What the proxy counted.

_HOST = re.compile(r"[a-z0-9._:\[\]-]{1,100}|\(other\)")


def parse_totals(logs: str) -> dict[str, dict[str, int]] | None:
    """The proxy's last totals line, with a name it could not have printed set aside."""
    for line in reversed(logs.splitlines()):
        try:
            totals = json.loads(line).get("totals")
        except (ValueError, AttributeError):
            continue
        if isinstance(totals, dict) and all(
            isinstance(counted, dict) for counted in totals.values()
        ):
            return {
                verdict: {
                    (host if _HOST.fullmatch(host) else "(invalid)"): int(count)
                    for host, count in counted.items()
                    if isinstance(count, int)
                }
                for verdict, counted in totals.items()
                if verdict in ("allow", "deny", "error")
            }
    return None


# What the self-test found.

# The mount points a container of the box has: its own file system, the kernel's, the three files
# Docker puts in for the name service and the init program `--init` runs it under.
_MOUNTS = re.compile(
    r"/|/proc(/.*)?|/dev(/.*)?|/sys(/.*)?|/etc/(hosts|hostname|resolv\.conf)|/usr/sbin/docker-init"
)
_ZERO = re.compile(r"0+")


class Expect(NamedTuple):
    """What the self-test holds a container to: the limits it was made with and the variable
    names it may have."""

    limits: Limits
    env: frozenset[str]


def expect(limits: Limits, image_env: Sequence[str]) -> Expect:
    """The names a container may have: its image's, the allowlist's and the two Docker adds."""
    return Expect(limits, frozenset(image_env) | {"HOSTNAME", "HOME", *ENV_ALLOWED})


def judge_probe(report: Mapping[str, Any], expect: Expect) -> list[str]:
    """Every isolation property the probe's document does not show; none if all hold. A fact the
    document lacks is a failure, not a pass."""
    found: list[str] = []
    status = report.get("status") or {}
    cgroup = report.get("cgroup") or {}
    limits = expect.limits
    found += [
        f"{name} is {report.get(name)}, not 10001"
        for name in ("uid", "gid")
        if set(report.get(name) or [None]) != {10001}
    ]
    groups = report.get("groups")
    if not isinstance(groups, list) or set(groups) - {10001}:
        found.append(f"supplementary groups {groups}")
    caps = [status.get(name) for name in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")]
    if not all(isinstance(cap, str) and _ZERO.fullmatch(cap) for cap in caps):
        found.append(f"capabilities are not empty: {caps}")
    if status.get("NoNewPrivs") != "1":
        found.append("no-new-privileges is not set")
    if "probe.py" not in str(report.get("pid1")):
        found.append("the process namespace is not the container's own")
    odd = [one for one in report.get("mounts") or [] if not _MOUNTS.fullmatch(str(one))]
    if odd or not report.get("mounts"):
        found.append(f"mounts beyond the container's own: {odd or 'none read'}")
    if report.get("host_paths") != []:
        found.append(f"host paths exist: {report.get('host_paths')}")
    if stray := sorted(set(report.get("env") or ()) - expect.env):
        found.append(f"variables beyond the allowlist: {stray}")
    wanted = {
        "memory.max": str(limits.memory_gb << 30),
        "memory.swap.max": "0",
        "pids.max": str(limits.pids),
    }
    found += [
        f"{name} is {cgroup.get(name)}, not {value}"
        for name, value in wanted.items()
        if cgroup.get(name) != value
    ]
    if not str(cgroup.get("cpu.max")).startswith(f"{limits.cpus * 100000} 100000"):
        found.append(f"cpu.max is {cgroup.get('cpu.max')}")
    found += [
        f"reached {one.get('label')}: {one.get('detail')}"
        for one in report.get("direct") or []
        if one.get("reached")
    ]
    if not report.get("direct"):
        found.append("no direct attempt was made")
    held = report.get("pythons") or {}
    found += [f"the box holds no Python {minor}" for minor in CANDIDATES if minor not in held]
    found += _proxied(report)
    return found


def _proxied(report: Mapping[str, Any]) -> list[str]:
    found = []
    denied = report.get("denied") or []
    if not denied:
        found.append("no request to the proxy was denied or tried")
    found += [
        f"the proxy answered {one.get('status')} to {one.get('target')}, not 403"
        for one in denied
        if one.get("status") != 403
    ]
    allowed = report.get("allowed") or []
    if sorted(str(one.get("target")) for one in allowed) != sorted(INDEX_HOSTS):
        found.append(f"the index hosts tried were {[one.get('target') for one in allowed]}")
    found += [
        f"the proxy did not carry {one.get('target')}: {one.get('status')}/{one.get('http')} "
        f"{one.get('detail')}"
        for one in allowed
        if one.get("status") != 200 or not isinstance(one.get("http"), int) or one["http"] >= 500
    ]
    return found


def judge_inspect(
    container: Mapping[str, Any], network: Mapping[str, Any], expect: Expect
) -> list[str]:
    """The same properties as the daemon holds them, read from `docker inspect` of the container
    and of the network, so a flag that did not reach the daemon shows without the probe."""
    host = container.get("HostConfig") or {}
    config = container.get("Config") or {}
    limits = expect.limits
    wanted: dict[str, Any] = {
        "Privileged": False,
        "CapAdd": None,
        "CapDrop": ["ALL"],
        "SecurityOpt": ["no-new-privileges"],
        "NetworkMode": NETWORK,
        "Memory": limits.memory_gb << 30,
        "MemorySwap": limits.memory_gb << 30,
        "NanoCpus": limits.cpus * 10**9,
        "PidsLimit": limits.pids,
        "PidMode": "",
        "UsernsMode": "",
    }
    found = [
        f"HostConfig.{key} is {host.get(key)!r}, not {value!r}"
        for key, value in wanted.items()
        if host.get(key) != value
    ]
    for key in ("Binds", "PortBindings", "Devices", "ExtraHosts", "Dns", "VolumesFrom"):
        if host.get(key):
            found.append(f"HostConfig.{key} is not empty: {host.get(key)!r}")
    if container.get("Mounts"):
        found.append(f"the container has mounts: {container.get('Mounts')!r}")
    if config.get("User") != USER:
        found.append(f"Config.User is {config.get('User')!r}")
    names = {one.partition("=")[0] for one in config.get("Env") or []}
    if stray := sorted(names - expect.env):
        found.append(f"Config.Env names beyond the allowlist: {stray}")
    joined = sorted((container.get("NetworkSettings") or {}).get("Networks") or {})
    if joined != [NETWORK]:
        found.append(f"the container is on {joined}, not only {NETWORK}")
    if network.get("Internal") is not True:
        found.append(f"{NETWORK} is not an internal network")
    return found


# A record.

TAIL_LINES: Final = 30
TAIL_CHARS: Final = 4000
BROKEN_NAMES: Final = 20


def scrub(text: str, work: str) -> str:
    """`text` with this machine's work directory and the container's own paths written as names, so
    no record holds a path of the machine that made it."""
    for path, name in ((work.rstrip("/\\"), "<work>"), (REPOSITORY, "<repo>"), (HOME, "<home>")):
        text = text.replace(path, name)
    return text


def tail(output: str, work: str) -> str:
    """The end of the output, for a run that reached no verdict or none that compares."""
    return scrub("\n".join(output.splitlines()[-TAIL_LINES:])[-TAIL_CHARS:], work)


def repository_record(
    entry: Mapping[str, Any],
    frame: Mapping[str, Any],
    python: str,
    outcome: Outcome,
    seconds: float,
    work: str,
) -> dict[str, Any]:
    """One repository's record: the verdict, what it compared and wrote, and how it ended."""
    status, reason = classify(outcome)
    trial = outcome.trial or {}
    line = parse_trial_line(outcome.output)
    wrote, left, places = parse_files(outcome.output)
    broken = [scrub(name, work) for name in trial.get("broken", [])]
    held = len(trial["held"]) if trial else (left or 0)
    return {
        "full_name": entry["full_name"],
        "sha": entry["sha"],
        "band": entry["band"],
        "distribution": frame["distribution"],
        "from": frame["from"],
        "python": python,
        "status": status,
        "reason": reason,
        "compared": trial.get("compared", line.compared if line else 0),
        "broken": broken[:BROKEN_NAMES],
        "broken_count": len(broken),
        "flaky": len(trial.get("flaky", [])),
        "written": wrote if wrote is not None else len(trial.get("written", [])),
        "held": held,
        "places": places,
        "partial": (held > 0 or outcome.exit_code == 4) if status == "pass" else None,
        "exit_code": outcome.exit_code,
        "oom": outcome.oom,
        "seconds": round(seconds, 1),
        "tail": tail(outcome.output, work)
        if status in ("error", "timeout", "inconclusive")
        else None,
    }


def select(dry_run: Mapping[str, Any]) -> list[str]:
    """The repositories whose dry-run record says the plan writes at least one file, whichever
    rule that record was made with."""
    return [
        row["full_name"]
        for row in dry_run["upgrade"]
        if "error" not in row and row.get("files", 0) >= 1
    ]


_INTS: Final = ("compared", "broken_count", "flaky", "written", "held", "places")
_PATHS: Final = ("/Users/", "/private/", "/var/folders/", "C:\\")


def validate_record(document: Mapping[str, Any]) -> list[str]:
    """What is wrong with a record of the trial measurement; none if it is well formed."""
    problems = [
        f"missing {key}"
        for key in (
            "obelize_version",
            "obelize_commit",
            "wheel_sha256",
            "image",
            "docker",
            "uv",
            "machine",
            "pythons",
            "date",
            "limits",
            "allowlist",
            "frame",
            "distribution",
            "from",
            "to",
            "dry_run",
            "selftest",
            "proxy",
            "trial",
        )
        if key not in document
    ]
    if problems:
        return problems
    tested = document["selftest"]
    if tested.get("passed") is not True:
        problems.append("the self-test did not pass")
    if not isinstance(tested.get("attempts"), dict) or "at" not in tested:
        problems.append("the self-test has no attempts or no date")
    if not document["trial"]:
        problems.append("no repository was tried")
    for row in document["trial"]:
        name = row.get("full_name", "?")
        if row.get("status") not in STATUSES:
            problems.append(f"{name}: status {row.get('status')!r}")
        elif row.get("reason") not in REASONS[row["status"]]:
            problems.append(f"{name}: reason {row.get('reason')!r} for {row['status']}")
        problems += [
            f"{name}: {key} is not a count"
            for key in _INTS
            if not isinstance(row.get(key), int) or isinstance(row.get(key), bool)
        ]
        if not _strings(row.get("broken")) or len(row["broken"]) > BROKEN_NAMES:
            problems.append(f"{name}: broken is not a short list of names")
        if (row.get("status") == "pass") != isinstance(row.get("partial"), bool):
            problems.append(f"{name}: partial is for a pass, and only a pass")
    text = json.dumps(document)
    problems += [f"a path of the machine: {path}" for path in _PATHS if path in text]
    return problems


def wheel_version(name: str) -> str:
    """The version in a wheel's file name."""
    parts = name.split("-")
    try:
        return str(Version(parts[1]))
    except (IndexError, InvalidVersion) as error:
        raise ValueError(f"{name} is not a wheel's name") from error

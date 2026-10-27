"""Measure `obelize upgrade --apply --yes`, the trial, over the frames of the dry-run measurement,
in a box that holds back everything it can.

A trial installs the dependencies of a stranger's repository, which runs their build scripts, and
runs that repository's tests. Nothing here does that on the machine itself: each repository is
copied into a container of its own (`bench/trial/Dockerfile`) that is on an internal network with
no route out, whose only way to the world is a proxy (`bench/trial/proxy.py`) that carries the two
package index hosts and answers 403 to anything else. The container has no capability, no mount, no
published port, no variable of the machine and a cap on memory, processes, CPU, disk and time. What
may be given to it is decided in `bench/trial_box.py`, where it is tested; `selftest` shows, with a
container made exactly as a trial's, that every one of those holds, and `run` and `smoke` start
with it and stop if it does not.

Usage::

    python -m bench.trial_collect selftest [--image TAG]
    python -m bench.trial_collect run -m SLUG --work DIR [--only O/R ...] [--jobs N] [--wheel PATH]
                                      [--again] [--out DIR] [--wall S] [--disk-gb N]
                                      [--test-timeout S]
    python -m bench.trial_collect smoke DIR DISTRIBUTION [--from V] --work DIR [--wheel PATH]
                                      [--out FILE] [--wall S] [--disk-gb N] [--test-timeout S]
    python -m bench.trial_collect cleanup

`run` tries the repositories whose dry-run record (`bench/results/upgrade/<slug>.json`) says the
plan writes a file, and writes `bench/results/trial/<slug>.json`. `smoke` tries one synthetic
repository you made, for the box itself. Neither is to be pointed at a public repository without
the maintainer's say; both need Docker and the package index, and `run` needs `git` and the
network of GitHub as `bench/upgrade_collect.py` does. The wheel is built with `uv build` from a
clean `git archive` of HEAD, never from the working tree. The networks and the proxy have fixed
names, so one run at a time on a machine; `cleanup` removes what a run that was killed left.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

from . import gate1_collect, read_yaml, trial_box, upgrade_collect
from .trial_box import Limits, Outcome

ROOT = Path(__file__).resolve().parent.parent
BOX = ROOT / "bench" / "trial"
RESULTS = ROOT / "bench" / "results" / "trial"
DRY_RUNS = upgrade_collect.RESULTS
FRAMES = upgrade_collect.FRAMES

# How long the harness waits for each of the small things it asks Docker.
DOCKER_S = 120
BUILD_S = 3600
# A container's size is looked at this often, and its output read in pieces of this size.
WATCH_S = 20
READ = 65536
EVIDENCE_BYTES = 1 << 20
# What a smoke record keeps of the output, which is read by a person.
OUTPUT_CHARS = 12000


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def docker(
    *arguments: str, timeout: int = DOCKER_S, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """One `docker` command, with every argument given as a word: no shell reads any of them."""
    done = subprocess.run(
        ["docker", *arguments], capture_output=True, text=True, timeout=timeout, check=False
    )
    if check and done.returncode != 0:
        raise SystemExit(f"docker {' '.join(arguments[:2])} failed: {done.stderr.strip()[-400:]}")
    return done


def inspect(kind: str, name: str) -> dict[str, Any]:
    found = json.loads(docker(kind, "inspect", name).stdout)
    return found[0]  # type: ignore[no-any-return]


# The wheel and the image.


def build_wheel(work: Path) -> tuple[Path, str]:
    """A wheel of the tree at HEAD, made from `git archive` and not from the working tree, and
    the commit it is of."""
    source, out = work / "source", work / "wheel"
    shutil.rmtree(source, ignore_errors=True)
    shutil.rmtree(out, ignore_errors=True)
    archive = subprocess.run(
        ["git", "-C", str(ROOT), "archive", "--format=tar", "HEAD"],
        capture_output=True,
        check=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(source, filter="data")
    commit = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out), str(source)],
        capture_output=True,
        check=True,
        timeout=BUILD_S,
    )
    return next(out.glob("*.whl")), commit


def build_image(wheel: Path, work: Path) -> str:
    """The box's image with `wheel` in it, tagged by the wheel's hash; its tag."""
    tag = f"{trial_box.IMAGE}:{hashlib.sha256(wheel.read_bytes()).hexdigest()[:12]}"
    context = work / "context"
    shutil.rmtree(context, ignore_errors=True)
    (context / "wheel").mkdir(parents=True)
    shutil.copy(wheel, context / "wheel" / wheel.name)
    for name in ("Dockerfile", "proxy.py", "probe.py"):
        shutil.copy(BOX / name, context / name)
    docker("build", "--tag", tag, str(context), timeout=BUILD_S)
    return tag


def newest_image() -> str:
    found = docker(
        "image", "ls", trial_box.IMAGE, "--format", "{{.Repository}}:{{.Tag}}"
    ).stdout.split()
    if not found:
        raise SystemExit("no image of the box: `run` and `smoke` build one")
    return found[0]


# The box: two networks and a proxy.


class Box:
    """The networks and the proxy of a run, which it removes when it ends."""

    def __init__(self, image: str, limits: Limits) -> None:
        self.image, self.limits = image, limits
        found = inspect("image", image)
        self.facts = {
            "id": found["Id"],
            "env": [e.partition("=")[0] for e in found["Config"]["Env"]],
        }
        for name in (trial_box.NETWORK, trial_box.EGRESS):
            if docker("network", "inspect", name, check=False).returncode == 0:
                continue
            docker(*trial_box.network_args(name))
        if inspect("network", trial_box.NETWORK).get("Internal") is not True:
            raise SystemExit(f"{trial_box.NETWORK} exists and is not an internal network")

    def start_proxy(self) -> None:
        self.stop_proxy()
        docker(*trial_box.proxy_args(self.image))
        docker(*trial_box.connect_args())
        docker("start", trial_box.PROXY)
        for _ in range(60):
            if "proxy up" in docker("logs", trial_box.PROXY, check=False).stdout:
                return
            time.sleep(0.5)
        raise SystemExit("the proxy did not start")

    def totals(self) -> dict[str, dict[str, int]] | None:
        """What the proxy has allowed and denied since it started."""
        docker("kill", "--signal", "USR1", trial_box.PROXY, check=False)
        time.sleep(1)
        return trial_box.parse_totals(docker("logs", trial_box.PROXY, check=False).stdout)

    def stop_proxy(self) -> None:
        docker("rm", "--force", "--volumes", trial_box.PROXY, check=False)

    def close(self) -> None:
        self.stop_proxy()
        for name in (trial_box.NETWORK, trial_box.EGRESS):
            docker("network", "rm", name, check=False)


def cleanup() -> None:
    """Remove what this module made: containers that carry its label and its prefix, and its two
    networks. Nothing else on the machine is looked at."""
    found = docker(
        "ps", "--all", "--filter", f"label={trial_box.LABEL}", "--format", "{{.Names}}"
    ).stdout.split()
    ours = [name for name in found if name.startswith(trial_box.PREFIX)]
    for name in ours:
        docker("rm", "--force", "--volumes", name, check=False)
    for name in (trial_box.NETWORK, trial_box.EGRESS):
        docker("network", "rm", name, check=False)
    print(f"removed {len(ours)} container(s) and the networks of the box")


# A container.


def _owned(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = info.gid = 10001
    info.uname = info.gname = ""
    info.mode &= 0o777
    return info


def send(directory: Path, name: str) -> None:
    """`directory` as `/work/repo` in the created container `name`, owned by its user. A file is
    copied as it is, a link stays a link, and nothing of the machine is mounted."""
    copy = subprocess.Popen(
        ["docker", "cp", "-", f"{name}:/work"], stdin=subprocess.PIPE, stderr=subprocess.PIPE
    )
    assert copy.stdin is not None  # noqa: S101 - PIPE was asked for
    with tarfile.open(fileobj=copy.stdin, mode="w|") as tar:
        tar.add(directory, arcname="repo", filter=_owned)
    copy.stdin.close()
    if copy.wait(DOCKER_S) != 0:
        raise SystemExit(f"docker cp failed: {(copy.stderr or io.BytesIO()).read()[-300:]!r}")


def evidence(name: str) -> str | None:
    """`trial.json`, which the container's own command copied to a fixed place, read from the
    archive Docker makes of it and no further than a file of that size: nothing else of the
    container's files is read."""
    with subprocess.Popen(
        ["docker", "cp", f"{name}:/work/out/trial.json", "-"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ) as copy:
        assert copy.stdout is not None  # noqa: S101 - PIPE was asked for
        data = copy.stdout.read(EVIDENCE_BYTES + 2048)
        copy.kill()
    try:
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            member = tar.next()
            if member is None or not member.isreg() or member.size > EVIDENCE_BYTES:
                return None
            handle = tar.extractfile(member)
            return None if handle is None else handle.read().decode("utf-8", "replace")
    except tarfile.TarError:
        return None


def size_exceeds(name: str, limits: Limits) -> bool:
    found = docker("container", "inspect", "--size", "--format", "{{.SizeRw}}", name, check=False)
    text = found.stdout.strip()
    return text.isdigit() and int(text) > limits.disk_gb << 30


def drain(stream: IO[bytes], capture: trial_box.Capture) -> None:
    for piece in iter(lambda: stream.read(READ), b""):
        capture.feed(piece)


def run_container(
    name: str,
    image: str,
    command: Sequence[str],
    limits: Limits,
    *,
    repository: Path | None = None,
    inspected: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[Outcome, float]:
    """Create a container, copy the repository in, run it to its end or to its limits, and read
    what it left. The container is always removed. `inspected` sees its `docker inspect` before it
    starts, for a self-test that has to find what the daemon holds."""
    docker(*trial_box.trial_args(name, image, command, limits, trial_box.trial_env(limits)))
    try:
        if repository is not None:
            send(repository, name)
        if inspected is not None:
            inspected(inspect("container", name))
        capture, started = trial_box.Capture(), time.monotonic()
        process = subprocess.Popen(
            ["docker", "start", "--attach", name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        assert process.stdout is not None  # noqa: S101 - PIPE was asked for
        reader = threading.Thread(target=drain, args=(process.stdout, capture))
        reader.start()
        timed_out = disk = False
        while process.poll() is None:
            left = limits.wall_s - (time.monotonic() - started)
            try:
                process.wait(max(0.1, min(WATCH_S, left)))
            except subprocess.TimeoutExpired:
                timed_out = timed_out or left <= WATCH_S
                disk = disk or (not timed_out and size_exceeds(name, limits))
                if timed_out or disk:
                    docker("kill", name, check=False)
        reader.join()
        state = inspect("container", name)["State"]
        outcome = Outcome(
            state.get("ExitCode"),
            timed_out,
            bool(state.get("OOMKilled")),
            disk,
            capture.text(),
            trial_box.parse_trial_json(evidence(name)),
        )
        return outcome, time.monotonic() - started
    finally:
        docker("rm", "--force", "--volumes", name, check=False)


# The self-test.


def selftest(box: Box) -> dict[str, Any]:
    """A container made exactly as a trial's, asked what it can reach and hold; the proxy is
    started for it and stopped after, so its counts are not a run's."""
    box.start_proxy()
    box_expect = trial_box.expect(box.limits, box.facts["env"])
    problems: list[str] = []

    def held(container: dict[str, Any]) -> None:
        problems.extend(
            trial_box.judge_inspect(container, inspect("network", trial_box.NETWORK), box_expect)
        )

    try:
        outcome, _ = run_container(
            f"{trial_box.PREFIX}probe",
            box.image,
            ["python", "/opt/box/probe.py"],
            box.limits,
            inspected=held,
        )
        try:
            report = json.loads(outcome.output)
            if not isinstance(report, dict):
                raise ValueError("not a document")
        except ValueError:
            problems.append(f"the probe printed no document: {outcome.output[-300:]!r}")
            report = {}
        problems += trial_box.judge_probe(report, box_expect) if report else []
        totals = box.totals()
    finally:
        box.stop_proxy()
    result = {
        "passed": not problems,
        "failures": problems,
        "at": now(),
        "attempts": {kind: len(report.get(kind) or []) for kind in ("direct", "denied", "allowed")},
    }
    _show(report, totals, problems)
    return {**result, "report": report}


def _show(
    report: dict[str, Any], totals: dict[str, dict[str, int]] | None, problems: list[str]
) -> None:
    for one in report.get("direct") or []:
        print(f"  direct  {one['label']:<42} {'REACHED' if one['reached'] else 'blocked'}")
    for one in report.get("denied") or []:
        print(f"  proxy   {one['target']:<42} {one['status']}")
    for one in report.get("allowed") or []:
        print(f"  proxy   {one['target']:<42} {one['status']} then {one['http']}")
    for key in ("uid", "gid", "groups", "status", "cgroup", "machine", "pythons", "uv"):
        print(f"  {key}: {report.get(key)}")
    print(f"  proxy totals: {totals}")
    print("self-test: PASS" if not problems else "self-test: FAIL\n  " + "\n  ".join(problems))


# A repository.


def python_for(directory: Path, installed: dict[str, str]) -> str:
    def text(name: str) -> str | None:
        try:
            return (directory / name).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    return trial_box.choose_python(text("pyproject.toml"), text(".python-version"), installed)


def try_repository(
    box: Box,
    entry: dict[str, Any],
    frame: dict[str, Any],
    directory: Path,
    name: str,
    installed: dict[str, str],
    work: Path,
    test_timeout: int | None,
) -> dict[str, Any]:
    """One repository's record, whatever happens to it."""
    python = python_for(directory, installed)
    try:
        command = trial_box.run_command(frame["distribution"], frame["from"], python, test_timeout)
        outcome, seconds = run_container(name, box.image, command, box.limits, repository=directory)
    except (SystemExit, subprocess.SubprocessError, OSError) as error:
        outcome, seconds = Outcome(None, False, False, False, str(error), None), 0.0
        record = trial_box.repository_record(entry, frame, python, outcome, seconds, str(work))
        return {**record, "status": "error", "reason": "container"}
    return trial_box.repository_record(entry, frame, python, outcome, seconds, str(work))


def provenance(box: Box, wheel: Path, commit: str | None, probe: dict[str, Any]) -> dict[str, Any]:
    return {
        "obelize_version": trial_box.wheel_version(wheel.name),
        "obelize_commit": commit,
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "image": box.facts["id"],
        "docker": docker("version", "--format", "{{.Server.Version}}").stdout.strip(),
        "uv": probe.get("uv"),
        "pythons": probe.get("pythons"),
        "machine": probe.get("machine"),
        "date": now(),
        "limits": box.limits._asdict(),
        "allowlist": list(trial_box.INDEX_HOSTS),
    }


def prepare(
    work: Path, wheel: Path | None, limits: Limits
) -> tuple[Box, Path, str | None, dict[str, Any]]:
    """The wheel, the image, the box and a self-test that passed; or an exit with why not."""
    work.mkdir(parents=True, exist_ok=True)
    commit = None
    if wheel is None:
        wheel, commit = build_wheel(work)
    box = Box(build_image(wheel, work), limits)
    try:
        tested = selftest(box)
    except BaseException:
        box.close()
        raise
    if not tested["passed"]:
        box.close()
        raise SystemExit("the self-test failed: nothing was run")
    return box, wheel, commit, tested


def run(
    slug: str,
    work: Path,
    out: Path,
    only: list[str] | None,
    jobs: int,
    wheel: Path | None,
    again: bool,
    limits: Limits,
    test_timeout: int | None,
) -> None:
    frame_path = FRAMES / slug / "sample.yaml"
    frame = read_yaml(frame_path)
    dry = json.loads((DRY_RUNS / f"{slug}.json").read_text(encoding="utf-8"))
    chosen = set(trial_box.select(dry)) & {row["full_name"] for row in frame["repositories"]}
    entries = [
        row
        for row in frame["repositories"]
        if row["full_name"] in chosen and (not only or row["full_name"] in only)
    ]
    if not entries:
        raise SystemExit(f"{slug}: no repository whose dry run writes a file")
    target = out / f"{slug}.json"
    memory = int(docker("info", "--format", "{{.MemTotal}}").stdout)
    if jobs < 1 or (jobs * limits.memory_gb << 30) + (256 << 20) > memory:
        raise SystemExit(
            f"--jobs {jobs} of {limits.memory_gb} GiB each does not fit in {memory >> 20} MiB"
        )
    box, built, commit, tested = prepare(work / slug, wheel, limits)
    try:
        header = {
            **provenance(box, built, commit, tested["report"]),
            "frame": frame_path.relative_to(ROOT).as_posix(),
            "distribution": frame["distribution"],
            "from": frame["from"],
            "to": frame["to"],
            "dry_run": {"obelize_version": dry["obelize_version"], "unit": dry.get("unit")},
            "selftest": {key: tested[key] for key in ("passed", "failures", "at", "attempts")},
        }
        done = _resumed(target, header, again)
        todo = [row for row in entries if row["full_name"] not in done]
        box.start_proxy()
        lock = threading.Lock()
        started = len(done)

        def one(position: int, entry: dict[str, Any]) -> None:
            nonlocal started
            directory = work / slug / "repos" / entry["full_name"].replace("/", "__")
            shutil.rmtree(directory, ignore_errors=True)
            try:
                try:
                    gate1_collect.fetch(entry, directory)
                except gate1_collect.RECORDED as error:
                    record = {
                        **_failed(entry, frame),
                        "tail": trial_box.scrub(str(error), str(work))[:400],
                    }
                else:
                    record = try_repository(
                        box,
                        entry,
                        frame,
                        directory,
                        f"{trial_box.PREFIX}{slug[:12]}-{position}",
                        tested["report"]["pythons"],
                        work,
                        test_timeout,
                    )
            finally:
                shutil.rmtree(directory, ignore_errors=True)
            with lock:
                done[entry["full_name"]] = record
                started += 1
                _save(target, header, entries, done, box.totals())
                print(
                    f"[{started}/{len(entries)}] {entry['full_name']}: {record['status']}"
                    f"{' (' + record['reason'] + ')' if record['reason'] else ''}, "
                    f"{record['compared']} compared, {record['broken_count']} broke, "
                    f"{record['seconds']:g} s",
                    flush=True,
                )

        with ThreadPoolExecutor(max_workers=jobs) as pool:
            for future in [pool.submit(one, number, entry) for number, entry in enumerate(todo)]:
                future.result()
        print(f"{len(entries)} record(s) -> {target}")
    finally:
        box.close()


def _failed(entry: dict[str, Any], frame: dict[str, Any]) -> dict[str, Any]:
    return {
        "full_name": entry["full_name"],
        "sha": entry["sha"],
        "band": entry["band"],
        "distribution": frame["distribution"],
        "from": frame["from"],
        "python": None,
        "status": "error",
        "reason": "fetch",
        "compared": 0,
        "broken": [],
        "broken_count": 0,
        "flaky": 0,
        "written": 0,
        "held": 0,
        "places": 0,
        "partial": None,
        "exit_code": None,
        "oom": False,
        "seconds": 0.0,
    }


def _resumed(target: Path, header: dict[str, Any], again: bool) -> dict[str, dict[str, Any]]:
    """The rows of an earlier run of this record, if the same wheel and image made them."""
    if again or not target.exists():
        return {}
    earlier = json.loads(target.read_text(encoding="utf-8"))
    if (earlier.get("wheel_sha256"), earlier.get("image")) != (
        header["wheel_sha256"],
        header["image"],
    ):
        raise SystemExit(f"{target.name} was made with another wheel or image: pass --again")
    return {row["full_name"]: row for row in earlier["trial"]}


def _save(
    target: Path,
    header: dict[str, Any],
    entries: list[dict[str, Any]],
    done: dict[str, dict[str, Any]],
    totals: dict[str, dict[str, int]] | None,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = [done[row["full_name"]] for row in entries if row["full_name"] in done]
    document = {**header, "proxy": totals, "trial": rows}
    scratch = target.with_suffix(".tmp")
    scratch.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    scratch.replace(target)


def smoke(
    directory: Path,
    distribution: str,
    old: str | None,
    work: Path,
    wheel: Path | None,
    out: Path | None,
    limits: Limits,
    test_timeout: int | None,
) -> dict[str, Any]:
    """One synthetic repository through the box, as a repository of a frame goes."""
    if directory == Path.home() or directory in Path.home().parents:
        raise SystemExit(f"{directory} holds the home directory: give the project's own folder")
    box, built, commit, tested = prepare(work / "smoke", wheel, limits)
    try:
        box.start_proxy()
        sha = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        entry = {"full_name": f"smoke/{directory.name}", "sha": sha or "0" * 40, "band": "smoke"}
        frame = {"distribution": distribution, "from": old or "the manifests"}
        name = f"{trial_box.PREFIX}smoke-{directory.name[:30].lower()}"
        python = python_for(directory, tested["report"]["pythons"])
        command = trial_box.run_command(distribution, old, python, test_timeout)
        outcome, seconds = run_container(name, box.image, command, limits, repository=directory)
        record = trial_box.repository_record(entry, frame, python, outcome, seconds, str(work))
        record["output"] = trial_box.scrub(outcome.output[-OUTPUT_CHARS:], str(work))
        document = {
            **provenance(box, built, commit, tested["report"]),
            "selftest": {key: tested[key] for key in ("passed", "failures", "at", "attempts")},
            "proxy": box.totals(),
            "trial": [record],
        }
    finally:
        box.close()
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return document


def _limits(arguments: argparse.Namespace) -> Limits:
    base = Limits()
    return base._replace(
        wall_s=getattr(arguments, "wall", None) or base.wall_s,
        disk_gb=getattr(arguments, "disk_gb", None) or base.disk_gb,
    )


def _outside(parser: argparse.ArgumentParser, work: Path) -> Path:
    resolved = work.resolve()
    if resolved == ROOT or ROOT in resolved.parents:
        parser.error("--work must be outside the repository")
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    tester = sub.add_parser(
        "selftest", help="prove the box holds, with a container made as a trial's"
    )
    tester.add_argument("--image", help="default: the newest image of the box")
    runner = sub.add_parser(
        "run", help="try the repositories of a frame whose dry run writes a file"
    )
    runner.add_argument(
        "-m", "--migration", required=True, choices=list(upgrade_collect.MIGRATIONS)
    )
    runner.add_argument("--only", action="append", help="a repository full name; needs --out")
    runner.add_argument("--jobs", type=int, default=2, help="containers at once (default: 2)")
    runner.add_argument("--out", type=Path, default=RESULTS, help="where the record goes")
    runner.add_argument("--again", action="store_true", help="try every repository again")
    smoker = sub.add_parser("smoke", help="try one synthetic repository you made")
    smoker.add_argument("directory", type=Path)
    smoker.add_argument("distribution")
    smoker.add_argument("--from", dest="old")
    smoker.add_argument("--out", type=Path, help="where to write the record")
    sub.add_parser("cleanup", help="remove the containers and networks this module made")
    for command in (runner, smoker):
        command.add_argument(
            "--work", type=Path, required=True, help="a directory outside the repository"
        )
        command.add_argument("--wheel", type=Path, help="a wheel to test; default: HEAD, built")
        command.add_argument("--wall", type=int, help="seconds a container may run (default: 5400)")
        command.add_argument("--disk-gb", type=int, help="GiB a container may write (default: 8)")
        command.add_argument("--test-timeout", type=int, help="obelize's own --timeout, in seconds")
    arguments = parser.parse_args(argv)
    if arguments.command == "cleanup":
        cleanup()
        return 0
    if arguments.command == "selftest":
        box = Box(arguments.image or newest_image(), Limits())
        try:
            return 0 if selftest(box)["passed"] else 1
        finally:
            box.close()
    work = _outside(parser, arguments.work)
    limits = _limits(arguments)
    if arguments.command == "smoke":
        document = smoke(
            arguments.directory.resolve(),
            arguments.distribution,
            arguments.old,
            work,
            arguments.wheel,
            arguments.out,
            limits,
            arguments.test_timeout,
        )
        print(json.dumps(document["trial"][0], indent=2))
        return 0
    if arguments.only and arguments.out == RESULTS:
        parser.error("--only measures part of a frame: give --out, or the record would be partial")
    run(
        arguments.migration,
        work,
        arguments.out,
        arguments.only,
        arguments.jobs,
        arguments.wheel,
        arguments.again,
        limits,
        arguments.test_timeout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

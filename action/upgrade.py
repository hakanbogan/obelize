"""The upgrade mode of the action: the job that runs the repository's code, and the job that may
write to the repository, which does not (ADR-078).

`run` is the unprivileged job. It upgrades each dependency named, in the checkout, with
`obelize upgrade --apply --yes --branch`, which tries the move in a copy and commits it to a new
branch only if the tests agree, and leaves for each, in a folder, a bundle of that branch, a patch,
the trial's evidence and a report. It holds no token and pushes nothing. `gate` is the job's
verdict on the exit codes. `publish` is the privileged job: it reads the folders as data from a
stranger, refuses a folder unless every rule of `verified` holds, and only then pushes its one
commit and opens the pull request. It runs none of the repository's code.

Every value reaches this file through the environment or the command line and is checked against
the shape it may have before it joins a command line; nothing is expanded into a shell.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, NamedTuple

VERSION = re.compile(r"^[0-9]+(\.[0-9]+)*([.-]?(a|b|rc|dev|post)[0-9]+)*$")
DISTRIBUTION = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$")
ARTIFACT = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
FOLDER = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# What the CLI names a branch: `obelize/upgrade-` and the install spec, lower case and dashed.
BRANCH = re.compile(r"^obelize/upgrade-[a-z0-9][a-z0-9.-]{0,120}$")
# A release as the trial prints it: a version, or the specifier it installed.
RELEASE = re.compile(r"^[A-Za-z0-9._+!<>=~,*-]{1,100}$")
SUBJECT = re.compile(r"^Upgrade (?P<name>\S+) (?P<old>\S+) to (?P<new>\S+)$")
HELD = re.compile(r"^Not written, for you to change: the dependency line at (?P<where>.+)\.$", re.M)
PLACE = re.compile(r"^[^\x00-\x1f`\\]{1,200}:[0-9]{1,7}$")
TRAILER = re.compile(r"^Obelize-Trial: (?P<id>[A-Za-z0-9._-]{1,80})$", re.M)
SHA = re.compile(r"^[0-9a-f]{40}$")
# The manifests obelize reads and writes (`scan/manifests.py` NAMES and REQUIREMENTS_GLOB).
MANIFESTS = frozenset({"Pipfile", "pyproject.toml", "setup.cfg", "setup.py"})
# A commit needs an identity, and this is the one the publishing job looks for.
IDENTITY = ("obelize", "obelize@users.noreply.github.com")
# The exit codes of `obelize upgrade` for a move the tests did not prove: they broke (3), a place is
# left for a person (4), no verdict (6). Any other code is a mistake or a crash.
UNPROVEN = frozenset({3, 4, 6})
TOKENS = ("GH_TOKEN", "GITHUB_TOKEN")
MAX_DISTRIBUTIONS = 20
MAX_FILES = 2000
MAX_BLOB = 8 << 20
MAX_BUNDLE = 256 << 20
MAX_REPORT = 1 << 20
LISTED = 50
EVIDENCE = ("trial.json", "old.txt", "new.txt")


class RefusedError(Exception):
    """Why a folder of the artifact is not published, in words for the person."""


class Outcome(NamedTuple):
    name: str
    folder: str
    code: int
    branch: str | None


class Verified(NamedTuple):
    branch: str
    tip: str
    title: str
    body: str


def canonical(name: str) -> str:
    """The name as an index folds it: lower case, every run of `-_.` one `-`."""
    return re.sub(r"[-_.]+", "-", name).lower()


def shown(text: str) -> str:
    """`text` as one line of a workflow log: a value or a message that came from the artifact, or
    from git about it, cannot end the command and start another."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def fail(message: str) -> int:
    print(f"::error::{shown(message)}")
    return 2


def git(root: Path, *arguments: str, check: bool = True) -> str:
    """One git command in `root`, with no hook, filter command or maintenance run for it."""
    quiet = ["-c", f"core.hooksPath={os.devnull}", "-c", "core.fsmonitor=", "-c", "gc.auto=0"]
    done = subprocess.run(
        ["git", *quiet, "-C", str(root), *arguments], capture_output=True, check=False
    )
    if check and done.returncode:
        said = done.stderr.decode("utf-8", "replace").strip()
        raise RefusedError(f"git {arguments[0]} failed: {said}")
    return done.stdout.decode("utf-8", "surrogateescape")


# The unprivileged job.


def run(environ: dict[str, str]) -> int:
    """Upgrade each dependency; the exit code of the first that was not proven goes to the output,
    and this returns 0 so that the artifact is uploaded before the job is failed (`gate`)."""
    if environ.get("GITHUB_EVENT_NAME") == "pull_request_target":
        return fail("mode: upgrade runs the repository's tests: never on pull_request_target")
    if held := [name for name in TOKENS if environ.get(name)]:
        return fail(f"{held[0]} is set: the job that runs the repository's tests holds no token")
    version = environ.get("OBELIZE_VERSION", "")
    if not VERSION.fullmatch(version):
        return fail(f"version takes a release such as 0.7.0, got '{version}'")
    names = environ.get("OBELIZE_DISTRIBUTIONS", "").split()
    if not names or len(names) > MAX_DISTRIBUTIONS:
        return fail("distributions takes the dependencies to upgrade, such as pydantic")
    for name in names:
        if not DISTRIBUTION.fullmatch(name):
            return fail(f"distributions takes distribution names such as pydantic, got '{name}'")
    folders = [canonical(name) for name in names]
    if len(set(folders)) != len(folders):
        return fail("distributions names one dependency twice")
    stated = environ.get("OBELIZE_FROM", "")
    if stated and not VERSION.fullmatch(stated):
        return fail(f"from takes a release such as 1.10.26, got '{stated}'")
    if stated and len(names) != 1:
        return fail("from goes with one distribution: it is the release the code is written for")
    artifact = environ.get("OBELIZE_ARTIFACT_NAME", "obelize-upgrade")
    if not ARTIFACT.fullmatch(artifact):
        return fail(f"artifact-name takes letters, digits, '.', '_' and '-', got '{artifact}'")
    work = environ.get("OBELIZE_WORKDIR", ".")
    if not Path(work).is_dir():
        return fail(f"working-directory '{work}' is not a directory")
    out = Path(environ["OBELIZE_OUT"])
    if out.exists() and any(out.iterdir()):
        return fail(f"{out} holds files already")
    root = Path(work).resolve()
    try:
        base = git(root, "rev-parse", "--verify", "HEAD^{commit}").strip()
    except RefusedError:
        return fail(f"working-directory '{work}' is not a git checkout with a commit")
    committer = {
        **environ,
        "GIT_AUTHOR_NAME": IDENTITY[0],
        "GIT_COMMITTER_NAME": IDENTITY[0],
        "GIT_AUTHOR_EMAIL": IDENTITY[1],
        "GIT_COMMITTER_EMAIL": IDENTITY[1],
    }
    outcomes = []
    for name, folder in zip(names, folders, strict=True):
        before = branches(root)
        command = ["uvx", f"obelize=={version}", "upgrade", name, "--apply", "--yes", "--branch"]
        if stated:
            command += ["--from", stated]
        code = subprocess.run(command, cwd=root, env=committer, check=False).returncode
        made = [one for one in branches(root) if one not in before]
        branch = None
        if code == 0 and len(made) == 1 and BRANCH.fullmatch(made[0]):
            branch = made[0] if collect(root, base, made[0], out / folder) else None
        if code == 0 and branch is None:
            print(f"::error::obelize upgrade {name} exited 0 and left no one branch to publish")
            code = 1
        outcomes.append(Outcome(name, folder, code, branch))
    published(outcomes, out, environ)
    return 0


def branches(root: Path) -> list[str]:
    listed = git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads/obelize/")
    return listed.split()


def collect(root: Path, base: str, branch: str, folder: Path) -> bool:
    """The bundle, the patch, the evidence and the report of the branch a passed trial made."""
    folder.mkdir(parents=True)
    ref = f"refs/heads/{branch}"
    try:
        git(root, "bundle", "create", str(folder / "upgrade.bundle"), ref, f"^{base}")
        patch = git(root, "format-patch", "--stdout", "--no-signature", f"{base}..{ref}")
        message = git(root, "log", "-1", "--format=%B", ref)
    except RefusedError as error:
        print(f"::error::{shown(str(error))}")
        return False
    (folder / "upgrade.patch").write_text(patch, encoding="utf-8", errors="surrogateescape")
    found = TRAILER.search(message)
    kept = root / ".obelize" / "trials" / found["id"] if found else None
    for name in EVIDENCE:
        if kept is not None and (kept / name).is_file():
            shutil.copyfile(kept / name, folder / name)
    (folder / "REPORT.md").write_text(report(folder, message), encoding="utf-8")
    return True


def report(folder: Path, message: str) -> str:
    """What the trial said, for a person who opens the artifact. The publishing job reads the
    trial and the bundle, never this."""
    try:
        said = json.loads((folder / "trial.json").read_text(encoding="utf-8"))
        line = (
            f"{said['distribution']} {said['from']} to {said['to']}: {said['status']}; "
            f"{said['compared']} test(s) passed before, {len(said['broken'])} broke, "
            f"{len(said['flaky'])} failed once and passed again.\n\nWritten: "
            + ", ".join(f"`{path}`" for path in said["written"])
        )
    except (OSError, ValueError, LookupError, TypeError):
        line = "The trial left no evidence this report could read."
    return f"# obelize upgrade\n\n{line}\n\n## The commit message\n\n```\n{message.rstrip()}\n```\n"


def published(outcomes: list[Outcome], out: Path, environ: dict[str, str]) -> None:
    """The step's outputs and summary."""
    made = [one for one in outcomes if one.branch]
    values = {
        "exit-code": str(next((one.code for one in outcomes if one.code), 0)),
        "changed": "true" if made else "false",
        "bundle-file": " ".join(str(out / one.folder / "upgrade.bundle") for one in made),
        "report-file": " ".join(str(out / one.folder / "REPORT.md") for one in made),
        "out-dir": str(out) if out.is_dir() else "",
    }
    lines = ["## obelize upgrade", "", "| Dependency | Exit | Branch |", "|---|---|---|"]
    for one in outcomes:
        print(f"obelize upgrade {one.name}: exit {one.code}, branch {one.branch or 'none'}")
        lines.append(
            f"| `{one.name}` | {one.code} | {f'`{one.branch}`' if one.branch else 'none'} |"
        )
    if target := environ.get("GITHUB_STEP_SUMMARY"):
        with Path(target).open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    if target := environ.get("GITHUB_OUTPUT"):
        with Path(target).open("a", encoding="utf-8") as handle:
            handle.writelines(f"{key}={value}\n" for key, value in values.items())


def gate(environ: dict[str, str]) -> int:
    """The job's verdict on the exit code of the upgrades."""
    strict = environ.get("OBELIZE_FAIL_ON_UNPROVEN", "")
    if strict not in {"true", "false"}:
        return fail(f"fail-on-unproven takes true or false, got '{strict}'")
    text = environ.get("OBELIZE_EXIT_CODE", "")
    if not text.isdecimal():
        print("::error::obelize upgrade left no exit code, so nothing was proven")
        return 1
    code = int(text)
    if code == 0:
        return 0
    if code in UNPROVEN and strict == "false":
        print(f"::notice::obelize upgrade exited {code}: the move was not proven (docs/CLI.md)")
        return 0
    print(f"::error::obelize upgrade exited {code} (docs/CLI.md)")
    return code


# The privileged job.


def verified(folder: Path, repo: Path, base: str) -> Verified:
    """The one commit of `folder`'s bundle, if every rule holds; else `RefusedError`, saying which.

    The bundle, the trial and everything else in the folder come from a job that ran the
    repository's code and its dependencies' build scripts, so each is taken to be forged. The
    bundle must hold one branch, named as the CLI names one, of one commit on `base` by the identity
    `run` sets, whose subject names the upgrade the trial describes and says passed. Every path the
    commit changes must be one the trial names, a Python source or a manifest (`place`), a regular
    file that is not executable and had the mode it has. Nothing else of the folder is looked at.
    """
    if not FOLDER.fullmatch(folder.name):
        raise RefusedError(f"'{folder.name}' is not a folder this action makes")
    document = loaded(folder / "trial.json")
    if document.get("status") != "pass":
        raise RefusedError(f"the trial says '{document.get('status')}', not 'pass'")
    shown = _text(document.get("distribution"), DISTRIBUTION, "distribution")
    old = _text(document.get("from"), RELEASE, "from")
    new = _text(document.get("to"), RELEASE, "to")
    if canonical(shown) != folder.name:
        raise RefusedError(f"the trial is about {shown}, not {folder.name}")
    written = set(_strings(document.get("written"), "written"))
    counts = (
        _count(document.get("compared"), "compared"),
        len(_strings(document.get("broken"), "broken")),
        len(_strings(document.get("flaky"), "flaky")),
    )
    bundle = folder / "upgrade.bundle"
    if bundle.is_symlink() or not bundle.is_file() or bundle.stat().st_size > MAX_BUNDLE:
        raise RefusedError("upgrade.bundle is missing, is not a file or is too big")
    listed = git(repo, "bundle", "list-heads", str(bundle)).splitlines()
    heads = [line.partition(" ")[2] for line in listed]
    branch = heads[0].removeprefix("refs/heads/") if len(heads) == 1 else ""
    if not (BRANCH.fullmatch(branch) and heads == [f"refs/heads/{branch}"]) or not git(
        repo, "check-ref-format", "--branch", branch, check=False
    ):
        raise RefusedError(f"the bundle must hold one branch of obelize/upgrade-..., not {heads}")
    git(repo, "bundle", "verify", str(bundle))
    private = f"refs/obelize-verify/{folder.name}"
    git(
        repo,
        *("-c", "transfer.fsckObjects=true", "-c", "fetch.fsckObjects=true"),
        *("fetch", "--quiet", "--no-tags", "--no-recurse-submodules"),
        str(bundle),
        f"+refs/heads/{branch}:{private}",
    )
    tip = git(repo, "rev-parse", "--verify", f"{private}^{{commit}}").strip()
    if git(repo, "rev-list", "--parents", "-n", "1", tip).split() != [tip, base]:
        raise RefusedError("the branch must be one commit on the commit the job ran on")
    if git(repo, "log", "-1", "--format=%an%n%ae%n%cn%n%ce", tip).splitlines() != [*IDENTITY] * 2:
        raise RefusedError("the commit is not by the identity the action gives it")
    message = git(repo, "log", "-1", "--format=%B", tip)
    subject = SUBJECT.fullmatch(message.splitlines()[0] if message else "")
    if not subject or (canonical(subject["name"]), subject["old"], subject["new"]) != (
        folder.name,
        old,
        new,
    ):
        raise RefusedError("the commit's subject does not name the upgrade the trial describes")
    paths = changed(repo, base, tip, written)
    text = prose(shown, old, new, counts, paths, message, base)
    return Verified(branch, tip, f"Upgrade {shown} {old} to {new}", text)


def loaded(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_REPORT:
        raise RefusedError("trial.json is missing, is not a file or is too big")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as error:
        raise RefusedError(f"trial.json cannot be read: {error}") from error
    if not isinstance(document, dict):
        raise RefusedError("trial.json is not an object")
    return document


def _text(value: object, shape: re.Pattern[str], what: str) -> str:
    if not isinstance(value, str) or not shape.fullmatch(value):
        raise RefusedError(f"trial.json: {what} is not a value this action reads")
    return value


def _strings(value: object, what: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(one, str) for one in value):
        raise RefusedError(f"trial.json: {what} is not a list of strings")
    return value


def _count(value: object, what: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RefusedError(f"trial.json: {what} is not a count")
    return value


def changed(repo: Path, base: str, tip: str, named: set[str]) -> tuple[str, ...]:
    """The paths `tip` changes from `base`, if each is a regular file of a kind obelize writes that
    the trial names; else `RefusedError`."""
    raw = git(repo, "diff-tree", "-r", "-z", "--raw", "--no-renames", "--no-abbrev", base, tip)
    fields = raw.split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    if len(fields) % 2:
        raise RefusedError("git printed a change this action cannot read")
    found = []
    for meta, path in zip(fields[::2], fields[1::2], strict=True):
        before, after, _, blob, status = meta.removeprefix(":").split(" ")
        if status not in {"A", "M"}:
            raise RefusedError(f"{path}: a change of kind {status}; obelize adds and edits files")
        if after not in {"100644", "100755"} or (status == "A" and after != "100644"):
            raise RefusedError(
                f"{path}: mode {after}; a link, a submodule or an executable is refused"
            )
        if status == "M" and before != after:
            raise RefusedError(f"{path}: its mode changes from {before} to {after}")
        place(path)
        if path not in named:
            raise RefusedError(f"{path}: the trial does not name it")
        if int(git(repo, "cat-file", "-s", blob).strip()) > MAX_BLOB:
            raise RefusedError(f"{path}: more than {MAX_BLOB} bytes")
        found.append(path)
    if not 0 < len(found) <= MAX_FILES:
        raise RefusedError(
            f"the commit changes {len(found)} files; it must change 1 to {MAX_FILES}"
        )
    return tuple(sorted(found))


def place(path: str) -> None:
    """A path obelize writes: a Python source or a manifest, in the repository and outside what git
    or GitHub reads as configuration (`.git*`, `.github`, in whatever case a file system folds
    them), with no character that could end a line of the pull request."""
    parts = path.split("/")
    if (
        "\\" in path
        or re.search(r"[\x00-\x1f\x7f`]", path)
        or any(
            part in {"", ".", ".."} or part.casefold().startswith((".git", ".obelize"))
            for part in parts
        )
    ):
        raise RefusedError(f"{path}: not a path this action publishes")
    leaf = parts[-1]
    if not (
        leaf.endswith((".py", ".pyi"))
        or leaf in MANIFESTS
        or (leaf.endswith(".txt") and ("requirement" in leaf or parts[-2:-1] == ["requirements"]))
    ):
        raise RefusedError(f"{path}: obelize writes no file of this kind")


def held(message: str) -> list[str]:
    """The dependency lines the commit says were not written, if all are `path:line`."""
    found = HELD.search(message)
    places = [one.strip() for one in found["where"].split(",")] if found else []
    return places if all(PLACE.fullmatch(one) for one in places) else []


def prose(
    name: str,
    old: str,
    new: str,
    counts: tuple[int, int, int],
    paths: tuple[str, ...],
    message: str,
    base: str,
) -> str:
    """The pull request's text, made here from values that passed a shape: nothing of the
    artifact's own prose reaches it."""
    compared, broke, flaky = counts
    shown = "\n".join(f"- `{one}`" for one in paths[:LISTED])
    more = f"\n- and {len(paths) - LISTED} more" if len(paths) > LISTED else ""
    left = held(message)
    unwritten = (
        "\n\nNot written, for you to change: the dependency line at "
        + ", ".join(f"`{one}`" for one in left)
        + "."
        if left
        else ""
    )
    return (
        f"obelize moved `{name}` from {old} to {new} in a copy of this repository and ran its "
        f"tests before and after the move: {compared} test(s) passed before, {broke} broke, "
        f"{flaky} failed once and passed again.\n\n"
        f"The move changes {len(paths)} file(s):\n\n{shown}{more}{unwritten}\n\n"
        f"The tests ran in the first job of the workflow, which held no token. This pull request "
        f"was opened by a second job that ran none of the repository's code: it checked that the "
        f"branch holds one commit on `{base[:10]}`, that every path in it is one the trial names, "
        f"and that none is a workflow, a link or an executable. Read the diff all the same.\n"
    )


def publish(
    artifacts: Path, repo: Path, base: str, base_branch: str, remote: str = "origin"
) -> int:
    """Verify each folder of the artifact, push the branch of each that passes and open its pull
    request. A folder that fails is said, and the others go on."""
    if not SHA.fullmatch(base):
        return fail(f"base takes a commit, got '{base}'")
    if not git(repo, "check-ref-format", "--branch", base_branch, check=False):
        return fail(f"base-branch takes a branch name, got '{base_branch}'")
    folders = sorted(one for one in artifacts.iterdir() if one.is_dir() and not one.is_symlink())
    if not folders:
        print("::notice::the artifact holds no upgrade")
        return 0
    failed = 0
    for folder in folders:
        try:
            opened(verified(folder, repo, base), repo, base_branch, remote)
        except RefusedError as error:
            print(f"::error::{shown(f'{folder.name}: {error}')}")
            failed += 1
        finally:
            git(repo, "update-ref", "-d", f"refs/obelize-verify/{folder.name}", check=False)
    return 1 if failed else 0


def opened(result: Verified, repo: Path, base_branch: str, remote: str) -> None:
    if git(repo, "ls-remote", "--heads", remote, f"refs/heads/{result.branch}").strip():
        print(f"::notice::{result.branch} exists on {remote} already, so it was not touched")
        return
    git(repo, "push", "--no-verify", remote, f"{result.tip}:refs/heads/{result.branch}")
    with tempfile.TemporaryDirectory(prefix="obelize-pr-") as scratch:
        body = Path(scratch) / "body.md"
        body.write_text(result.body, encoding="utf-8")
        command = ["gh", "pr", "create", "--head", result.branch, "--base", base_branch]
        command += ["--title", result.title, "--body-file", str(body)]
        done = subprocess.run(command, cwd=repo, check=False)
    if done.returncode:
        raise RefusedError(f"gh pr create exited {done.returncode}; {result.branch} is pushed")
    print(f"::notice::opened a pull request for {result.branch}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="upgrade.py")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run")
    commands.add_parser("gate")
    one = commands.add_parser("publish")
    one.add_argument("--artifacts", type=Path, required=True)
    one.add_argument("--repo", type=Path, required=True)
    one.add_argument("--base", required=True)
    one.add_argument("--base-branch", required=True)
    given = parser.parse_args(argv)
    if given.command == "run":
        return run(dict(os.environ))
    if given.command == "gate":
        return gate(dict(os.environ))
    return publish(given.artifacts, given.repo, given.base, given.base_branch)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

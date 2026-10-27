"""The upgrade mode of the action: the job that runs the repository's code, and the job that may
write to the repository, which does not (ADR-078).

`run` is the job that runs the repository's tests. It upgrades each dependency named, in the
checkout, with `obelize upgrade --apply --yes --branch`, which tries the move in a copy and commits
it to a new branch only if the tests agree, and leaves for each, in a folder, a bundle of that
branch, a patch, the trial's evidence and a report. It refuses to start where a credential that
writes is in reach, and pushes nothing. `gate` is the job's verdict on the exit codes. `publish` is
the job that may write: it reads the folders as data from a stranger, takes only those of the
dependencies the workflow asked for, refuses a folder unless every rule of `verified` holds, and
only then pushes a commit it made itself from the verified tree and opens the pull request. It
runs none of the repository's code.

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
import unicodedata
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
HELD = re.compile(r"^Not written, for you to change: the dependency line at (?P<where>.+)\.$", re.M)
PLACE = re.compile(r"^[^\x00-\x1f`\\]{1,200}:[0-9]{1,7}$")
# What Windows shows a long name as (`GITHUB~1` for `.github`): a name this action never publishes.
SHORT = re.compile(r"^[^.]{1,6}~[0-9]+(\..*)?$")
# What a checkout leaves in the repository's own git configuration to push with.
CREDENTIALS = r"extraheader|^includeif\.|^credential\."
TRAILER = re.compile(r"^Obelize-Trial: (?P<id>[A-Za-z0-9._-]{1,80})$", re.M)
SHA = re.compile(r"^[0-9a-f]{40}$")
# The manifests obelize reads and writes (`scan/manifests.py` NAMES and REQUIREMENTS_GLOB).
MANIFESTS = frozenset({"Pipfile", "pyproject.toml", "setup.cfg", "setup.py"})
# A commit needs an identity, and this is the one the publishing job looks for.
IDENTITY = ("obelize", "obelize@users.noreply.github.com")
# The exit codes of `obelize upgrade --apply --branch` for a move the tests did not prove: they
# broke (3), or there is no verdict (6). Any other code is a mistake or a crash: `fix` has a 4
# (nothing applied, a place to review), which a trial that ends on a branch never gives.
UNPROVEN = frozenset({3, 6})
# A job that runs the repository's tests must not run where one of these exists. The runner sets
# `ACTIONS_RUNTIME_TOKEN` itself, for the artifact and cache services; it is not refused.
TOKENS = ("GH_TOKEN", "GITHUB_TOKEN", "ACTIONS_ID_TOKEN_REQUEST_TOKEN")
# Events that give a job that reads someone else's files a token, or run it on their account.
EVENTS = ("pull_request_target", "workflow_run", "issue_comment")
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
    from git about it, cannot end the command and start another, or fail to print."""
    escaped = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return escaped.encode("utf-8", "backslashreplace").decode("utf-8")


def lines(text: str) -> list[str]:
    """The lines of `text` that git ended with a line feed: `str.splitlines` also splits at a form
    feed, a separator and a next-line character, which a name or a value may hold."""
    return [one.removesuffix("\r") for one in text.split("\n") if one]


def fail(message: str) -> int:
    print(f"::error::{shown(message)}")
    return 2


def identity() -> dict[str, str]:
    """What git reads to know who commits: a runner has none, and the publishing job gives the
    commit it makes the same one."""
    name, email = IDENTITY
    return {
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
    }


def git(
    root: Path,
    *arguments: str,
    check: bool = True,
    env: dict[str, str] | None = None,
    data: bytes | None = None,
) -> str:
    """One git command in `root`, with no hook, filter command, signing or maintenance run."""
    quiet = ["-c", f"core.hooksPath={os.devnull}", "-c", "core.fsmonitor=", "-c", "gc.auto=0"]
    quiet += ["-c", "commit.gpgsign=false"]
    done = subprocess.run(
        ["git", *quiet, "-C", str(root), *arguments],
        input=data,
        capture_output=True,
        check=False,
        env={**os.environ, **env} if env else None,
    )
    if check and done.returncode:
        said = done.stderr.decode("utf-8", "replace").strip()
        # The command, not the `-c name=value` before it.
        word = next(
            one
            for i, one in enumerate(arguments)
            if one != "-c" and arguments[max(i - 1, 0)] != "-c"
        )
        raise RefusedError(f"git {word} failed: {said}")
    return done.stdout.decode("utf-8", "surrogateescape")


# The unprivileged job.


def named(text: str) -> tuple[list[str], list[str]]:
    """The dependencies a workflow asks for and the folder each gets; else `RefusedError`."""
    names = text.split()
    if not names or len(names) > MAX_DISTRIBUTIONS:
        raise RefusedError("distributions takes the dependencies to upgrade, such as pydantic")
    for name in names:
        if not DISTRIBUTION.fullmatch(name):
            raise RefusedError(
                f"distributions takes distribution names such as pydantic, got '{name}'"
            )
    folders = [canonical(name) for name in names]
    if len(set(folders)) != len(folders):
        raise RefusedError("distributions names one dependency twice")
    return names, folders


def run(environ: dict[str, str]) -> int:
    """Upgrade each dependency. The exit code of the first upgrade that failed outright, else of the
    first that was not proven, goes to the output, and this returns 0 so that the artifact is
    uploaded before the job is failed (`gate`)."""
    if (event := environ.get("GITHUB_EVENT_NAME")) in EVENTS:
        return fail(f"mode: upgrade runs the repository's tests: never on {event}")
    if unsafe := [name for name in TOKENS if environ.get(name)]:
        return fail(
            f"{unsafe[0]} is set: the job that runs the repository's tests must not hold it"
        )
    version = environ.get("OBELIZE_VERSION", "")
    if not VERSION.fullmatch(version):
        return fail(f"version takes a release such as 0.7.0, got '{version}'")
    try:
        names, folders = named(environ.get("OBELIZE_DISTRIBUTIONS", ""))
    except RefusedError as error:
        return fail(str(error))
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
    # The names of what is set, never a value: a credential is read by whatever the tests run.
    kept = [
        one.split(None, 1)[0]
        for one in lines(git(root, "config", "--local", "--get-regexp", CREDENTIALS, check=False))
    ]
    if kept:
        return fail(
            f"the checkout keeps a credential ({', '.join(kept[:3])}): check out with "
            f"persist-credentials: false"
        )
    outcomes = []
    for name, folder in zip(names, folders, strict=True):
        before = branches(root)
        command = ["uvx", f"obelize=={version}", "upgrade", name, "--apply", "--yes", "--branch"]
        if stated:
            command += ["--from", stated]
        env = {**environ, **identity()}
        code = subprocess.run(command, cwd=root, env=env, check=False).returncode
        made = [one for one in branches(root) if one not in before]
        branch = None
        if code == 0 and len(made) == 1 and BRANCH.fullmatch(made[0]):
            branch = made[0] if collect(root, base, made[0], out / folder) else None
        # An upgrade that exits 0 and makes no branch had nothing to move; one that makes a branch
        # this script cannot publish, or two, is a failure.
        if code == 0 and (made and branch is None):
            print(
                f"::error::obelize upgrade {shown(name)} exited 0 and left no one branch to publish"
            )
            code = 1
        outcomes.append(Outcome(name, folder, code, branch))
    published(outcomes, out, environ)
    return 0


def branches(root: Path) -> list[str]:
    return lines(git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads/obelize/"))


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
            + (
                "\n\nLeft as they were, so the move is partial: "
                + ", ".join(f"`{path}`" for path in said["held"])
                if said.get("held")
                else ""
            )
        )
    except (OSError, ValueError, LookupError, TypeError):
        line = "The trial left no evidence this report could read."
    return f"# obelize upgrade\n\n{line}\n\n## The commit message\n\n```\n{message.rstrip()}\n```\n"


def published(outcomes: list[Outcome], out: Path, environ: dict[str, str]) -> None:
    """The step's outputs and summary."""
    made = [one for one in outcomes if one.branch]
    failed = [one.code for one in outcomes if one.code and one.code not in UNPROVEN]
    unproven = [one.code for one in outcomes if one.code in UNPROVEN]
    values = {
        "exit-code": str((failed or unproven or [0])[0]),
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


# The job that may write.


def verified(folder: Path, repo: Path, base: str) -> Verified:
    """The commit to push for `folder`, made from its bundle's tree if every rule holds; else
    `RefusedError`, saying which.

    The bundle, the trial and everything else in the folder come from a job that ran the
    repository's code and its dependencies' build scripts, so each is taken to be forged. The
    bundle must hold one branch, named as the CLI names one, of one commit whose parent is `base`.
    Only the edits of its tree are used: the commit that is pushed is made here, on `base`, with a
    tree written here from `base` and those edits, by the action's identity, with a message made
    from the values below, so nothing else of the forged commit (its message, its headers, its
    dates, the encoding of its tree) is published. The edits must be to files that exist, each a
    Python source or a manifest (`place`), regular, not changed in mode. The trial's list of paths
    is a consistency check, not a control: it is as forged as the rest.
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
    # Files the rules left as they were for a place of their own; an older trial names none.
    left = _strings(document.get("held", []), "held")
    for path in left:
        place(path)
    counts = (
        _count(document.get("compared"), "compared"),
        len(_strings(document.get("broken"), "broken")),
        len(_strings(document.get("flaky"), "flaky")),
    )
    bundle = folder / "upgrade.bundle"
    if bundle.is_symlink() or not bundle.is_file() or bundle.stat().st_size > MAX_BUNDLE:
        raise RefusedError("upgrade.bundle is missing, is not a file or is too big")
    heads = [
        line.partition(" ")[2] for line in lines(git(repo, "bundle", "list-heads", str(bundle)))
    ]
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
    edits = changed(repo, base, tip, written)
    paths = tuple(sorted(path for _, _, path in edits))
    title = f"Upgrade {shown} {old} to {new}"
    message = git(repo, "log", "-1", "--format=%B", tip)
    facts = prose(shown, old, new, counts, paths, message, tuple(sorted(left)))
    tree = rebuilt(repo, base, edits)
    made = git(repo, "commit-tree", tree, "-p", base, "-m", f"{title}\n\n{facts}", env=identity())
    return Verified(branch, made.strip(), title, f"{facts}\n\n{CLOSING.format(base[:10])}")


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


def changed(repo: Path, base: str, tip: str, named: set[str]) -> list[tuple[str, str, str]]:
    """The edits `tip` makes to `base` as (mode, blob, path), if each is the edit of a regular file
    that exists, of a kind obelize writes, that the trial names; else `RefusedError`. An upgrade
    edits files in place (every change it makes carries the bytes the file had), so an added file
    is never one."""
    raw = git(repo, "diff-tree", "-r", "-z", "--raw", "--no-renames", "--no-abbrev", base, tip)
    fields = raw.split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    if len(fields) % 2:
        raise RefusedError("git printed a change this action cannot read")
    found = []
    for meta, path in zip(fields[::2], fields[1::2], strict=True):
        before, after, _, blob, status = meta.removeprefix(":").split(" ")
        place(path)
        if status != "M":
            raise RefusedError(
                f"{path!r}: a change of kind {status}; an upgrade edits files that exist"
            )
        if before != after or after not in {"100644", "100755"}:
            raise RefusedError(
                f"{path!r}: mode {before} to {after}; a link, a submodule and a change of mode "
                f"are refused"
            )
        if path not in named:
            raise RefusedError(f"{path!r}: the trial does not name it")
        if int(git(repo, "cat-file", "-s", blob).strip()) > MAX_BLOB:
            raise RefusedError(f"{path!r}: more than {MAX_BLOB} bytes")
        found.append((after, blob, path))
    if not 0 < len(found) <= MAX_FILES:
        raise RefusedError(
            f"the commit changes {len(found)} files; it must change 1 to {MAX_FILES}"
        )
    return found


def rebuilt(repo: Path, base: str, edits: list[tuple[str, str, str]]) -> str:
    """The tree of `base` with `edits` and nothing else, written here: the bundle's own tree is not
    pushed, because a mode such as 100664 reads as 100644 to a diff and stays in the object."""
    with tempfile.TemporaryDirectory(prefix="obelize-index-") as scratch:
        env = {"GIT_INDEX_FILE": str(Path(scratch) / "index")}
        git(repo, "read-tree", base, env=env)
        listing = "".join(f"{mode} {blob}\t{path}\0" for mode, blob, path in edits)
        git(repo, "update-index", "-z", "--index-info", env=env, data=listing.encode())
        return git(repo, "write-tree", env=env).strip()


def place(path: str) -> None:
    """A path obelize writes: a Python source or a manifest, in the repository and outside what git
    or GitHub reads as configuration (`.git*`, `.github`, in whatever case a file system folds
    them), that UTF-8 holds, with no character that could end a line, hide another or name a file
    some other way on a system that folds names (a control or format character, a separator, a
    colon, a name NFKC changes, a short name such as `GITHUB~1`)."""
    try:
        path.encode("utf-8")
    except UnicodeEncodeError:
        raise RefusedError(f"{path!r}: not a path this action publishes") from None
    parts = path.split("/")
    if (
        "\\" in path
        or "`" in path
        or ":" in path
        or any(unicodedata.category(one) in {"Cc", "Cf", "Zl", "Zp"} for one in path)
        or unicodedata.normalize("NFKC", path) != path
        or any(
            part in {"", ".", ".."}
            or part.casefold().startswith((".git", ".obelize"))
            or SHORT.fullmatch(part)
            for part in parts
        )
    ):
        raise RefusedError(f"{path!r}: not a path this action publishes")
    leaf = parts[-1]
    if not (
        leaf.endswith((".py", ".pyi"))
        or leaf in MANIFESTS
        or (leaf.endswith(".txt") and ("requirement" in leaf or parts[-2:-1] == ["requirements"]))
    ):
        raise RefusedError(f"{path!r}: obelize writes no file of this kind")


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
    unmoved: tuple[str, ...] = (),
) -> str:
    """What the commit and the pull request say of the move, made here from values that passed a
    shape: nothing of the artifact's own prose reaches either. The counts are the first job's
    claim, and are said to be. `unmoved` are the files the move did not write, so that a move of
    some files does not read as all of it."""
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
    apart = (
        "\n\nLeft as they were, for you to change: "
        + ", ".join(f"`{one}`" for one in unmoved[:LISTED])
        + (f", and {len(unmoved) - LISTED} more" if len(unmoved) > LISTED else "")
        + ". A place in each is left for you, so this move is partial: the tests that passed "
        "before still pass, which does not show that the rest has moved."
        if unmoved
        else ""
    )
    return (
        f"The job that ran the tests reports that, in a copy of this repository, {compared} "
        f"test(s) passed before the move of `{name}` from {old} to {new} and that after it "
        f"{broke} broke and {flaky} failed once and passed again. These counts are that job's "
        f"claim: no test was run or checked by the job that pushed this.\n\n"
        f"The move changes {len(paths)} file(s):\n\n{shown}{more}{unwritten}{apart}"
    )


CLOSING = (
    "This pull request was opened by a second job that ran none of the repository's code. It "
    "checked that the branch is `{}` and edits to files that exist, each a Python source or a "
    "manifest, none a workflow, a link or an executable, and made the commit itself. It did not "
    "check what the edits do: read the diff, and read any file that runs later, such as a "
    "`setup.py` or a `conftest.py`, with particular care."
)


def publish(
    artifacts: Path,
    repo: Path,
    base: str,
    base_branch: str,
    names: list[str],
    remote: str = "origin",
) -> int:
    """Verify each folder of the artifact that a dependency in `names` asked for, push the branch of
    each that passes and open its pull request. A folder that fails is said, and the others go on.
    `names` is what the workflow asked for, read from the workflow and not from the artifact."""
    if not SHA.fullmatch(base):
        return fail(f"base takes a commit, got '{base}'")
    if not git(repo, "check-ref-format", "--branch", base_branch, check=False):
        return fail(f"base-branch takes a branch name, got '{base_branch}'")
    folders = sorted(one for one in artifacts.iterdir() if one.is_dir() and not one.is_symlink())
    if len(folders) > MAX_DISTRIBUTIONS:
        return fail(
            f"the artifact holds {len(folders)} folders; at most {MAX_DISTRIBUTIONS} are asked for"
        )
    if not folders:
        print("::notice::the artifact holds no upgrade")
        return 0
    asked = {canonical(one) for one in names}
    failed = 0
    for folder in folders:
        try:
            if folder.name not in asked:
                raise RefusedError("not a dependency this workflow asked for")
            opened(verified(folder, repo, base), repo, base_branch, remote)
        except RefusedError as error:
            print(f"::error::{shown(f'{folder.name}: {error}')}")
            failed += 1
        except Exception as error:  # one folder's crash must not stop the next
            print(f"::error::{shown(folder.name)}: {type(error).__name__}; nothing more was done")
            failed += 1
        finally:
            git(repo, "update-ref", "-d", f"refs/obelize-verify/{folder.name}", check=False)
    return 1 if failed else 0


def opened(result: Verified, repo: Path, base_branch: str, remote: str) -> None:
    with tempfile.TemporaryDirectory(prefix="obelize-pr-") as scratch:
        # Before the push: a body that cannot be written leaves no branch without a pull request.
        body = Path(scratch) / "body.md"
        body.write_text(result.body, encoding="utf-8")
        if git(repo, "ls-remote", "--heads", remote, f"refs/heads/{result.branch}").strip():
            print(f"::notice::{result.branch} exists on {remote} already, so it was not touched")
            return
        git(repo, "push", "--no-verify", remote, f"{result.tip}:refs/heads/{result.branch}")
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
    one.add_argument("--distributions", required=True)
    given = parser.parse_args(argv)
    if given.command == "run":
        return run(dict(os.environ))
    if given.command == "gate":
        return gate(dict(os.environ))
    try:
        names, _ = named(given.distributions)
    except RefusedError as error:
        return fail(str(error))
    return publish(given.artifacts, given.repo, given.base, given.base_branch, names)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""Command-line entry point.

Startup budget: `obelize --help` must stay well under 300 ms, so only typer is imported at module
scope; heavy imports (libcst, pydantic models, packs) go inside the command body that needs them.
"""

from __future__ import annotations

import contextlib
import os
import re
import sys
import time
import warnings
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from obelize import __version__

if TYPE_CHECKING:
    from collections.abc import Callable, Collection

    from packaging.version import Version

    from obelize.config import LoadedConfig, Overrides
    from obelize.models import Config, ConfigOrigin, ExitCode, ModelConfig, ScanSpec
    from obelize.net import Fetcher
    from obelize.outdated import Dependency
    from obelize.packs.loader import LoadedPack
    from obelize.packs.schema import PackDocument
    from obelize.resolve import Resolved
    from obelize.scan.runner import Scan, Tree
    from obelize.transforms.kinds.flag_only import Guide
    from obelize.trial.run import Trial
    from obelize.upgrade import Chosen
    from obelize.verify.runner import Mode

# The finding statuses `scan --fail-on` can name: the ones that leave something to do.
FAIL_ON = frozenset({"eligible", "needs_review", "unsupported"})

# A bundled pack failing validation exits 1, not 7: the input was obelize's own.
# `fix --apply` writing a change that no verification command judged.
_NO_VERDICT = 6
_CONSENT = (
    "A trial installs the dependencies of this repository and the two releases with uv, which runs "
    "the build scripts of what it installs, and runs the repository's tests, in a copy outside it."
)
# What each verdict a trial cannot judge asks of the person.
_UNJUDGED = {
    "no_tests": "No tests were found. Pass --test-command, or write the migration without a "
    "trial: obelize fix --apply.",
    "no_junit": "The tests produced no result obelize can read, so nothing was compared.",
    "timeout": "The tests did not finish in time, so nothing was compared. Raise --timeout, or "
    "name the part that runs on its own with --test-command.",
    "nothing_to_compare": "No test passed before the migration, or it changed no file, so "
    "nothing was compared.",
    "unresolved": "Places the pack flags are left, and the library has one release for both "
    "APIs, so the rules write nothing until each has moved. See the trial's evidence.",
    "tests_broke": "",
}
_BUNDLED_DEFECT = (
    "This pack ships with obelize, so this is a bug in obelize. "
    "Please report it at https://github.com/hakanbogan/obelize/issues."
)

app = typer.Typer(
    name="obelize",
    help="Verified codemods for breaking Python dependency upgrades. "
    "Supported migrations: google-generativeai to google-genai, numpy 1.x to 2.x, "
    "openai 0.x to 1.x, PyPDF2 to pypdf, and in the Python itself datetime.utcnow(), "
    "pkg_resources and the modules Python 3.12 and 3.13 removed.",
    no_args_is_help=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"obelize {__version__}")
        raise typer.Exit(0)


def colour_is_disabled(argv: Sequence[str], env: Mapping[str, str]) -> bool:
    """Decide whether to strip colour, before anything has been rendered.

    Only leading options count: a `--no-color` inside `--verify` is another tool's. Any non-empty
    `NO_COLOR` disables it, even `0`, per https://no-color.org (typer's `envvar=` reads `0` as on).
    """
    for argument in argv:
        if not argument.startswith("-"):
            break
        if argument == "--no-color":
            return True
    return bool(env.get("NO_COLOR"))


def disable_colour() -> None:
    """Turn off the colour in typer's own help and error rendering.

    typer's console ignores `NO_COLOR` and eager `--help` exits before any callback runs, so this
    must precede `app()`. The import stays lazy for the startup budget.
    """
    from typer import rich_utils

    rich_utils.COLOR_SYSTEM = None


@app.command("scan")
def scan(
    repo: str = typer.Option(
        ".",
        "--repo",
        metavar="<path>",
        help="Repository root to scan. Defaults to the current directory.",
    ),
    pack: list[str] | None = typer.Option(
        None,
        "--pack",
        metavar="<id|path>",
        help="A pack id, or a path to a pack file. Repeat it to run several. Without it, every "
        "known pack whose library the repository uses runs.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Print the findings as JSON instead of the table. "
        "Two runs on the same input print the same bytes.",
    ),
    jobs: int | None = typer.Option(
        None,
        "--jobs",
        metavar="N",
        help="Number of worker processes. The default is one fewer than the CPU "
        "count, at most 8, with a small repository scanned in-process; a number you "
        "give is always used, at most 61 on Windows. The number does not change the output.",
    ),
    list_files: bool = typer.Option(
        False,
        "--list-files",
        help="Print the files selected for the scan, in order, and stop.",
    ),
    sarif: bool = typer.Option(
        False,
        "--sarif",
        help="Print the findings as SARIF 2.1.0, which GitHub code scanning reads, instead of "
        "the table. Two runs on the same input print the same bytes.",
    ),
    fail_on: list[str] | None = typer.Option(
        None,
        "--fail-on",
        metavar="<status>",
        help="Exit 4 when a finding has this status: eligible, needs_review or unsupported. "
        "Repeat it to name several.",
    ),
    library: str | None = typer.Option(
        None,
        "--library",
        metavar="<distribution>",
        help="List every place the repository uses this library, with no pack. Nothing can be "
        "rewritten. Its modules are the ones it installed in a .venv, venv or env directory in "
        "the repository, else those --module names, else its name.",
    ),
    modules: list[str] | None = typer.Option(
        None,
        "--module",
        metavar="<module>",
        help="A module of --library to list, as it is imported. Repeat it to name several.",
    ),
) -> None:
    """Find the call sites, imports and manifest entries a pack affects.

    Edits no source file. Evidence goes to .obelize/runs/<id>/, which every
    scan excludes.
    """
    from obelize import gitutil
    from obelize.commands import CommandError
    from obelize.commands import fix as fixer
    from obelize.config import ConfigError, with_fixture_dirs
    from obelize.evidence import report, run_dir
    from obelize.evidence.sarif import document as sarif_document
    from obelize.models import FindingsDocument, PackRef
    from obelize.scan import runner, walker
    from obelize.transforms.kinds import flag_only

    root = Path(repo)
    if as_json and sarif:
        typer.echo("--json and --sarif each replace the table; pass one.", err=True)
        raise typer.Exit(2)
    failing = _fail_on(fail_on)
    _library_flags(library, modules, pack)
    packs, named = ([], False) if library else _packs_or_exit(pack)
    started = run_dir.now()
    began = time.monotonic()
    try:
        # Before anything is read, so `--jobs 0` is refused before the repository is hashed.
        runner.worker_count(jobs)
        configuration = _configuration(root)
        if list_files:
            own = [one.path for one in packs if not one.bundled]
            scanned = with_fixture_dirs(configuration.config, root, own)
            for path in walker.walk(root, scanned).files:
                typer.echo(path)
            return
        if library:
            listing = _listing(root, configuration.config, library, modules or [], jobs)
        else:
            chosen = fixer.select(root, configuration.config, packs, named=named, jobs=jobs)
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    except CommandError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(error.code) from error
    loaded: list[LoadedPack]
    documents: list[PackDocument]
    guides: tuple[Guide, ...]
    fixtures: tuple[str, ...]
    tried: tuple[str, ...]
    refs: tuple[PackRef, ...]
    if library:
        spec, result = listing
        loaded, documents, guides, fixtures, tried = [], [], (), (), ()
        used = [run_dir.Used.inventory(spec)]
        refs = (PackRef(id=spec.pack_id, version=spec.pack_version, sha256=spec.pack_sha256),)
    else:
        result = runner.counted(
            runner.merged([one.scan for one in chosen.packs], chosen.tree), chosen.parsed
        )
        loaded = [one.loaded for one in chosen.packs]
        documents = [one.pack for one in loaded]
        guides = tuple(
            guide
            for one in chosen.packs
            for guide in flag_only.guides(one.loaded.pack, one.scan.findings)
        )
        fixtures, tried = chosen.fixture_dirs, chosen.tried
        used = [run_dir.Used.of(one.loaded, one.scan) for one in chosen.packs]
        refs = run_dir.refs(loaded)
    scan_ms = int((time.monotonic() - began) * 1000)
    held = sum(1 for row in result.findings if row.scan_status in failing)
    code: ExitCode = 4 if held else 0

    document = FindingsDocument(
        obelize_version=__version__,
        packs=refs,
        counts=result.counts,
        findings=result.findings,
    )
    findings = document.model_dump_json(indent=2) + "\n"
    record = run_dir.compose(
        run_id=run_dir.new_id(started),
        scan=result,
        packs=used,
        config=configuration.config,
        source=configuration.source,
        git=gitutil.state(root),
        argv=_recorded_argv(),
        started=started,
        finished=run_dir.now(),
        total_ms=int((time.monotonic() - began) * 1000),
        scan_ms=scan_ms,
        exit_code=code,
    )
    try:
        written = run_dir.write(
            root,
            record,
            findings,
            loaded,
            report.document(record, result, guides=guides, packs=documents, fixture_dirs=fixtures),
        )
    except run_dir.EvidenceError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error

    evidence = _under(repo, written.relative)
    if as_json or sarif:
        _document(findings if as_json else sarif_document(result.findings, document.packs))
        # On stderr, so stdout stays the document; `obelize verify --run <id>` needs the id.
        typer.echo(f"Evidence: {evidence}", err=True)
    else:
        label = ", ".join(f"{one.pack.id} {one.pack.pack_version}" for one in loaded)
        label = label or (refs[0].id if library else "no pack applies")
        fix_flags = report.flags(repo, pack or ())
        for line in report.terminal(
            result, label, evidence, guides, fix_flags, inventory=bool(library)
        ):
            typer.echo(line)
        if not loaded and not library:
            typer.echo(f"No pack applies. Checked: {', '.join(tried) or 'none'}.")
            for line in _popular(chosen.tree, report.flags(repo)):
                typer.echo(line)
    if held:
        typer.echo(f"--fail-on: {held} finding(s) have a status you named.", err=True)
        raise typer.Exit(code)


@app.command("fix")
def fix(
    pack: list[str] | None = typer.Option(
        None,
        "--pack",
        metavar="<id|path>",
        help="A pack id, or a path to a pack file. Repeat it to run several. Without it, every "
        "known pack whose library the repository uses runs.",
    ),
    repo: str = typer.Option(
        ".",
        "--repo",
        metavar="<path>",
        help="Repository root. Defaults to the current directory.",
    ),
    apply_changes: bool = typer.Option(
        False,
        "--apply",
        help="Write the planned edits. Without it nothing in the repository is touched.",
    ),
    allow_dirty: bool = typer.Option(
        False,
        "--allow-dirty",
        help="Allow --apply when a tracked file has uncommitted changes or a file it "
        "would edit is not tracked by git.",
    ),
    verify_commands: list[str] | None = typer.Option(
        None,
        "--verify",
        metavar='"<cmd>"',
        help="A verification command to run, such as your tests. Runs only with --apply. "
        "Repeatable. Replaces the commands in .obelize.yml, and runs without asking.",
    ),
    timeout: int | None = typer.Option(
        None,
        "--timeout",
        metavar="<s>",
        min=1,
        help="Per-command timeout in seconds, overriding verify.timeout_s (default 600).",
    ),
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        help="Never prompt. A command that would need your approval is refused instead.",
    ),
    trust_repo_config: bool = typer.Option(
        False,
        "--trust-repo-config",
        help="Trust the verify.commands in this repository's .obelize.yml for this run.",
    ),
    provider: str | None = typer.Option(
        None,
        "--model",
        metavar="<provider>",
        help="Model provider to ask about call sites the rules could not migrate: "
        "none or openai_compat. Overrides model.provider.",
    ),
    accept_model: bool = typer.Option(
        False,
        "--accept-model",
        help="Also write the model's edits that passed validation. Requires --apply.",
    ),
    show_context: bool = typer.Option(
        False,
        "--show-context",
        help="Print what would be sent to a model and stop. Nothing is sent.",
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Print the plan as JSON instead of the summary."
    ),
) -> None:
    """Build a migration plan from a pack and, with --apply, write it.

    Dry run by default: the change is printed and saved as patch.diff in the run
    folder. --apply needs a clean tree and runs, in order: your tests, the
    write, a compile check, your tests again. If your tests fail before the
    write, the change is still written and neither the compile check nor the
    tests run again. Without a test command, only the write happens.
    """
    _fix(
        pack,
        repo,
        apply_changes,
        allow_dirty,
        verify_commands,
        timeout,
        non_interactive,
        trust_repo_config,
        provider,
        accept_model,
        show_context,
        as_json,
    )


def _fix(
    pack: list[str] | None,
    repo: str,
    apply_changes: bool,
    allow_dirty: bool,
    verify_commands: list[str] | None,
    timeout: int | None,
    non_interactive: bool,
    trust_repo_config: bool,
    provider: str | None,
    accept_model: bool,
    show_context: bool,
    as_json: bool,
    stated: tuple[str, str] | None = None,
) -> None:
    """`fix`, to which `upgrade` adds the release it was told the code is written for."""
    from obelize.commands import CommandError
    from obelize.commands import fix as fixer
    from obelize.config import ConfigError
    from obelize.evidence import report
    from obelize.providers import proposals

    _model_flags(apply_changes, accept_model=accept_model, show_context=show_context)
    root = Path(repo)
    packs, named = _packs_or_exit(pack)
    try:
        config, source = _settings(root, _overrides(verify_commands, timeout, allow_dirty))
        model = _model(provider)
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    request = fixer.Request(
        root=root,
        packs=packs,
        named=named,
        config=config,
        source=source,
        cli_commands=tuple(verify_commands or ()),
        mode=_trust(non_interactive=non_interactive, trust_repo_config=trust_repo_config),
        config_dir=_config_dir(),
        environ=os.environ,
        argv=_recorded_argv(),
        apply=apply_changes,
        accept_model=accept_model,
        ask=_ask,
        say=_say,
        model=model,
        model_flagged=provider is not None or accept_model,
        stated=stated,
    )
    if show_context:
        try:
            lines = fixer.context(request)
        except CommandError as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(error.code) from error
        for line in lines:
            typer.echo(line)
        raise typer.Exit(0)
    if model.provider != "none":
        # Announced before the scan, on stderr so `--json` stdout stays one document.
        typer.echo(proposals.heading(model), err=True)
    try:
        outcome = fixer.run(request)
    except CommandError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(error.code) from error
    evidence = _under(repo, outcome.evidence)
    for note in outcome.notes:
        typer.echo(note, err=True)
    used = ", ".join(f"{one.id} {one.pack_version}" for one in outcome.record.packs)
    _emit(
        outcome.document if as_json else None,
        evidence,
        lambda: report.fixed(
            outcome.record,
            outcome.plan,
            used or "no pack applies",
            evidence,
            outcome.blocked,
            outcome.assumed,
            outcome.patch,
            os.environ,
            repo,
            pack or (),
            outcome.manifest_plan,
            outcome.guides,
            outcome.locks,
            outcome.unwritten,
            outcome.pins,
            stated=outcome.stated,
            imports=outcome.imports,
            runs=outcome.runs,
        ),
    )
    raise typer.Exit(outcome.exit_code)


@app.command("verify")
def verify(
    run_id: str = typer.Option(
        ..., "--run", metavar="<id>", help="The run id under .obelize/runs/. Required."
    ),
    repo: str = typer.Option(
        ".",
        "--repo",
        metavar="<path>",
        help="Repository root. Defaults to the current directory.",
    ),
    verify_commands: list[str] | None = typer.Option(
        None,
        "--verify",
        metavar='"<cmd>"',
        help="A verification command to run. Repeatable. Replaces the ones the "
        "repository configures.",
    ),
    timeout: int | None = typer.Option(
        None,
        "--timeout",
        metavar="<s>",
        min=1,
        help="Per-command timeout in seconds, overriding verify.timeout_s (default 600).",
    ),
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        help="Never prompt. A command that would need your approval is refused instead.",
    ),
    trust_repo_config: bool = typer.Option(
        False,
        "--trust-repo-config",
        help="Trust the verify.commands in this repository's .obelize.yml for this run.",
    ),
    current: bool = typer.Option(
        False,
        "--current",
        help="Check the tree as it stands, even where it differs from what the run wrote, and "
        "record which files differ. Without it such a run is inconclusive.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Print the run's record as JSON, the bytes of its run.json, instead of the summary.",
    ),
) -> None:
    """Re-run the verification phase for an existing run and update its evidence.

    If a file the run wrote has changed since, the result is inconclusive
    (tree_changed) and nothing runs. Commands come from your configuration,
    never the run folder, so the trust flags apply again.
    """
    from obelize.commands import CommandError
    from obelize.commands import verify as verifier
    from obelize.config import ConfigError
    from obelize.evidence import report

    root = Path(repo)
    try:
        config, _ = _settings(root, _overrides(verify_commands, timeout, allow_dirty=False))
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    try:
        outcome = verifier.run(
            verifier.Request(
                root=root,
                run_id=run_id,
                config=config,
                cli_commands=tuple(verify_commands or ()),
                mode=_trust(non_interactive=non_interactive, trust_repo_config=trust_repo_config),
                config_dir=_config_dir(),
                environ=os.environ,
                ask=_ask,
                say=_say,
                current=current,
            )
        )
    except CommandError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(error.code) from error
    except ConfigError as error:
        # The user's allowlist, read only when the repository asks for a command.
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    evidence = _under(repo, outcome.evidence)
    if as_json:
        _document(outcome.record.model_dump_json(indent=2) + "\n")
        typer.echo(f"Evidence: {evidence}", err=True)
        raise typer.Exit(outcome.exit_code)
    for line in report.verified(outcome.record, evidence):
        typer.echo(line)
    if not outcome.rewritten:
        typer.echo("Nothing was re-run, so nothing in the folder changed.")
    raise typer.Exit(outcome.exit_code)


@app.command("undo")
def undo(
    run_id: str = typer.Option(
        ..., "--run", metavar="<id>", help="The run id under .obelize/runs/. Required."
    ),
    repo: str = typer.Option(
        ".",
        "--repo",
        metavar="<path>",
        help="Repository root. Defaults to the current directory.",
    ),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Print what became of each file as JSON, the bytes of undo.json, instead of the "
        "summary.",
    ),
) -> None:
    """Revert the files an applied run wrote, checked against its own hashes.

    A file edited since is skipped and reported with both hashes and its
    snapshots/before/ copy. Obelize never overwrites content it did not
    write, so there is no --force.
    """
    from obelize.commands import CommandError
    from obelize.commands import undo as reverter
    from obelize.evidence import report

    root = Path(repo)
    # No `.obelize.yml`: putting files back must not depend on a file the user may be mending.
    if not root.is_dir():
        typer.echo(f"--repo {root} is not a directory", err=True)
        raise typer.Exit(2)
    try:
        outcome = reverter.run(reverter.Request(root=root, run_id=run_id, argv=_recorded_argv()))
    except CommandError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(error.code) from error
    if as_json:
        _document(outcome.record.model_dump_json(indent=2) + "\n")
        typer.echo(f"Evidence: {_under(repo, outcome.evidence)}", err=True)
        raise typer.Exit(outcome.exit_code)
    for line in report.reverted(
        outcome.record, _under(repo, outcome.folder), _under(repo, outcome.evidence)
    ):
        typer.echo(line)
    raise typer.Exit(outcome.exit_code)


def _fail_on(named: list[str] | None) -> frozenset[str]:
    """The statuses `--fail-on` names, or a usage error before anything is read."""
    wanted = frozenset(named or ())
    unknown = sorted(wanted - FAIL_ON)
    if unknown:
        typer.echo(
            f"--fail-on takes {', '.join(sorted(FAIL_ON))}; got {', '.join(unknown)}.", err=True
        )
        raise typer.Exit(2)
    return wanted


def _library_flags(library: str | None, modules: list[str] | None, pack: list[str] | None) -> None:
    """`--library` and `--module` as a pair, and never beside a pack, before anything is read."""
    if library is None:
        if modules:
            typer.echo("--module names a module of --library; pass --library too.", err=True)
            raise typer.Exit(2)
        return
    if pack:
        typer.echo(
            "--library lists a library that has no pack and --pack names one; pass one of them.",
            err=True,
        )
        raise typer.Exit(2)


def _popular(tree: Tree, where: str) -> list[str]:
    """What to try when no pack applies: the libraries the repository imports most."""
    from obelize.scan import inventory

    popular = inventory.imported(tree)
    if not popular:
        return []
    named = ", ".join(f"{name} ({count} file{'s' * (count != 1)})" for name, count in popular)
    first = popular[0][0]
    return [
        f"The repository imports these most: {named}.",
        f"Next: obelize scan --library {first} --module {first}{where} lists every place it uses "
        f"one.",
    ]


def _listing(
    root: Path, config: Config, library: str, modules: list[str], jobs: int | None
) -> tuple[ScanSpec, Scan]:
    """The inventory of `library` over one read of the repository: the spec and its scan."""
    from obelize.config import ConfigError
    from obelize.models import QUALIFIED_NAME
    from obelize.scan import inventory, runner

    bad = [name for name in modules if not QUALIFIED_NAME.fullmatch(name)]
    if bad:
        raise ConfigError(f"--module takes dotted module names, got {', '.join(bad)}.")
    found = () if modules else inventory.modules(root, library)
    chosen = tuple(modules) or found or (library.replace("-", "_").replace(".", "_"),)
    where = (
        "named with --module"
        if modules
        else "installed in an environment in the repository"
        if found
        else "taken from its name; pass --module if it is imported under another"
    )
    try:
        spec = inventory.spec(library, chosen)
    except ValueError as error:
        raise ConfigError(f"--library takes a distribution name, got {library!r}.") from error
    typer.echo(f"Listing the uses of {library}: {', '.join(chosen)} ({where}).", err=True)
    tree = runner.read(root, config, [spec])
    return spec, runner.scan(root, config, spec, jobs=jobs, tree=tree)


def _recorded_argv() -> tuple[str, ...]:
    """The command line as `run.json` keeps it: a `--verify` command can carry a credential."""
    from obelize.verify import redact

    return tuple(redact.redact(argument, os.environ) for argument in sys.argv[1:])


def _under(repo: str, relative: str) -> str:
    """A repository-relative path under `--repo` as typed, so it opens from where the user is."""
    return str(Path(repo) / relative)


def _document(text: str) -> None:
    """A `--json` document, as the UTF-8 bytes the run folder holds.

    Bytes skip the text layer, which on Windows encodes in the ANSI code page and ends each line
    with CRLF; click flushes that layer first.
    """
    typer.echo(text.encode("utf-8"), nl=False)


def _emit(document: str | None, evidence: str, lines: Callable[[], list[str]]) -> None:
    """The `--json` document (evidence path on stderr), or the summary."""
    if document is not None:
        _document(document)
        typer.echo(f"Evidence: {evidence}", err=True)
        return
    for line in lines():
        typer.echo(line)


def _overrides(commands: list[str] | None, timeout: int | None, allow_dirty: bool) -> Overrides:
    from obelize import config as configuration

    return configuration.flags(commands or (), timeout, allow_dirty=allow_dirty)


def _model(provider: str | None) -> ModelConfig:
    """The user's own `model:` block with `--model` over it."""
    from obelize import config as configuration
    from obelize.verify.runner import ALLOWLIST_FILENAME, user_config

    home = _config_dir()
    return configuration.model(user_config(home).model, provider, home / ALLOWLIST_FILENAME)


def _model_flags(apply_changes: bool, *, accept_model: bool, show_context: bool) -> None:
    """Refuse contradictory model flags before any pack load or scan."""
    if accept_model and not apply_changes:
        typer.echo(
            "--accept-model requires --apply. Leave it out to see the model's proposals "
            "without writing them.",
            err=True,
        )
        raise typer.Exit(2)
    if show_context and apply_changes:
        typer.echo(
            "--show-context cannot be combined with --apply: it only prints what would be sent.",
            err=True,
        )
        raise typer.Exit(2)


def _settings(root: Path, overrides: Overrides) -> tuple[Config, ConfigOrigin]:
    """`.obelize.yml` with the command line over it, and where the file was."""
    from obelize import config as configuration

    loaded = _configuration(root)
    return configuration.merge(loaded.config, overrides), loaded.source


def _trust(*, non_interactive: bool, trust_repo_config: bool) -> Mode:
    """This invocation as the trust ladder sees it; the only place the terminal is asked."""
    from obelize.verify.runner import Mode

    return Mode.of(
        os.environ,
        non_interactive=non_interactive,
        trust_repo_config=trust_repo_config,
        tty=sys.stdin.isatty(),
    )


def _config_dir() -> Path:
    """`~/.config/obelize`, or wherever `XDG_CONFIG_HOME` puts it."""
    from obelize.verify.runner import config_home

    return config_home(os.environ)


def _ask(command: str) -> bool:
    """Ask once whether a repository's command may run; a yes is remembered for that command."""
    typer.echo(f"This repository asks to run: {command}")
    return typer.confirm("Run it, and remember the answer for this repository?", default=False)


def _say(text: str) -> None:
    """Progress goes to stderr, so a `--json` document stays the whole of stdout."""
    typer.echo(text, err=True)


def _configuration(root: Path) -> LoadedConfig:
    """`.obelize.yml` under `root`; a non-directory root is reported against `--repo`."""
    from obelize import config as configuration
    from obelize.config import ConfigError

    if not root.is_dir():
        raise ConfigError(f"--repo {root} is not a directory, so there is nothing to scan")
    return configuration.load(root)


def _pack_dirs() -> tuple[Path, ...]:
    """The directories the user's own config adds to the wheel's packs; never a repository's."""
    from obelize.verify.runner import user_config

    return tuple(Path(entry) for entry in user_config(_config_dir()).pack_dirs)


def _activate_plugins(packs: Sequence[LoadedPack], *, named: bool = True) -> tuple[LoadedPack, ...]:
    """Load the plugins the packs require, or exit 7 saying why one cannot run: one the user has
    not allowed, one missing, the wrong release, or one that does not load.

    For packs the user named, that stops the run. For every known pack (none was named) a pack
    whose plugin cannot run is left out and said so, since it is not what the person asked for.
    """
    from obelize.transforms import plugins
    from obelize.verify.runner import user_config

    permits = [
        plugins.Permit(one.distribution, one.name) for one in user_config(_config_dir()).plugins
    ]
    try:
        done = plugins.activate((one.pack for one in packs), permits, skip=not named)
    except plugins.PluginError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(7) from error
    left = dict(done.skipped)
    for name, why in done.skipped:
        typer.echo(f"{name} was left out: {why}", err=True)
    return tuple(one for one in packs if one.pack.id not in left)


def _packs_or_exit(references: list[str] | None) -> tuple[tuple[LoadedPack, ...], bool]:
    """The packs a run tries, and whether the user named them; exit 2 / 7 / 1 as `pack validate`.

    Unnamed, that is every known pack, so a run is not tied to one library.
    """
    from obelize.config import ConfigError
    from obelize.packs import loader

    try:
        dirs = _pack_dirs()
        loaded = tuple(
            loader.load(reference, dirs=dirs) for reference in references or loader.known(dirs)
        )
        ids = [one.pack.id for one in loaded]
        repeated = next((name for name in ids if ids.count(name) > 1), None)
        if repeated is not None:
            raise loader.PackConflictError(f"--pack names {repeated} more than once")
    except (loader.PackNotFoundError, loader.PackConflictError, ConfigError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    except loader.PackInvalidError as error:
        typer.echo(str(error), err=True)
        if error.bundled:
            typer.echo(_BUNDLED_DEFECT, err=True)
            raise typer.Exit(1) from error
        raise typer.Exit(7) from error
    return _activate_plugins(loaded, named=bool(references)), bool(references)


pack_app = typer.Typer(
    name="pack",
    help="Inspect migration packs.",
    no_args_is_help=True,
)
app.add_typer(pack_app)


@pack_app.command("validate")
def pack_validate(
    reference: str = typer.Argument(
        ...,
        metavar="<id|path>",
        help="A bundled pack id, or a path to a pack file.",
    ),
) -> None:
    """Validate a migration pack against the pack format.

    Errors name the path of each invalid key. Exit codes: 2 pack not found,
    7 pack invalid, 1 bundled pack invalid (a bug in obelize).

    The format is described at https://github.com/hakanbogan/obelize/blob/main/docs/PACK_SPEC.md
    """
    from obelize.config import ConfigError
    from obelize.packs import loader
    from obelize.transforms import fixers

    try:
        loaded = loader.load(reference, dirs=_pack_dirs())
    except (loader.PackNotFoundError, ConfigError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    except loader.PackInvalidError as error:
        typer.echo(str(error), err=True)
        if error.bundled:
            typer.echo(_BUNDLED_DEFECT, err=True)
            raise typer.Exit(1) from error
        raise typer.Exit(7) from error

    pack = loaded.pack
    typer.echo(f"{pack.id} {pack.pack_version} is a valid migration pack.")
    typer.echo(f"  sha256       {loaded.sha256}")
    typer.echo(f"  migrates     {pack.from_.label()} -> {pack.to.label()}")
    if pack.pattern_imports():
        typer.echo(f"  imports      {', '.join(pack.to_modules())}")
    typer.echo(f"  changes      {len(pack.changes)}")
    typer.echo(f"  limitations  {len(pack.limitations)}")
    for change in pack.fixers():
        spec = fixers.FIXERS[change.params.fixer]
        typer.echo(f"  fixer        {change.params.fixer} runs {spec.tool} {' '.join(spec.argv)}")
        typer.echo(
            f"               accepts {spec.tool} {spec.releases}; obelize installs nothing: "
            f"uv tool install {spec.install}"
        )
    if pack.requires_plugins:
        names = ", ".join(one.name for one in pack.requires_plugins)
        typer.echo(
            f"  plugins      {names} (not loaded by this command, so their params are not read)"
        )
    # A local pack may ship without fixtures; tests/packs/ checks the bundled ones.
    typer.echo("  fixtures     not checked by this command; obelize pack test runs them")


@pack_app.command("test")
def pack_test(
    reference: str = typer.Argument(
        ...,
        metavar="<id|path>",
        help="A pack id, a path to a pack file, or the folder that holds it.",
    ),
) -> None:
    """Check a migration pack against the fixtures and sources beside it.

    Runs the pack over its own fixtures: each is on disk, each answer key is what the
    rules write, a second run changes nothing, and every change cites a source. Exit
    codes: 0 every check passed, 7 one failed, 2 pack not found, 1 a bundled pack
    failed (a bug in obelize).
    """
    from obelize.config import ConfigError
    from obelize.packs import loader
    from obelize.packtools import check

    where = Path(reference)
    named = str(where / loader.PACK_FILENAME) if where.is_dir() else reference
    try:
        loaded = loader.load(named, dirs=_pack_dirs())
    except (loader.PackNotFoundError, ConfigError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    except loader.PackInvalidError as error:
        typer.echo(str(error), err=True)
        if error.bundled:
            typer.echo(_BUNDLED_DEFECT, err=True)
            raise typer.Exit(1) from error
        raise typer.Exit(7) from error

    typer.echo(f"{loaded.pack.id} {loaded.pack.pack_version}")
    _activate_plugins([loaded])
    results = check.run(loaded)
    for result in results:
        typer.echo(f"  {'ok  ' if result.ok else 'FAIL'}  {result.name}")
        for problem in result.problems:
            typer.echo(f"          - {problem}")
    failed = [result for result in results if not result.ok]
    if not failed:
        typer.echo(f"All {len(results)} checks passed.")
        return
    typer.echo(f"{len(failed)} of {len(results)} checks failed.", err=True)
    if loaded.bundled and not all(result.setup for result in failed):
        typer.echo(_BUNDLED_DEFECT, err=True)
        raise typer.Exit(1)
    raise typer.Exit(7)


@pack_app.command("new")
def pack_new(
    pack_id: str = typer.Argument(
        ...,
        metavar="<id>",
        help="The id of the new pack, <provider>/<name>: lowercase letters, digits and hyphens.",
    ),
    legacy: str = typer.Option(
        ...,
        "--from",
        metavar='"<requirement>"',
        help='The distribution to migrate from and the releases, such as "PyPDF2>=3,<4".',
    ),
    new: str = typer.Option(
        ...,
        "--to",
        metavar='"<requirement>"',
        help='The distribution to migrate to and the releases, such as "pypdf>=6.19".',
    ),
    guide: str = typer.Option(
        ...,
        "--guide",
        metavar="<url>",
        help="The https address of the official guide the migration follows. It is cited and "
        "never requested.",
    ),
    module: str | None = typer.Option(
        None,
        "--module",
        metavar="<module>",
        help="The module code imports from the old distribution. Default: its name.",
    ),
    to_module: str | None = typer.Option(
        None,
        "--to-module",
        metavar="<module>",
        help="The module code imports from the new distribution. Default: its name.",
    ),
    requires_python: str = typer.Option(
        ">=3.9",
        "--requires-python",
        metavar="<range>",
        help="The Pythons the new distribution installs on.",
    ),
    directory: str = typer.Option(
        ".",
        "--dir",
        metavar="<path>",
        help="Where to make the pack's folder, <provider>/<name>. Defaults to the current "
        "directory.",
    ),
) -> None:
    """Make a migration pack that loads, with fixtures and sources to edit.

    The pack renames one module and moves the dependency line, and its fixtures pass
    obelize pack test as made. Exit codes: 0 made, 2 the request is wrong or the
    folder exists.
    """
    from obelize.packtools import scaffold

    try:
        made = scaffold.plan(
            pack_id,
            legacy,
            new,
            guide,
            module=module,
            to_module=to_module,
            requires_python=requires_python,
        )
        files = scaffold.write(Path(directory), made)
    except scaffold.ScaffoldError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    shown = Path(directory) / made.provider / made.slug
    typer.echo(f"Made {made.pack_id} in {shown}:")
    for name in files:
        typer.echo(f"  {name}")
    typer.echo(f"Next: edit pack.yaml and SOURCES.md, then run obelize pack test {shown}")


@app.command("outdated")
def outdated(
    repo: str = typer.Option(
        ".", "--repo", metavar="<path>", help="Repository root. Defaults to the current directory."
    ),
    show_all: bool = typer.Option(
        False, "--all", help="Also list the dependencies that are current."
    ),
    as_json: bool = typer.Option(False, "--json", help="Print the rows as JSON."),
    offline: bool = typer.Option(
        False, "--offline", help="Reach no host: use only what an earlier run kept in the cache."
    ),
) -> None:
    """List the dependencies a repository declares that the package index says have moved on.

    Reads the manifests (nothing is installed), asks the index about each distribution
    and prints the release in use, the newest, the size of the gap, whether the library
    is marked inactive, withdrawn or has an advisory for that release, and what obelize
    can migrate it with: a bundled pack, or two releases to compare with pack synth.
    Exit codes: 0 listed, 2 the request is wrong, 6 the index could not be reached for
    any distribution.
    """
    from urllib.parse import urlsplit

    from obelize import outdated as survey
    from obelize.config import ConfigError
    from obelize.packs import loader

    root = Path(repo)
    try:
        config, _ = _settings(root, _overrides(None, None, False))
        fetcher = _fetcher(offline)
        packs = _known_packs()
    except (ConfigError, loader.PackError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    rows = survey.survey(fetcher, _declared(root, config), packs)
    if survey.unreachable(rows):
        typer.echo("The index could not be reached for any dependency.", err=True)
        raise typer.Exit(6)
    shown = [row for row in rows if show_all or survey.worth_showing(row)]
    if as_json:
        document = survey.Document(index=urlsplit(fetcher.index).hostname or "", rows=tuple(shown))
        _document(document.model_dump_json(indent=2) + "\n")
        return
    if not shown:
        typer.echo(f"{len(rows)} dependencies read, none behind a major release or flagged.")
        return
    for line in survey.table(shown):
        typer.echo(line)
    step = survey.next_step(shown)
    if step:
        typer.echo(f"Next: {step}")


def _interactive() -> bool:
    return sys.stdin.isatty()


def _picked(fetcher: Fetcher, root: Path, config: Config) -> str:
    """The dependency to move when none was named: the one a person picks from those behind that
    obelize can migrate. Where no one can be asked, the list and the command are all there is."""
    from obelize import outdated as survey

    rows = survey.survey(fetcher, _declared(root, config), _known_packs())
    if survey.unreachable(rows):
        typer.echo("The index could not be reached for any dependency.", err=True)
        raise typer.Exit(6)
    movable = [
        row
        for row in rows
        if survey.worth_showing(row)
        and row.error is None
        and row.knowledge in ("bundled", "synthesizable")
    ]
    if not movable:
        typer.echo(f"{len(rows)} dependencies read, none behind a major release that can be moved.")
        raise typer.Exit(0)
    head, *body = survey.table(movable)
    typer.echo(f"   {head}", err=True)
    for number, line in enumerate(body, start=1):
        typer.echo(f"{number:>2} {line}", err=True)
    if not _interactive():
        typer.echo("Name one of them: obelize upgrade <distribution>", err=True)
        raise typer.Exit(2)
    answer = typer.prompt("Which one? A number or a name", default="1", err=True).strip()
    chosen = next(
        (
            row.distribution
            for number, row in enumerate(movable, start=1)
            if answer in (str(number), row.distribution)
        ),
        None,
    )
    if chosen is None:
        typer.echo(f"{answer!r} is none of the {len(movable)} listed.", err=True)
        raise typer.Exit(2)
    return chosen


def _declared(root: Path, config: Config) -> list[Dependency]:
    """The distributions the repository's manifests declare, read without parsing any source."""
    from obelize import outdated as survey
    from obelize.scan import manifests
    from obelize.scan import runner as scanner

    tree = scanner.read(root, config, ())
    followed = dict(tree.walk.followed)
    return survey.dependencies(
        row
        for name in tree.walk.manifests
        for row in manifests.read(name, tree.contents, followed.get(name)).declarations
    )


def _known_packs() -> list[LoadedPack]:
    """Every pack the wheel and the user's own directories hold, loaded."""
    from obelize.packs import loader

    dirs = _pack_dirs()
    return [loader.load(reference, dirs=dirs) for reference in loader.known(dirs)]


@app.command("upgrade")
def upgrade(
    distribution: str | None = typer.Argument(
        None,
        metavar="[<distribution>]",
        help="The dependency to move to a newer release. Default: the one you pick from the "
        "list of those behind, where a person can be asked.",
    ),
    old: str | None = typer.Option(
        None,
        "--from",
        metavar="<version>",
        help="The release the code is written for. Default: the one the manifests name. Where no "
        "manifest declares the dependency, it is the release the run takes it to be.",
    ),
    new: str | None = typer.Option(
        None,
        "--to",
        metavar="<version>",
        help="The release to move to. Default: the newest that is neither withdrawn nor a "
        "pre-release.",
    ),
    module: str | None = typer.Option(
        None, "--module", metavar="<module>", help="The module to compare, as for pack synth."
    ),
    repo: str = typer.Option(
        ".", "--repo", metavar="<path>", help="Repository root. Defaults to the current directory."
    ),
    offline: bool = typer.Option(
        False, "--offline", help="Reach no host: use only what an earlier run kept in the cache."
    ),
    apply_changes: bool = typer.Option(
        False,
        "--apply",
        help="Try the move in a copy of the repository first: install both releases with uv and "
        "run your tests before and after. Write it only if no test that passed now fails.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="With --apply, agree to the trial: it installs packages, which runs their build "
        "scripts, and runs your tests.",
    ),
    python: str | None = typer.Option(
        None,
        "--python",
        metavar="<version>",
        help="The Python the trial's environments use. Default: .python-version, else uv's own.",
    ),
    test_command: str | None = typer.Option(
        None,
        "--test-command",
        metavar='"<cmd>"',
        help="The tests to run in the trial, as one command. Default: pytest, if the repository "
        "is set up for it.",
    ),
    timeout: int | None = typer.Option(
        None,
        "--timeout",
        metavar="<seconds>",
        min=1,
        help="How long the tests of the trial may run, each time. Default: 1800.",
    ),
    branch: bool = typer.Option(
        False,
        "--branch",
        help="With --apply, commit the move to a new branch and leave the working tree as it is. "
        "Nothing is pushed.",
    ),
    branch_name: str | None = typer.Option(
        None,
        "--branch-name",
        metavar="<name>",
        help="The name of the branch --branch makes. Default: obelize/upgrade-<the new release>.",
    ),
    agent: str | None = typer.Option(
        None,
        "--agent",
        metavar="<backend>",
        help="With --apply and --branch, put the places the pack only flags to your own coding "
        "agent (claude_code), one at a time, in the trial's copy. Overrides agent.backend.",
    ),
    max_asks: int = typer.Option(
        50,
        "--max-asks",
        min=1,
        metavar="<n>",
        help="The most places --agent is asked about in one round.",
    ),
    max_rounds: int = typer.Option(
        3,
        "--max-rounds",
        min=0,
        metavar="<n>",
        help="The most rounds --agent is put the tests that broke after the move. 0 asks none.",
    ),
) -> None:
    """Show what moving one dependency to a newer release would change.

    Uses the pack that migrates the dependency when obelize has one, and otherwise makes
    one from the public API of the two releases and keeps it, as pack synth does. Then
    plans the migration as fix does and prints the diff, writing nothing. With --apply it
    tries the move in a copy of the repository, in two environments made with uv, and runs
    your tests before and after; the move is written only if no test that passed before
    fails after, and --branch commits it to a new branch instead of the working tree.
    Exit codes: as fix, plus 2 for a dependency the manifests do not name and no --from,
    or an --apply without --yes where no one can be asked, 3 for tests that broke, and 6
    for an index that could not be reached or a trial the tests could not judge.
    """
    from packaging.utils import canonicalize_name

    from obelize import index, libdiff, net
    from obelize import outdated as survey
    from obelize import upgrade as upgrading
    from obelize.config import ConfigError
    from obelize.net import NetworkError
    from obelize.packtools import synth

    root = Path(repo)
    if (branch or branch_name) and not apply_changes:
        typer.echo(
            "--branch commits a move that a trial has passed, so it needs --apply.", err=True
        )
        raise typer.Exit(2)
    try:
        agent_name, agent_model = _agent(agent)
        if agent is None and not (apply_changes and (branch or branch_name)):
            agent_name = None
        config, _ = _settings(root, _overrides(None, None, False))
        fetcher = _fetcher(offline)
        known = _known_packs()
        if distribution is None:
            distribution = _picked(fetcher, root, config)
        elif (pack_id := upgrading.runtime_pack(known, distribution)) and not any(
            one.name == canonicalize_name(distribution) for one in _declared(root, config)
        ):
            raise libdiff.LibraryError(
                f"{distribution} is not a dependency the manifests in {root.resolve()} declare: it "
                f"is a module of the Python or of setuptools. The pack {pack_id} reports its uses: "
                f"obelize fix --pack {pack_id}."
            )
        project = index.project(fetcher, distribution)
        target = libdiff.version(new) if new else libdiff.newest(project)
        declared = next((one for one in _declared(root, config) if one.name == project.name), None)
        now = libdiff.version(old) if old else survey.current(declared.specs if declared else ())
        if now is None:
            raise libdiff.LibraryError(
                f"{project.name} is not declared with a release in {repo}: pass --from."
            )
        chosen = upgrading.choose(
            fetcher,
            project,
            now,
            target,
            targeted=new is not None,
            module=module,
            known=known,
            kept=net.Cache.home(os.environ).directory / "packs" / __version__,
            root=root,
        )
    except (ConfigError, libdiff.LibraryError, synth.SynthError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1 if isinstance(error, synth.SynthDefectError) else 2) from error
    except NetworkError as error:
        typer.echo(error.detail, err=True)
        raise typer.Exit(2 if error.reason == "not_found" else 6) from error
    goal = chosen.install if chosen.remove else target
    typer.echo(f"Moving {project.name} {now} to {goal}. {chosen.note}", err=True)
    if (moves := upgrading.moves_off(known, project.name, now)) is not None:
        typer.echo(
            f"The pack {moves} moves what {project.name} {now} holds onto the Python itself, which "
            f"is no release to move to, and this move does not run it: obelize fix --pack {moves}.",
            err=True,
        )
    stated = (project.name, str(now)) if old else None
    wants_branch = bool(branch or branch_name)
    if agent_name and not (apply_changes and wants_branch):
        typer.echo(
            "--agent puts code to a model, and what a model helped write is lines to review: "
            "use --apply with --branch, so the move lands on a branch and not in your tree.",
            err=True,
        )
        raise typer.Exit(2)
    if apply_changes:
        _trial(
            root,
            chosen,
            project.name,
            now,
            yes=yes,
            python=python,
            test_command=test_command,
            timeout=timeout,
            branch=(branch_name or _branch_name(chosen.install)) if wants_branch else None,
            agent=agent_name,
            agent_model=agent_model,
            max_asks=max_asks,
            max_rounds=max_rounds,
            offline=_offline(offline),
            stated=stated,
        )
        if wants_branch:
            raise typer.Exit(0)
    try:
        _fix(
            pack=[chosen.reference],
            repo=repo,
            apply_changes=apply_changes,
            allow_dirty=False,
            verify_commands=None,
            timeout=None,
            non_interactive=True,
            trust_repo_config=False,
            provider=None,
            accept_model=False,
            show_context=False,
            as_json=False,
            stated=stated,
        )
    except typer.Exit as done:
        # An apply with no verification command of its own ends `6`; the trial was the verification.
        if apply_changes and done.exit_code == _NO_VERDICT:
            raise typer.Exit(0) from done
        raise


def _agent(flag: str | None) -> tuple[str | None, str | None]:
    """The coding agent asked about flagged places: the flag, else the user's own `agent` block."""
    from obelize.providers import agent_cli
    from obelize.verify.runner import user_config

    block = user_config(_config_dir()).agent
    chosen = flag or (None if block.backend == "none" else block.backend)
    if chosen is not None and chosen not in agent_cli.BACKENDS:
        backends = ", ".join(agent_cli.BACKENDS)
        typer.echo(f"--agent takes one of {backends}, not {chosen!r}.", err=True)
        raise typer.Exit(2)
    return chosen, block.model


def _resolver(
    loaded: LoadedPack, backend: str, model: str | None, limit: int, hints: Mapping[str, str]
) -> tuple[
    Callable[[Path], Resolved], Callable[[Path, Mapping[str, str], Collection[str]], Resolved]
]:
    """What a trial calls to put the places a pack flags, and then the tests that broke, to the
    agent, in its copy."""
    from obelize import repair as repairing
    from obelize import resolve as resolving
    from obelize.packs import loader
    from obelize.providers import agent_cli, base
    from obelize.scan import runner as scanner

    try:
        provider = agent_cli.build(backend, model, os.environ)
    except base.ProviderError as error:
        typer.echo(error.detail, err=True)
        raise typer.Exit(6) from error
    typer.echo(
        f"The places {loaded.pack.id} flags, and then the tests the move broke, will be put to "
        f"{provider.program}, one place at a time, with the lines around each (redacted) and "
        f"the pack's words or the test's error; your own login decides where they go. Nothing it "
        f"writes reaches your files before your tests agree.",
        err=True,
    )

    def resolve(tree: Path) -> Resolved:
        config, _ = _settings(tree, _overrides(None, None, True))
        found = scanner.scan(tree, config, loader.to_scan_spec(loaded), jobs=1).findings
        return resolving.resolve(
            tree,
            resolving.rows(found, loaded.pack, hints),
            provider=provider,
            pack=loaded.pack,
            environ=os.environ,
            limit=limit,
        )

    def repair(tree: Path, failures: Mapping[str, str], changed: Collection[str]) -> Resolved:
        found = repairing.rows(tree, failures, changed, os.environ)
        return resolving.resolve(
            tree, found, provider=provider, pack=loaded.pack, environ=os.environ, limit=limit
        )

    return resolve, repair


def _branch_name(install: str) -> str:
    """`obelize/upgrade-pydantic-2.5.0` for `pydantic==2.5.0`."""
    return "obelize/upgrade-" + re.sub(r"[^a-z0-9.]+", "-", install.lower()).strip("-")


def _commit_branch(
    root: Path,
    branch: str,
    done: Trial,
    pack: str,
    distribution: str,
    now: Version,
    install: str,
    named: str,
    held: Sequence[str],
) -> None:
    """The move a trial passed, as one commit on a new branch; the working tree is not touched."""
    from obelize import branch as branching

    verdict = done.verdict
    message = (
        f"Upgrade {distribution} {now} to {install}\n\n"
        f"obelize {__version__} moved the code with the pack {pack}. In a copy of the repository, "
        f"the {verdict.compared} test(s) that passed before were run again after the move: "
        f"{len(verdict.broken)} broke, {len(verdict.flaky)} failed once and passed again.\n"
        + (
            f"A model edited {', '.join(done.by_model)}: read those lines first.\n"
            if done.by_model
            else ""
        )
        + (
            f"A model said {len(done.unchanged)} flagged place(s) need no edit "
            f"({', '.join(done.unchanged[:5])}{', ...' if len(done.unchanged) > 5 else ''}); "
            f"only the tests checked that.\n"
            if done.unchanged
            else ""
        )
        + (
            f"Not written, for you to change: the dependency line at {', '.join(held)}.\n"
            if held
            else ""
        )
        + f"\nObelize-Trial: {named}\n"
    )
    try:
        commit = branching.commit(root, branch, done.changes, message)
    except branching.BranchError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    if held:
        typer.echo(
            f"The dependency line at {', '.join(held)} could not be written: change it by hand.",
            err=True,
        )
    typer.echo(
        f"Committed {commit[:10]} on the new branch {branch}; the working tree is unchanged. "
        f"Nothing was pushed.\nNext: git log -p -1 {branch}"
    )


def _trial(
    root: Path,
    chosen: Chosen,
    distribution: str,
    now: Version,
    *,
    yes: bool,
    python: str | None,
    test_command: str | None,
    timeout: int | None,
    branch: str | None,
    agent: str | None,
    agent_model: str | None,
    max_asks: int,
    max_rounds: int,
    offline: bool,
    stated: tuple[str, str] | None,
) -> None:
    """Try the move in a copy; return if the tests agree to it, else exit with why. With a branch
    name the move is committed there, and the caller ends. Offline, uv installs from its cache."""
    from obelize import gitutil, net
    from obelize.commands import CommandError
    from obelize.commands import fix as fixer
    from obelize.config import ConfigError
    from obelize.evidence import report, run_dir
    from obelize.models import ModelConfig
    from obelize.packs import loader
    from obelize.packtools import synth
    from obelize.trial import copy, envs
    from obelize.trial import run as trying

    if not yes and not (sys.stdin.isatty() and "CI" not in os.environ and typer.confirm(_CONSENT)):
        typer.echo(f"{_CONSENT}\nPass --yes to agree.", err=True)
        raise typer.Exit(2)
    # Refused before the trial, which can take minutes, and not after it.
    dirty = gitutil.state(root).dirty
    if dirty:
        typer.echo(
            "The tree has uncommitted changes. Commit or stash them, so the trial's copy is the "
            "committed code and the move can be undone.",
            err=True,
        )
        raise typer.Exit(5)
    loaded = loader.load(chosen.reference, dirs=_pack_dirs())
    _activate_plugins([loaded])
    named = run_dir.new_id()
    hints = synth.hints_for(chosen.reference)
    resolver, repairer = (
        _resolver(loaded, agent, agent_model, max_asks, hints) if agent else (None, None)
    )

    # Dependency lines the last run of the rules could not write, as `path:line`, and why the
    # last run planned nothing, if a declaration stopped it.
    held: list[str] = []
    stopped: list[str] = []

    def migrate(tree: Path, elsewhere: Collection[str]) -> list[str]:
        config, source = _settings(tree, _overrides(None, None, True))
        outcome = fixer.run(
            fixer.Request(
                root=tree,
                packs=(loaded,),
                named=True,
                config=config,
                source=source,
                cli_commands=(),
                mode=_trust(non_interactive=True, trust_repo_config=False),
                config_dir=_config_dir(),
                environ=os.environ,
                argv=_recorded_argv(),
                apply=True,
                say=_say,
                model=ModelConfig(),
                elsewhere=tuple(sorted(elsewhere)),
                stated=stated,
            )
        )
        stopped[:] = [report.why_blocked(one) for one in outcome.blocked]
        held[:] = [
            f"{row.path}:{row.line}"
            for row in outcome.manifest_plan.findings
            if row.scan_status == "needs_review"
        ]
        return [row.path for row in outcome.record.file_edits]

    try:
        run_dir.home_of(root.resolve())
        done = trying.run(
            trying.Plan(
                root=root,
                scratch=net.Cache.home(os.environ).directory / "trials" / named,
                evidence=root.resolve() / ".obelize" / "trials" / named,
                distribution=distribution,
                old=now,
                install=chosen.install,
                remove=chosen.remove,
                environ={**os.environ, "UV_OFFLINE": "1"} if offline else os.environ,
                say=_say,
                migrate=migrate,
                resolve=resolver,
                repair=repairer,
                max_rounds=max_rounds,
                python=python,
                test_command=test_command,
                **({"timeout_s": timeout} if timeout else {}),
            )
        )
    except (
        copy.CopyError,
        envs.EnvError,
        CommandError,
        ConfigError,
        run_dir.EvidenceError,
    ) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(6) from error
    verdict = done.verdict
    shown = _under(str(root), f".obelize/trials/{named}")
    counts = (
        f"; {verdict.compared} test(s) passed before, {len(verdict.broken)} broke, "
        f"{len(verdict.flaky)} failed once and passed again"
        if verdict.compared
        else ""
    )
    typer.echo(
        f"Trial of {distribution} {now} to {chosen.install}: {verdict.status}"
        f"{f' ({verdict.reason})' if verdict.reason else ''}{counts}. Evidence: {shown}",
        err=True,
    )
    for name in verdict.broken[:10]:
        typer.echo(f"  broke: {name}", err=True)
    if verdict.status == "fail":
        raise typer.Exit(3)
    if verdict.status != "pass":
        typer.echo(_UNJUDGED[verdict.reason or "no_junit"], err=True)
        for text in stopped:
            typer.echo(text, err=True)
        raise typer.Exit(6)
    if branch is not None:
        _commit_branch(
            root, branch, done, loaded.pack.id, distribution, now, chosen.install, named, held
        )


@pack_app.command("synth")
def pack_synth(
    distribution: str = typer.Argument(
        ..., metavar="<distribution>", help="The library on the package index, such as acme-kit."
    ),
    old: str = typer.Option(
        ..., "--from", metavar="<version>", help="The release the code is written for."
    ),
    new: str | None = typer.Option(
        None,
        "--to",
        metavar="<version>",
        help="The release to move to. Default: the newest that is neither withdrawn nor a "
        "pre-release.",
    ),
    module: str | None = typer.Option(
        None,
        "--module",
        metavar="<module>",
        help="The module to compare, when the library has more than one. Default: the one both "
        "releases have.",
    ),
    directory: str = typer.Option(
        ".",
        "--dir",
        metavar="<path>",
        help="Where to make the pack's folder, <provider>/<name>. Defaults to the current "
        "directory.",
    ),
    used_by: str | None = typer.Option(
        None,
        "--used-by",
        metavar="<path>",
        help="Flag only the names the code in this folder reaches through its imports, for a "
        "library that changed too much to flag name by name.",
    ),
    offline: bool = typer.Option(
        False,
        "--offline",
        help="Reach no host: read only what an earlier run kept in the cache.",
    ),
) -> None:
    """Make a migration pack from what two releases of a library offer.

    Downloads the two releases from the package index (and, for the names that
    left, the newest of each minor line between them, at most six), reads what
    each exports without importing or building anything, and
    writes a pack for the names that were renamed, moved or removed, with the
    library's own deprecation messages where it gave any. Every host is printed
    before it is contacted. Exit codes: 0 made, 2 the request is wrong or the
    folder exists, 6 the releases could not be fetched or read, 1 a pack obelize
    made fails its own checks. A library that changed more than a pack can name gets
    exit 2; --used-by then makes the pack for the names your code reaches.
    """
    from obelize import index, libdiff
    from obelize.config import ConfigError
    from obelize.net import NetworkError
    from obelize.packtools import synth, uses

    try:
        fetcher = _fetcher(offline)
        project = index.project(fetcher, distribution)
        before = libdiff.version(old)
        after = libdiff.version(new) if new else libdiff.newest(project)
        compared = libdiff.compare(fetcher, project, before, after, module=module)
        scope = uses.names(Path(used_by), compared.module) if used_by else None
        if used_by and scope is None:
            typer.echo(
                f"{used_by} imports every name of {compared.module} with a star import, so there "
                f"is no telling which it uses.",
                err=True,
            )
            raise typer.Exit(2)
        asked = synth.request(project.name, before, after, compared, scope)
        made = synth.make(
            Path(directory), asked, compared.old_surface, compared.changes, compared.new_surface
        )
    except (ConfigError, libdiff.LibraryError, synth.SynthError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1 if isinstance(error, synth.SynthDefectError) else 2) from error
    except NetworkError as error:
        typer.echo(error.detail, err=True)
        raise typer.Exit(2 if error.reason == "not_found" else 6) from error
    shown = Path(directory) / made.pack_id
    typer.echo(f"Made {made.pack_id} in {shown}:")
    for change, count in made.covered.items():
        typer.echo(f"  {change}: {count} name(s)")
    if made.unseen:
        typer.echo(
            f"{made.unseen} name(s) could not be judged: the newer release makes its exports "
            f"when it is imported, so a name not seen may still be there."
        )
    typer.echo(f"Next: obelize pack test {shown}, then obelize scan --pack {shown}/pack.yaml")


def _offline(flag: bool) -> bool:
    """`--offline`, the person's `network.offline` or `OBELIZE_OFFLINE` in the environment."""
    from obelize.verify.runner import user_config

    return flag or user_config(_config_dir()).network.offline or "OBELIZE_OFFLINE" in os.environ


def _fetcher(offline: bool) -> Fetcher:
    """The seam to the index, as the person's own settings say, telling each host it reaches."""
    from obelize import net
    from obelize.config import ConfigError
    from obelize.verify.runner import user_config

    network = user_config(_config_dir()).network
    try:
        address = net.index_url(os.environ.get("OBELIZE_INDEX_URL") or network.index)
    except ValueError as error:
        raise ConfigError(f"OBELIZE_INDEX_URL: {error}") from error
    return net.Fetcher(
        index=address,
        offline=_offline(offline),
        cache=net.Cache.home(os.environ),
        credentials=os.environ.get("OBELIZE_INDEX_AUTHORIZATION"),
        say=lambda line: typer.echo(line, err=True),
    )


@app.command("mcp")
def mcp(
    repo: str = typer.Option(
        ".",
        "--repo",
        metavar="<path>",
        help="The repository to serve. Defaults to the current directory.",
    ),
    trust_repo_config: bool = typer.Option(
        False,
        "--trust-repo-config",
        help="Let the verification tools run the commands in this repository's .obelize.yml "
        "without asking. Only you can set this: no tool can.",
    ),
    read_only: bool = typer.Option(
        False,
        "--read-only",
        help="Leave out obelize_apply and obelize_undo, the tools that write source files. The "
        "others still write .obelize/, and obelize_verify runs your tests.",
    ),
) -> None:
    """Serve obelize to a coding agent over the Model Context Protocol.

    Speaks JSON-RPC on standard input and output, so start it from the agent's own
    configuration and not in a terminal. The tools scan, plan, apply, verify, undo
    and report on one repository, and list what obelize could not migrate; none takes
    a command to run, a path or a consent. Verification commands come from your
    configuration, as for obelize verify.
    """
    root = Path(repo)
    if not root.is_dir():
        typer.echo(f"--repo {root} is not a directory", err=True)
        raise typer.Exit(2)
    from obelize.mcp import server, tools

    # A client that goes away while a reply is written leaves nobody to tell.
    with contextlib.suppress(BrokenPipeError):
        server.serve(
            tools.Session.start(root.resolve(), trust=trust_repo_config, read_only=read_only)
        )


@app.callback()
def main_callback(
    version: bool = typer.Option(
        False,
        "--version",
        help="Show the obelize version and exit.",
        callback=_version_callback,
        is_eager=True,
    ),
    no_color: bool = typer.Option(
        False,
        "--no-color",
        help="Disable coloured output. Also honoured as the NO_COLOR environment variable.",
    ),
) -> None: ...


def main() -> None:
    """Console-script entry point."""
    from obelize.native import console

    console.utf8_stdio()
    if colour_is_disabled(sys.argv[1:], os.environ):
        disable_colour()
    # An invalid escape or an always-true assert in the code read is the author's to fix, and
    # compile() and libcst would report each one on stderr.
    warnings.simplefilter("ignore", SyntaxWarning)
    app()


if __name__ == "__main__":  # pragma: no cover
    main()

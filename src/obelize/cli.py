"""Command-line entry point.

Startup budget: `obelize --help` must stay well under 300 ms, so only typer is imported at module
scope; heavy imports (libcst, pydantic models, packs) go inside the command body that needs them.
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import typer

from obelize import __version__

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable

    from obelize.config import LoadedConfig, Overrides
    from obelize.models import Config, ConfigOrigin, ModelConfig
    from obelize.packs.loader import LoadedPack
    from obelize.verify.runner import Mode

# A bundled pack failing validation exits 1, not 7: the input was obelize's own.
_BUNDLED_DEFECT = (
    "This pack ships with obelize, so this is a bug in obelize. "
    "Please report it at https://github.com/hakanbogan/obelize/issues."
)

app = typer.Typer(
    name="obelize",
    help="Migrate Python code across external SDK versions, with evidence. "
    "Supported migrations: google-generativeai to google-genai, openai 0.x to 1.x, "
    "PyPDF2 to pypdf.",
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
        "give is always used. The number does not change the output.",
    ),
    list_files: bool = typer.Option(
        False,
        "--list-files",
        help="Print the files selected for the scan, in order, and stop.",
    ),
) -> None:
    """Find the call sites, imports and manifest entries a pack affects.

    Edits no source file. Evidence goes to .obelize/runs/<id>/, which every
    scan excludes.
    """
    from obelize import gitutil
    from obelize.commands import CommandError
    from obelize.commands import fix as fixer
    from obelize.config import ConfigError
    from obelize.evidence import report, run_dir
    from obelize.models import FindingsDocument
    from obelize.scan import runner, walker
    from obelize.transforms.kinds import flag_only

    root = Path(repo)
    packs, named = _packs_or_exit(pack)
    started = run_dir.now()
    began = time.monotonic()
    try:
        # Before anything is read, so `--jobs 0` is refused before the repository is hashed.
        runner.worker_count(jobs)
        configuration = _configuration(root)
        if list_files:
            for path in walker.walk(root, configuration.config).files:
                typer.echo(path)
            return
        chosen = fixer.select(root, configuration.config, packs, named=named, jobs=jobs)
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    except CommandError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(error.code) from error
    result = runner.merged([one.scan for one in chosen.packs], chosen.tree)
    loaded = [one.loaded for one in chosen.packs]
    documents = [one.pack for one in loaded]
    guides = tuple(
        guide
        for one in chosen.packs
        for guide in flag_only.guides(one.loaded.pack, one.scan.findings)
    )
    scan_ms = int((time.monotonic() - began) * 1000)

    document = FindingsDocument(
        obelize_version=__version__,
        packs=run_dir.refs(loaded),
        counts=result.counts,
        findings=result.findings,
    )
    findings = document.model_dump_json(indent=2) + "\n"
    record = run_dir.compose(
        run_id=run_dir.new_id(started),
        scan=result,
        packs=[
            run_dir.Used(one.loaded, one.scan.blocked[0] if one.scan.blocked else None)
            for one in chosen.packs
        ],
        config=configuration.config,
        source=configuration.source,
        git=gitutil.state(root),
        argv=tuple(sys.argv[1:]),
        started=started,
        finished=run_dir.now(),
        total_ms=int((time.monotonic() - began) * 1000),
        scan_ms=scan_ms,
    )
    try:
        written = run_dir.write(
            root,
            record,
            findings,
            loaded,
            report.document(record, result, guides=guides, packs=documents),
        )
    except run_dir.EvidenceError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error

    evidence = _under(repo, written.relative)
    if as_json:
        _document(findings)
        # On stderr, so stdout stays the document; `obelize verify --run <id>` needs the id.
        typer.echo(f"Evidence: {evidence}", err=True)
        return
    label = ", ".join(f"{one.pack.id} {one.pack.pack_version}" for one in loaded)
    for line in report.terminal(result, label or "no pack applies", evidence, guides):
        typer.echo(line)
    if not loaded:
        typer.echo(f"No pack applies. Checked: {', '.join(chosen.tried) or 'none'}.")


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
        help="A verification command to run, such as your tests. Repeatable. Replaces "
        "the commands in .obelize.yml, and runs without asking.",
    ),
    timeout: int | None = typer.Option(
        None,
        "--timeout",
        metavar="<s>",
        min=1,
        help="Per-command timeout, overriding verify.timeout_s for this run.",
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
    write, the change is still written and the tests are not run a second time.
    """
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
        argv=tuple(sys.argv[1:]),
        apply=apply_changes,
        accept_model=accept_model,
        ask=_ask,
        model=model,
        model_flagged=provider is not None or accept_model,
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
            outcome.patch,
            os.environ,
            repo,
            outcome.guides,
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
        help="Per-command timeout, overriding verify.timeout_s for this run.",
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
            )
        )
    except CommandError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(error.code) from error
    except ConfigError as error:
        # The user's allowlist, read only when the repository asks for a command.
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    for line in report.verified(outcome.record, _under(repo, outcome.evidence)):
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
) -> None:
    """Revert the files an applied run wrote, checked against its own hashes.

    A file edited since is skipped and reported with both hashes and its
    snapshots/before/ copy. Obelize never overwrites content it did not
    write, so there is no --force.
    """
    from obelize.commands import CommandError
    from obelize.commands import undo as reverter
    from obelize.config import ConfigError
    from obelize.evidence import report

    root = Path(repo)
    try:
        _configuration(root)
    except ConfigError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(2) from error
    try:
        outcome = reverter.run(reverter.Request(root=root, run_id=run_id, argv=tuple(sys.argv[1:])))
    except CommandError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(error.code) from error
    for line in report.reverted(
        outcome.record, _under(repo, outcome.folder), _under(repo, outcome.evidence)
    ):
        typer.echo(line)
    raise typer.Exit(outcome.exit_code)


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
    return loaded, bool(references)


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
    typer.echo(
        f"  migrates     {pack.from_.package} {pack.from_.version} -> "
        f"{pack.to.package} {pack.to.version}"
    )
    typer.echo(f"  changes      {len(pack.changes)}")
    typer.echo(f"  limitations  {len(pack.limitations)}")
    # A local pack may ship without fixtures; tests/packs/ checks the bundled ones.
    typer.echo("  fixtures     not checked by this command")


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
    app()


if __name__ == "__main__":  # pragma: no cover
    main()

"""The CLI surface: commands and flags against docs/CLI.md, exit codes, colour, `--help` imports.

What each command does is graded elsewhere, starting at `tests/fixtures/commands/`.
"""

from __future__ import annotations

import ast
import inspect
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest
import typer.main
from typer.testing import CliRunner

import obelize
from obelize import cli
from obelize.cli import app
from obelize.models import EXIT_CODES, PROVIDER_NAMES
from obelize.packs import loader

ROOT = Path(__file__).resolve().parents[2]

runner = CliRunner()

# Commands docs/CLI.md promises that do not work yet; empty, but kept for the next one.
# Remove an entry, and update README.md's commands table, in the commit that implements it.
UNIMPLEMENTED_COMMANDS: list[str] = []


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == f"obelize {obelize.__version__}"


def test_python_dash_m_runs_the_cli() -> None:
    """Where the console script's directory is not on PATH, the module still runs."""
    completed = subprocess.run(
        [sys.executable, "-m", "obelize", "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == f"obelize {obelize.__version__}\n"


def test_help_exits_zero() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Migrate Python code across external SDK versions" in result.stdout


def test_no_arguments_shows_help_and_usage_exit_code() -> None:
    """2 is the usage-error exit code in docs/CLI.md."""
    result = runner.invoke(app, [])
    assert result.exit_code == 2


def test_help_names_each_migration_a_bundled_pack_makes() -> None:
    shown = runner.invoke(app, ["--help"]).stdout
    for pack_id in loader.bundled_ids():
        pack = loader.load(pack_id).pack
        assert f"{pack.from_.package} to {pack.to.package}" in shown, pack_id


# An installed wheel has no `docs/`, so the text a user reads points at the repository instead.
URLS = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["urls"]
PAGE = f"{URLS['Repository']}/blob/main/"


def _help(command: Any) -> list[str]:
    """The help of one typer command, its parameters and every command under it."""
    texts = [command.help or ""]
    texts.extend(getattr(parameter, "help", None) or "" for parameter in command.params)
    for child in getattr(command, "commands", {}).values():
        texts.extend(_help(child))
    return texts


def _messages(path: Path) -> list[str]:
    """Every string in one module except its docstrings, which only `--help` shows."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def _pointers(texts: list[str]) -> list[str]:
    return [found.rstrip(".,;:)") for text in texts for found in re.findall(r"\S*docs/\S*", text)]


def test_help_points_at_pages_in_the_repository() -> None:
    for pointer in _pointers(_help(typer.main.get_command(app))):
        assert pointer.startswith(PAGE + "docs/"), pointer
        assert (ROOT / pointer.removeprefix(PAGE)).is_file(), pointer


def test_pack_validate_help_links_the_format_it_checks() -> None:
    shown = runner.invoke(app, ["pack", "validate", "--help"]).stdout
    assert f"{PAGE}docs/PACK_SPEC.md" in shown


def _invocations(command: Any, words: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    """The words that reach each command, the group's own empty tuple first."""
    children = getattr(command, "commands", {}).items()
    return [
        words,
        *(found for name, child in children for found in _invocations(child, (*words, name))),
    ]


def test_no_help_prints_a_markdown_backtick() -> None:
    """A terminal shows a code span's backticks as they are."""
    invocations = _invocations(typer.main.get_command(app))
    assert {("scan",), ("undo",), ("pack", "validate")} <= set(invocations)
    for words in invocations:
        assert "`" not in runner.invoke(app, [*words, "--help"]).stdout, words


def test_no_message_names_a_path_in_a_checkout() -> None:
    modules = [
        path
        for path in sorted((ROOT / "src" / "obelize").rglob("*.py"))
        if "fixtures" not in path.parts
    ]
    found = {
        str(path.relative_to(ROOT)): pointer
        for path in modules
        for pointer in _pointers(_messages(path))
        if not pointer.startswith(PAGE)
    }
    assert found == {}


def test_a_defect_in_obelize_says_where_to_report_it(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(reference: str, root: Path | None = None) -> object:
        raise loader.PackInvalidError(reference, ["id: Field required"], bundled=True)

    monkeypatch.setattr(loader, "load", refuse)
    result = runner.invoke(app, ["pack", "validate", cli.DEFAULT_PACK])
    assert result.exit_code == 1, result.output
    assert URLS["Issues"] in result.output


@pytest.mark.parametrize("command", UNIMPLEMENTED_COMMANDS)
def test_documented_commands_are_not_implemented_yet(command: str) -> None:  # pragma: no cover
    """Nothing may claim to work before it does; runs zero times while the list is empty."""
    result = runner.invoke(app, [command])
    assert result.exit_code != 0


def test_every_command_the_contract_publishes_is_registered() -> None:
    page = (ROOT / "docs" / "CLI.md").read_text(encoding="utf-8")
    surface = page.split("## Surface")[1].split("```")[1]
    published = {
        line.split()[1]
        for line in surface.splitlines()
        if line.startswith("obelize ") and not line.startswith("obelize --")
    }
    for name in sorted(published):
        assert runner.invoke(app, [name, "--help"]).exit_code == 0, name
    assert published == {"scan", "fix", "verify", "undo", "pack"}
    assert not set(UNIMPLEMENTED_COMMANDS) & published


def test_every_flag_the_contract_publishes_is_a_flag_the_command_takes() -> None:
    """Read off the command's own parameters: `--help` wraps at a width no test controls."""
    page = (ROOT / "docs" / "CLI.md").read_text(encoding="utf-8")
    for name in ("scan", "fix", "verify", "undo"):
        section = page.split(f"\n## `obelize {name}`\n")[1].split("\n---\n")[0]
        table = section.split("\n| Flag |")[1].split("\n\n")[0]
        published = {
            found.replace("\\", "")
            for row in table.splitlines()
            for found in re.findall(r"`(--[a-z-]+)", row.split("|")[1] if "|" in row else "")
        }
        assert published, name
        command = next(one for one in app.registered_commands if one.name == name)
        declared = {
            spelling
            for parameter in _options(command)
            for spelling in parameter
            if spelling.startswith("--")
        }
        assert published <= declared, (name, sorted(published - declared))


def test_a_flag_with_a_floor_states_it_in_the_contract() -> None:
    page = (ROOT / "docs" / "CLI.md").read_text(encoding="utf-8")
    floors = 0
    for command in app.registered_commands:
        section = page.split(f"\n## `obelize {command.name}`\n")[1].split("\n## ")[0]
        for parameter in inspect.signature(command.callback).parameters.values():  # type: ignore[arg-type]
            option = parameter.default
            if not isinstance(option, typer.models.OptionInfo) or option.min is None:
                continue
            floors += 1
            spelling = next(iter(option.param_decls or ()))
            row = next(line for line in section.splitlines() if line.startswith(f"| `{spelling}"))
            assert f"(at least {option.min})" in row, (command.name, spelling)
    assert floors == 2


def test_the_model_flag_names_every_provider_it_accepts() -> None:
    """docs/CLI.md lists them, and `--help` is where a user looks first."""
    fix = typer.main.get_command(app).commands["fix"]  # type: ignore[attr-defined]
    shown = next(one.help for one in fix.params if "--model" in one.opts)
    assert set(re.findall(r"[a-z_]+", shown)) >= PROVIDER_NAMES


def test_the_jobs_flag_states_the_cap_on_its_default() -> None:
    """Above the cap, one fewer than the CPU count is not the default."""
    from obelize.scan.runner import MAX_WORKERS

    scan = typer.main.get_command(app).commands["scan"]  # type: ignore[attr-defined]
    shown = next(one.help for one in scan.params if "--jobs" in one.opts)
    assert f"at most {MAX_WORKERS}" in shown


def _options(command: object) -> list[tuple[str, ...]]:
    """Every option spelling one registered typer command declares."""
    import typer

    found = []
    for parameter in inspect.signature(command.callback).parameters.values():  # type: ignore[attr-defined]
        default = parameter.default
        if isinstance(default, typer.models.OptionInfo):
            found.append(tuple(str(one) for one in default.param_decls or ()))
    return found


def test_the_exit_codes_the_contract_publishes_are_the_ones_the_code_knows() -> None:
    page = (ROOT / "docs" / "CLI.md").read_text(encoding="utf-8")
    table = page.split("\n## Exit codes\n")[1].split("\n###")[0]
    documented = {int(row[0]) for row in re.findall(r"^\| `(\d)` \| ", table, re.MULTILINE)}
    assert documented == EXIT_CODES


# `--verify` texts that cannot run as one command, and what the refusal says about each.
UNRUNNABLE = [
    ("pytest | tee log", "runs without a shell"),
    ("pytest 'x", "does not split into arguments"),
]


@pytest.mark.parametrize(("command", "said"), UNRUNNABLE)
@pytest.mark.parametrize("name", ["fix", "verify"])
def test_a_verify_command_that_cannot_run_is_a_usage_error(
    tmp_path: Path, name: str, command: str, said: str
) -> None:
    """Refused as `.obelize.yml`'s `verify.commands` is: exit 2, the reason, no traceback."""
    target = (
        ["--pack", cli.DEFAULT_PACK] if name == "fix" else ["--run", "20260101T000000Z-deadbeef"]
    )
    result = runner.invoke(app, [name, "--repo", str(tmp_path), *target, "--verify", command])
    assert result.exit_code == 2, result.output
    (line,) = result.output.splitlines()
    assert line.startswith("--verify is not valid: ")
    assert said in line
    assert not (tmp_path / ".obelize").exists()


ANSI = "\x1b["
COLOUR_CASES = [
    # (argv, environment, colour is disabled)
    ([], {}, False),
    (["--no-color"], {}, True),
    (["--no-color", "--help"], {}, True),
    (["--help"], {"NO_COLOR": "1"}, True),
    # https://no-color.org: present and not empty, WHATEVER the value.
    (["--help"], {"NO_COLOR": "0"}, True),
    (["--help"], {"NO_COLOR": "false"}, True),
    (["--help"], {"NO_COLOR": ""}, False),
    # `--no-color` is global: inside another tool's argument it does not silence obelize.
    (["fix", "--verify", "pytest --no-color"], {}, False),
]


@pytest.mark.parametrize(("argv", "env", "expected"), COLOUR_CASES)
def test_colour_is_disabled_reads_the_flag_and_the_convention(
    argv: list[str], env: dict[str, str], expected: bool
) -> None:
    assert cli.colour_is_disabled(argv, env) is expected


def _run(args: list[str], env: dict[str, str]) -> str:
    """Run the CLI as its own process, with colour forced on unless `env` refuses it.

    `TERM` is pinned too: rich never colours a dumb terminal, and a CI `run:` step is one.
    """
    environment = {**os.environ, "FORCE_COLOR": "1", "TERM": "xterm-256color"}
    environment.pop("NO_COLOR", None)
    environment.update(env)
    completed = subprocess.run(
        [sys.executable, "-m", "obelize.cli", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        check=False,
    )
    return completed.stdout + completed.stderr


# Two rich consoles on two streams; each is first shown coloured, so "no escape" is not vacuous.
COLOURED_SURFACES = [(["--help"], "help"), (["--nope"], "usage-error")]


@pytest.mark.parametrize(
    ("args", "surface"), COLOURED_SURFACES, ids=[s for _, s in COLOURED_SURFACES]
)
def test_the_surface_is_coloured_when_nothing_refuses_it(args: list[str], surface: str) -> None:
    assert ANSI in _run(args, {}), (
        f"{surface}: no colour to remove, so the tests below prove nothing"
    )


@pytest.mark.parametrize(
    ("args", "surface"), COLOURED_SURFACES, ids=[s for _, s in COLOURED_SURFACES]
)
@pytest.mark.parametrize(
    ("extra_args", "env"),
    [(["--no-color"], {}), ([], {"NO_COLOR": "1"})],
    ids=["flag", "environment"],
)
def test_no_colour_leaves_no_escape_sequence(
    args: list[str], surface: str, extra_args: list[str], env: dict[str, str]
) -> None:
    assert ANSI not in _run(extra_args + args, env), surface


def test_main_runs_the_application(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing else runs the console-script entry point in-process."""
    monkeypatch.setattr(sys, "argv", ["obelize", "--version"])
    with pytest.raises(SystemExit) as excinfo:
        cli.main()
    assert excinfo.value.code == 0


def test_main_sets_the_output_streams_up_before_the_application_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A redirected Windows stream is cp1252 until then; on POSIX the call changes nothing."""
    from obelize.native import console

    calls: list[str] = []
    monkeypatch.setattr(console, "utf8_stdio", lambda: calls.append("streams"))
    monkeypatch.setattr(cli, "app", lambda: calls.append("app"))
    cli.main()
    assert calls == ["streams", "app"]


def test_main_disables_colour_before_anything_is_rendered(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--help` is eager, so colour is decided before `app()` runs."""
    from typer import rich_utils

    monkeypatch.setattr(rich_utils, "COLOR_SYSTEM", "auto")
    monkeypatch.setattr(sys, "argv", ["obelize", "--no-color", "--version"])
    with pytest.raises(SystemExit):
        cli.main()
    assert rich_utils.COLOR_SYSTEM is None


# `--help` stays under 300 ms by importing these inside command bodies (cli.py). Timing is flaky on
# a shared runner; the import graph is not.
HEAVY = [
    "libcst",
    "pydantic",
    "yaml",
    "pathspec",
    "obelize.commands.fix",
    "obelize.commands.undo",
    "obelize.commands.verify",
    "obelize.config",
    "obelize.evidence.run_dir",
    "obelize.fsutil",
    "obelize.models",
    "obelize.packs.loader",
    "obelize.packs.schema",
    "obelize.scan.parse",
    "obelize.scan.walker",
    "obelize.transforms.codemod",
    "obelize.verify.runner",
]


@pytest.mark.parametrize("module", HEAVY)
def test_importing_the_cli_does_not_pull_in_a_heavy_dependency(module: str) -> None:
    """Each `obelize` module listed reaches a third-party one listed, often indirectly."""
    probe = (
        "import sys; import obelize.cli; "
        f"print(any(name == {module!r} or name.startswith({module + '.'!r}) "
        "for name in sys.modules))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, encoding="utf-8", check=True
    )
    assert completed.stdout.strip() == "False", (
        f"importing obelize.cli imported {module}. Move the import into the command body "
        f"that needs it -- see the module docstring in src/obelize/cli.py."
    )

# Getting started

obelize reads a repository, finds the places that use a library you are leaving, and rewrites the
ones it can prove safe. This page takes you from nothing to a verified migration. The shortest path
is on the [README](../README.md#quickstart); this page adds the details that decide whether it works
on your project.

## Install

Run it once, in your project's directory, with [uv](https://docs.astral.sh/uv/):

```bash
uvx obelize scan
```

Or keep it installed, with uv or pipx:

```bash
uv tool install obelize
pipx install --python python3.12 obelize
```

`uvx` keeps the version it first downloaded; `uvx obelize@latest` fetches the newest. When you did
not install the tool, put `uvx` in front of each `obelize` command a `Next:` line names.

obelize is a command-line tool, so install it as one and not into your project's environment.

## Requirements

obelize needs Python 3.12 or newer, and pipx takes the one `--python` names. It runs on Linux, macOS
and Windows. The project it migrates needs the Python its new library does: 3.10 or newer for
`google-genai`, 3.9 or newer for `pypdf`, and 3.8 or newer for `openai`, where pip picks the newest
release that installs.

On Python 3.15, PyYAML has no wheel yet, so pip builds it (in pure Python, with no compiler), and an
Intel Mac, whose libcst has no 3.15 wheel either, compiles that with Rust.

## First run

In a git repository with everything committed:

```bash
uvx obelize scan
uvx obelize fix
```

`scan` lists each import, call and dependency line of the old libraries that it can resolve, and
whether it can migrate it. `fix` is a dry run until you pass `--apply`: it prints the plan and the
diff, and writes only its own record under `.obelize/`, which git ignores.

## Verify with your tests

To apply the change and have your tests check it, first install the new libraries, here
`google-genai` and `pypdf`, into your project's environment beside the old ones, without changing
a tracked file. `uv pip` works whether pip or uv made the environment. Your tests then run once
before the change and once after:

```bash
uv pip install --python .venv/bin/python google-genai pypdf
uvx obelize fix --apply --verify ".venv/bin/python -m pytest -q"
git diff
```

Name your project's own interpreter in `--verify`, so the tests run with its dependencies. On
Windows that is `.venv/Scripts/python.exe`, written with forward slashes, since `--verify` reads a
backslash as an escape. The run ends with a `Next:` line, and after a clean apply that line names
`obelize undo --run <id>`, which puts the files back.

A run is verified when your test command passed before the change and still passes after it.
Without `--verify`, or when the tests already failed before the change, there is no verdict and the
run exits `6`.

## openai 0.x to 1.x

`openai` 0.x and 1.x are one install, so your tests can run against only one of them at a time.
`openai/openai-0-to-1` writes no file while it leaves anything in the repository, and the new pin
moves in the run that migrates all of it. Check it in four steps: pass your tests on 0.x, write the
change, install the new release, and run the tests again.

```bash
uvx obelize fix --apply
uv pip install --python .venv/bin/python "openai>=1.109.1"
uvx obelize verify --run "$(cat .obelize/latest)" --verify ".venv/bin/python -m pytest -q"
```

If you ran `fix --apply --verify` with 1.x already installed, the tests fail before the change and
`verify` cannot rerun that run: `obelize undo` it, run `fix --apply` without `--verify`, then
`verify --run` the new id. A notebook whose code cells call the old `openai` API holds the pin
until you migrate it by hand or list it under `exclude` in `.obelize.yml`; obelize reads a
notebook and never writes one.

## Next steps

- [After a run](AFTER_A_RUN.md) explains each exit code and what to do with the places it left.
- [With a coding agent](WITH_A_CODING_AGENT.md) hands those places to an agent and keeps the check.
- [CLI](CLI.md) lists every flag, and [Configuration](CLI.md#configuration-file-obelizeyml) the
  `.obelize.yml` file.

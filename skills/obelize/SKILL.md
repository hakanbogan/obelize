---
name: obelize
description: Migrate Python code off a retired library (google-generativeai, PyPDF2, openai 0.x) with obelize, then finish by hand what it leaves. Use when a repository still imports one of them.
---

# Migrating with obelize

obelize writes the part of a migration it can prove and lists every other place with a reason. Do
the hand work on those places, and let obelize check that nothing is left.

## Steps

1. Commit everything. obelize refuses `--apply` over uncommitted changes, and a commit before each
   run, a rerun after your own edits included, makes `git diff` the migration alone.
2. Look first. This edits nothing:

   ```bash
   uvx obelize scan
   ```

3. Write what it can prove:

   ```bash
   uvx obelize fix --apply
   ```

   The summary names the most common reasons, what to change for each, and the first rows left for
   you. `REPORT.md` in the run folder it prints lists every one, and the guide of each pack that
   left them.
4. Fix the rows `REPORT.md` lists under `Withheld`, apart from those whose reason is
   `file_not_fully_migrated` or `repo_not_fully_migrated`: those only wait for the others. Use the
   guide for the pack. Commit, then run `uvx obelize fix --apply` again.
5. Install the new library for `google-genai` or `pypdf`, then run the tests:

   ```bash
   uv pip install --python .venv/bin/python google-genai pypdf
   ```

   For `openai`, 0.x and 1.x are one install: pass the tests on 0.x first, run `fix --apply`, then
   install the release the pin names and verify.

   ```bash
   uv pip install --python .venv/bin/python "openai>=1.109.1"
   uvx obelize verify --run "$(cat .obelize/latest)" --verify ".venv/bin/python -m pytest -q"
   ```

6. Regenerate the lockfile, run your formatter on the changed files, and read `git diff`.

## Done

The migration is done when `uvx obelize scan` reports no row but `not_a_usage` and your tests pass.
`obelize undo --run <id>` puts back the files a run wrote, unless they were edited since.

Do not edit the files under `.obelize/`. obelize never commits or pushes; that is yours.

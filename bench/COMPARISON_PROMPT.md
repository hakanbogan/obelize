<!-- The comparison arm's prompt: one text for every case, varying only in the {{TREE}},
     {{GUIDE}} and {{META}} paths. bench/comparison_collect.py strips this note and refuses a
     case whose rendered copy differs. Editing this file edits the experiment (ADR-045). -->

# Migrating a project off the legacy Google Generative AI SDK

You are migrating a Python project off a deprecated SDK. Do the whole job in
one pass.

## The project

`{{TREE}}`

It uses the legacy Google Generative AI Python SDK — the distribution
`google-generativeai`, imported as `google.generativeai`. Move it to the
current SDK — the distribution `google-genai`, imported as
`from google import genai`.

That means every place the old SDK is used, and the dependency declarations
that name it: `requirements*.txt`, `setup.py`, `pyproject.toml`, `Pipfile`,
`environment.yml` and anything else in the project that pins it.

The program has to keep doing what it did. Where the two SDKs differ in
behaviour and you have to choose, choose the reading that keeps the existing
behaviour, and say so in your report.

## The guide

`{{GUIDE}}`

That is a saved copy of the official migration guide,
<https://ai.google.dev/gemini-api/docs/migrate>. Read it before you start.

## Rules

1. **One pass, source only.** Edit the files. Do not install anything, do not
   create a virtual environment, and do not run the project's tests or its
   entry points. Neither SDK is installed and nothing here is set up to run.
2. **Stay inside the project.** Read and write only under `{{TREE}}`, plus the
   two files under `{{META}}` named below. Nothing else on this machine is
   part of the job.
3. **No network.** The guide above is the reference. Beyond it, use what you
   already know about the two SDKs.
4. **Do not commit.** Leave your changes in the working tree.
5. **Leave the project's own history and metadata alone** — do not touch
   `.git/`, and do not add tooling, formatters or configuration the project did
   not have.

## Bookkeeping

Before your first edit:

```
date -u +%s > {{META}}/started
```

After your last edit:

```
date -u +%s > {{META}}/finished
```

Then write `{{META}}/report.md`: what you changed, what you deliberately left
alone, and anything you were not sure about. A line you could not migrate with
confidence belongs in that report rather than in a guess.

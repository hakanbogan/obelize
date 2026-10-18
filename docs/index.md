# obelize

Verified codemods for breaking Python dependency upgrades. obelize rewrites the code it can prove
safe to change, tells you why it left the rest, and runs your tests before and after.

```bash
uvx obelize scan
uvx obelize fix
```

`scan` lists every place in your repository that a migration touches and edits nothing. `fix` prints
the plan and the diff, and writes only with `--apply`. It ships migrations from `google-generativeai`
to `google-genai`, `openai` 0.x to 1.x and `PyPDF2` to `pypdf`.

## Start here

- [Getting started](GETTING_STARTED.md) installs obelize and takes one migration from a dry run to
  a verified change.
- [After a run](AFTER_A_RUN.md) explains the exit codes and what to do with the places it left.
- [With a coding agent](WITH_A_CODING_AGENT.md) hands those places to an agent and keeps the check.

## How it earns trust

- A [migration pack](GLOSSARY.md#migration-pack) is reviewed data that cites the library's own
  guide, and it holds no code.
- A rewrite happens only where obelize can resolve the call and prove the edit. Everything else
  stays as written, with a [reason](GLOSSARY.md#reason).
- Your tests run before and after, so a change is [verified](GLOSSARY.md#verified) against
  your own suite.
- Nothing is written without `--apply`, and `obelize undo` puts the files back.

Read [Safety](SAFETY.md) for what it does to your machine, [Limits](LIMITS.md) for what it does not
do yet, and the [Benchmark](BENCHMARK.md) for what it measured.

# Releasing

The release workflow has not run yet, so each step here stays unproven until the first release
goes through it.

## Versions and tags

- The version lives only in `__version__` in `src/obelize/__init__.py`, which hatchling reads at
  build time. `pyproject.toml` holds no version.
- Versions are `0.MINOR.PATCH` in PEP 440 normal form, which the release workflow checks: write
  `0.1.0rc1`, not `0.1.0-rc1`.
- Every format is unstable through 0.x ([CHANGELOG.md](../CHANGELOG.md#stability)), and each
  release's changelog section names the formats it changed.
- The tag is `v` and the version, such as `v0.1.0`. Once the repository is public, a tag ruleset
  lets only me create `v*` tags.

## Accounts

PyPI and TestPyPI are separate sites with separate accounts. Each needs a verified e-mail
address, two-factor authentication with a security key (WebAuthn) and an authenticator app
(TOTP) as the fallback, and recovery codes kept offline. Trusted Publishing keeps working
without a login, but yanking a release or changing a publisher needs one.

## Trusted Publishing

No API token exists in the repository or in GitHub secrets. `release.yml` uploads through
`pypa/gh-action-pypi-publish` over OIDC, which also uploads an attestation for each file.

On release day, not before, add a pending publisher under Account settings, Publishing, on each
site:

| Field | PyPI | TestPyPI |
|---|---|---|
| PyPI Project Name | `obelize` | `obelize` |
| Owner | `hakanbogan` | `hakanbogan` |
| Repository name | `obelize` | `obelize` |
| Workflow name | `release.yml` | `release.yml` |
| Environment name | `pypi` | `testpypi` |

A pending publisher reserves no name, and PyPI deletes one that has not been used 30 days after
it was created. If the form refuses the name, someone else holds it.

Once the repository is public, two GitHub environments hold the uploads: `pypi` names me as its
required reviewer and accepts only `v*` tags, and `testpypi` accepts only `main`. A private
repository on my plan can have neither the reviewer nor the tag ruleset, so until then an upload
to PyPI waits for nobody. Before tagging, check the reviewer:

```bash
gh api repos/hakanbogan/obelize/environments/pypi --jq '[.protection_rules[].type]'
gh api repos/hakanbogan/obelize/environments/pypi/deployment-branch-policies \
  --jq '[.branch_policies[] | [.type, .name]]'
```

The first must list `required_reviewers`, and the second must print exactly `[["tag","v*"]]`.

## Release checklist

Run in order. A failed step stops the release.

1. Licences. Run `pip-licenses` over the locked dependency set. A GPL, AGPL, SSPL or unknown
   licence stops the release until it is resolved; any other licence passes. `NOTICE` lists
   only third-party code shipped inside the package, and there is none today.
2. README. Read `README.md` line by line. Every claim must be backed by a green CI job or a row
   in [BENCHMARK_RESULTS.md](BENCHMARK_RESULTS.md), and the commands table lists only what the
   release does. After the benchmark is measured again, copy its numbers into the README's
   benchmark tables; `tests/unit/test_readme.py` fails until they match.
3. CLI contract. Check the real `--help` output of every command and the real exit codes
   against [CLI.md](CLI.md), and fix any difference, in the code or the page, before the
   release.
4. Pre-flight. Run [Pre-flight](#pre-flight) from a clean tree.
5. Changelog. Write this version's section as `## [0.x.y] - YYYY-MM-DD` in Keep a Changelog
   format, saying which formats changed, with the benchmark headline and its `n` and the
   patterns still unsupported. The workflow takes this section as the GitHub release notes and
   stops before building if it is missing or empty.
6. Version. Set `__version__`, commit, push to `main` and wait for ci to pass there. The
   release workflow refuses a commit without a successful ci run on `main`.
7. Rehearsal. Run the release workflow by hand on `main`
   (`gh workflow run release.yml --ref main`). It builds `<version>.dev<run number>` and
   uploads it to TestPyPI only. Run [`post-release.yml`](../.github/workflows/post-release.yml)
   by hand with index `testpypi` and that version, and read the page on test.pypi.org. Its
   README links name the tag of that `.dev` version, which is never created, so they never
   work; step 8 checks the release's own.
8. Tag. Push the tag `v0.x.y`. The build job checks ci, the version, the tag and the changelog
   section, builds, and runs `twine check --strict`; then the `pypi` environment waits for me.
   Download the run's `dist` artifact into `dist/` (`gh run download <run id> -n dist -D dist`)
   and check every link the PyPI page takes to the tag. The command prints each with its status
   and fails unless all are 200:

   ```bash
   unzip -p dist/obelize-<version>-py3-none-any.whl '*.dist-info/METADATA' | grep -o 'https://github.com/hakanbogan/obelize/blob/v<version>/[^)" ]*' | sort -u | xargs -n 1 curl -sL -o /dev/null -w '%{http_code} %{url}\n' | awk '{ print } $1 != 200 { bad++ } END { exit bad || NR == 0 }'
   ```

   Approve it only once that passes and the tag's own ci run, macOS included, is green.
9. Attestations. For both files, the provenance must name the repository `hakanbogan/obelize`,
   the workflow `release.yml` and the environment `pypi`:

   ```bash
   curl -s https://pypi.org/integrity/obelize/<version>/<file>/provenance \
     | jq '.attestation_bundles[0].publisher'
   ```

   The project links in the PyPI sidebar should show as verified.
10. Install. Run `post-release.yml` with index `pypi` and the version. It installs with
    uvx, `uv tool install`, pipx and pip on Linux, macOS and Windows, and runs `--version`, `--help`,
    `pack validate` and a scan of `examples/quickstart`. On my own machine,
    `uvx --refresh obelize@<version> --version` must print the version.
11. GitHub release. Read the release the workflow created from the changelog section, with
    `dist/` attached.
12. Announcement. The repository link, a 60-90 second recording, the technical write-up, the
    benchmark table with every `n` and a list of what obelize does not do.
    [PRODUCT.md](PRODUCT.md#what-would-make-this-a-product) says how the benchmark result
    shapes it. For 0.1.0 the new public repository and the PyPI upload happen on the same day,
    public first.

## When a release goes wrong

If a run stops after a file reached PyPI, use "Re-run failed jobs" on that run within 7 days,
while its `dist` artifact is kept. PyPI accepts a file it already holds only with the same
bytes, and the re-run uploads the same artifact. Never delete the tag to build again.

If only the GitHub release failed, create it by hand from the changelog section:

```bash
gh release create v<version> dist/* --verify-tag --notes-file <section>.md
```

A broken release is yanked on PyPI, with the reason, and the fix ships as the next version. It
is never deleted: PyPI takes each file name once, even after a deletion, so the same version
can never be uploaded again.

## Pre-flight

Step 4 catches what a checkout hides: missing package data, an import that only works from an
editable install, or a dependency only the development environment has.

```bash
# Build with the release's backend, and check the files as the upload does.
UV_BUILD_CONSTRAINT=.github/build-constraints.txt uv build
uvx --from twine==7.0.0 --with packaging==26.2 twine check --strict dist/*

# Install the wheel where nothing else is installed, at both ends of the supported range,
# and run the example.
for image in python:3.12-slim python:3.14-slim; do
  docker run --rm -v "$PWD:/w:ro" "$image" bash -c '
    set -e
    python -m venv /tmp/v
    /tmp/v/bin/pip install --quiet --no-cache-dir /w/dist/obelize-*.whl
    /tmp/v/bin/obelize --version
    /tmp/v/bin/obelize --help > /dev/null
    cp -r /w/examples/quickstart /tmp/app
    /tmp/v/bin/obelize scan --repo /tmp/app
    /tmp/v/bin/obelize fix --repo /tmp/app
  '
done

# An Intel Mac installs from wheels alone, so it needs no Rust compiler for libcst.
for python in 3.12 3.13 3.14; do
  uv pip compile pyproject.toml --quiet --python-version "$python" \
    --python-platform x86_64-apple-darwin --only-binary :all: > /dev/null
done

# The suite passes on the libcst an Intel Mac installs; `uv sync` restores the lock's.
uv run --with 'libcst==1.8.6' pytest
uv sync
```

`obelize --version` must print the version being released, and `obelize --help` must return in
well under 300 ms.

Python 3.15 joins the supported range, classifier included, once the pydantic-core that a
stable pydantic pins has cp315 wheels; without them a 3.15 install compiles pydantic-core with
Rust.

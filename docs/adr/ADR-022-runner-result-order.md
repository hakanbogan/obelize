# ADR-022: Runner and result order

## Status

Accepted; amended by ADR-050 and ADR-052.

## Decision

### D1. The parent reads and prefilters; only a candidate crosses into a worker

The parent reads and hashes every selected file once (`runner.read`, shared by every pack of a run,
keeping bytes only where a pack could look) and finishes the unreadable and eliminated ones itself; only a prefilter survivor reaches a
worker, which is then a pure function of `(path, bytes, spec)`. So the
threshold counts candidates, not selected files (the prefilter removed 97.81% of
a real tree), and the hash and the analysis describe one read. The survivors'
bytes are held until their worker returns.

### D2. Bytes go in, plain data comes out, and the parent re-validates

A worker receives `(path, sha256, bytes)` and returns plain data
(`runner.payload`, read back by `runner.restore`); no libcst node crosses. The
parent re-validates each plan through `ImpactPlan.model_validate`, so ADR-010
F-1 is checked on the far side of the process boundary.

### D3. `spawn` on every platform, and an initializer rather than per-task arguments

`spawn`, explicitly, on Linux too: `fork` is unsafe in a process with threads,
and a forked child inherits the parent's hash seed. The spec is set
once per worker by an `initializer` rather than pickled with every task. No
behavioural test tells `spawn` from `fork` in a suite without threads.

### D4. The total order is `(path bytes, sha256)`, over file results

`runner.ordered` sorts `FileResult`s by `(os.fsencode(path), sha256)`, because a
path is unique within one root and not across two (C-12); an unread file hashes
to the empty string. `Scan.findings` sorts by `Finding.sort_key`, on the `str`
path, which agrees because UTF-8 keeps code-point order and the walker refuses
a name that is not valid UTF-8 (ADR-016).

### D5. The default leaves one core for the parent

The default worker count is `max(1, min(8, cpu_count - 1))`, because the parent
reads, hashes, prefilters, pickles and re-validates: on the two-core CI runner
`min(8, cpu_count)` reached parity only at 128 candidates, while on eight cores,
with a core to spare, parity came at 24. On two cores the default is one
worker, the in-process path. A typed `--jobs` is used as typed.

### D6. The threshold is 32 candidates, and it governs the default only

`POOL_THRESHOLD` is 32: on eight-core Apple silicon, the first size at which the
pool won in every configuration with a core to spare (1.12x at two workers to
1.33x at seven), where 24 was parity (0.98x to 1.09x). It applies only when
`--jobs` is not given. `bench/crossover.py`, run by
`.github/workflows/crossover.yml`, re-measures it.

### D7. A pool that cannot start is not caught

`BrokenProcessPool` propagates: this interpreter cannot be re-created (obelize
reached through a `sys.path` shim, say), and an in-process fallback would hide
the defect behind a slow scan. `--jobs 1` is the published way around it.

### D8. The manifest pass is the reduce step, and the runner sorts what it feeds it

The manifest pass (`survey`, then `plan`) runs once, in the parent, after every
file has a plan, since its question is about every file. The runner orders the
file results and passes the manifest paths unsorted: `manifests.plan` sorts its
own rows and is order-independent, and a test shuffles both lists to pin that
the whole scan is.

### D9. A file result carries the receiver records

`FileResult.receivers` carries the `Receiver` records across the boundary,
because `escape_lines` is the evidence for a group's bail and `Binding` does
not carry it; without them a report would resolve the file a second time.

### D10. The oracle runs the runner

`tests/oracle/harness.py` calls `runner.scan`, so the answer keys grade the
composition that ships. `tests/oracle/test_scan_determinism.py` re-runs the
cases in one process and in the pool, under three `PYTHONHASHSEED` settings in
separate interpreters, over a shuffled walk and over a two-root path collision.

## Consequences

- A script that starts a scan at module level in `__main__` needs the usual
  `if __name__ == "__main__":` guard, or each `spawn` child re-executes it.
  `python -m obelize` needs none, since `spawn` never re-runs a package's
  `__main__.py`.
- Peak memory is the sum of the candidates' sizes, each bounded by
  `max_file_bytes`; streaming submission would bound it if a repository needs it.
- A typed `--jobs` above the free cores is obeyed and can be slower: eight
  workers on a two-core runner ran at 0.19x to 0.66x of one process.
- Inside a container with a CPU quota `os.cpu_count()` reports the host's cores,
  so the default can over-subscribe; `os.process_cpu_count()` (3.13+) is the
  change a measurement there would justify.
- The worker count is printed in `REPORT.md`, not recorded in `run.json`.

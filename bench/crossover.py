"""Where starting processes begins to pay for itself, measured rather than assumed.

The sweep behind `obelize.scan.runner.POOL_THRESHOLD` (ADR-022 D6), rerunnable on any machine.
Deliberately not a test (timing on a shared runner is flaky); `.github/workflows/crossover.yml`
runs it on demand.

Usage::

    uv run python bench/crossover.py [--sizes 8,16,24,32] [--jobs auto,8] [--repeat 3]

Every corpus file passes the prefilter on purpose: the threshold counts candidates.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# A fully resolving legacy module, so each worker does a real file's work.
SOURCE = ROOT / "examples" / "gemini-legacy-app" / "summarizer" / "conversation.py"
PACK = "gemini/google-generativeai-to-google-genai"


def corpus(directory: Path, count: int) -> None:
    """`count` copies of `SOURCE`, each under a name of its own."""
    body = SOURCE.read_bytes()
    for index in range(count):
        (directory / f"module_{index:05d}.py").write_bytes(body)


def measure(root: Path, repeat: int, jobs: int) -> float:
    """The best of `repeat` scans, in milliseconds. Best, because noise is one-sided."""
    from obelize.models import Config
    from obelize.packs import loader
    from obelize.scan import runner

    spec = loader.to_scan_spec(loader.load(PACK))
    config = Config()
    timings: list[float] = []
    for _ in range(repeat):
        started = time.perf_counter()
        runner.scan(root, config, spec, jobs=jobs)
        timings.append((time.perf_counter() - started) * 1000)
    return min(timings)


def sweep(sizes: list[int], jobs: list[int | None], repeat: int) -> int:
    """Time serial against pooled per corpus size, one table per worker count.

    The default and a typed `--jobs 8` differ on a two-core runner, where the pool may never win,
    so both are measured.
    """
    from obelize.scan import runner

    print(f"python {sys.version.split()[0]}  cores={os.cpu_count()}  repeat={repeat}  best of each")
    print(f"corpus: {SOURCE.relative_to(ROOT)}")
    print(
        f"shipping POOL_THRESHOLD={runner.POOL_THRESHOLD}, default jobs={runner.worker_count(None)}"
    )
    for count in jobs:
        workers = runner.worker_count(count)
        label = f"{workers} (the default)" if count is None else str(workers)
        print()
        print(f"--- jobs={label} ---")
        if workers == 1:
            print("one worker is the in-process path; there is nothing to compare")
            continue
        print(f"{'n':>6}  {'serial ms':>10}  {'pooled ms':>10}  {'speedup':>8}")
        crossover: int | None = None
        for size in sizes:
            directory = Path(tempfile.mkdtemp(prefix="obelize-crossover-"))
            try:
                corpus(directory, size)
                serial = measure(directory, repeat, jobs=1)
                pooled = measure(directory, repeat, jobs=workers)
            finally:
                shutil.rmtree(directory, ignore_errors=True)
            speedup = serial / pooled
            if crossover is None and speedup > 1.0:
                crossover = size
            print(f"{size:>6}  {serial:>10.1f}  {pooled:>10.1f}  {speedup:>7.2f}x")
        print(f"first size where the pool wins: {crossover}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sizes", default="4,8,12,16,20,24,32,48,64")
    parser.add_argument(
        "--jobs",
        default="auto",
        help="comma-separated worker counts; `auto` is the shipping default",
    )
    parser.add_argument("--repeat", type=int, default=3)
    arguments = parser.parse_args(argv)
    sizes = [int(value) for value in arguments.sizes.split(",") if value]
    jobs = [None if value == "auto" else int(value) for value in arguments.jobs.split(",") if value]
    return sweep(sizes, jobs, arguments.repeat)


if __name__ == "__main__":
    raise SystemExit(main())

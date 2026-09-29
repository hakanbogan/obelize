"""Ignores SIGTERM, which is what makes the second signal necessary.

A process that catches the first signal and does not act on it is the reason
ADR-007 escalates rather than sending one signal and hoping. Given a `marker`,
it first starts a child that inherits the ignored SIGTERM and writes `marker`
if its sleep ever finishes, so only a second signal to the whole group ends
both; `armed` is followed by the child's pid. Nothing in the answer key uses
this: the grace period is a mechanism rather than a decision, so it is graded
in `tests/unit/test_verify_runner.py`, which shortens the grace period so the
test does not wait out the real one.
"""

import signal
import subprocess
import sys
import time

signal.signal(signal.SIGTERM, signal.SIG_IGN)
children = []
if len(sys.argv) > 2:
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys, time; time.sleep(float(sys.argv[1])); "
            "open(sys.argv[2], 'w', encoding='utf-8').write('survived')",
            sys.argv[1],
            sys.argv[2],
        ]
    )
    children.append(child.pid)
print("armed", *children, flush=True)
time.sleep(float(sys.argv[1]))

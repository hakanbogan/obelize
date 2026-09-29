"""Spawns a child in a session of its own, which a group kill cannot reach.

The child inherits this process's stdout and holds it open. `killpg` reaches
only this process's group, so no end-of-file follows the kill: a reader whose
only stopping condition were end-of-file would wait for ever, having already
killed everything it knows about. This is the one shape that makes the drain
deadline load-bearing rather than tidy, and it is graded in
`tests/unit/test_verify_runner.py`, which shortens that deadline and then
cleans the child up.
"""

import subprocess
import sys
import time

child = subprocess.Popen(
    [sys.executable, "-c", "import sys, time; time.sleep(float(sys.argv[1]))", sys.argv[1]],
    start_new_session=True,
)
print("child", child.pid, flush=True)
time.sleep(float(sys.argv[1]))

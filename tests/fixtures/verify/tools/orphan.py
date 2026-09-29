"""Spawns a child that outlives it, prints the child's pid, then sleeps.

This is the shape TM-10 is about. The child inherits this process's stdout, so
killing *this* process leaves the pipe open and a reader waiting for an EOF
that never comes; only killing the process group closes it. The child writes
`marker` when its sleep finishes, so a group kill that did not work leaves
evidence behind rather than merely taking longer.
"""

import subprocess
import sys
import time

seconds, marker = sys.argv[1], sys.argv[2]
child = subprocess.Popen(
    [
        sys.executable,
        "-c",
        "import sys, time; time.sleep(float(sys.argv[1])); "
        "open(sys.argv[2], 'w', encoding='utf-8').write('survived')",
        seconds,
        marker,
    ]
)
print("child", child.pid, flush=True)
time.sleep(float(seconds))

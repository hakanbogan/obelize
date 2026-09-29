"""Starts a child that holds the pipe, and exits before the child does.

The child is in this process's group and inherits its stdout, so the pipe stays
open after this process has exited with its own code. A reader waiting for an
end-of-file would sit out the whole deadline and call a suite that finished a
timeout (vpr:VPR-04). The child inherits the ignored SIGTERM, so only a SIGKILL
ends it, and it writes `marker` if its sleep ever finishes, so a group that was
not ended leaves evidence behind.
"""

import signal
import subprocess
import sys

code, seconds, marker = int(sys.argv[1]), sys.argv[2], sys.argv[3]
signal.signal(signal.SIGTERM, signal.SIG_IGN)
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
sys.exit(code)

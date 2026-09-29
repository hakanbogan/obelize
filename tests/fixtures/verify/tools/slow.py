"""Prints one line, then sleeps past any timeout this corpus sets.

The line is flushed before the sleep so that a timed-out command still has
output: what a runaway command printed before it was killed is the only thing
its report can say about it.
"""

import sys
import time

print("started", flush=True)
time.sleep(float(sys.argv[1]))

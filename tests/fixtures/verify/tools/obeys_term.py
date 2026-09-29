"""Ends with code 0 when it is told to stop, and otherwise outlives any deadline.

A command stopped at its deadline can still exit 0 (vpr:VPR-04). The code it
leaves after the signal is not a verdict, and the row says `timeout` whatever
the code is.
"""

import signal
import sys
import time

signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
print("waiting", flush=True)
time.sleep(float(sys.argv[1]))

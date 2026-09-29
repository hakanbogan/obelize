"""Closes its output and keeps running, which is the timeout's other shape.

A reader waiting for end-of-file gets one immediately and learns nothing: the
program is still there. A runner that treated end-of-file as "it finished"
would wait for this process for ever, and `verify.timeout_s` would be a setting
that works only for programs that are polite about their pipes.

Both descriptors are closed, because stderr is a duplicate of the same pipe --
closing one of them produces no end-of-file at all.
"""

import os
import sys
import time

sys.stdout.write("before\n")
sys.stdout.flush()
os.close(1)
os.close(2)
time.sleep(float(sys.argv[1]))

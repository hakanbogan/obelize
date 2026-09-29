"""Exits non-zero the way a failing test suite does, and writes to stderr.

The exit code is 3 rather than 1 so that a `CommandResult` carrying the
program's own code can be told apart from one carrying a truthy default, and
the message goes to stderr because ADR-007 captures the two streams together:
a run whose only evidence is on stderr must still have evidence.
"""

import sys

print("boom", file=sys.stderr)
sys.exit(3)

"""Reports the four things ADR-007 promises about how a command is run.

`OBELIZE_RUN=1` is added, the rest of the environment is inherited, the working
directory is the repository root, and stdin is closed -- a command that prompts
must meet an EOF rather than hang a run that nobody is watching.
"""

import os
import sys

print("OBELIZE_RUN=" + os.environ.get("OBELIZE_RUN", "<unset>"))
print("CWD=" + os.getcwd())
print("STDIN=" + repr(sys.stdin.read()))
print("INHERITED=" + os.environ.get("OBELIZE_SAMPLE_INHERITED", "<unset>"))

"""Starting a verification command, reading its output, and stopping all it started.

`close` releases what `spawn` holds for a command, whatever ended its run. `WORKER_LIMIT` is the
most workers a process pool takes here, or `None` for no limit. `git`, `locate` and
`program_name` say which program runs, and `command_problem` why a configured command would not
read here as written.
"""

import sys

if sys.platform == "win32":
    from obelize.native.processes_windows import (  # pragma: windows-only
        WORKER_LIMIT,
        close,
        command_problem,
        end,
        git,
        locate,
        program_name,
        read,
        spawn,
        stop,
    )
else:
    from obelize.native.processes_posix import (  # pragma: posix-only
        WORKER_LIMIT,
        close,
        command_problem,
        end,
        git,
        locate,
        program_name,
        read,
        spawn,
        stop,
    )

__all__ = [
    "WORKER_LIMIT",
    "close",
    "command_problem",
    "end",
    "git",
    "locate",
    "program_name",
    "read",
    "spawn",
    "stop",
]

# ADR-049: The platform seam

## Status

Accepted.

## Decision

Two guarantees rest on calls whose meaning depends on the operating system:
obelize never reads or writes through a link, and a verification command stops
together with everything it started. Those calls go through
`src/obelize/native/`, one module per mechanism:

- `files`: the opens, creates, renames and deletes that the path guard in
  `fsutil.py` and the run folder in `evidence/folder.py` make. Each name is
  opened relative to its parent directory and never through a link, and the
  root the user gave is followed. `fsutil.read` is the exception: it opens by
  path and guards only the last component. `files.reserved` names what a
  platform opens as something else: nothing on POSIX, and on Windows what
  CPython 3.13's `ntpath.isreserved` refuses (a device such as `aux.py`, a `:`
  stream, a trailing dot or space) plus a backslash or a drive. The path guard,
  the walker, the edit guard, `undo` and `verify` refuse such a name before
  anything reads it, and the models stay the same on every platform, so a
  record written on one is valid on the other. A Windows junction is a link
  wherever a symlink is: `fsutil.linked`, the fallback walk and the run folder
  ask `st_reparse_tag`, `os.path.isjunction` or `Path.is_junction`, which
  answer nothing on POSIX.
- `processes`: starting a verification command, reading its output against a
  deadline, stopping it with everything it started, and releasing what was
  held for it however its run ended (`close`). `WORKER_LIMIT` is the
  most workers a process pool takes: none on POSIX, 61 on Windows, where
  `--jobs` above it is a usage error rather than a traceback. On Windows,
  where `CreateProcess` looks in Python's directory and the current one before
  `PATH`, a bare argv[0] and git (once) are looked up on the command's own
  `PATH` alone, an argv[0] with a directory in the command's directory, a git
  found nowhere fails closed, and only an `.exe` or `.com` runs, judged after
  the trailing dots and spaces Windows drops, so a batch file, which `cmd.exe`
  would parse again, and a name relative to a drive's current directory are
  refused. The DLLs git loads are not looked up that way: Windows looks in the
  current directory for one it finds neither beside git nor in the system
  directories, and git's is the repository once `-C` has moved it there, so a
  DLL placed in the repository can be loaded. A backslash `shlex` would drop
  is refused where configuration is read and never in a recorded command, so a
  run folder loads on both platforms.
- `console`: what the standard streams encode. A redirected Windows stream
  encodes in the ANSI code page, so there stdout and stderr are made UTF-8 at
  startup; POSIX follows the locale.
- `shell`: how a command printed for the user to copy, such as a `Next:`
  line, quotes an argument. POSIX takes `shlex.quote`; `cmd.exe` reads no
  single quote, so Windows takes double quotes, escaped as
  `subprocess.list2cmdline` escapes them, around any argument that holds
  whitespace or a character `cmd.exe` or PowerShell acts on. A path the
  summary joins under the run folder takes the platform's separator
  throughout.

Each module picks its implementation once, at import, by `sys.platform`. The
code that calls it keeps its own logic and holds no platform branch, and the
two import lines of a selector are the only place a coverage pragma may name a
platform: `windows-only` or `posix-only`, which `coverage-conditional-plugin`
reads. The plugin also leaves the other platform's modules out of each run, so
each platform is held to 100% of the code it runs.

What obelize writes is the same bytes on every platform. Evidence files and
the `--json` document are encoded to UTF-8 and written as bytes, never through
a text stream, which on Windows would end each line with CRLF.

The POSIX implementations, `files_posix.py` and `processes_posix.py`, make the
`openat`-style calls with `O_NOFOLLOW`, start the command in its own session
and signal its whole process group. One exclusive create serves both writers:
`O_CREAT | O_EXCL` already fails on a name that exists, a link included, so it
needs no `O_NOFOLLOW`.

`files_windows.py` makes the NT form of each of those calls, through ctypes in
`_win32.py`, so it adds no dependency. The root is opened with `CreateFileW`,
which follows a link. Every name below it is opened with `NtCreateFile`
relative to its parent's handle, with `FILE_OPEN_REPARSE_POINT` and
`OBJ_CASE_INSENSITIVE`, so a symbolic link or a junction is opened as itself.
Where a directory or a file to read is asked for, a reparse point that names
another path fails with `ELOOP`, and a file where a directory is asked for
with `ENOTDIR`, so the refusals read as they do on POSIX. Any other reparse
point, such as a OneDrive placeholder, is opened again through its filter and
must be the same file. The exclusive create is `FILE_CREATE`. A rename or a
delete is `NtSetInformationFile` on the open file, and a rename names its
target relative to the parent. A volume that reports POSIX semantics takes
`FileRenameInformationEx` and `FileDispositionInformationEx`, which replace or
delete a file another program holds open and ignore the read-only attribute.
Any other volume takes the classic classes, and a delete there clears the
read-only attribute first. The choice is made once, when the root is opened:
a mount point is a junction, so nothing below a root is on another volume.
`remove_tree` lists each directory from its handle and deletes a link below it
as a link. A name that is empty, `.` or `..`, or that holds a separator or a
colon, is `EINVAL` before any call, since relative to a handle an empty name
opens the directory itself. A `files.Handle` is an opaque open directory,
because a Windows handle is no descriptor `os.fstat` or `os.close` could take.
The read-only attribute is all a write keeps of a mode there. `_win32.py`
imports on any system, where its structures are checked against the
documented 64-bit layouts and its table, which gives each NT status the errno
POSIX raises for the same failure, is tested; only a Windows run measures it.

`processes_windows.py` gives each command a job object of its own, through
`_win32.py`. The command is created suspended, assigned to the job, and only
then resumed with `NtResumeProcess`, so nothing it starts can be outside the
job. It is also in a new process group, for which Windows disables Ctrl+C, so
an interrupted obelize ends the job itself. If the job cannot be made, the
command is never started, and if the job cannot take it, it is killed before
it ran; either way it is recorded as `command_not_executable`. The job sets
`KILL_ON_JOB_CLOSE` and no breakaway flag. At the deadline the job is
terminated at once, with no grace period, since nothing in a job can ignore
that. Every process in it exits with
`STATUS_CONTROL_C_EXIT`, so a killed command's code is 3221225786 rather than
negative. A leftover after the command's exit is ended the same way, and each
wait for the job to empty is bounded. `close` terminates the job and closes its
handle whatever ended the run, and if obelize dies the kernel closes the handle
and `KILL_ON_JOB_CLOSE` ends everything in the job. None of the three gaps
[ADR-048](ADR-048-accepted-gaps-in-0-1-0.md) accepts for TM-10 on POSIX
therefore exists on Windows. A process the command has a broker start, such as
WMI, Task Scheduler, a COM server, `runas`, `wsl` or `docker`, is that
service's child, outside the job, and outlives the command. `select` takes no
pipe on Windows, so the pipe is made non-blocking and polled.

The claim that obelize runs on Windows rests on the suite, which CI runs on
GitHub's `windows-latest` runner for the oldest and newest supported Python. A
real console, a OneDrive folder and a path longer than 260 characters are not
covered.

## Consequences

- A difference between platforms that these guarantees meet is handled in one
  package, and a new mechanism gets its own module there.
- The Windows modules export the same names as the POSIX ones. `close`,
  which the runner calls once per command, releases nothing on POSIX.
- The seam is tested through its callers: the tests of the path guard, the run
  folder and the verification runner fail when a call in the seam loses its
  link check, its parent directory or its group kill.
- The Windows calls run only on Windows. Each test of them there first makes
  the plain call it stands in for and shows that it escapes, so a passing run
  has refused something.

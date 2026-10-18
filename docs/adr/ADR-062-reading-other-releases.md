# ADR-062: Reading other releases

## Status

Accepted.

## Decision

To migrate a library that has no pack, obelize reads two releases of it: what each exports, and
what changed between them. This ADR records how those releases are fetched, opened and read. Each
decision is numbered as it lands. Nothing here installs, builds or runs a stranger's code, and
nothing here is reached by `scan` or `fix`, which stay free of the network.

### D1. The network is a seam with a cache and a short list of hosts

`obelize.net` is the one place a request to an index leaves the process. A request names its
`Accept` type, a byte limit and a deadline, and an answer is kept per user for an hour (a project
page) or for good (a file, which is kept under its hash). A redirect is followed only to the same
scheme and host, so an index cannot send obelize to another server, and a credential given for the
index is sent to the index's host and no other. Offline, the cache answers or the request fails with
a reason; the person can always see which hosts a command would reach before it reaches them.
Requests carry no cookie, no body and an identifying `User-Agent` that names obelize and its
version.

The model adapter (ADR-003) keeps its own client, which sends no proxy and follows no redirect,
because it carries a key. The two are not merged: what a model may do with a key and what an index
may do with a URL are different promises.

### D2. A file is the bytes whose hash the index gave

`obelize.index` reads the Simple JSON API (PEP 691) for a project's files and PyPI's JSON API,
where the index has one, for its classifiers, project links and advisories. A file the index lists
with no sha256 is not offered. `obelize.release` downloads a file and compares its sha256 with the
one the page gave, every time, including when the bytes came from the cache, so a poisoned cache
entry is refused like a poisoned download. A withdrawn (yanked) release is never chosen, a
pre-release only when nothing else exists, and a file the person's Python cannot install is skipped.
The file read is a wheel that runs anywhere, then any other wheel, then the source distribution:
the source of a wheel is what a user imports, and that is the surface to compare.

### D3. An archive is opened for source and nothing else

`obelize.archive` writes the Python source of a release and the files that describe a distribution
(`METADATA`, `RECORD`, `top_level.txt`, `entry_points.txt`) to a new directory, and refuses the rest
of what an archive can carry. It stops, with a message, at a name that leaves the directory, a name
with a drive letter or a backslash, a name Windows reads as a device, two names that are one on a
system that ignores case, a link or a device, a file or an archive past its size, more files than
a library has, and an archive that unpacks to far more than it holds. Files that are neither source
nor description are counted and left unwritten. Opening is not building: no `setup.py` runs and no
build backend is called.

### D4. The surface of a release is read statically, in a child process

`obelize.apidiff` reads the public API of a release with griffe, which parses source and resolves
`__all__`, re-exports and bases without importing the library. It runs in a child process started
with `-P` and an environment holding only what Python needs, over a directory that was unpacked and
never executed, with a memory limit and a deadline, because griffe parses with the interpreter's
`ast` and a stranger's file can exhaust it. The child prints JSON, which the parent reads as data
into plain objects. `allow_inspection` is off, so a compiled module is a name without a signature
and is reported as unseen, not as removed.

Two things griffe does not give are read from the files directly: the message of a call to
`warnings.warn` with a deprecation category (and of a `@deprecated` decorator), which is the
library's own account of what replaces a name, and whether a function is a stub, which decides
whether a pairing of two names by signature says anything. The comparison itself is obelize's:
it pairs only a name that kept its signature and has a body, or one whose deprecation message
names a single name that exists in the newer release, and reports everything else as removed
for a person to read. A change is a closed, internal vocabulary and not a promise to the user.

### D5. griffe is the seventh runtime dependency

`griffelib` (ISC licence, from the mkdocstrings project, pure Python, with no dependency of its
own) brings the budget of ADR-005 to seven. The standard library's `ast`
would parse the files, but resolving a re-export through three modules, an `__all__` built from
another, and the bases of a class is what griffe is for and what a comparison needs to be right;
writing it would add more code to audit than the dependency does. It is imported only in the child
process, so `obelize --help` and the commands that do not read a release do not load it.

## Consequences

Reading a release is the first thing obelize does that is not a function of the repository and the
installed pack, so the hosts it reaches, the cache it keeps and the files it writes are in
`docs/THREAT_MODEL.md` and `docs/PRIVACY.md` with the first command that uses them. The seam can
be pointed at a local index in tests, so no test needs the network.

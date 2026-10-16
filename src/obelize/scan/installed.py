"""What else in a repository can decide which release of the legacy distribution is installed.

A declaration that names no version installs the pack's newest release only where nothing else
decides: a lock, a constraints file, an index setting, a version written outside the manifests, an
environment kept in the repository, code that uses what that release removed. `contrary` names the
first path that says another release is in use. Every check fails closed (a manifest it cannot
read is evidence, and so is a name no report can spell, which hides what is under it), but one: a
listed file that cannot be read, or is over `_LIMIT`, is not searched for a version. One over
`max_file_bytes` is searched in windows and never held whole, since that limit bounds what a scan
holds. Files are opened through `parse.contents`, or `fsutil.windows` for those, only after the
walk's own refusal check.

Nothing outside the repository is read, on purpose: no `PIP_*` variable, no `pip.conf` in the home
directory, no index. The machine that scans is not the one that installs, and a finding is the same
on every machine that scans the same files.
"""

from __future__ import annotations

import os
import posixpath
import re
import tomllib
from typing import TYPE_CHECKING, Any, Final

from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

from obelize import fsutil
from obelize.models import printable
from obelize.scan import manifests, parse, runtime

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

    from obelize.models import Finding, ScanSpec
    from obelize.scan.walker import Walk

# A requirement option that cannot move the release: another file the scan reads, a local project,
# a further index (the newest release across all of them wins) or a trusted host.
_FILES: Final = frozenset({"-r", "--requirement", "-c", "--constraint"})
_HARMLESS: Final = frozenset({"--extra-index-url", "--trusted-host"})
_EDITABLE: Final = frozenset({"-e", "--editable"})
_OPTION: Final = re.compile(r"(?P<flag>--?[A-Za-z][\w-]*)(?:[=\s]+(?P<argument>.*))?$")

# One line only, and a version starts with a digit: a markdown quote or an `<https://...>` link
# after the name is prose, not a release.
_OPERATOR: Final = r"(?:===|==|~=|!=|<=|>=|<|>)"
_CLAUSE: Final = rf"{_OPERATOR}[ \t]*\d[\w.*+!]*"

_RESOLVER_FILES: Final = ("pyproject.toml", "Pipfile")
# Where a key or a string of such a file can be a dependency: PEP 621's and 735's and the dependency
# managers' own tables (a key there can be a distribution no row carries: a source, an override).
# Not what a tool that reads source holds (isort, Ruff, mypy) or a project's own text. In a Pipfile
# every table is one, a category of its own (`[docs]`) too, but these.
_DEPENDING: Final = (
    ("project", "dependencies"),
    ("project", "optional-dependencies"),
    ("dependency-groups",),
    ("tool", "uv"),
    ("tool", "poetry", "dependencies"),
    ("tool", "poetry", "dev-dependencies"),
    ("tool", "poetry", "group"),
    ("tool", "poetry", "extras"),
    ("tool", "pdm"),
    ("tool", "hatch"),
    ("tool", "pixi"),
    ("tool", "rye"),
)
_PIPFILE_OTHER: Final = frozenset({"source", "requires", "scripts", "pipenv"})
_PYPI: Final = "https://pypi.org/simple"
# Settings that hold a release back, take it from elsewhere or pick the lowest one.
_SETTINGS: Final = (
    ("tool", "uv", "exclude-newer"),
    ("tool", "uv", "resolution"),
    ("tool", "uv", "index-url"),
    ("tool", "uv", "find-links"),
    ("tool", "uv", "no-index"),
    ("tool", "uv", "pip"),
    ("tool", "poetry", "source"),
    ("tool", "pdm", "source"),
)

_UTF_16: Final = (b"\xff\xfe", b"\xfe\xff")

# A file over `max_file_bytes` is searched for a version in windows of this size, which repeat this
# much of the one before so that a mention is whole in one of them, up to this size: past it a file
# is not searched. A window reads only the mentions that start in it up to this far from its end.
_WINDOW: Final = 1 << 20
_OVERLAP: Final = 1 << 12
_LIMIT: Final = 32 << 20

# A virtual environment kept in the repository, and where one holds the installed distributions.
_ENVIRONMENTS: Final = (".venv", "venv", "env")
_PACKAGES: Final = (("lib", "site-packages"), ("Lib", "site-packages"))


def contrary(
    root: Path,
    walk: Walk,
    contents: parse.Contents,
    found: Sequence[manifests.Declaration],
    findings: Sequence[Finding],
    spec: ScanSpec,
) -> str:
    """The first path that says a release the run does not take is in use, or `""`: other than
    `spec.legacy_newest`, or, where the pack has none, outside `spec.legacy_range`."""
    taken = spec.legacy_newest or SpecifierSet(spec.legacy_range)
    name = canonicalize_name(spec.legacy_distribution)
    rows = [row for row in found if row.name == name]
    spelled = "[-_.]+".join(re.escape(part) for part in name.split("-"))
    return printable(
        _removed(findings, spec)
        or _unread(walk, contents, rows, spelled)
        or _settings(walk, contents)
        or _hidden(walk)
        or _mentioned(root, walk, contents, spelled, taken)
        or _on_disk(root, walk, rows, spelled, taken)
    )


def _hidden(walk: Walk) -> str:
    """A listed file that can pin or constrain a release, or a name no report can spell, under
    which anything may be.

    A constraints file or a pip-tools input is one where no manifest was read from it: a link, or
    a file in a directory the scan leaves out (`.ci/`, `vendor/`).
    """
    read = {*walk.manifests, *walk.excluded_manifests}
    return next(
        (
            path
            for path in walk.listed
            if manifests.is_lock(path)
            or (manifests.layout(path) == "unwritten" and path not in read)
        ),
        "",
    ) or next((row.path for row in walk.skipped if row.reason == "unusable_name"), "")


def _removed(findings: Sequence[Finding], spec: ScanSpec) -> str:
    """Code that uses a name the newest release no longer defines cannot run on it."""
    return next(
        (
            row.path
            for row in findings
            if row.kind != "manifest"
            and row.scan_status != "not_a_usage"
            and row.symbol in spec.legacy_lacks
        ),
        "",
    )


def _unread(
    walk: Walk, contents: parse.Contents, rows: Sequence[manifests.Declaration], spelled: str
) -> str:
    """A manifest that cannot be read whole, names the distribution where no row was read, or has
    a pip option that can change where a release comes from.

    A manifest the user excluded is judged by its options alone: no row was read from it, and a
    version it names is judged with every listed file.
    """
    named = re.compile(rf"(?<![\w-]){spelled}(?!\w|-[a-z])", re.IGNORECASE)
    for path in (*walk.manifests, *walk.excluded_manifests):
        data, _refused = contents(path)
        whole = path in walk.manifests
        # A NUL byte is UTF-16 (`pip freeze` on Windows): every line would read as nothing.
        if data is None or b"\0" in data:
            if whole:
                return path
            continue
        if manifests.layout(path) == "toml":
            # Counted, not placed by line: a row stands for one name, so more names than rows leave
            # one unread. A file `_settings` cannot parse has no name to count.
            counted = _names_in(data, named, posixpath.basename(path) == "Pipfile")
            if whole and counted > sum(row.path == path for row in rows):
                return path
            continue
        pip = manifests.layout(path) in manifests.PIP
        read = {row.line for row in rows if row.path == path}
        for number, line in enumerate(data.decode("utf-8", "surrogateescape").split("\n"), 1):
            body = manifests.PIP_COMMENT.sub("", line) if pip else manifests.uncommented(line)
            if whole and named.search(body) and number not in read:
                return path
            if pip and body.lstrip().startswith("-") and not _harmless(path, body.strip(), walk):
                return path
    return ""


def _names_in(data: bytes, named: re.Pattern[str], pipfile: bool) -> int:
    """How many keys and strings of a TOML file, where a dependency can be declared, name the
    distribution; none where it is not TOML this Python reads."""
    try:
        document = tomllib.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, RecursionError):
        return 0
    found = 0
    pending: list[tuple[Any, tuple[str, ...]]] = [(document, ())]
    while pending:
        node, path = pending.pop()
        if isinstance(node, dict):
            for key, value in node.items():
                pending.append((value, (*path, key)))
                found += _counts((*path, key), key, named, pipfile)
        elif isinstance(node, list):
            pending.extend((item, path) for item in node)
        elif isinstance(node, str):
            found += _counts(path, node, named, pipfile)
    return found


def _counts(path: tuple[str, ...], text: str, named: re.Pattern[str], pipfile: bool) -> bool:
    """Whether `text`, a key or a string at `path`, is a name where a dependency can be declared."""
    place = (
        path[0] not in _PIPFILE_OTHER
        if pipfile
        else any(path[: len(place)] == place for place in _DEPENDING)
    )
    return place and bool(named.search(text))


def _harmless(path: str, option: str, walk: Walk) -> bool:
    found = _OPTION.match(option)
    if found is None:
        return False
    flag, argument = found["flag"], (found["argument"] or "").strip()
    if flag in _FILES:
        return posixpath.normpath(posixpath.join(posixpath.dirname(path), argument)) in set(
            walk.manifests
        )
    if flag in _EDITABLE:
        return "://" not in argument and "+" not in argument.split("/")[0]
    return flag in _HARMLESS


def _settings(walk: Walk, contents: parse.Contents) -> str:
    """A resolver setting in `pyproject.toml` or `Pipfile` that can hold a release back or take it
    from another index; a file that is not TOML this Python reads cannot say."""
    for path in (*walk.manifests, *walk.excluded_manifests):
        base = posixpath.basename(path)
        data, _refused = contents(path)
        if base not in _RESOLVER_FILES or data is None:
            continue
        try:
            document = tomllib.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, tomllib.TOMLDecodeError, RecursionError):
            return path
        indexes = _dig(document, "tool", "uv", "index")
        sources = document.get("source")
        if (
            any(_dig(document, *keys) is not None for keys in _SETTINGS)
            or (isinstance(indexes, list) and any(not _explicit(index) for index in indexes))
            or (
                base == "Pipfile"
                and isinstance(sources, list)
                and any(_index(source) != _PYPI for source in sources)
            )
        ):
            return path
    return ""


def _dig(document: Any, *keys: str) -> Any:
    for key in keys:
        document = document.get(key) if isinstance(document, dict) else None
    return document


def _explicit(index: Any) -> bool:
    return isinstance(index, dict) and index.get("explicit") is True


def _index(source: Any) -> str:
    url = source.get("url") if isinstance(source, dict) else None
    return url.rstrip("/") if isinstance(url, str) else ""


def _mentioned(
    root: Path, walk: Walk, contents: parse.Contents, spelled: str, taken: str | SpecifierSet
) -> str:
    """A version of the distribution written anywhere, in a file or in a file's name, that rules
    the release taken out: `PyPDF2==1.26.0`, `PyPDF2-1.26.0.dist-info`."""
    mention = _mention(spelled)
    vetted = {*walk.files, *walk.manifests}
    for path in walk.listed:
        if _rules_out(os.fsencode(path), mention, taken):
            return path
        # The walk opened and checked only what it selected, so the rest is checked here: a fifo
        # named in the listing would block the read.
        if path not in vetted and fsutil.refusal(root, root / path) is not None:
            continue
        data, refused = contents(path)
        if data is None:
            too_large = any(row.code == "file_too_large" for row in refused)
            if too_large and _searched(root / path, mention, taken):
                return path
            continue
        if data[:2] in _UTF_16:  # a PowerShell `pip freeze > freeze.txt`
            data = data.decode("utf-16", "ignore").encode()
        if _rules_out(data, mention, taken):
            return path
    return ""


def _mention(spelled: str) -> re.Pattern[bytes]:
    return re.compile(
        (
            rf"(?<![\w-]){spelled}(?:\[[^\]\n]{{0,100}}\])?[ \t]*"
            rf"(?P<spec>{_CLAUSE}(?:[ \t]*,[ \t]*{_CLAUSE})*)"
            rf"|(?<![\w-]){spelled}-(?P<release>\d+(?:\.\d+)*)"
        ).encode(),
        re.IGNORECASE,
    )


def _searched(path: Path, mention: re.Pattern[bytes], taken: str | SpecifierSet) -> bool:
    """`_rules_out` over a file too large to hold, a window at a time; a UTF-16 one is read as
    bytes, which finds nothing.

    A mention is read by the window it starts in, up to `_OVERLAP` from its end, where it lies whole
    (the last window reads the rest): cut by an edge it would read as another release, and the next
    window starts on a byte that may be part of a name.
    """
    try:
        window = b""
        for at, window in enumerate(fsutil.windows(path, _WINDOW, _OVERLAP, _LIMIT)):
            if _rules_out(window, mention, taken, min(at, 1), len(window) - _OVERLAP):
                return True
        return _rules_out(window, mention, taken, max(len(window) - _OVERLAP + 1, 0))
    except OSError:  # gone or unreadable since it was listed, as `parse.contents` finds
        return False


def _rules_out(
    data: bytes,
    mention: re.Pattern[bytes],
    taken: str | SpecifierSet,
    start: int = 0,
    stop: int | None = None,
) -> bool:
    """Whether `data` writes a release of the distribution that is not, or may not be, the one
    taken: a release (`3.0.1`), or one of a range of them.

    Only a mention that starts from `start` on, and at or before `stop`, is read.
    """
    for found in mention.finditer(data, start):
        if stop is not None and found.start() > stop:
            return False
        try:
            if found["spec"] is None:
                if _outside(taken, Version(found["release"].decode())):
                    return True
            elif _excludes(taken, SpecifierSet(found["spec"].decode())):
                return True
        except ValueError:  # not a version, or one of more digits than Python converts
            return True
    return False


def _outside(taken: str | SpecifierSet, release: Version) -> bool:
    """Whether `release` is none of the releases taken."""
    return release not in taken if isinstance(taken, SpecifierSet) else release != Version(taken)


def _excludes(taken: str | SpecifierSet, clauses: SpecifierSet) -> bool:
    """Whether `clauses` admit none of the releases taken."""
    if isinstance(taken, SpecifierSet):
        return not runtime.meets((clauses,), taken)
    return not clauses.contains(taken)


def _on_disk(
    root: Path,
    walk: Walk,
    rows: Sequence[manifests.Declaration],
    spelled: str,
    taken: str | SpecifierSet,
) -> str:
    """What the listing may not show, because git ignores it: a lock, or a requirements,
    constraints or pip-tools input file, beside the repository root or a declaring manifest, and
    an environment kept in the root or beside any listed file, with another release."""
    installed = re.compile(
        rf"{spelled}-(?P<release>\d+(?:\.\d+)*)(?:-py[\d.]+)?\.(?:dist|egg)-info", re.IGNORECASE
    )
    listed = set(walk.listed)
    for directory in sorted({"", *(posixpath.dirname(row.path) for row in rows)}):
        for name in _names(root / directory):
            path = posixpath.join(directory, name)
            if path not in listed and (
                manifests.is_lock(path) or manifests.layout(path) in manifests.PIP
            ):
                return path
    # `lexists` first: nearly every directory holds none of the three, and a listing costs more.
    for directory in sorted({"", *map(posixpath.dirname, listed)}):
        for environment in _ENVIRONMENTS:
            here = posixpath.join(directory, environment)
            if not os.path.lexists(root / here):
                continue
            for packages in _site_packages(root / here):
                for name in _names(root / here / packages):
                    found = installed.fullmatch(name)
                    if found and _outside(taken, Version(found["release"])):
                        return posixpath.join(here, packages, name)
    return ""


def _site_packages(environment: Path) -> Iterator[str]:
    """Where an environment keeps its installed distributions, on Windows and elsewhere."""
    yield "Lib/site-packages"
    for name in _names(environment / "lib"):
        if name.startswith("python"):
            yield f"lib/{name}/site-packages"


def _names(directory: Path) -> list[str]:
    """What is in `directory`, listed and never followed; nothing where it cannot be listed."""
    try:
        with os.scandir(directory) as entries:
            return sorted(entry.name for entry in entries)
    except OSError:
        return []


__all__ = ["contrary"]

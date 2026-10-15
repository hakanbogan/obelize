"""What else in a repository can decide which release of the legacy distribution is installed.

A declaration that names no version installs the pack's newest release only where nothing else
decides: a lock, a constraints file, an index setting, a version written outside the manifests, an
environment kept in the repository, code that uses what that release removed. `contrary` names the
first path that says another release is in use. Every check fails closed (a manifest it cannot
read is evidence, and so is a name no report can spell, which hides what is under it), but one: a
listed file over `max_file_bytes` or unreadable is not searched for a version, since no read of a
scan goes past that limit. Files are opened through `parse.contents` only, after the walk's own
refusal check.
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
from obelize.scan import manifests, parse

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
    """The first path that says a release other than `spec.legacy_newest` is in use, or `""`."""
    newest = spec.legacy_newest
    if newest is None:  # pragma: no cover - callers ask `runtime.inferred` first
        return ""
    name = canonicalize_name(spec.legacy_distribution)
    rows = [row for row in found if row.name == name]
    spelled = "[-_.]+".join(re.escape(part) for part in name.split("-"))
    return printable(
        _removed(findings, spec)
        or _unread(walk, contents, rows, spelled)
        or _settings(walk, contents)
        or _hidden(walk)
        or _mentioned(root, walk, contents, spelled, newest)
        or _on_disk(root, walk, rows, spelled, newest)
    )


def _hidden(walk: Walk) -> str:
    """A listed file that can pin or constrain a release, or a name no report can spell, under
    which anything may be."""
    return next((path for path in walk.listed if manifests.is_lock(path)), "") or next(
        (row.path for row in walk.skipped if row.reason == "unusable_name"), ""
    )


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
    a pip option that can change where a release comes from."""
    named = re.compile(rf"(?<![\w-]){spelled}(?!\w|-[a-z])", re.IGNORECASE)
    for path in walk.manifests:
        data, _refused = contents(path)
        # A NUL byte is UTF-16 (`pip freeze` on Windows): every line would read as nothing.
        if data is None or b"\0" in data:
            return path
        pip = manifests.layout(path) in manifests.PIP
        read = {row.line for row in rows if row.path == path}
        for number, line in enumerate(data.decode("utf-8", "surrogateescape").split("\n"), 1):
            body = manifests.PIP_COMMENT.sub("", line) if pip else manifests.uncommented(line)
            if named.search(body) and number not in read:
                return path
            if pip and body.lstrip().startswith("-") and not _harmless(path, body.strip(), walk):
                return path
    return ""


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
    for path in walk.manifests:
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


def _mentioned(root: Path, walk: Walk, contents: parse.Contents, spelled: str, newest: str) -> str:
    """A version of the distribution written anywhere, in a file or in a file's name, that rules
    the newest release out: `PyPDF2==1.26.0`, `PyPDF2-1.26.0.dist-info`."""
    mention = re.compile(
        (
            rf"(?<![\w-]){spelled}(?:\[[^\]\n]{{0,100}}\])?[ \t]*"
            rf"(?P<spec>{_CLAUSE}(?:[ \t]*,[ \t]*{_CLAUSE})*)"
            rf"|(?<![\w-]){spelled}-(?P<release>\d+(?:\.\d+)*)"
        ).encode(),
        re.IGNORECASE,
    )
    vetted = {*walk.files, *walk.manifests}
    for path in walk.listed:
        if _rules_out(os.fsencode(path), mention, newest):
            return path
        # The walk opened and checked only what it selected, so the rest is checked here: a fifo
        # named in the listing would block the read.
        if path not in vetted and fsutil.refusal(root, root / path) is not None:
            continue
        data, _refused = contents(path)
        if data is not None and data[:2] in _UTF_16:  # a PowerShell `pip freeze > freeze.txt`
            data = data.decode("utf-16", "ignore").encode()
        if data is not None and _rules_out(data, mention, newest):
            return path
    return ""


def _rules_out(data: bytes, mention: re.Pattern[bytes], newest: str) -> bool:
    """Whether `data` writes a release of the distribution that is not, or may not be, `newest`."""
    for found in mention.finditer(data):
        try:
            if found["spec"] is None:
                if Version(found["release"].decode()) != Version(newest):
                    return True
            elif not SpecifierSet(found["spec"].decode()).contains(newest):
                return True
        except ValueError:  # not a version, or one of more digits than Python converts
            return True
    return False


def _on_disk(
    root: Path, walk: Walk, rows: Sequence[manifests.Declaration], spelled: str, newest: str
) -> str:
    """What the listing may not show, because git ignores it: a lock, a constraints file or a
    pip-tools input beside the repository root or a declaring manifest, and an environment kept
    there with another release."""
    installed = re.compile(
        rf"{spelled}-(?P<release>\d+(?:\.\d+)*)(?:-py[\d.]+)?\.(?:dist|egg)-info", re.IGNORECASE
    )
    listed = set(walk.listed)
    for directory in sorted({"", *(posixpath.dirname(row.path) for row in rows)}):
        for name in _names(root / directory):
            path = posixpath.join(directory, name)
            if path not in listed and (
                manifests.is_lock(path) or manifests.layout(path) == "unwritten"
            ):
                return path
        for environment in _ENVIRONMENTS:
            here = posixpath.join(directory, environment)
            for packages in _site_packages(root / here):
                for name in _names(root / here / packages):
                    found = installed.fullmatch(name)
                    if found and Version(found["release"]) != Version(newest):
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

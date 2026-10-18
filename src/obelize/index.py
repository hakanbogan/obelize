"""A package index as obelize reads it: the Simple JSON API (PEP 691) for what a project has
released, and PyPI's JSON API, where the index has one, for what the project says about itself.

Reading an index writes nothing and installs nothing. A file is known by the sha256 the index gives,
which is checked when the file is read (`obelize.release`); an answer without one is not offered.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Literal
from urllib.parse import urljoin, urlsplit

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import (
    InvalidSdistFilename,
    InvalidWheelFilename,
    canonicalize_name,
    parse_sdist_filename,
    parse_wheel_filename,
)
from packaging.version import InvalidVersion, Version

from obelize.net import Fetcher, NetworkError

if TYPE_CHECKING:
    from collections.abc import Mapping

SIMPLE: Final = "application/vnd.pypi.simple.v1+json"
JSON: Final = "application/json"
# The most one project page or metadata document may hold: the biggest projects list thousands of
# files, and none is as big as this.
PAGE_BYTES: Final = 64 << 20


@dataclass(frozen=True, slots=True)
class File:
    """One file of a release, as the index lists it."""

    filename: str
    url: str
    sha256: str
    version: Version
    kind: Literal["wheel", "sdist"]
    requires_python: str | None = None
    # The reason a release was withdrawn, `""` if it gave none, `None` if it was not.
    yanked: str | None = None
    # A wheel's tags: pure when it runs on any platform of Python 3.
    pure: bool = False

    def admits(self, python: Version | None) -> bool:
        """Whether the Python `python` may install it; every one does if none is named."""
        if python is None or not self.requires_python:
            return True
        try:
            return python in SpecifierSet(self.requires_python)
        except InvalidSpecifier:
            return True


@dataclass(frozen=True, slots=True)
class Project:
    """What a project has released, by the index's account."""

    name: str
    files: tuple[File, ...]

    @property
    def versions(self) -> tuple[Version, ...]:
        return tuple(sorted({one.version for one in self.files}))

    def newest(self, *, prereleases: bool = False) -> Version | None:
        """The newest release that is not withdrawn and, unless asked for, not a pre-release; a
        project that has only pre-releases offers its newest."""
        live = sorted({one.version for one in self.files if one.yanked is None})
        final = [version for version in live if not version.is_prerelease]
        pool = live if prereleases or not final else final
        return pool[-1] if pool else None

    def of(self, version: Version) -> tuple[File, ...]:
        return tuple(one for one in self.files if one.version == version)

    def choose(self, version: Version, python: Version | None = None) -> File | None:
        """The file to read for `version`: a wheel that runs anywhere, then any other wheel, then
        the source distribution, never a withdrawn one."""
        live = [one for one in self.of(version) if one.yanked is None and one.admits(python)]
        ranked = sorted(live, key=lambda one: (one.kind != "wheel", not one.pure, one.filename))
        return ranked[0] if ranked else None


@dataclass(frozen=True, slots=True)
class Vulnerability:
    id: str
    summary: str
    fixed_in: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Metadata:
    """What PyPI's JSON API says about a project's newest release."""

    classifiers: tuple[str, ...]
    project_urls: Mapping[str, str]
    vulnerabilities: tuple[Vulnerability, ...]
    summary: str
    requires_python: str | None


def simple_root(index: str) -> str:
    """The address of the Simple API: the index as typed if it already ends in `/simple`."""
    base = index.rstrip("/")
    return base if urlsplit(base).path.endswith("/simple") else f"{base}/simple"


def project(fetcher: Fetcher, name: str) -> Project:
    """Every file the index lists for `name`; `not_found` if it has no such project."""
    wanted = canonicalize_name(name)
    url = f"{simple_root(fetcher.index)}/{wanted}/"
    body = fetcher.get(url, accept=SIMPLE, max_bytes=PAGE_BYTES)
    try:
        document = json.loads(body)
    except (ValueError, RecursionError) as error:
        raise NetworkError(
            "refused", f"{urlsplit(url).hostname}: not a Simple JSON page"
        ) from error
    entries = document.get("files") if isinstance(document, dict) else None
    if not isinstance(entries, list):
        raise NetworkError("refused", f"{urlsplit(url).hostname}: the page lists no files")
    found = (_file(entry, url) for entry in entries if isinstance(entry, dict))
    return Project(wanted, tuple(sorted((one for one in found if one), key=_order)))


def _order(one: File) -> tuple[Version, str]:
    return one.version, one.filename


def _file(entry: dict[str, Any], page: str) -> File | None:
    filename, url = entry.get("filename"), entry.get("url")
    hashes = entry.get("hashes")
    sha256 = hashes.get("sha256") if isinstance(hashes, dict) else None
    if not (isinstance(filename, str) and isinstance(url, str) and isinstance(sha256, str)):
        return None
    try:
        if filename.endswith(".whl"):
            _name, version, _build, tags = parse_wheel_filename(filename)
            kind: Literal["wheel", "sdist"] = "wheel"
            pure = any(tag.abi == "none" and tag.platform == "any" for tag in tags)
        else:
            _name, version = parse_sdist_filename(filename)
            kind, pure = "sdist", False
    except (InvalidWheelFilename, InvalidSdistFilename, InvalidVersion):
        return None
    required = entry.get("requires-python")
    yanked = entry.get("yanked")
    return File(
        filename=filename,
        url=urljoin(page, url),
        sha256=sha256.lower(),
        version=version,
        kind=kind,
        requires_python=required if isinstance(required, str) else None,
        yanked=yanked if isinstance(yanked, str) else "" if yanked is True else None,
        pure=pure,
    )


def metadata(fetcher: Fetcher, name: str) -> Metadata | None:
    """What PyPI's JSON API says of `name`, or `None` where the index has no such API or project."""
    base = fetcher.index.rstrip("/")
    root = base.removesuffix("/simple")
    url = f"{root}/pypi/{canonicalize_name(name)}/json"
    try:
        body = fetcher.get(url, accept=JSON, max_bytes=PAGE_BYTES)
        document = json.loads(body)
    except NetworkError as error:
        if error.reason == "not_found":
            return None
        raise
    except (ValueError, RecursionError):
        return None
    info = document.get("info") if isinstance(document, dict) else None
    if not isinstance(info, dict):
        return None
    urls = info.get("project_urls")
    required = info.get("requires_python")
    summary = info.get("summary")
    return Metadata(
        classifiers=tuple(one for one in info.get("classifiers") or () if isinstance(one, str)),
        project_urls={
            k: v for k, v in (urls or {}).items() if isinstance(k, str) and isinstance(v, str)
        },
        vulnerabilities=_vulnerabilities(document.get("vulnerabilities")),
        summary=summary if isinstance(summary, str) else "",
        requires_python=required if isinstance(required, str) else None,
    )


def _vulnerabilities(listed: object) -> tuple[Vulnerability, ...]:
    found = []
    for entry in listed if isinstance(listed, list) else ():
        if (
            isinstance(entry, dict)
            and isinstance(entry.get("id"), str)
            and not entry.get("withdrawn")
        ):
            fixed = entry.get("fixed_in")
            found.append(
                Vulnerability(
                    id=entry["id"],
                    summary=entry["summary"] if isinstance(entry.get("summary"), str) else "",
                    fixed_in=tuple(one for one in fixed or () if isinstance(one, str)),
                )
            )
    return tuple(found)


__all__ = [
    "File",
    "Metadata",
    "Project",
    "Vulnerability",
    "metadata",
    "project",
    "simple_root",
]

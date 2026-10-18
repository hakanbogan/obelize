"""A package index on this machine, for the suites that read one: PEP 691 pages, PyPI's JSON API and
the files they list. Releases are built from source given as text, so no test needs the network.

Imported as `fakeindex`, like `support`.
"""

from __future__ import annotations

import hashlib
import http.server
import io
import json
import tarfile
import threading
import zipfile
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping


def wheel(files: Mapping[str, str]) -> bytes:
    """A wheel holding `files`, relative path to source."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as handle:
        for name, text in files.items():
            handle.writestr(name, text)
    return buffer.getvalue()


def sdist(prefix: str, files: Mapping[str, str]) -> bytes:
    """A source distribution of `files` under the directory `prefix`."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as handle:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"{prefix}/{name}")
            info.size = len(data)
            handle.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


@dataclass
class Release:
    """One release: the files it ships by file name, and whether it was withdrawn."""

    files: dict[str, bytes]
    yanked: str | None = None
    requires_python: str | None = None


@dataclass
class Project:
    name: str
    releases: dict[str, Release] = field(default_factory=dict)
    info: dict[str, Any] = field(default_factory=dict)
    vulnerabilities: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class FakeIndex:
    """`url` is the index as a person types it; `asked` is every path requested, in order."""

    origin: str = ""
    projects: dict[str, Project] = field(default_factory=dict)
    asked: list[str] = field(default_factory=list)
    corrupt: set[str] = field(default_factory=set)

    @property
    def url(self) -> str:
        return f"{self.origin}/simple"

    def add(
        self,
        name: str,
        version: str,
        source: Mapping[str, str],
        *,
        module: str | None = None,
        kind: str = "wheel",
        yanked: str | None = None,
        requires_python: str | None = None,
        **info: Any,
    ) -> str:
        """Release `version` of `name` whose importable package `module` holds `source` (file name
        in the package to text); returns the file name."""
        package = module or name.replace("-", "_")
        project = self.projects.setdefault(name, Project(name))
        body = {f"{package}/{path}": text for path, text in source.items()}
        slug = name.replace("-", "_")
        if kind == "wheel":
            filename = f"{slug}-{version}-py3-none-any.whl"
            data = wheel(
                {
                    **body,
                    f"{slug}-{version}.dist-info/METADATA": f"Name: {name}\nVersion: {version}\n",
                    f"{slug}-{version}.dist-info/top_level.txt": f"{package}\n",
                }
            )
        else:
            filename = f"{slug}-{version}.tar.gz"
            data = sdist(f"{slug}-{version}", {f"src/{path}": text for path, text in body.items()})
        release = project.releases.setdefault(version, Release({}, yanked, requires_python))
        release.files[filename] = data
        project.info.update(info)
        return filename

    def serve(self) -> Iterator[FakeIndex]:
        index = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                index.asked.append(self.path)
                status, kind, body = index._answer(self.path)
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
                return

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        index.origin = f"http://127.0.0.1:{server.server_address[1]}"
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            yield index
        finally:
            server.shutdown()
            server.server_close()

    def _answer(self, path: str) -> tuple[int, str, bytes]:
        parts = [part for part in path.split("/") if part]
        if len(parts) == 2 and parts[0] == "simple" and parts[1] in self.projects:
            return 200, "application/vnd.pypi.simple.v1+json", self._page(self.projects[parts[1]])
        if (
            len(parts) == 3
            and parts[0] == "pypi"
            and parts[2] == "json"
            and parts[1] in self.projects
        ):
            return 200, "application/json", self._json(self.projects[parts[1]])
        if len(parts) == 2 and parts[0] == "files":
            for project in self.projects.values():
                for release in project.releases.values():
                    if parts[1] in release.files:
                        data = release.files[parts[1]]
                        return (
                            200,
                            "application/octet-stream",
                            b"corrupt" if parts[1] in self.corrupt else data,
                        )
        return 404, "text/plain", b"not found"

    def _page(self, project: Project) -> bytes:
        files = []
        for release in project.releases.values():
            for filename, data in release.files.items():
                entry: dict[str, Any] = {
                    "filename": filename,
                    "url": f"../../files/{filename}",
                    "hashes": {"sha256": hashlib.sha256(data).hexdigest()},
                    "yanked": release.yanked if release.yanked is not None else False,
                }
                if release.requires_python:
                    entry["requires-python"] = release.requires_python
                files.append(entry)
        return json.dumps(
            {"meta": {"api-version": "1.0"}, "name": project.name, "files": files}
        ).encode()

    def _json(self, project: Project) -> bytes:
        info = {
            "name": project.name,
            "classifiers": [],
            "project_urls": {},
            "summary": "",
            **project.info,
        }
        return json.dumps({"info": info, "vulnerabilities": project.vulnerabilities}).encode()

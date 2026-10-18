"""The one place obelize opens a socket for anything that is not a model: a package index, the
files it lists and a migration guide.

Nothing here runs unless a command that needs it was asked for, and every host is told to the
person the first time it is contacted. A request goes to https (plain http only to this machine, for
a local index), follows a redirect only to the same host, is read up to a size and a time and no
further, and carries a credential only to the index host. An answer is kept in the person's cache so
that `--offline` can use it, and a cache that other users can write to is not used.

`providers/openai_compat.py` opens its own connection to a model and shares nothing with this: a
model gets no proxy and no redirect, because a payload of source code goes with it.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import os
import ssl
import stat
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, TYPE_CHECKING, Final, Literal
from urllib.parse import urlsplit

from obelize import __version__

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

USER_AGENT: Final = f"obelize/{__version__} (+https://github.com/hakanbogan/obelize)"
READ_CHUNK: Final = 64 << 10
# The most one answer may hold, unless the caller names another: an index page is small, a wheel is
# not, and nothing here is as big as this.
DEFAULT_MAX_BYTES: Final = 32 << 20
DEFAULT_TIMEOUT_S: Final = 30.0
REDIRECTS: Final = 5
# How long a cached index page is believed, in seconds. `--offline` believes any age.
INDEX_TTL_S: Final = 3600

Reason = Literal[
    "offline",
    "insecure",
    "unreachable",
    "refused",
    "not_found",
    "redirected",
    "too_large",
    "timeout",
]


class NetworkError(Exception):
    """A request that did not give an answer, with the word for why; `detail` is for the person."""

    def __init__(self, reason: Reason, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def loopback(host: str) -> bool:
    """`localhost` or a loopback address by its text."""
    try:
        return host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def index_url(value: str) -> str:
    """An index as the person typed it, without its trailing slash: https, or http to this machine,
    with a host and nothing a request would have to carry besides (a credential, a query)."""
    parts = urlsplit(value)
    host = parts.hostname or ""
    if parts.scheme != "https" and not (parts.scheme == "http" and loopback(host)):
        raise ValueError(f"{value!r} is not an index address: use https, or http to this machine")
    if not host or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError(f"{value!r} is not an index address: a host and a path, nothing else")
    return value.rstrip("/")


class Cache:
    """Answers kept on disk by the key of the request, for the person alone."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @classmethod
    def home(cls, environ: Mapping[str, str]) -> Cache:
        """`$XDG_CACHE_HOME/obelize`, or `~/.cache/obelize`; a relative base is not followed, as it
        would name a directory under wherever the command runs, which can be a repository."""
        base = environ.get("XDG_CACHE_HOME")
        if base and Path(base).is_absolute():
            return cls(Path(base) / "obelize")
        return cls(Path(environ.get("HOME", "~")).expanduser() / ".cache" / "obelize")

    @staticmethod
    def key(*parts: str) -> str:
        """The name of a request: the release of obelize and what was asked, hashed, so a newer
        release never reads what an older one parsed another way."""
        return hashlib.sha256("\0".join((__version__, *parts)).encode("utf-8")).hexdigest()

    def get(self, key: str, *, ttl_s: float | None) -> bytes | None:
        """The answer kept under `key`, if it is younger than `ttl_s` (`None` accepts any age)."""
        path = self._path(key)
        try:
            if ttl_s is not None and time.time() - path.stat().st_mtime > ttl_s:
                return None
            return path.read_bytes()
        except OSError:
            return None

    def put(self, key: str, body: bytes) -> None:
        """Keep `body`, through a temporary file and a rename, and say nothing if it cannot be."""
        path = self._path(key)
        try:
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.parent.mkdir(mode=0o700, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
                handle.write(body)
            Path(handle.name).replace(path)
        except OSError:
            return

    def usable(self) -> bool:
        """Whether the directory may be trusted: one that others can write to could hold an answer
        somebody else chose. Absent is usable, since `put` makes it for the person alone."""
        try:
            status = self.directory.stat()
        except FileNotFoundError:
            return True
        except OSError:
            return False
        if os.name == "nt":  # pragma: windows-only
            return stat.S_ISDIR(status.st_mode)
        return stat.S_ISDIR(status.st_mode) and not status.st_mode & 0o022  # pragma: posix-only

    def _path(self, key: str) -> Path:
        return self.directory / key[:2] / key


class _SameHost(urllib.request.HTTPRedirectHandler):
    """A redirect is followed only to the same host and the same scheme, up to `REDIRECTS` times:
    where a request goes next is the server's choice, and only the first host is the person's."""

    max_redirections = REDIRECTS

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: http.client.HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        here, there = urlsplit(req.full_url), urlsplit(newurl)
        if (there.scheme, there.hostname) != (here.scheme, here.hostname):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass(slots=True)
class Fetcher:
    """Requests to an index and the hosts it names, under the rules at the top of this module.

    `say` is told each host the first time it is contacted. `credentials` is the header value an
    index asks for, sent to the index host and to none other.
    """

    index: str
    offline: bool = False
    cache: Cache | None = None
    timeout_s: float = DEFAULT_TIMEOUT_S
    credentials: str | None = None
    say: Callable[[str], None] | None = None
    hosts: list[str] = field(default_factory=list)

    def get(
        self,
        url: str,
        *,
        accept: str = "*/*",
        max_bytes: int = DEFAULT_MAX_BYTES,
        ttl_s: float | None = INDEX_TTL_S,
        key: str | None = None,
    ) -> bytes:
        """The body of `url`, from the cache while it is fresh, else from the network.

        `key` names the answer in the cache when the url is not what identifies it (a file is
        known by its hash). Raises `NetworkError`.
        """
        named = key or Cache.key(url, accept)
        cache = self.cache if self.cache is not None and self.cache.usable() else None
        if cache is not None and (kept := cache.get(named, ttl_s=None if self.offline else ttl_s)):
            return kept
        if self.offline:
            raise NetworkError("offline", f"{urlsplit(url).hostname}: {url} is not in the cache")
        body = self._fetch(url, accept, max_bytes)
        if cache is not None:
            cache.put(named, body)
        return body

    def _fetch(self, url: str, accept: str, max_bytes: int) -> bytes:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.scheme != "https" and not (parts.scheme == "http" and loopback(host)):
            raise NetworkError(
                "insecure", f"{host or url}: only https is used, or http to this machine"
            )
        if parts.username or parts.password:
            raise NetworkError("insecure", f"{host}: a url carries no credential")
        self._told(host)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})  # noqa: S310
        if self.credentials and host == urlsplit(self.index).hostname:
            request.add_header("Authorization", self.credentials)
        # The environment's proxy, and the system's certificates: this is the person's network.
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler(),
            _SameHost(),
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        )
        deadline = time.monotonic() + self.timeout_s
        try:
            with opener.open(request, timeout=self.timeout_s) as response:
                return _read(response, max_bytes, deadline, host)
        except urllib.error.HTTPError as error:
            moved = 300 <= error.code < 400
            raise NetworkError(
                "redirected" if moved else "not_found" if error.code == 404 else "refused",
                f"{host}: HTTP {error.code} {error.reason}",
            ) from error
        except TimeoutError as error:
            raise NetworkError(
                "timeout", f"{host}: no complete answer within {self.timeout_s:g} s"
            ) from error
        except (urllib.error.URLError, http.client.HTTPException, OSError) as error:
            raise NetworkError("unreachable", f"{host}: {error}") from error

    def _told(self, host: str) -> None:
        if host not in self.hosts:
            self.hosts.append(host)
            if self.say is not None:
                self.say(f"obelize contacts {host}")


def _read(
    response: http.client.HTTPResponse | urllib.error.HTTPError,
    limit: int,
    deadline: float,
    host: str,
) -> bytes:
    """The body up to `limit` bytes, or `NetworkError`: the socket timeout bounds each wait, so a
    reply dripped a byte at a time would outlast it, and the deadline does not."""
    body = bytearray()
    while piece := response.read1(READ_CHUNK):
        body += piece
        if len(body) > limit:
            raise NetworkError("too_large", f"{host}: the answer passed {limit} bytes")
        if time.monotonic() > deadline:
            raise TimeoutError
    return bytes(body)


__all__ = ["Cache", "Fetcher", "NetworkError", "loopback"]

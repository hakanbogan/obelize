"""`obelize.net`: what a request may do, the answers it keeps, and what `--offline` may use."""

from __future__ import annotations

import http.server
import os
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest

from obelize import __version__
from obelize.net import USER_AGENT, Cache, Fetcher, NetworkError, loopback
from platforms import posix_only

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@dataclass
class Site:
    """A local web server whose answers a test chooses, and which remembers what it was asked."""

    origin: str
    routes: dict[str, tuple[int, dict[str, str], bytes]] = field(default_factory=dict)
    asked: list[tuple[str, dict[str, str]]] = field(default_factory=list)
    slow: float = 0.0

    @property
    def port(self) -> str:
        return self.origin.rsplit(":", 1)[1]

    def serve(self, path: str, body: bytes = b"ok", *, status: int = 200, **headers: str) -> str:
        self.routes[path] = (status, headers, body)
        return f"{self.origin}{path}"


@pytest.fixture
def site() -> Iterator[Site]:
    state = Site(origin="")

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            state.asked.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
            status, headers, body = state.routes.get(self.path, (404, {}, b"missing"))
            if state.slow:
                time.sleep(state.slow)
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name.replace("_", "-"), value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except OSError:
                return

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.origin = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


def _fetcher(site: Site, **kwargs: Any) -> Fetcher:
    return Fetcher(index=site.origin, **kwargs)


# What a request is.


def test_a_request_asks_for_what_it_wants_and_says_who_asks(site: Site) -> None:
    url = site.serve("/page", b"hello")
    assert _fetcher(site).get(url, accept="application/json") == b"hello"
    ((path, headers),) = site.asked
    assert path == "/page"
    assert headers["accept"] == "application/json"
    assert headers["user-agent"] == USER_AGENT
    assert __version__ in USER_AGENT


def test_each_host_is_told_once_the_first_time_it_is_contacted(site: Site) -> None:
    told: list[str] = []
    fetcher = _fetcher(site, say=told.append)
    fetcher.get(site.serve("/a"))
    fetcher.get(site.serve("/b"))
    assert told == ["obelize contacts 127.0.0.1"]
    assert fetcher.hosts == ["127.0.0.1"]


@pytest.mark.parametrize(
    ("url", "detail"),
    [
        ("http://example.com/x", "only https is used"),
        ("ftp://example.com/x", "only https is used"),
        ("file:///etc/passwd", "only https is used"),
        ("https://user:secret@example.com/x", "carries no credential"),
    ],
)
def test_only_https_is_used_apart_from_this_machine_and_a_url_holds_no_credential(
    url: str, detail: str
) -> None:
    told: list[str] = []
    with pytest.raises(NetworkError, match=detail) as raised:
        Fetcher(index="https://pypi.org", say=told.append).get(url)
    assert raised.value.reason == "insecure"
    assert told == []


def test_a_credential_goes_to_the_index_host_and_to_no_other(site: Site) -> None:
    fetcher = _fetcher(site, credentials="Bearer token")
    fetcher.get(site.serve("/one"))
    elsewhere = f"http://localhost:{site.port}/two"
    site.serve("/two")
    fetcher.get(elsewhere)
    assert site.asked[0][1]["authorization"] == "Bearer token"
    assert "authorization" not in site.asked[1][1]


def test_a_redirect_to_the_same_host_is_followed(site: Site) -> None:
    site.serve("/new", b"arrived")
    url = site.serve("/old", status=302, Location=f"{site.origin}/new")
    assert _fetcher(site).get(url) == b"arrived"


def test_a_redirect_to_another_host_is_an_answer_and_not_a_new_place_to_go(site: Site) -> None:
    url = site.serve("/old", status=302, Location=f"http://localhost:{site.port}/new")
    with pytest.raises(NetworkError) as raised:
        _fetcher(site).get(url)
    assert raised.value.reason == "redirected"


def test_a_redirect_to_another_scheme_is_refused(site: Site) -> None:
    url = site.serve("/old", status=302, Location="https://127.0.0.1/new")
    with pytest.raises(NetworkError) as raised:
        _fetcher(site).get(url)
    assert raised.value.reason == "redirected"


def test_a_redirect_that_never_ends_stops(site: Site) -> None:
    url = site.serve("/loop", status=302, Location=f"{site.origin}/loop")
    with pytest.raises(NetworkError) as raised:
        _fetcher(site).get(url)
    assert raised.value.reason == "redirected"


@pytest.mark.parametrize(
    ("status", "reason"), [(404, "not_found"), (500, "refused"), (403, "refused")]
)
def test_a_status_other_than_success_is_named(site: Site, status: int, reason: str) -> None:
    url = site.serve("/x", status=status)
    with pytest.raises(NetworkError) as raised:
        _fetcher(site).get(url)
    assert raised.value.reason == reason
    assert f"HTTP {status}" in raised.value.detail


def test_a_host_that_does_not_answer_is_unreachable() -> None:
    with pytest.raises(NetworkError) as raised:
        Fetcher(index="http://127.0.0.1:1").get("http://127.0.0.1:1/x")
    assert raised.value.reason == "unreachable"


def test_an_answer_that_takes_too_long_is_a_timeout(site: Site) -> None:
    url = site.serve("/slow")
    site.slow = 1.0
    with pytest.raises(NetworkError) as raised:
        _fetcher(site, timeout_s=0.2).get(url)
    assert raised.value.reason == "timeout"


def test_an_answer_over_the_limit_is_refused(site: Site) -> None:
    url = site.serve("/big", b"x" * 5000)
    with pytest.raises(NetworkError) as raised:
        _fetcher(site).get(url, max_bytes=4096)
    assert raised.value.reason == "too_large"


def test_an_answer_that_trickles_past_the_deadline_is_a_timeout(
    site: Site, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The socket timeout bounds each wait; only the deadline bounds the whole."""
    url = site.serve("/trickle", b"x" * 200_000)
    clock = iter([0.0, 0.0, 99.0, 99.0, 99.0])
    monkeypatch.setattr(time, "monotonic", lambda: next(clock, 99.0))
    with pytest.raises(NetworkError) as raised:
        _fetcher(site, timeout_s=5).get(url)
    assert raised.value.reason == "timeout"


# The cache.


def test_an_answer_is_kept_and_asked_for_once(site: Site, tmp_path: Path) -> None:
    url = site.serve("/page", b"first")
    fetcher = _fetcher(site, cache=Cache(tmp_path / "cache"))
    assert fetcher.get(url) == b"first"
    site.serve("/page", b"second")
    assert fetcher.get(url) == b"first"
    assert len(site.asked) == 1


def test_an_answer_older_than_its_time_is_asked_for_again(site: Site, tmp_path: Path) -> None:
    url = site.serve("/page", b"first")
    fetcher = _fetcher(site, cache=Cache(tmp_path / "cache"))
    fetcher.get(url)
    site.serve("/page", b"second")
    assert fetcher.get(url, ttl_s=-1) == b"second"


def test_what_is_asked_for_differently_is_kept_apart(site: Site, tmp_path: Path) -> None:
    url = site.serve("/page", b"body")
    fetcher = _fetcher(site, cache=Cache(tmp_path / "cache"))
    fetcher.get(url, accept="a/b")
    fetcher.get(url, accept="c/d")
    assert len(site.asked) == 2


def test_a_named_key_stands_for_the_request(site: Site, tmp_path: Path) -> None:
    fetcher = _fetcher(site, cache=Cache(tmp_path / "cache"))
    fetcher.get(site.serve("/file-a", b"same"), key="abc")
    assert fetcher.get(site.serve("/file-b", b"other"), key="abc") == b"same"


def test_offline_uses_the_cache_at_any_age_and_never_the_network(
    site: Site, tmp_path: Path
) -> None:
    cache = Cache(tmp_path / "cache")
    url = site.serve("/page", b"kept")
    _fetcher(site, cache=cache).get(url)
    offline = _fetcher(site, cache=cache, offline=True)
    assert offline.get(url, ttl_s=-1) == b"kept"
    with pytest.raises(NetworkError, match="is not in the cache") as raised:
        offline.get(site.serve("/other"))
    assert raised.value.reason == "offline"
    assert len(site.asked) == 1


def test_offline_with_no_cache_has_nothing(site: Site) -> None:
    with pytest.raises(NetworkError) as raised:
        _fetcher(site, offline=True).get(site.serve("/page"))
    assert raised.value.reason == "offline"
    assert site.asked == []


@posix_only("a group-writable directory is a POSIX mode")
def test_a_cache_other_users_can_write_to_is_not_used(site: Site, tmp_path: Path) -> None:
    directory = tmp_path / "cache"
    cache = Cache(directory)
    url = site.serve("/page", b"first")
    fetcher = _fetcher(site, cache=cache)
    fetcher.get(url)
    directory.chmod(0o777)
    assert not cache.usable()
    site.serve("/page", b"second")
    assert fetcher.get(url) == b"second"
    assert len(site.asked) == 2


@posix_only("the mode of a directory the cache makes is POSIX")
def test_the_cache_makes_its_directory_for_the_person_alone(site: Site, tmp_path: Path) -> None:
    directory = tmp_path / "cache"
    _fetcher(site, cache=Cache(directory)).get(site.serve("/page"))
    assert directory.stat().st_mode & 0o077 == 0


def test_a_cache_that_cannot_be_written_is_no_error(site: Site, tmp_path: Path) -> None:
    blocked = tmp_path / "cache"
    blocked.write_text("a file where the directory should be", encoding="utf-8")
    cache = Cache(blocked)
    assert not cache.usable()
    assert _fetcher(site, cache=cache).get(site.serve("/page", b"fine")) == b"fine"
    cache.put("abc", b"x")
    assert cache.get("abc", ttl_s=None) is None


def test_a_missing_cache_directory_is_usable_and_empty(tmp_path: Path) -> None:
    cache = Cache(tmp_path / "later")
    assert cache.usable()
    assert cache.get("abc", ttl_s=None) is None


def test_the_cache_lives_under_the_persons_cache_home(tmp_path: Path) -> None:
    assert Cache.home({"XDG_CACHE_HOME": str(tmp_path)}).directory == tmp_path / "obelize"
    relative = Cache.home({"XDG_CACHE_HOME": "relative", "HOME": str(tmp_path)})
    assert relative.directory == tmp_path / ".cache" / "obelize"


def test_the_key_of_a_request_names_the_release_that_parsed_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = Cache.key("https://x/y", "json")
    monkeypatch.setattr("obelize.net.__version__", "9.9.9")
    assert Cache.key("https://x/y", "json") != first


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("localhost", True),
        ("127.0.0.1", True),
        ("::1", True),
        ("example.com", False),
        ("10.0.0.1", False),
    ],
)
def test_this_machine_is_recognised_by_its_text(host: str, expected: bool) -> None:
    assert loopback(host) is expected


@pytest.mark.skipif(os.name != "nt", reason="Windows has no POSIX mode to check")
def test_a_cache_on_windows_is_a_directory_or_nothing(tmp_path: Path) -> None:
    assert Cache(tmp_path).usable()


def test_a_cache_directory_under_a_file_is_not_usable(tmp_path: Path) -> None:
    (tmp_path / "file").write_text("x", encoding="utf-8")
    assert not Cache(tmp_path / "file" / "cache").usable()

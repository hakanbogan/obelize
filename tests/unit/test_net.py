"""`obelize.net`: what a request may do, the answers it keeps, and what `--offline` may use."""

from __future__ import annotations

import http.server
import os
import socketserver
import threading
import time
from dataclasses import dataclass, field
from email.message import Message
from typing import TYPE_CHECKING, Any
from urllib.request import Request

import pytest

from obelize import __version__
from obelize.net import USER_AGENT, Cache, Fetcher, NetworkError, _SameHost, index_url, loopback
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
    yield from _serving()


@pytest.fixture
def elsewhere() -> Iterator[Site]:
    """A second server, on another port of this machine."""
    yield from _serving()


def _serving() -> Iterator[Site]:
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


@pytest.fixture
def raw() -> Iterator[dict[str, bytes]]:
    """A server that sends the bytes a test gives it for a path, exactly, and closes."""
    replies: dict[str, bytes] = {}

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            path = self.rfile.readline().split()[1].decode()
            while self.rfile.readline().strip():
                pass
            self.wfile.write(replies[path])

    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    replies[""] = f"http://127.0.0.1:{server.server_address[1]}".encode()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield replies
    finally:
        server.shutdown()
        server.server_close()


def _ask(replies: dict[str, bytes], path: str, answer: bytes) -> bytes:
    replies[path] = answer
    origin = replies[""].decode()
    return Fetcher(index=origin).get(f"{origin}{path}")


HEAD = b"HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n"


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


def test_a_type_of_page_that_was_not_asked_for_is_refused_before_it_is_read_or_kept(
    site: Site, tmp_path: Path
) -> None:
    url = site.serve("/page", b"%PDF", Content_Type="application/pdf")
    kept = Cache(tmp_path / "cache")
    fetcher = _fetcher(site, cache=kept)
    with pytest.raises(NetworkError, match="application/pdf") as raised:
        fetcher.get(url, types=("text/html", "text/plain"))
    assert raised.value.reason == "refused"
    assert kept.get(Cache.key(url, "*/*"), ttl_s=None) is None
    assert fetcher.get(url) == b"%PDF"


def test_a_page_of_a_type_asked_for_is_read_whatever_its_charset(site: Site) -> None:
    url = site.serve("/page", b"words", Content_Type="text/PLAIN; charset=utf-8")
    assert _fetcher(site).get(url, types=("text/plain",)) == b"words"


@pytest.mark.parametrize(
    ("location", "said"),
    [
        ("https://docs.example.org/new", "to docs.example.org"),
        ("https://docs.\u00e9xample.org/new", "to another host"),
        ("", "to another host"),
    ],
)
def test_a_redirect_refused_says_the_host_it_was_for_where_a_terminal_may_show_it(
    site: Site, location: str, said: str
) -> None:
    url = (
        site.serve("/old", status=301, Location=location)
        if location
        else site.serve("/old", status=301)
    )
    with pytest.raises(NetworkError) as raised:
        _fetcher(site).get(url)
    assert raised.value.detail.endswith(said)


def test_an_answer_that_ends_before_the_length_it_declared_is_not_the_whole_of_it(
    raw: dict[str, bytes],
) -> None:
    with pytest.raises(NetworkError, match="ended after 55 of 100 bytes") as raised:
        _ask(raw, "/short", HEAD + b"Content-Length: 100\r\n\r\n" + b"x" * 55)
    assert raised.value.reason == "unreachable"


def test_an_answer_is_read_as_far_as_its_length_says_and_no_further(raw: dict[str, bytes]) -> None:
    assert _ask(raw, "/long", HEAD + b"Content-Length: 5\r\n\r\n" + b"x" * 10) == b"xxxxx"


def test_an_answer_with_no_length_is_read_to_its_end(raw: dict[str, bytes]) -> None:
    assert _ask(raw, "/open", HEAD + b"\r\nhello") == b"hello"


def test_a_chunked_answer_is_read_whole_and_one_cut_short_is_not(raw: dict[str, bytes]) -> None:
    chunked = b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nContent-Length: 100\r\n\r\n"
    assert _ask(raw, "/chunked", chunked + b"5\r\nhello\r\n0\r\n\r\n") == b"hello"
    with pytest.raises(NetworkError) as raised:
        _ask(raw, "/cut", chunked + b"5\r\nhel")
    assert raised.value.reason == "unreachable"


def test_a_redirect_to_another_port_of_the_same_host_is_not_followed(
    site: Site, elsewhere: Site
) -> None:
    elsewhere.serve("/new", b"arrived")
    url = site.serve("/old", status=302, Location=f"{elsewhere.origin}/new")
    with pytest.raises(NetworkError) as raised:
        _fetcher(site).get(url)
    assert raised.value.reason == "redirected"
    assert elsewhere.asked == []


@pytest.mark.parametrize(
    ("there", "followed"),
    [
        ("http://127.0.0.1:8080/y", True),
        ("http://127.0.0.1/y", False),
        ("http://127.0.0.1:8081/y", False),
        ("http://127.0.0.1:99999/y", False),
        ("https://127.0.0.1:8080/y", False),
        ("http://localhost:8080/y", False),
    ],
)
def test_a_redirect_keeps_the_scheme_the_host_and_the_port(there: str, followed: bool) -> None:
    asked = Request("http://127.0.0.1:8080/x")
    sent = _SameHost().redirect_request(asked, None, 302, "Found", Message(), there)  # type: ignore[arg-type]
    assert (sent is not None) is followed


def test_a_default_port_is_the_same_port_written_or_not() -> None:
    asked = Request("https://example.org/x")
    handler = _SameHost()
    for there in ("https://example.org:443/y", "https://example.org/y"):
        assert handler.redirect_request(asked, None, 302, "Found", Message(), there) is not None  # type: ignore[arg-type]


def test_a_page_is_kept_with_its_type_and_offline_knows_it_too(site: Site, tmp_path: Path) -> None:
    url = site.serve("/p", b"# words", Content_Type="text/Markdown; charset=utf-8")
    kept = Cache(tmp_path / "cache")
    online = _fetcher(site, cache=kept)
    assert online.page(url, accept="*/*", max_bytes=100, types=("text/markdown",)) == (
        "text/markdown",
        b"# words",
    )
    site.routes.clear()
    offline = _fetcher(site, cache=kept, offline=True)
    assert offline.page(url, accept="*/*", max_bytes=100, types=("text/markdown",)) == (
        "text/markdown",
        b"# words",
    )
    with pytest.raises(NetworkError, match="not in the cache"):
        offline.page(url + "x", accept="*/*", max_bytes=100, types=("text/markdown",))


def test_a_page_of_a_type_not_asked_for_is_refused_and_not_kept(site: Site, tmp_path: Path) -> None:
    url = site.serve("/p", b"%PDF", Content_Type="application/pdf")
    kept = Cache(tmp_path / "cache")
    with pytest.raises(NetworkError, match="application/pdf"):
        _fetcher(site, cache=kept).page(url, accept="*/*", max_bytes=100, types=("text/html",))
    assert not any(path.is_file() for path in (tmp_path / "cache").rglob("*"))


def test_offline_says_which_page_the_cache_lacks_without_its_query(site: Site) -> None:
    with pytest.raises(NetworkError) as raised:
        _fetcher(site, offline=True).get(f"{site.origin}/p?token=secret#part")
    assert raised.value.detail.endswith(f"{site.origin}/p is not in the cache")
    assert "secret" not in raised.value.detail


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


@pytest.mark.parametrize(
    ("given", "kept"),
    [
        ("https://pypi.org", "https://pypi.org"),
        ("https://pypi.org/", "https://pypi.org"),
        ("https://example.com/root/simple/", "https://example.com/root/simple"),
        ("http://127.0.0.1:8080/simple", "http://127.0.0.1:8080/simple"),
        ("http://localhost/simple", "http://localhost/simple"),
    ],
)
def test_an_index_address_is_kept_without_its_trailing_slash(given: str, kept: str) -> None:
    assert index_url(given) == kept


@pytest.mark.parametrize(
    "given",
    [
        "http://example.com/simple",
        "ftp://example.com",
        "https://user:secret@example.com/simple",
        "https://example.com/simple?token=1",
        "https://example.com/simple#top",
        "https:///simple",
        "pypi.org",
    ],
)
def test_an_index_address_that_could_leak_or_downgrade_is_refused(given: str) -> None:
    with pytest.raises(ValueError, match="not an index address"):
        index_url(given)

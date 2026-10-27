"""The proxy a trial reaches the package index through: it carries an allowed `host:port` and
answers 403 to everything else, and its totals count every event."""

from __future__ import annotations

import asyncio
import json
import socket
import struct
from collections.abc import Awaitable, Callable

import pytest

from bench.trial import proxy
from platforms import BENCH

pytestmark = BENCH

Allowed = frozenset[tuple[str, int]]


async def echo(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    while data := await reader.read(1024):
        writer.write(data)
    writer.close()


async def free_port() -> int:
    """A port nothing listens on."""
    server = await asyncio.start_server(echo, "127.0.0.1", 0)
    port: int = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()
    return port


def through(
    scenario: Callable[[int, proxy.Counts, int], Awaitable[None]],
    allowed: Allowed | None = None,
) -> proxy.Counts:
    """Run `scenario(proxy_port, counts, echo_port)` against a proxy that allows the local echo
    server (or `allowed`), and return what it counted."""
    counts = proxy.Counts()

    async def main() -> None:
        upstream = await asyncio.start_server(echo, "127.0.0.1", 0)
        target = upstream.sockets[0].getsockname()[1]
        server = await proxy.serve(
            "127.0.0.1", 0, allowed or frozenset({("127.0.0.1", target)}), counts
        )
        try:
            await scenario(server.sockets[0].getsockname()[1], counts, target)
        finally:
            server.close()
            upstream.close()
            await server.wait_closed()

    asyncio.run(main())
    return counts


async def ask(port: int, request: bytes) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(request)
    await writer.drain()
    try:
        answer = await reader.read()
    except ConnectionError:
        answer = b""
    writer.close()
    return answer


def test_an_allowed_host_is_carried_both_ways() -> None:
    async def scenario(port: int, counts: proxy.Counts, target: int) -> None:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(f"CONNECT 127.0.0.1:{target} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
        assert await reader.readuntil(b"\r\n\r\n") == b"HTTP/1.1 200 Connection established\r\n\r\n"
        writer.write(b"ping")
        assert await reader.readexactly(4) == b"ping"
        writer.close()
        await asyncio.sleep(0.05)

    counts = through(scenario)
    [(target, one)] = counts.totals()["allow"].items()
    assert target.startswith("127.0.0.1:")
    assert one == 1
    assert counts.totals()["deny"] == {}


def test_a_tunnel_that_the_client_resets_ends_and_is_still_counted() -> None:
    async def scenario(port: int, counts: proxy.Counts, target: int) -> None:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(f"CONNECT 127.0.0.1:{target} HTTP/1.1\r\n\r\n".encode())
        await reader.readuntil(b"\r\n\r\n")
        sock = writer.get_extra_info("socket")
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        writer.close()
        await asyncio.sleep(0.1)

    assert sum(through(scenario).totals()["allow"].values()) == 1


@pytest.mark.parametrize(
    ("request_line", "counted"),
    [
        (b"CONNECT example.com:443 HTTP/1.1\r\n\r\n", "example.com:443"),
        (b"CONNECT EXAMPLE.com:443 HTTP/1.1\r\n\r\n", "example.com:443"),
        (b"GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n", "example.com"),
        (b"POST /x HTTP/1.1\r\n\r\n", "/x"),
        (b"CONNECT example.com:443\r\n\r\n", "example.com:443"),
        (b"CONNECT example.com:\xc2\xb2 HTTP/1.1\r\n\r\n", "example.com:\xc3\x82\xc2\xb2"),
        (b"CONNECT [::1]:443 HTTP/1.1\r\n\r\n", "[::1]:443"),
        (b"\r\n", "?"),
        (b"GET http://[::1 HTTP/1.1\r\n\r\n", "?"),
        (b"", "?"),
    ],
    ids=[
        "other",
        "case",
        "plain-get",
        "path",
        "no-version",
        "unicode-port",
        "ipv6",
        "blank",
        "bad-url",
        "empty",
    ],
)
def test_anything_but_a_connect_to_an_allowed_host_is_answered_403(
    request_line: bytes, counted: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(proxy, "HEAD_S", 0.3)
    answers: list[bytes] = []

    async def scenario(port: int, counts: proxy.Counts, target: int) -> None:
        answers.append(await ask(port, request_line))

    counts = through(scenario)
    assert answers[0] in (b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n", b"")
    assert sum(counts.totals()["deny"].values()) == 1
    assert counts.totals()["allow"] == {}


def test_an_allowed_host_on_another_port_is_denied() -> None:
    async def scenario(port: int, counts: proxy.Counts, target: int) -> None:
        answer = await ask(port, f"CONNECT 127.0.0.1:{target + 1} HTTP/1.1\r\n\r\n".encode())
        assert answer.startswith(b"HTTP/1.1 403")

    assert list(through(scenario).totals()["deny"]) != []


def test_an_allowed_host_that_cannot_be_reached_is_a_502_and_an_error() -> None:
    dead = asyncio.run(free_port())

    async def scenario(port: int, counts: proxy.Counts, target: int) -> None:
        answer = await ask(port, f"CONNECT 127.0.0.1:{dead} HTTP/1.1\r\n\r\n".encode())
        assert answer.startswith(b"HTTP/1.1 502")

    counts = through(scenario, frozenset({("127.0.0.1", dead)}))
    assert counts.totals()["error"] == {f"127.0.0.1:{dead}": 1}
    assert counts.totals()["allow"] == {}


def test_a_client_that_says_nothing_is_dropped_after_the_header_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(proxy, "HEAD_S", 0.05)

    async def scenario(port: int, counts: proxy.Counts, target: int) -> None:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        assert await asyncio.wait_for(reader.read(), 5) == b""
        writer.close()

    assert through(scenario).totals()["deny"] == {"?": 1}


def test_a_header_line_that_never_ends_is_dropped() -> None:
    async def scenario(port: int, counts: proxy.Counts, target: int) -> None:
        assert await ask(port, b"CONNECT " + b"a" * 200_000 + b"\r\n\r\n") in (
            b"",
            b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n",
        )

    assert through(scenario).totals()["deny"] == {"?": 1}


def test_an_event_is_printed_as_one_json_line_up_to_a_limit_and_always_counted(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(proxy, "LOGGED", 2)
    counts = proxy.Counts()
    for _ in range(4):
        counts.add("deny", "Example.COM:443")
    printed = capsys.readouterr().out.splitlines()
    assert [json.loads(line) for line in printed] == [
        {"verdict": "deny", "target": "example.com:443"}
    ] * 2
    assert counts.totals() == {"allow": {}, "deny": {"example.com:443": 4}, "error": {}}


def test_a_client_that_names_thousands_of_hosts_is_counted_under_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(proxy, "TARGETS", 2)
    monkeypatch.setattr(proxy, "LOGGED", 0)
    counts = proxy.Counts()
    for name in ("a.org", "b.org", "c.org", "d.org", "a.org"):
        counts.add("deny", name)
    assert counts.totals()["deny"] == {"a.org": 2, "b.org": 1, proxy.OTHER: 2}
    counts.add("allow", "x" * 300)
    assert list(counts.totals()["allow"]) == ["x" * 100]

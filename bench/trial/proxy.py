"""A CONNECT-only proxy: a trial reaches the two package index hosts through it and nothing else.

It runs in a container of its own that is on the trial's internal network and on one with a route
out. Every request that is not a CONNECT to an allowed `host:port` is answered 403. `SIGUSR1`
prints the totals of what it has allowed and denied as one JSON line, which is what the harness
records; the first events are printed one by one as well.
"""

from __future__ import annotations

import asyncio
import json
import signal
import sys
from collections import Counter
from functools import partial
from urllib.parse import urlsplit

INDEX = frozenset({("pypi.org", 443), ("files.pythonhosted.org", 443)})
PORT = 3128
HEAD_S = 10
CONNECT_S = 15
# Events printed one by one; the totals count every one, so a flood cannot hide what was allowed.
LOGGED = 500
# Targets kept by name; a client that names thousands is counted under one.
TARGETS = 50
OTHER = "(other)"


class Counts:
    """What was allowed, denied or failed, by `host:port`."""

    def __init__(self) -> None:
        self.by_verdict: dict[str, Counter[str]] = {
            "allow": Counter(),
            "deny": Counter(),
            "error": Counter(),
        }
        self.printed = 0

    def add(self, verdict: str, target: str) -> None:
        counted = self.by_verdict[verdict]
        name = target[:100].lower()
        counted[name if name in counted or len(counted) < TARGETS else OTHER] += 1
        if self.printed < LOGGED:
            self.printed += 1
            print(json.dumps({"verdict": verdict, "target": name}), flush=True)

    def totals(self) -> dict[str, dict[str, int]]:
        return {verdict: dict(counted) for verdict, counted in self.by_verdict.items()}


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except OSError:
        pass
    finally:
        writer.close()


async def head(reader: asyncio.StreamReader) -> list[str]:
    """The request line's words; the headers after it are read and dropped."""
    words = (await reader.readline()).decode("latin-1").split()
    while words and await reader.readline() not in (b"\r\n", b"\n", b""):
        pass
    return words


async def handle(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    allowed: frozenset[tuple[str, int]],
    counts: Counts,
) -> None:
    target = "?"
    try:
        words = await asyncio.wait_for(head(reader), HEAD_S)
        target = words[1] if len(words) > 1 else "?"
        if "//" in target:
            target = urlsplit(target).netloc or "?"
        host, _, port = target.rpartition(":")
        if (
            len(words) == 3
            and words[0] == "CONNECT"
            and port.isascii()
            and port.isdigit()
            and (host.lower(), int(port)) in allowed
        ):
            try:
                upstream = await asyncio.wait_for(
                    asyncio.open_connection(host, int(port)), CONNECT_S
                )
            except (OSError, TimeoutError):
                counts.add("error", target)
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                return
            counts.add("allow", target)
            writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
            await writer.drain()
            await asyncio.gather(pipe(reader, upstream[1]), pipe(upstream[0], writer))
            return
        counts.add("deny", target)
        writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
        await writer.drain()
    except (OSError, TimeoutError, ValueError):
        counts.add("deny", target)
    finally:
        writer.close()


async def serve(
    host: str = "0.0.0.0",  # noqa: S104 - the container's own network is the boundary
    port: int = PORT,
    allowed: frozenset[tuple[str, int]] = INDEX,
    counts: Counts | None = None,
) -> asyncio.Server:
    counts = counts or Counts()
    return await asyncio.start_server(partial(handle, allowed=allowed, counts=counts), host, port)


async def main() -> None:  # pragma: no cover - runs as the container's process
    counts = Counts()
    server = await serve(counts=counts)
    asyncio.get_running_loop().add_signal_handler(
        signal.Signals["SIGUSR1"],
        lambda: print(json.dumps({"totals": counts.totals()}), flush=True),
    )
    print("proxy up", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":  # pragma: no cover - see above
    sys.exit(asyncio.run(main()))

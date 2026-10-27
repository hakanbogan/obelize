"""What a trial's container can reach and hold, as one JSON document on stdout.

Run by `bench/trial_collect.py selftest` in a container built exactly as a trial's is. It only
observes; `bench/trial_box.py` judges the document, and a property it cannot read is a failure.
Everything here is the standard library of the image's own Python.
"""

from __future__ import annotations

import json
import os
import platform
import re
import socket
import ssl
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

PROXY = ("obelize-trial-proxy", 3128)
GATEWAY_PORTS = (22, 80, 443)
# Hosts and ports a trial must not reach by any road. The first group is straight out; the second
# is asked of the proxy, which must answer each with 403.
DIRECT = (
    ("1.1.1.1", 443),
    ("8.8.8.8", 53),
    ("9.9.9.9", 443),
    ("2606:4700:4700::1111", 443),
)
NAMES = ("example.com", "pypi.org", "files.pythonhosted.org", "host.docker.internal")
DENIED = (
    "example.com:443",
    "github.com:443",
    "1.1.1.1:443",
    "pypi.org:80",
    "pypi.org:22",
    "files.pythonhosted.org:80",
    "host.docker.internal:443",
    "localhost:3128",
    "127.0.0.1:22",
    "obelize-trial-proxy:3128",
    "[::1]:443",
)
ALLOWED = ("pypi.org", "files.pythonhosted.org")
HOST_PATHS = (
    "/Users",
    "/Volumes",
    "/host_mnt",
    "/mnt/host",
    "/run/host-services",
    "/var/run/docker.sock",
    "/run/docker.sock",
)
TIMEOUT = 8


def reads(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return None


def status() -> dict[str, str]:
    found = {}
    for line in (reads("/proc/self/status") or "").splitlines():
        key, _, value = line.partition(":")
        if key in {"CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb", "NoNewPrivs", "Seccomp"}:
            found[key] = value.strip()
    return found


def ids() -> dict[str, list[int]]:
    """The real, effective, saved and file-system user and group ids and the supplementary groups,
    as the kernel lists them for this process."""
    found = {}
    for line in (reads("/proc/self/status") or "").splitlines():
        key, _, value = line.partition(":")
        if key in {"Uid", "Gid", "Groups"}:
            found[key.lower()] = [int(word) for word in value.split()]
    return found


def mounts() -> list[str]:
    return [line.split()[4] for line in (reads("/proc/self/mountinfo") or "").splitlines()]


def reached(label: str, attempt: Callable[..., object], *arguments: object) -> dict[str, object]:
    """Whether `attempt(*arguments)` got through, and what it said."""
    try:
        return {"label": label, "reached": True, "detail": str(attempt(*arguments))}
    except Exception as error:
        return {
            "label": label,
            "reached": False,
            "detail": f"{type(error).__name__}: {error}"[:120],
        }


def connect(host: str, port: int) -> str:
    with socket.create_connection((host, port), timeout=TIMEOUT):
        return "connected"


def resolve(name: str) -> str:
    return str(socket.getaddrinfo(name, 443)[0][4][0])


def gateways() -> list[str]:
    """The default routes' gateways, from the routing table."""
    found = []
    for line in (reads("/proc/net/route") or "").splitlines()[1:]:
        fields = line.split()
        if len(fields) > 2 and fields[1] == "00000000":
            raw = bytes.fromhex(fields[2])[::-1]
            found.append(".".join(str(part) for part in raw))
    return found


def through_proxy(target: str, request: str | None = None) -> dict[str, object]:
    """The status the proxy gives to a CONNECT, and, for an allowed host, to a request over TLS."""
    row: dict[str, object] = {"target": target, "status": None, "http": None, "detail": ""}
    try:
        with socket.create_connection(PROXY, timeout=TIMEOUT) as sock:
            sock.sendall(
                request.encode() if request else f"CONNECT {target} HTTP/1.1\r\n\r\n".encode()
            )
            answer = sock.recv(256).decode("latin-1")
            match = re.match(r"HTTP/1\.[01] (\d{3})", answer)
            row["status"] = int(match.group(1)) if match else None
            if row["status"] == 200 and request is None:
                host = target.partition(":")[0]
                with ssl.create_default_context().wrap_socket(sock, server_hostname=host) as tls:
                    tls.sendall(
                        f"GET / HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode()
                    )
                    first = tls.recv(64).decode("latin-1")
                    reply = re.match(r"HTTP/1\.[01] (\d{3})", first)
                    row["http"] = int(reply.group(1)) if reply else None
    except Exception as error:
        row["detail"] = f"{type(error).__name__}: {error}"[:120]
    return row


def pythons() -> dict[str, str]:
    """The minor release and full version of each interpreter uv holds."""
    found = {}
    for path in Path(os.environ.get("UV_PYTHON_INSTALL_DIR", "/opt/uv-python")).glob("cpython-*"):
        match = re.match(r"cpython-(3\.\d+)\.(\d+)-", path.name)
        if match:
            found[match.group(1)] = f"{match.group(1)}.{match.group(2)}"
    return found


def uv_version() -> str | None:
    try:
        return subprocess.run(
            ["uv", "--version"], capture_output=True, text=True, timeout=20, check=False
        ).stdout.strip()
    except OSError:
        return None


def main() -> None:
    first = gateways()
    document = {
        **ids(),
        "status": status(),
        "pid1": (reads("/proc/1/cmdline") or "").replace("\0", " "),
        "mounts": mounts(),
        "host_paths": [path for path in HOST_PATHS if os.path.exists(path)],
        "env": sorted(os.environ),
        "cgroup": {
            name: reads(f"/sys/fs/cgroup/{name}")
            for name in ("memory.max", "memory.swap.max", "pids.max", "cpu.max")
        },
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "pythons": pythons(),
        "uv": uv_version(),
        "gateways": first,
        "direct": [
            *(reached(f"tcp {host}:{port}", connect, host, port) for host, port in DIRECT),
            *(
                reached(f"tcp {gate}:{port}", connect, gate, port)
                for gate in first
                for port in GATEWAY_PORTS
            ),
            *(reached(f"dns {name}", resolve, name) for name in NAMES),
        ],
        "denied": [through_proxy(target) for target in DENIED]
        + [
            through_proxy(
                "example.com:80", "GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n"
            )
        ],
        "allowed": [through_proxy(f"{host}:443") for host in ALLOWED],
    }
    print(json.dumps(document))


if __name__ == "__main__":
    main()

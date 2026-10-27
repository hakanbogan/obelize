"""Records of the trial measurement as the collector writes them, for the tests of its scorer."""

from __future__ import annotations

from typing import Any

from bench import trial_box


def row(status: str = "pass", reason: str | None = None, **kept: Any) -> dict[str, Any]:
    """One repository's record; `kept` replaces any field."""
    base: dict[str, Any] = {
        "full_name": "o/r",
        "sha": "a" * 40,
        "band": "size:<1000",
        "distribution": "lib",
        "from": "1.0.0",
        "python": "3.12",
        "status": status,
        "reason": reason,
        "compared": 0,
        "broken": [],
        "broken_count": 0,
        "flaky": 0,
        "written": 0,
        "held": 0,
        "places": 0,
        "partial": False if status == "pass" else None,
        "exit_code": 0,
        "oom": False,
        "seconds": 10.0,
        "tail": None,
    }
    return {**base, **kept}


def record(rows: list[dict[str, Any]] | None = None, **kept: Any) -> dict[str, Any]:
    """A whole record of a frame; `kept` replaces any field."""
    base: dict[str, Any] = {
        "obelize_version": "0.10.0",
        "obelize_commit": "c" * 40,
        "wheel_sha256": "b" * 64,
        "image": "sha256:" + "d" * 64,
        "docker": "29.8.2",
        "uv": "uv 0.12.15 (aarch64-unknown-linux-gnu)",
        "machine": "aarch64",
        "python": "3.12.14",
        "pythons": {"3.9": "3.9.25", "3.12": "3.12.14", "3.13": "3.13.15"},
        "date": "2026-10-29T08:00:00Z",
        "limits": trial_box.Limits()._asdict(),
        "allowlist": list(trial_box.INDEX_HOSTS),
        "frame": "bench/upgrade/lib/sample.yaml",
        "distribution": "lib",
        "from": "1.0.0",
        "to": "2.0.0",
        "dry_run": {"obelize_version": "0.10.0", "unit": "file"},
        "selftest": {
            "passed": True,
            "failures": [],
            "at": "2026-10-29T07:59:00Z",
            "attempts": {"direct": 8, "denied": 12, "allowed": 2},
        },
        "proxy": {
            "allow": {"pypi.org:443": 90, "files.pythonhosted.org:443": 410},
            "deny": {"example.com:443": 2},
            "error": {},
        },
        "trial": rows
        if rows is not None
        else [
            row("pass", written=3, compared=12, seconds=40.0),
            row("pass", written=2, held=1, places=3, partial=True, compared=30, seconds=55.5),
            row("fail", "tests_broke", compared=20, broken=["t::a"], broken_count=2, flaky=1),
            row("inconclusive", "no_tests", seconds=8.0),
            row("error", "environment", exit_code=6, tail="uv sync failed", seconds=300.0),
        ],
    }
    return {**base, **kept}


FRAME = {
    "queried_at": "2026-10-24T00:00:00Z",
    "term": "t",
    "population": 4321,
    "repositories": [{"full_name": f"o/r{number}"} for number in range(20)],
}

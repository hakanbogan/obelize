"""Calls that take what they took, and names that are imported, annotated or handed to a call."""

from __future__ import annotations

import acme.calls
from acme.calls import Handle, Session, connect


def dial(host, port, hosts):
    acme.calls.connect(host, port, retries=2, secure=True)
    connect(host, port, retries=1, secure=False)
    return map(connect, hosts), Session(), isinstance(host, Session), Handle(*hosts, **{})


def typed(session: Session, other: "acme.calls.Handle") -> acme.calls.Session:
    return session

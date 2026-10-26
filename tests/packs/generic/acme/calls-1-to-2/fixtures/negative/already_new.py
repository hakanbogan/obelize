"""Calls that take what they took, and names that are imported, annotated or handed to a call."""

from __future__ import annotations

import acme.calls
from acme.calls import Session, connect


def dial(host, port, hosts):
    acme.calls.connect(host, port, retries=2, secure=True)
    connect(host, port, retries=1, secure=False)
    return map(connect, hosts), Session(), isinstance(host, Session)


def typed(session: Session, other: "acme.calls.Session") -> acme.calls.Session:
    return session

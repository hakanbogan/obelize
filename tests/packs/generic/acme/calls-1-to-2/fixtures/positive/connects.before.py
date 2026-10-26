"""Names acme-calls 2 changed, used where what changed reaches them: each call passes it, leaves
it out or hides it, and a name that is not called is read for a call to come."""

import acme.calls
from acme.calls import Session


class Pool(Session):
    pass


dial = acme.calls.connect


def open_all(host, rest):
    acme.calls.connect(host, 1, 2)
    acme.calls.connect(host, timeout=1, retries=2, secure=True)
    acme.calls.connect(host, 1, retries=2)
    acme.calls.connect(*rest)
    return Session(verbose=True)

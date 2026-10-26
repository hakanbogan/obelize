"""A name acme-calls 2 dropped, flagged wherever it is used."""

import acme.calls


def close(handle):
    return acme.calls.drop(handle)

"""A name acme-kit 2 dropped, which is reported and never rewritten."""

import acme.kit


def alive(client: acme.kit.Client) -> bool:
    return acme.kit.Client.ping(client)

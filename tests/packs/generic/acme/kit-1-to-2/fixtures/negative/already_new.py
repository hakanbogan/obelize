"""Code on acme-kit 2 already, which the rename must leave alone."""

import acme.kit
from acme.kit import Client, greet


def hello(name):
    greet(name)
    return acme.kit.greet(name), Client

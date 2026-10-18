"""Every way a renamed function is written: a module read, an alias, a from-import."""

import acme.kit
import acme.kit as kit
from acme.kit import Client, greet
from acme.kit import greet as hello


def greet_everyone(names):
    acme.kit.greet("all")
    kit.greet("alias")
    handler = acme.kit.greet
    greet("bound")
    hello("renamed on import")
    return [handler(name) for name in names], Client

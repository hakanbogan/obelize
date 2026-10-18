"""Every way a renamed function is written: a module read, an alias, a from-import."""

import acme.kit
import acme.kit as kit
from acme.kit import Client, old_greet
from acme.kit import old_greet as hello


def greet_everyone(names):
    acme.kit.old_greet("all")
    kit.old_greet("alias")
    handler = acme.kit.old_greet
    old_greet("bound")
    hello("renamed on import")
    return [handler(name) for name in names], Client

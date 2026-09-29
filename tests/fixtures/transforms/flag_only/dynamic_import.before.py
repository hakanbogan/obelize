"""The legacy module fetched by name, both ways the reason covers.

Neither resolves to an import statement, so the rewrite cannot follow it: what
the pack has to offer is a sentence, which is what this kind is.
"""

import importlib


def loaded():
    return importlib.import_module("google.generativeai")


def imported():
    return __import__("google.generativeai")

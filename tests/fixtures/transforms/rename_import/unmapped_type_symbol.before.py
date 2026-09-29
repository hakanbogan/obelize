"""A `types` name the pack's symbol map does not carry.

`BlockedPromptException` exists in the legacy submodule and the pack maps five
names, none of them this one, so the line is withheld rather than guessed at.
"""

from google.generativeai.types import BlockedPromptException


def safe(call, fallback=""):
    """Run `call`, and answer with `fallback` when the prompt was blocked."""
    try:
        return call()
    except BlockedPromptException:
        return fallback

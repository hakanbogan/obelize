"""Get and delete, where the one positional argument becomes the new keyword.

Both new methods are keyword-only, so the argument has to be lifted onto the
name at its index before anything else happens. Neither takes a configuration,
so neither call brings in the types submodule.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def fetch(name):
    return client.files.get(name=name)


def discard(name):
    client.files.delete(name=name)

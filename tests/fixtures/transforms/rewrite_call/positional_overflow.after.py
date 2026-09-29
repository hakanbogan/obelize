"""More positional arguments than the legacy signature the pack declares.

Not runnable as the author wrote it -- the legacy function takes one name --
which makes this the one refusal here that can only be graded against code
that does not run. Refusing is still the right answer: the alternative is to
map an argument onto a parameter the pack never named.

The key beside this file is what the rules produce and not what a run writes:
one of them refused, so ADR-010 F-1 leaves the file exactly as it was.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def fetch(name, revision):
    return genai.get_file(name, revision)

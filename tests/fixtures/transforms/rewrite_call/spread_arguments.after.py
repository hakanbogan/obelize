"""A call whose arguments are a mapping the rule cannot read.

A `**` splat is refused for the same reason a keyword outside the two lists is:
the rule cannot say which parameters are being passed, so it cannot say that
each of them carries.

The key beside this file is what the rules produce and not what a run writes:
one of them refused, so ADR-010 F-1 leaves the file exactly as it was.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def fetch(options):
    return genai.get_file(**options)

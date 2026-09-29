"""One parameter given by position and again by keyword.

The same shape as the overflow beside it and a different mistake: here the
pack does name the parameter, and the call names it twice. Also a `TypeError`
as written, and also refused rather than resolved in one direction.

The key beside this file is what the rules produce and not what a run writes:
one of them refused, so ADR-010 F-1 leaves the file exactly as it was.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def discard(handle):
    genai.delete_file(handle, name="files/other")

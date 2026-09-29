"""The one upload keyword that did not survive the move.

`resumable=` has no field on `types.UploadFileConfig` and no argument on
`client.files.upload`, so the pack names it in neither list and the call is
refused for passing a keyword with nowhere to go.

The key beside this file is what the rules produce and not what a run writes:
one of them refused, so ADR-010 F-1 leaves the file exactly as it was.
"""

from google import genai

client = genai.Client(api_key="AIzaNotARealKey")


def attach(path):
    return genai.upload_file(path, resumable=True)

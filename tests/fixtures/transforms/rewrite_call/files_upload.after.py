"""The upload, whose one positional argument is renamed and whose keywords are not.

`path` becomes `file` and the two remaining keywords become fields of a
configuration object the legacy call had no counterpart for.
"""

from google import genai
from google.genai import types

client = genai.Client(api_key="AIzaNotARealKey")


def attach(path):
    return client.files.upload(
        file=path,
        config=types.UploadFileConfig(mime_type="text/plain", display_name="notes"),
    )

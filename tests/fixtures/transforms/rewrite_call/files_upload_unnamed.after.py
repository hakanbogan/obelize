"""The upload that names no file, which the legacy call named after its path.

The new `files.upload` gives the file no display name, so the edit warns.
"""

from google import genai
from google.genai import types

client = genai.Client(api_key="AIzaNotARealKey")


def attach(path):
    return client.files.upload(file=path, config=types.UploadFileConfig(mime_type="text/plain"))

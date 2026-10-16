"""The upload that names no file, which the legacy call named after its path.

The new `files.upload` gives the file no display name, so the edit warns.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")


def attach(path):
    return genai.upload_file(path, mime_type="text/plain")

"""The upload, whose one positional argument is renamed and whose keywords are not.

`path` becomes `file` and the two remaining keywords become fields of a
configuration object the legacy call had no counterpart for.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")


def attach(path):
    return genai.upload_file(path, mime_type="text/plain", display_name="notes")

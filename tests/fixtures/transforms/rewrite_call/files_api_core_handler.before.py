"""An upload inside a handler for an exception the legacy SDK raised.

The new call raises `google.genai.errors.ClientError` where the legacy one
raised `google.api_core.exceptions.InvalidArgument`, so the fallback below
never runs once the call is rewritten.
"""

import google.generativeai as genai
from google.api_core import exceptions

genai.configure(api_key="AIzaNotARealKey")


def upload(path):
    try:
        return genai.upload_file(path)
    except exceptions.InvalidArgument:
        return None

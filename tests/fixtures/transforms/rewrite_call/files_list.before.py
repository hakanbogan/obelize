"""Listing files: one call whose only argument is a config field, one with none.

`page_size` was an argument of the legacy function and is a field of the new
configuration, so the emitted call carries `config=` and nothing else.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")


def recent():
    handles = genai.list_files(page_size=10)
    return [handle.display_name for handle in handles]


def everything():
    return list(genai.list_files())

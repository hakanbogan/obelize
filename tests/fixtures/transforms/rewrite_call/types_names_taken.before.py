"""A module that already binds both names the configuration could arrive under.

The configuration class is reached through a submodule, the module has to bind
a name for it, and the pack offers two. When the file has taken both there is
no name left to introduce, and the call is refused with the code the import
manager raises rather than with one of this rule's own.

The key beside this file is what the rules produce and not what a run writes:
one of them refused, so ADR-010 F-1 leaves the file exactly as it was.
"""

import google.generativeai as genai

types = {"plain": "text/plain"}
genai_types = {"plain": "text/plain"}

genai.configure(api_key="AIzaNotARealKey")


def attach(path):
    return genai.upload_file(path, mime_type=types["plain"], display_name=genai_types["plain"])

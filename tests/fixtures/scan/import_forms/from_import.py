"""Support replies, importing the two symbols this module needs by name.

One of the two is renamed on the way in, which is the shape that has to resolve
through the local name rather than through a module alias.
"""

import os

from google.generativeai import GenerativeModel as Model
from google.generativeai import configure

configure(api_key=os.environ["GEMINI_API_KEY"])

DEFAULT = Model("gemini-1.5-flash")


def draft(question):
    return DEFAULT.generate_content(question).text


def generate_content(question):
    """This module's own helper. It shares a name with the legacy method."""
    return draft(question).strip()

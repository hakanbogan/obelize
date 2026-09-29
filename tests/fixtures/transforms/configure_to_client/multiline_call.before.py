"""A call the author already split, which the rewrite does not join back up.

The layout rule emits a rewritten call multi-line when it was multi-line in the
source, so this file pins the branch that has nothing to do with width.
"""

import os

import google.generativeai as genai

genai.configure(
    api_key=os.environ["GEMINI_API_KEY"],
)

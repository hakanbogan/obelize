"""Release notes, importing the package the way the new SDK's own idiom reads.

`from google import generativeai` resolves perfectly and matched no rewrite rule
until C-27 added one, which is why it is here. The pin this module was installed
from is google-generativeai==0.8.6.
"""

import os

from google import generativeai

generativeai.configure(api_key=os.environ["GEMINI_API_KEY"])


def summarise(text):
    model = generativeai.GenerativeModel("gemini-1.5-flash")
    return model.generate_content(text).text

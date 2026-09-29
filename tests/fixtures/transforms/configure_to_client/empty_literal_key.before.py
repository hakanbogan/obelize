"""The other side of D5's boundary, and the behaviour change F-6 measured.

`configure(api_key="")` returns without error and `Client(api_key="")` raises
at construction, so an empty string literal is not the exemption a non-empty
one is and the warning fires.
"""

import google.generativeai as genai

genai.configure(api_key="")

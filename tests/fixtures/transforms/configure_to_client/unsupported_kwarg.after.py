"""The keyword argument the spikes added to the refused four.

`transport`, `client_options` and `default_metadata` were on the plan's list;
`client_info` was found by reading the legacy signature. None of the four has a
mechanical equivalent on the new client. COVERAGE.md gap 5.

No run writes this file: the key beside it shows the import moved, because the
other rule succeeded, and F-1 withholds the whole file because this one did not.
"""

import os

from google import genai
from google.api_core import client_info

genai.configure(api_key=os.environ["GEMINI_API_KEY"], client_info=client_info.ClientInfo())

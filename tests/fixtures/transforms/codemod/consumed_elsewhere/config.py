"""The module that calls `configure`, and the one this run has to leave alone.

`answer.py` beside it still calls the legacy SDK and has no `configure` of its
own, so it runs on the process-wide default this call sets. Rewriting this
file deletes that default: `answer.py` then fails on its first real call, while
a test suite that mocks the SDK stays green (e2e:E2E-02).
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

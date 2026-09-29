# svc-b: Gemini notes

The service is still on the retired SDK. The setup below is what runs in
production today.

```python
import os

import google.generativeai as genai

genai.configure(api_key=os.environ["GEMINI_API_KEY"])
model = genai.GenerativeModel("gemini-1.5-flash")
print(model.generate_content("hello").text)
```

The replacement is `from google import genai` plus a `genai.Client()`; see
`already_new.py` in this directory for the shape we are moving to.

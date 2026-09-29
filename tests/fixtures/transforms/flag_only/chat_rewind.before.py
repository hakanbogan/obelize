"""The two out-of-scope names that hang off an object rather than the module.

`rewind` is not one of the methods the pack maps, so the scan reports it as an
attribute read on a resolved receiver and rung 1 claims it before the binding
group's own refusal does; `from_cached_content` is a constructor with no
counterpart, so the object it would have built is out of scope too.
"""

import google.generativeai as genai

genai.configure(api_key="")


def cached(name):
    return genai.GenerativeModel.from_cached_content(name)


def talk(question):
    model = genai.GenerativeModel("gemini-1.5-flash")
    chat = model.start_chat()
    reply = chat.send_message(question)
    chat.rewind()
    return reply

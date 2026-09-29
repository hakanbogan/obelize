"""A chat nothing binds, which the scan refuses before this rule sees it.

`MODEL.start_chat().send_message(...)` reaches the chat through an expression
rather than through a name, so the scan cannot resolve the receiver of the
second call and withholds it -- and file atomicity then withholds everything
else. This is the file that makes the rule's silence about an unbound result
safe rather than lucky: it never has to decide.

The key beside this file is the file itself. Nothing in it is eligible, so a
run writes nothing at all.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

MODEL = genai.GenerativeModel("gemini-1.5-flash")


def converse(opening):
    return MODEL.start_chat().send_message(opening).text

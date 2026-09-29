"""The deleted statement is the last one in its block.

There is no statement after it for the comment to move onto, so it goes to the
end of the block -- keeping the blank lines that separated it from what is
above, because nothing else is going to supply them, and landing in front of
whatever the block already ended with, because that is where it was written.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")


def answer(prompt):
    return MODEL.generate_content(prompt).text


# Built after the reader above, which is legal and unusual.
MODEL = genai.GenerativeModel("gemini-1.5-flash")
# A note about the module as a whole, written after everything in it.

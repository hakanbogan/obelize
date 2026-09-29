"""The file comes back byte-identical, because neither rule can name anything.

The repository has a package of its own called `genai`, so the import rule has
no name left for the module; the client rule then has no name to reach
`genai.Client` through and refuses for the same reason rather than inventing a
second answer to the same question.
"""

import genai

import google.generativeai

google.generativeai.configure(api_key=genai.API_KEY)

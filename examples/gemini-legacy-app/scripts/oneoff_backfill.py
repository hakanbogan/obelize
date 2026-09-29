"""One-off script from 2024 that backfilled summaries for the sample corpus.

Kept around because it documents the prompt we used. Nobody runs it any more,
it has no tests, and `.obelize.yml` excludes `scripts/**` from the migration for
exactly that reason.
"""

import glob
import sys

import google.generativeai as genai

genai.configure(api_key=sys.argv[1])

model = genai.GenerativeModel("gemini-1.0-pro")

for path in sorted(glob.glob("sample_docs/*.txt")):
    with open(path) as fh:
        print(path, model.generate_content(fh.read()).text[:80])

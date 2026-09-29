"""A row nothing claims, which withholds the file exactly as a refusal does.

`genai.embed_content` is referenced and never called, so the scan resolves an
`attribute` finding and grades it `eligible` -- there is nothing wrong with
it. The rule that owns the symbol is written for a call, so no rule claims
the row, and a run that wrote this file would rewrite the import out from
under a name it had left behind.

No rule refused, so the code that names it is the row's own and not another
row's: `usage_unmapped` here, and `file_not_fully_migrated` on the two rows
that were ready to be written.
"""

import google.generativeai as genai

genai.configure(api_key="AIzaNotARealKey")

EMBED = genai.embed_content

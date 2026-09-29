"""The file the hand edit lands in, so that the dirty tree is not the plan's.

It imports nothing and is never rewritten. TM-8's refusal is over the whole
tree and not over the files a run means to write, and a case whose only
uncommitted change is in a file nobody planned to touch is what says so.
"""

WHAT = "notes"

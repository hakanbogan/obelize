"""Writes more than the output cap, between two recognisable markers.

The cap keeps the first 256 KiB and the last 768 KiB, so a correct capture
holds both markers and not the middle.
"""

import sys

sys.stdout.write("HEAD-MARKER\n")
sys.stdout.write("m" * int(sys.argv[1]))
sys.stdout.write("\nTAIL-MARKER\n")

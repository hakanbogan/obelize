"""A stub installed under the legacy module's name.

The third pattern id, and the one that is not a confidence reason of its own:
an assignment into `sys.modules` reaches the module by name like the other two
dynamic shapes, so it is reported as `dynamic_access` (ADR-019 D7). It replaces
the module for every later importer in the process, which is why it is flagged
rather than ignored.
"""

import sys


def install(fake):
    sys.modules["google.generativeai"] = fake

"""Statements that bind a name in a class body, for the tests of `rename_member`.

Each of `BINDINGS` binds `old_area` at the class's own level, in some form and branch; each of
`UNBOUND` mentions it without binding it there (a lambda's parameter, a function's local, a nested
class's own).
"""

from __future__ import annotations

BINDINGS = [
    "def old_area(self):\n        return 1",
    "async def old_area(self):\n        return 1",
    "old_area = None",
    "old_area: int",
    "old_area: int = 1",
    "old_area, other = 1, 2",
    "[old_area, *rest] = 1, 2",
    "*old_area, other = 1, 2",
    "old_area = other = None",
    "for old_area in range(3):\n        pass",
    "with open('f') as old_area:\n        pass",
    "try:\n        pass\n    except ValueError as old_area:\n        pass",
    "from fast import old_area",
    "from fast import other as old_area",
    "import old_area",
    "import fast.sub as old_area",
    "class old_area:\n        pass",
    "value = (old_area := 1)",
    "old_area = 0\n    old_area += 1",
    "if FLAG:\n        def old_area(self):\n            return 1\n    else:\n        pass",
    "try:\n        from fast import old_area\n    except ImportError:\n        old_area = None",
    "while FLAG:\n        old_area = 1",
]
UNBOUND = [
    "value = lambda old_area: old_area",
    "def later(self):\n        old_area = 1",
    "class Inner:\n        old_area = 1",
    "try:\n        pass\n    except ValueError:\n        pass",
    "self.old_area = 1",
    "items[0] = 1",
    "import fast.sub",
]

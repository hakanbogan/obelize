"""What a plugin imports: the interface of a rule kind that a pack can name.

A plugin is a distribution the user installs, whose entry point in the group `obelize.kinds` names
a kind: an object with `api = 1`, a `params` model derived from `Params`, and a `rule(change_id,
params)` method that returns a rule. A pack uses it as `kind: plugin`, `plugin: <entry point>`,
beside `requires_plugins`. It runs in obelize's process with the user's rights, so it runs only
once the user has allowed that distribution and entry point in `~/.config/obelize/config.yml`.

The rule is the one every kind is: `claims(finding)` says which findings it rewrites,
`apply(context)` records the edits in `context.rewrites` and returns what it did, and `consumes`,
`client_readers` and `renames` say what it replaces. It reads and writes libcst nodes, so the range
of libcst that obelize installs (`pyproject.toml`) is part of this interface. Names here do not
change in 0.x without a line in the changelog; what is not here is not an interface.
"""

from __future__ import annotations

from obelize.models import BailCode, Edit, Finding
from obelize.transforms.base import BailError, Rule, RuleContext
from obelize.transforms.plugins import API, Params
from obelize.transforms.tree import Position, Tree

__all__ = [
    "API",
    "BailCode",
    "BailError",
    "Edit",
    "Finding",
    "Params",
    "Position",
    "Rule",
    "RuleContext",
    "Tree",
]

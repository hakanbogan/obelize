"""`plugin`: a change made by a rule the user's own plugin provides.

The plugin was loaded, allowed and given its params by `transforms/plugins.py` before any file was
read; this only stands in for its rule, so that a pack's change reaches it as any kind's does.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from obelize.models import Edit
from obelize.transforms import plugins

if TYPE_CHECKING:
    from obelize.models import Finding
    from obelize.packs.schema import ChangeKind, PluginChange
    from obelize.transforms.base import RuleContext


class Plugin:
    kind: ClassVar[ChangeKind] = "plugin"

    def __init__(self, change: PluginChange) -> None:
        self._id = change.id
        self._rule = plugins.rule(change)

    @property
    def consumes(self) -> frozenset[str]:
        return self._rule.consumes

    @property
    def client_readers(self) -> frozenset[str]:
        return self._rule.client_readers

    @property
    def renames(self) -> frozenset[str]:
        """What the rule renames to a name of the new release, if it says."""
        return frozenset(getattr(self._rule, "renames", ()))

    def claims(self, finding: Finding) -> bool:
        return self._rule.claims(finding)

    def apply(self, context: RuleContext) -> tuple[Edit, ...]:
        """What the plugin did, as rows of this change: it may hand back a generator, which the
        driver would read once and find empty the second time, and each row is named for the change
        and not for whatever the plugin called it."""
        reported = tuple(self._rule.apply(context))
        if not all(isinstance(row, Edit) for row in reported):
            raise TypeError("a plugin's apply returns Edit rows")
        return tuple(Edit(**{**row.model_dump(), "rule_id": self._id}) for row in reported)


__all__ = ["Plugin"]

"""Which class implements which pack `kind`; a new kind is a code change here, never a pack's.

`RULES` read parsed source; `MANIFEST_RULES` read unparsed dependency manifests, so a driver can
never hand one a libcst module. `IMPLEMENTED` must equal `packs/schema.py`'s `CHANGE_KINDS`;
`tests/packs/test_all_packs.py` reads this registry, so the two cannot drift.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from obelize.packs.schema import Change, ChangeKind
from obelize.transforms.kinds.configure_to_client import ConfigureToClient
from obelize.transforms.kinds.flag_only import FlagOnly
from obelize.transforms.kinds.generative_model_calls import GenerativeModelCalls
from obelize.transforms.kinds.manifest_dependency import ManifestDependency
from obelize.transforms.kinds.rename_import import RenameImport
from obelize.transforms.kinds.rename_setting import RenameSetting
from obelize.transforms.kinds.rewrite_call import RewriteCall

if TYPE_CHECKING:  # pragma: no cover - imported for typing only
    from obelize.packs.schema import PackDocument
    from obelize.transforms.base import Rule
    from obelize.transforms.manifest import ManifestRule

# Keyed by each class's own `kind`, so a class cannot be filed under the wrong key.
RULES: Final[dict[ChangeKind, type[Rule]]] = {
    RenameImport.kind: RenameImport,
    ConfigureToClient.kind: ConfigureToClient,
    GenerativeModelCalls.kind: GenerativeModelCalls,
    RewriteCall.kind: RewriteCall,
    RenameSetting.kind: RenameSetting,
    FlagOnly.kind: FlagOnly,
}

# A table, not a special case, so a second manifest kind is a new row, not a branch in a driver.
MANIFEST_RULES: Final[dict[ChangeKind, type[ManifestRule]]] = {
    ManifestDependency.kind: ManifestDependency,
}

IMPLEMENTED: Final[frozenset[ChangeKind]] = frozenset(RULES) | frozenset(MANIFEST_RULES)


def rule_for(change: Change) -> Rule | None:
    """The rule for one pack change, or `None` when it is not a file's."""
    factory = RULES.get(change.kind)
    return None if factory is None else factory(change)  # type: ignore[call-arg]


def manifest_rule_for(change: Change) -> ManifestRule | None:
    """The manifest rule for one pack change, or `None` when it is a file's."""
    factory = MANIFEST_RULES.get(change.kind)
    return None if factory is None else factory(change)  # type: ignore[call-arg]


def rules(pack: PackDocument) -> tuple[Rule, ...]:
    """Every source-file rule of `pack`, in declared order, which is the order they run in.

    The order matters: `configure_to_client` uses the alias `rename_import` bound, and
    `generative_model_calls` calls the client `configure_to_client` placed.
    """
    return tuple(rule for rule in map(rule_for, pack.changes) if rule is not None)


def manifest_rules(pack: PackDocument) -> tuple[ManifestRule, ...]:
    """Every manifest rule of `pack`, in declared order.

    Nothing may depend on that order: each reads only the repository-wide verdict and one file's
    bytes, and no rule writes either.
    """
    return tuple(rule for rule in map(manifest_rule_for, pack.changes) if rule is not None)

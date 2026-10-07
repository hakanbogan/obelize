"""An invented SDK whose 2.x keeps the module's name, for the shared-module unit tests.

`acme.kit` is the legacy and the new surface alike: `Greeter` and `Quote` are what 2.x dropped, and
everything else under it (`Client`, `token`) is what it kept, so nothing but `symbols` is legacy.
"""

from __future__ import annotations

from pathlib import Path

from obelize.packs import loader
from obelize.packs.schema import (
    FlagOnlyChange,
    FlagOnlyParams,
    ManifestDependencyChange,
    ManifestDependencyParams,
    Match,
    PackDocument,
    PackSource,
    RewriteCallChange,
    RewriteCallParams,
    Target,
    VersionRange,
)

SAY = RewriteCallChange(
    id="say",
    kind="rewrite_call",
    citation="Acme Kit 2 notes, 'Greeting'",
    fixtures=("fixtures/negative/none.py", "fixtures/positive/one.before.py"),
    params=RewriteCallParams(
        legacy_symbol="acme.kit.Greeter.say",
        new_call="talk.say",
        root="module",
        # `name` may also be positional, and is the only one renamed.
        positional_to_kw=("name",),
        keywords=("loud", "times"),
        arg_map={"name": "who"},
        result_paths=("reply.text", "spent.words"),
    ),
)

FETCH = RewriteCallChange(
    id="fetch",
    kind="rewrite_call",
    citation="Acme Kit 2 notes, 'Quotes'",
    fixtures=("fixtures/negative/none.py", "fixtures/positive/one.before.py"),
    params=RewriteCallParams(
        legacy_symbol="acme.kit.Quote.get",
        new_call="quotes.fetch",
        root="module",
        keywords=("symbol",),
        result_paths=("rows[].price",),
    ),
)

FLAGGED = FlagOnlyChange(
    id="flag-legacy",
    kind="flag_only",
    citation="Acme Kit 2 notes, 'What was dropped'",
    fixtures=("fixtures/negative/none.py", "fixtures/positive/one.before.py"),
    params=FlagOnlyParams(
        message="acme.kit 2 has no legacy module and no proxy setting.",
        suggestion="Port these call sites by hand against the acme.kit 2 reference.",
        symbols=("acme.kit.legacy", "acme.kit.proxy"),
        patterns=("dynamic_access", "mock_patch_target", "sys_modules_stub"),
    ),
)

# One name before and after: the major version is the migration.
PIN = ManifestDependencyChange(
    id="pin",
    kind="manifest_dependency",
    citation="Acme Kit 2 notes, 'Installing'",
    fixtures=("fixtures/negative/none.txt", "fixtures/positive/one.before.txt"),
    params=ManifestDependencyParams(from_name="acme-kit", to_name="acme-kit", to_spec=">=2,<3"),
)

PACK = PackDocument(
    id="acme/acme-kit-1-to-2",
    pack_version="0.1.0",
    provider="acme",
    language="python",
    source=PackSource(
        type="official_guide", url="https://example.invalid/acme-kit", retrieved_at="2026-10-07"
    ),
    **{"from": VersionRange(package="acme-kit", version=">=1.2,<2")},
    to=Target(package="acme-kit", version=">=2,<3", requires_python=">=3.9"),
    match=Match(
        imports=("acme.kit",),
        symbols=(
            "acme.kit.Greeter",
            "acme.kit.Quote",
            "acme.kit.legacy",
            "acme.kit.proxy",
        ),
        prefilter_tokens=("acme",),
        shared=True,
    ),
    changes=(SAY, FETCH, FLAGGED, PIN),
    limitations=("Invented for the tests; no library of this name exists.",),
)

SPEC = loader.to_scan_spec(
    loader.LoadedPack(
        pack=PACK,
        sha256="0" * 64,
        data=b"",
        reference=PACK.id,
        bundled=False,
        path=Path("pack.yaml"),
    )
)

"""What `obelize pack test` checks: a pack against the fixtures and sources beside it.

`obelize pack validate` reads the pack alone. These checks run it: every fixture is on disk, every
answer key is what the rules write, applying the pack twice changes nothing the first time did not,
and every change cites a source. A bundled pack passes the same checks (`tests/packs/`), so a pack
of your own is held to the standard the three that ship are.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from obelize.models import Config
from obelize.packs import loader

if TYPE_CHECKING:
    from collections.abc import Callable

    from obelize.transforms import codemod


@dataclass(frozen=True, slots=True)
class Check:
    """One thing a pack must satisfy, and what is wrong when it does not. A `setup` check is about
    the machine the pack is tested on and not about the pack."""

    name: str
    problems: tuple[str, ...] = ()
    setup: bool = False

    @property
    def ok(self) -> bool:
        return not self.problems


def run(loaded: loader.LoadedPack) -> tuple[Check, ...]:
    """Every check over one pack, in the order a person fixes them."""
    folder = loaded.path.parent
    steps: tuple[tuple[str, Callable[[loader.LoadedPack, Path], list[str]]], ...] = (
        ("every fixture the pack names is on disk, and every file there is named", _declared),
        ("every change has a positive and a negative fixture", _both_kinds),
        ("every Python fixture parses and compiles", _compiles),
        ("positive fixtures reach the scan, and negative ones do not", _prefilter),
        ("the tools the pack's fixers run are installed at a release it accepts", _tools),
        ("an answer key exists for exactly the fixtures a run migrates whole", _keys_exist),
        ("every answer key is what the rules write into its fixture", _keys_agree),
        ("applying the pack twice writes what applying it once did", _idempotent),
        ("two runs over one input write the same bytes", _deterministic),
        ("SOURCES.md has a section for every change and cites the page", _sources),
    )
    tools = _tools(loaded, folder)

    def one(name: str, step: Callable[[loader.LoadedPack, Path], list[str]]) -> Check:
        if step is _tools:
            return Check(name, tuple(tools), setup=True)
        if tools and step in _RUN:
            return Check(name, ("not run: it needs the tool above",), setup=True)
        return Check(name, tuple(step(loaded, folder)))

    return tuple(one(name, step) for name, step in steps)


def _fixtures(folder: Path) -> list[Path]:
    return [path for path in (folder / "fixtures").rglob("*") if path.is_file()]


def _declared(loaded: loader.LoadedPack, folder: Path) -> list[str]:
    declared = {name for change in loaded.pack.changes for name in change.fixtures}
    files = _fixtures(folder)
    keys = {path for path in files if ".after." in path.name}
    on_disk = {path.relative_to(folder).as_posix() for path in files if path not in keys}
    problems = [f"{name} is named and not on disk" for name in sorted(declared - on_disk)]
    problems += [f"{name} is on disk and no change names it" for name in sorted(on_disk - declared)]
    problems += [
        f"{key.name} is an answer key with no {key.name.replace('.after.', '.before.')} beside it"
        for key in sorted(keys)
        if not key.with_name(key.name.replace(".after.", ".before.")).exists()
    ]
    return problems


def _both_kinds(loaded: loader.LoadedPack, folder: Path) -> list[str]:
    problems = []
    for change in loaded.pack.changes:
        for kind in ("positive", "negative"):
            if not any(name.startswith(f"fixtures/{kind}/") for name in change.fixtures):
                problems.append(f"{change.id} names no {kind} fixture")
    return problems


def _compiles(loaded: loader.LoadedPack, folder: Path) -> list[str]:
    import libcst as cst

    problems = []
    for path in sorted(folder.joinpath("fixtures").rglob("*.py")):
        data = path.read_bytes()
        try:
            if cst.parse_module(data).bytes != data:
                problems.append(f"{path.name} does not read back byte for byte")
            compile(data, path.name, "exec")
        except (cst.ParserSyntaxError, SyntaxError, ValueError) as error:
            problems.append(f"{path.name} does not parse: {error}")
    return problems


def _prefilter(loaded: loader.LoadedPack, folder: Path) -> list[str]:
    tokens = loaded.pack.match.prefilter_tokens
    problems = []
    for path in sorted(folder.joinpath("fixtures", "positive").glob("*.before.py")):
        if not any(token.encode("ascii") in path.read_bytes() for token in tokens):
            problems.append(f"{path.name} holds no prefilter token, so the scan never parses it")
    for path in sorted(folder.joinpath("fixtures", "negative").glob("*.py")):
        if loaded.pack.match.shared:
            problems += _shared_negative(loaded, path)
        else:
            found = [token for token in tokens if token.encode("ascii") in path.read_bytes()]
            if found:
                problems.append(f"{path.name} holds {found}, so the prefilter does not skip it")
    return problems


def _shared_negative(loaded: loader.LoadedPack, path: Path) -> list[str]:
    """A shared module's token is the new SDK's too, so its negative is scanned and must find
    nothing to migrate."""
    from obelize.scan import runner as scanner

    with tempfile.TemporaryDirectory(prefix="obelize-pack-test-") as work:
        (Path(work) / path.name).write_bytes(path.read_bytes())
        found = scanner.scan(Path(work), Config(), loader.to_scan_spec(loaded), jobs=1).findings
    return [
        f"{path.name} line {row.line} is a usage of the legacy API ({row.symbol})"
        for row in found
        if row.scan_status != "not_a_usage"
    ]


def _tools(loaded: loader.LoadedPack, folder: Path) -> list[str]:
    from obelize.transforms import fixers

    found = (fixers.problem(change.params.fixer) for change in loaded.pack.fixers())
    return [problem for problem in found if problem is not None]


def migrate(loaded: loader.LoadedPack, work: Path) -> codemod.Run:
    """The product's driver over `work`, so a pack is graded by the code that runs it."""
    from obelize.scan import runner as scanner
    from obelize.transforms import codemod

    spec = loader.to_scan_spec(loaded)
    scan = scanner.scan(work, Config(), spec, jobs=1)
    sources = {result.path: (work / result.path).read_bytes() for result in scan.results}
    return codemod.run(scan, sources, loaded.pack, spec)


def migrated(loaded: loader.LoadedPack, folder: Path, work: Path) -> dict[str, tuple[bool, bytes]]:
    """Each positive fixture, a repository of its own, and whether a run migrated it whole.

    One repository each: a fixture left on the legacy SDK would hold back every other fixture's
    client.
    """
    decided: dict[str, tuple[bool, bytes]] = {}
    for path in sorted(folder.joinpath("fixtures", "positive").glob("*.before.py")):
        case = work / path.stem
        case.mkdir()
        (case / path.name).write_bytes(path.read_bytes())
        decided.update({row.path: (row.written, row.after) for row in migrate(loaded, case).files})
    return decided


def _keys_exist(loaded: loader.LoadedPack, folder: Path) -> list[str]:
    problems = []
    with tempfile.TemporaryDirectory(prefix="obelize-pack-test-") as work:
        decided = migrated(loaded, folder, Path(work))
    for change in loaded.pack.changes:
        for name in change.fixtures:
            if not name.startswith("fixtures/positive/") or not name.endswith(".py"):
                continue
            key = folder / name.replace(".before.", ".after.")
            expected = decided.get(Path(name).name, (False, b""))[0]
            if ".before." not in name:
                problems.append(f"{name} is a positive fixture with no .before. in its name")
            elif key.exists() is not expected:
                problems.append(
                    f"{key.name} {'is missing' if expected else 'exists'} while a run "
                    f"{'can' if expected else 'cannot'} migrate {Path(name).name} whole"
                )
    return problems


def _keys_agree(loaded: loader.LoadedPack, folder: Path) -> list[str]:
    keys = sorted(folder.joinpath("fixtures", "positive").glob("*.after.py"))
    problems = []
    if keys:
        with tempfile.TemporaryDirectory(prefix="obelize-pack-test-") as work:
            decided = migrated(loaded, folder, Path(work))
        for key in keys:
            source = key.name.replace(".after.", ".before.")
            produced = decided.get(source, (False, b""))[1]
            if produced.decode("utf-8", "replace") != key.read_text(encoding="utf-8"):
                problems.append(f"{key.name} is not what the rules write into {source}")
    return problems + _manifest_key(loaded, folder)


def manifest_output(loaded: loader.LoadedPack, folder: Path) -> bytes | None:
    """What the pack's dependency rule writes into `requirements.before.txt`, if it has both."""
    from obelize.scan import manifests
    from obelize.transforms import manifest as manifest_rules
    from obelize.transforms import registry

    before = folder / "fixtures" / "positive" / "requirements.before.txt"
    if not before.is_file() or not registry.manifest_rules(loaded.pack):
        return None
    name, data = "requirements.txt", before.read_bytes()
    plan = manifests.plan(
        manifests.declarations(name, data),
        manifests.Migration(migrated=("app.py",)),
        loader.to_scan_spec(loaded),
    )
    context = manifest_rules.ManifestContext.build(name, data, plan)
    for rule in registry.manifest_rules(loaded.pack):
        rule.apply(context)
    return manifest_rules.finish(context)


def _manifest_key(loaded: loader.LoadedPack, folder: Path) -> list[str]:
    produced = manifest_output(loaded, folder)
    if produced is None:
        return []
    key = folder / "fixtures" / "positive" / "requirements.after.txt"
    if not key.is_file():
        return [f"{key.name} is missing beside requirements.before.txt"]
    if produced != key.read_bytes():
        return [f"{key.name} is not what the rule writes into requirements.before.txt"]
    return []


def _idempotent(loaded: loader.LoadedPack, folder: Path) -> list[str]:
    """Written to disk and run again, not compared in memory: idempotence is a repository claim."""
    with tempfile.TemporaryDirectory(prefix="obelize-pack-test-") as scratch:
        cases, work = _fresh(Path(scratch), "cases"), _fresh(Path(scratch), "again")
        for name, (_written, data) in sorted(migrated(loaded, folder, cases).items()):
            (work / name).write_bytes(data)
        again = migrate(loaded, work)
    problems = [
        f"{row.path} is migrated again by a second run"
        for row in again.edits
        if row.status == "auto"
    ]
    if again.written:
        problems.append(
            "a second run writes " + ", ".join(sorted(row.path for row in again.written))
        )
    return problems


def _fresh(parent: Path, name: str) -> Path:
    path = parent / name
    path.mkdir()
    return path


def _deterministic(loaded: loader.LoadedPack, folder: Path) -> list[str]:
    with tempfile.TemporaryDirectory(prefix="obelize-pack-test-") as scratch:
        work = _fresh(Path(scratch), "once")
        for path in sorted(folder.joinpath("fixtures", "positive").glob("*.before.py")):
            (work / path.name).write_bytes(path.read_bytes())
        first, second = migrate(loaded, work), migrate(loaded, work)
    if [(row.path, row.after) for row in first.outcomes] != [
        (row.path, row.after) for row in second.outcomes
    ] or first.edits != second.edits:
        return ["two runs over the same files wrote different bytes"]
    return []


# The checks that run the pack, and so need the tools its fixers run.
_RUN = (_keys_exist, _keys_agree, _idempotent, _deterministic)


def _sources(loaded: loader.LoadedPack, folder: Path) -> list[str]:
    path = folder / "SOURCES.md"
    if not path.is_file():
        return ["SOURCES.md is missing: every change cites where its facts were read"]
    text = path.read_text(encoding="utf-8")
    _prose, _, sections = text.partition("\n---\n")
    headings = re.findall(r"^## (.+)$", sections, re.MULTILINE)
    cited = {part.strip() for heading in headings for part in heading.split(",")}
    changes = {change.id for change in loaded.pack.changes}
    problems = [f"SOURCES.md has no section for {name}" for name in sorted(changes - cited)]
    problems += [
        f"SOURCES.md has a section for {name}, which is no change"
        for name in sorted(cited - changes)
    ]
    source = loaded.pack.source
    if source.url not in text:
        problems.append(f"SOURCES.md does not name the source url {source.url}")
    if source.sha256 is not None and source.sha256 not in text:
        problems.append("SOURCES.md does not record the sha256 of the page the pack cites")
    return problems


__all__ = ["Check", "manifest_output", "migrate", "migrated", "run"]

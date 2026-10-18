"""`obelize pack new`: a pack that loads, with the fixtures and sources `obelize pack test` reads.

The skeleton migrates one thing, a module that moved to another, and moves the dependency line with
it. Its answer keys are what the rules write into the fixtures today, so they pass; they are
there to be read and replaced as the pack grows, and the pack says so.
"""

from __future__ import annotations

import datetime as dt
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet

from obelize.models import bounds
from obelize.packs import check, loader
from obelize.packs.schema import _PACK_ID


class ScaffoldError(ValueError):
    """What is wrong with the request, in words for the person who typed it."""


@dataclass(frozen=True, slots=True)
class Plan:
    """A pack to make: both sides as requirements, the modules, and where it was read from."""

    pack_id: str
    legacy: Requirement
    new: Requirement
    guide: str
    module: str
    to_module: str
    requires_python: str
    retrieved: dt.date

    @property
    def provider(self) -> str:
        return self.pack_id.split("/", 1)[0]

    @property
    def slug(self) -> str:
        return self.pack_id.split("/", 1)[1]


def plan(
    pack_id: str,
    legacy: str,
    new: str,
    guide: str,
    *,
    module: str | None = None,
    to_module: str | None = None,
    requires_python: str = ">=3.9",
    today: dt.date | None = None,
) -> Plan:
    """The request as a `Plan`, or a `ScaffoldError` saying which part is wrong."""
    if not _PACK_ID.fullmatch(pack_id):
        raise ScaffoldError(
            f"{pack_id!r} is not a pack id: write <provider>/<name> in lowercase letters, digits "
            f"and hyphens, such as py-pdf/pypdf2-to-pypdf."
        )
    old, fresh = _requirement("--from", legacy), _requirement("--to", new)
    floor = bounds(old.specifier)[0]
    if floor is None or not old.specifier.contains(floor):
        raise ScaffoldError(
            f"--from {legacy!r} needs a range with a lower bound that it admits, such as "
            f"{old.name}>=1,<2: the pack's fixtures pin the release it starts at."
        )
    try:
        SpecifierSet(requires_python)
    except ValueError as error:
        raise ScaffoldError(
            f"--requires-python {requires_python!r} is not a PEP 440 range."
        ) from error
    return Plan(
        pack_id=pack_id,
        legacy=old,
        new=fresh,
        guide=guide,
        module=module or old.name.replace("-", "_").replace(".", "_"),
        to_module=to_module or fresh.name.replace("-", "_").replace(".", "_"),
        requires_python=requires_python,
        retrieved=today or dt.datetime.now(dt.UTC).date(),
    )


def _requirement(flag: str, text: str) -> Requirement:
    try:
        requirement = Requirement(text)
    except InvalidRequirement as error:
        raise ScaffoldError(f"{flag} {text!r} is not a requirement such as pypdf>=6.19.") from error
    if not requirement.specifier:
        raise ScaffoldError(f"{flag} {text!r} names no versions: write a range, such as {text}>=1.")
    return requirement


def write(directory: Path, made: Plan) -> tuple[str, ...]:
    """Make `<directory>/<provider>/<slug>/`, load it, and write the answer keys from the rules.

    Returns the files made, relative to the pack's folder. A folder that exists is never written
    into, and one that does not make a pack that loads is removed.
    """
    folder = directory / made.provider / made.slug
    if folder.exists():
        raise ScaffoldError(
            f"{folder} exists already; pack new makes a folder and never writes into one."
        )
    files = _files(made)
    try:
        for name, text in files.items():
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
        keys = _keys(loader.load(str(folder / loader.PACK_FILENAME)), folder)
        for name, data in keys.items():
            (folder / name).write_bytes(data)
    except loader.PackInvalidError as error:
        shutil.rmtree(folder, ignore_errors=True)
        raise ScaffoldError(str(error)) from error
    return tuple(sorted({*files, *keys}))


def _keys(loaded: loader.LoadedPack, folder: Path) -> dict[str, bytes]:
    """The answer keys: what the rules write into each fixture that a run migrates whole."""
    with tempfile.TemporaryDirectory(prefix="obelize-pack-new-") as work:
        decided = check.migrated(loaded, folder, Path(work))
    keys = {
        f"fixtures/positive/{name.replace('.before.', '.after.')}": data
        for name, (written, data) in decided.items()
        if written
    }
    manifest = check.manifest_output(loaded, folder)
    assert manifest is not None  # noqa: S101 - the skeleton has both the fixture and the change
    keys["fixtures/positive/requirements.after.txt"] = manifest
    return keys


def _files(made: Plan) -> dict[str, str]:
    alias = made.to_module.rpartition(".")[2]
    token = made.module.rpartition(".")[2]
    pin = bounds(made.legacy.specifier)[0]
    assert pin is not None  # noqa: S101 - `plan` refused a range without a floor
    return {
        "pack.yaml": _pack(made, alias, token),
        "SOURCES.md": _sources(made),
        "fixtures/positive/import_module.before.py": (
            '"""The module imported whole: its name goes, and each read goes through the new '
            'module."""\n\n'
            f"import {made.module}\n\n\ndef use():\n    return {made.module}.example()\n"
        ),
        "fixtures/negative/unrelated.py": (
            '"""A different library, which the rename must not touch."""\n\n'
            "import json\n\n\ndef dump(value):\n    return json.dumps(value)\n"
        ),
        "fixtures/positive/requirements.before.txt": _requirements(made.legacy.name, f"=={pin}"),
        "fixtures/negative/requirements_already_new.txt": _requirements(
            made.new.name, str(made.new.specifier), "Already migrated, and the rule adds no pin."
        ),
    }


def _requirements(name: str, specifier: str, note: str | None = None) -> str:
    note = note or "The dependency declaration the migration has to move with the code."
    return f"# {note}\n{name}{specifier}\nrequests>=2.31\n"


def _pack(made: Plan, alias: str, token: str) -> str:
    return f"""# A migration pack is data: it picks rule kinds that obelize implements and supplies
# their parameters. Edit it, then run `obelize pack test <this folder>` to check it against
# the fixtures beside it. The format: https://github.com/hakanbogan/obelize/blob/main/docs/PACK_SPEC.md
id: {made.pack_id}
pack_version: 0.1.0
provider: {made.provider}
language: python

source:
  type: official_guide
  url: {made.guide}
  retrieved_at: {made.retrieved.isoformat()}

from:
  package: {made.legacy.name}
  version: "{made.legacy.specifier}"
to:
  package: {made.new.name}
  version: "{made.new.specifier}"
  requires_python: "{made.requires_python}"

match:
  imports:
    - {made.module}
  # Every name of the old module that the pack finds. `example` is a stand-in: list yours.
  symbols:
    - {made.module}.example
  prefilter_tokens:
    - {token}

changes:
  - id: rename-import
    kind: rename_import
    citation: "TODO: the page and section of the guide that says the module moved"
    params:
      from_module: {made.module}
      to_module: {made.to_module}
      default_alias: {alias}
      # The old name of each symbol, and what it is called in the new module.
      symbol_map:
        example: example
    fixtures:
      - fixtures/negative/unrelated.py
      - fixtures/positive/import_module.before.py

  - id: dependency-line
    kind: manifest_dependency
    citation: "TODO: the page and section of the guide that names the new distribution"
    params:
      from_name: {made.legacy.name}
      to_name: {made.new.name}
      to_spec: "{made.new.specifier}"
    fixtures:
      - fixtures/negative/requirements_already_new.txt
      - fixtures/positive/requirements.before.txt

limitations:
  - "TODO: say what this pack does not handle; it rewrites the import and the dependency line"
"""


def _sources(made: Plan) -> str:
    return f"""# Sources for `{made.pack_id}`

One section per `changes[].id`, in pack order. `obelize pack test` holds the sections equal to the
pack. The `.after` files beside the fixtures are what the rules wrote into them when this pack was
made: read each one before you trust it, and replace it by hand as the pack grows.

## The retrieved page

| Source | URL | `retrieved_at` |
|---|---|---|
| The pack's `source` | <{made.guide}> | {made.retrieved.isoformat()} |

Hash the page as served, put it under `source.sha256` in `pack.yaml`, and record it here. obelize
never requests the URL.

---

## rename-import

TODO: quote what the guide says about the module, and which versions you measured it on.

## dependency-line

TODO: quote what the guide says about the distribution that replaces the old one.
"""


__all__ = ["Plan", "ScaffoldError", "plan", "write"]

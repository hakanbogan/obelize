"""The classes of a repository that derive from a library's, found across files (`rename_member`).

The pack is `tests/packs/generic/acme/shapes-1-to-2`. A class is found by the name an import gives
it and the module the import comes from, so a name the repository defines elsewhere is not mistaken
for it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from obelize.models import Config
from obelize.packs import loader
from obelize.packtools import check
from obelize.scan import classes, members, runner

PACK = Path(__file__).resolve().parents[1] / "packs" / "generic" / "acme" / "shapes-1-to-2"
LOADED = loader.load(str(PACK / "pack.yaml"))
SPEC = loader.to_scan_spec(LOADED)
BASE = "acme.shapes.Shape"
MEMBERS = {BASE: frozenset({"old_area", "to_dict"})}
LEAF = members.Lineage(BASE, frozenset())
FROM = "from acme.shapes import Shape\n\n\n"


def indexed(files: dict[str, str]) -> classes.Index:
    """The index of an in-memory repository: path to source."""
    found = {path: classes.heads(source.encode()) for path, source in files.items()}
    spelled = frozenset().union(*(classes.aliases(source.encode()) for source in files.values()))
    return classes.build(found, lambda path: files[path].encode(), MEMBERS, spelled)


def lineage(files: dict[str, str], qualified: str) -> members.Lineage | None:
    return indexed(files).lookup(qualified)


def test_a_header_is_a_name_and_the_text_of_its_bases_over_any_number_of_lines() -> None:
    source = (
        b"class A(B):\n    class Inner(C, D):\n        pass\n\n\n"
        b"class E(\n    F,\n    G,\n):\n    pass\n"
    )
    assert classes.heads(source) == (
        ("A", "B"),
        ("Inner", "C, D"),
        ("E", "\n    F,\n    G,\n"),
    )
    assert classes.heads(b"class NoBases:\n    pass\nclassy = 1\n") == (("NoBases", ""),)


@pytest.mark.parametrize(
    ("path", "module"),
    [("app/models.py", "app.models"), ("app/__init__.py", "app"), ("top.py", "top")],
)
def test_a_file_is_the_dotted_module_its_path_says(path: str, module: str) -> None:
    assert classes.module_of(path) == module


@pytest.mark.parametrize(
    "head",
    [
        "from acme.shapes import Shape\n\n\nclass Square(Shape):\n    pass\n",
        "import acme.shapes\n\n\nclass Square(acme.shapes.Shape):\n    pass\n",
        "import acme.shapes as s\n\n\nclass Square(s.Shape):\n    pass\n",
        "from acme import shapes\n\n\nclass Square(shapes.Shape):\n    pass\n",
        "from acme.shapes import Shape as Base\n\n\nclass Square(Base):\n    pass\n",
        "import acme\n\n\nclass Square(acme.shapes.Shape):\n    pass\n",
    ],
)
def test_a_class_derived_from_the_library_in_any_way_it_is_imported_is_found(head: str) -> None:
    assert lineage({"app/models.py": head}, "app.models.Square") == LEAF
    assert lineage({"app/models.py": head}, "models.Square") == LEAF
    assert lineage({"app/models.py": head}, ".models.Square") == LEAF
    assert lineage({"app/models.py": head}, "app.Square") == LEAF
    assert lineage({"app/models.py": head}, ".Square") == LEAF


def test_a_class_is_found_through_the_files_it_passes_by() -> None:
    files = {
        "app/models.py": "from acme.shapes import Shape\n\n\nclass Square(Shape):\n    pass\n",
        "app/admin.py": "from .models import Square\n\n\nclass Admin(Square):\n    pass\n",
        "app/sub/deep.py": "from .. import admin\n\n\nclass Deep(admin.Admin):\n    pass\n",
        "app/more.py": "from app.sub.deep import Deep as D\n\n\nclass More(D):\n    pass\n",
    }
    index = indexed(files)
    assert index.names == {"Square", "Admin", "Deep", "More"}
    assert [index.lookup(f"app.{name}") for name in ("Square", "More")] == [LEAF, LEAF]
    assert index.lookup("app.admin.Admin") == LEAF


def test_a_class_beside_its_base_in_one_module_is_found_by_the_bare_name() -> None:
    source = (
        "from acme.shapes import Shape\n\n\nclass Square(Shape):\n    pass\n\n\n"
        "class Ring(Square):\n    pass\n"
    )
    assert lineage({"models.py": source}, "models.Ring") == LEAF


def test_what_a_class_between_defines_is_carried_to_the_classes_below() -> None:
    source = (
        "from acme.shapes import Shape\n\n\nclass Square(Shape):\n    def old_area(self):\n"
        "        return 1\n\n    other: int = 0\n    to_dict = None\n\n\n"
        "class Ring(Square):\n    async def to_dict(self):\n        return 2\n"
    )
    found = lineage({"models.py": source}, "models.Ring")
    assert found == members.Lineage(BASE, frozenset({"old_area", "to_dict"}))


def test_a_mixin_of_the_repository_beside_the_library_class_can_define_the_member_first() -> None:
    source = (
        f"{FROM}class Mixin:\n    def old_area(self):\n        return 1\n\n\n"
        "class Square(Mixin, Shape):\n    pass\n"
    )
    assert lineage({"models.py": source}, "models.Square") == members.Lineage(
        BASE, frozenset({"old_area"})
    )


def test_a_class_that_derives_from_two_libraries_or_from_nothing_it_knows_is_not_found() -> None:
    both = (
        "from acme.shapes import Shape\nfrom elsewhere import Other\n\n\n"
        "class Square(Shape):\n    pass\n\n\n"
        "class Odd(Square, Other):\n    pass\n\n\nclass Unknown(Other):\n    pass\n"
    )
    index = indexed({"models.py": both})
    assert index.names == {"Square", "Odd"}
    assert index.lookup("models.Unknown") is None


def test_a_class_defined_by_two_modules_the_import_could_mean_is_one_only_if_both_derive() -> None:
    files = {
        "a/models.py": f"{FROM}class Square(Shape):\n    def to_dict(self):\n        pass\n",
        "b/models.py": "from acme.shapes import Shape\n\n\nclass Square(Shape):\n    pass\n",
        "c/models.py": "class Square:\n    pass\n",
    }
    alone = {name: files[name] for name in ("a/models.py", "b/models.py")}
    assert lineage(alone, "models.Square") == members.Lineage(BASE, frozenset({"to_dict"}))
    assert lineage(alone, "a.models.Square") == members.Lineage(BASE, frozenset({"to_dict"}))
    assert lineage(alone, "b.models.Square") == LEAF
    # Another class of the name, that derives from nothing, is the one an import may mean.
    assert lineage(files, "models.Square") is None
    assert lineage(files, "b.models.Square") == LEAF


def test_two_classes_of_one_name_that_derive_from_different_libraries_are_not_one_class() -> None:
    files = {
        "a/models.py": "from acme.shapes import Shape\n\n\nclass Square(Shape):\n    pass\n",
        "b/models.py": "from acme.shapes import Solid\n\n\nclass Square(Solid):\n    pass\n",
    }
    both = {BASE: frozenset({"old_area"}), "acme.shapes.Solid": frozenset({"spin"})}
    found = {path: classes.heads(source.encode()) for path, source in files.items()}
    index = classes.build(found, lambda path: files[path].encode(), both)
    assert index.lookup("models.Square") is None
    assert index.lookup("a.models.Square") == LEAF


def test_a_name_the_import_takes_from_elsewhere_is_not_a_class_of_the_repository() -> None:
    files = {"app/models.py": "from acme.shapes import Shape\n\n\nclass Square(Shape):\n    pass\n"}
    assert lineage(files, "other.models.Square") is None
    assert lineage(files, "app.models.Missing") is None


def test_a_file_that_cannot_be_read_or_parsed_defines_nothing() -> None:
    files = {
        "broken.py": f"{FROM}class Square(Shape):\n    pass\n\n\nx = (\n",
        "gone.py": "from acme.shapes import Shape\n\n\nclass Round(Shape):\n    pass\n",
    }
    found = {path: classes.heads(source.encode()) for path, source in files.items()}
    index = classes.build(
        found, lambda path: None if path == "gone.py" else files[path].encode(), MEMBERS
    )
    assert index.derived == ()


def test_a_repository_with_no_class_that_could_derive_has_an_empty_index() -> None:
    assert indexed({"app.py": "class Plain:\n    pass\n"}) is classes.EMPTY


def test_bases_that_are_no_names_are_skipped() -> None:
    source = (
        "from acme.shapes import Shape\nfrom typing import Generic, TypeVar\n\n"
        "T = TypeVar('T')\n\n\n"
        "class Square(Shape, Generic[T], make().Base, metaclass=type):\n    pass\n"
    )
    assert lineage({"models.py": source}, "models.Square") == LEAF


def test_the_index_a_spec_reads_holds_only_the_classes_derived_from_its_own() -> None:
    files = {"models.py": "from acme.shapes import Shape\n\n\nclass Square(Shape):\n    pass\n"}
    index = indexed(files)
    assert index.restricted(SPEC).names == {"Square"}
    assert index.restricted(SPEC.model_copy(update={"member_classes": ()})).names == frozenset()
    assert index.mentions(b"x = Square()")
    assert not index.mentions(b"x = Circle()")


def write(root: Path, files: dict[str, str]) -> None:
    for name, source in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(source, encoding="utf-8")


REPOSITORY = {
    "app/models.py": f"{FROM}class Square(Shape):\n    side: float = 1.0\n",
    "app/admin.py": "from .models import Square\n\n\nclass Admin(Square):\n    pass\n",
    "views/pages.py": (
        "from app import models\nfrom app.admin import Admin\n\n\n"
        "def show(item):\n    admin = Admin()\n"
        "    return admin.old_area(), models.Square().to_dict(), item.old_area()\n"
    ),
    "views/clash.py": (
        "from other.thing import Admin\n\n\ndef f():\n    return Admin().old_area()\n"
    ),
    "util.py": "COUNT = 1\n",
    "requirements.txt": "acme-shapes==1.2.0\n",
}


@pytest.mark.parametrize("jobs", [1, 2])
def test_a_scan_finds_a_member_read_in_a_file_that_never_names_the_library(
    tmp_path: Path, jobs: int
) -> None:
    write(tmp_path, REPOSITORY)
    scan = runner.scan(tmp_path, Config(), SPEC, jobs=jobs)
    rows = [
        (row.path, row.line, row.symbol, row.scan_status)
        for row in scan.findings
        if row.kind != "manifest"
    ]
    assert rows == [
        ("views/pages.py", 7, f"{BASE}.old_area", "eligible"),
        ("views/pages.py", 7, f"{BASE}.to_dict", "eligible"),
    ]
    # The file that names `Admin` is read as well, and finds the one of another module is none.
    assert scan.counts.files_parsed == 4


def test_a_run_writes_the_new_name_in_that_file_and_leaves_the_others(tmp_path: Path) -> None:
    write(tmp_path, REPOSITORY)
    run = check.migrate(LOADED, tmp_path)
    pages = next(outcome for outcome in run.files if outcome.path == "views/pages.py")
    assert pages.after.decode().count("old_area") == 1
    assert "admin.area(), models.Square().as_dict(), item.old_area()" in pages.after.decode()
    assert "views/pages.py" in [outcome.path for outcome in run.written]


def test_a_tree_read_for_a_pack_with_no_member_class_has_no_index(tmp_path: Path) -> None:
    write(tmp_path, REPOSITORY)
    tree = runner.read(tmp_path, Config(), (SPEC.model_copy(update={"member_classes": ()}),))
    assert tree.derived is classes.EMPTY
    assert runner.read(tmp_path, Config(), (SPEC,)).derived.names == {"Square", "Admin"}


def test_a_repository_with_no_derived_class_keeps_the_bytes_it_kept(tmp_path: Path) -> None:
    write(tmp_path, {"app.py": "class Plain:\n    pass\n", "notes.txt": "acme\n"})
    tree = runner.read(tmp_path, Config(), (SPEC,))
    assert tree.derived is classes.EMPTY
    assert tree.entries["app.py"].data is None

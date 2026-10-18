"""`obelize.apidiff`: the public API of a release read from its source, and what changed."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

import pytest

from obelize.apidiff import diff as api
from obelize.apidiff import surface, worker
from obelize.apidiff.surface import Obj, Param, Surface, SurfaceError

if TYPE_CHECKING:
    from pathlib import Path

KIT = '''
"""Kit."""
import warnings
from acme_kit._impl import Client
from acme_kit.util import helper
from json import loads
from unresolved_lib import Gone
from other_missing import Exported
from other_pkg import elsewhere
from acme_kit._impl import LIMIT
from acme_kit import _impl as impl

__all__ = ["Client", "helper", "Exported", "OLD", "greet", "Thing", "_hidden"]

OLD = 3
_hidden = 1
_skipped = 2


def greet(name, loud=False, *, times=1) -> str:
    return name


def old(name):
    warnings.warn(f"old is deprecated, use {greet.__name__}", category=DeprecationWarning)
    warnings.warn(name)
    warnings.warn("not about deprecation", UserWarning)
    return name


def computed(name):
    warnings.warn(name, DeprecationWarning)


@deprecated("use Thing", category=DeprecationWarning)
class Old:
    pass


class Warns:
    def __init__(self):
        warnings.warn("Warns is going", PendingDeprecationWarning)

    @property
    def legacy(self):
        warnings.warn("legacy is going", FutureWarning)
        return 1


@deprecated("use greet")
def older():
    return 1


@typing_extensions.deprecated()
def oldest():
    return 1


def trivial(x):
    """Nothing."""
    ...


class Thing(Exception):
    attr = 5

    def __init__(self, a, b=1):
        self.a = a

    def method(self, a, b=2):
        pass

    @property
    def prop(self):
        return 1

    @staticmethod
    def make(x):
        return x

    @classmethod
    def build(cls, y):
        return y

    def _private(self):
        return 1

    class Inner:
        def f(self):
            return 1


print("loaded")
warnings.warn("kit is deprecated", DeprecationWarning)
if OLD:
    warnings.warn("conditional", FutureWarning)
try:
    pass
except Exception:
    warnings.warn("handled", DeprecationWarning)
'''


def lib(root: Path, files: dict[str, str], name: str = "acme_kit") -> Path:
    for path, text in files.items():
        target = root / name / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    return root


@pytest.fixture
def kit(tmp_path: Path) -> Path:
    lib(tmp_path, {"__init__.py": "elsewhere = 1\n"}, "other_pkg")
    return lib(
        tmp_path,
        {
            "__init__.py": KIT,
            "_impl.py": (
                "LIMIT = 5\n\nclass Client:\n    def __init__(self, key, *, timeout=3.0): ...\n"
            ),
            "util.py": "def helper(x): ...\n",
            "broken.py": "def (:\n",
        },
    )


# The worker.


def test_the_public_api_of_a_package_is_read_without_importing_it(kit: Path) -> None:
    objects = worker.surface(kit, "acme_kit")["objects"]
    assert objects["acme_kit.Client"]["target"] == "acme_kit._impl.Client"
    assert objects["acme_kit.Client"]["params"][1] == {
        "name": "timeout",
        "kind": "keyword-only",
        "default": "3.0",
        "required": False,
    }
    assert objects["acme_kit.helper"]["target"] == "acme_kit.util.helper"
    assert objects["acme_kit.Exported"] == {"kind": "alias", "target": "other_missing.Exported"}
    assert objects["acme_kit.LIMIT"]["target"] == "acme_kit._impl.LIMIT"
    for left_out in ("loads", "Gone", "elsewhere", "impl"):
        assert f"acme_kit.{left_out}" not in objects
    assert "acme_kit._skipped" not in objects
    assert objects["acme_kit._hidden"]["kind"] == "attribute"
    assert "acme_kit.__all__" not in objects
    assert objects["acme_kit.OLD"]["value"] == "3"


def test_a_function_is_its_parameters_and_whether_it_is_a_stub(kit: Path) -> None:
    objects = worker.surface(kit, "acme_kit")["objects"]
    greet = objects["acme_kit.greet"]
    assert [one["name"] for one in greet["params"]] == ["name", "loud", "times"]
    assert greet["returns"] == "str"
    assert greet["trivial"] is False
    assert objects["acme_kit.trivial"]["trivial"] is True


def test_a_class_is_its_bases_its_constructor_and_its_members(kit: Path) -> None:
    objects = worker.surface(kit, "acme_kit")["objects"]
    thing = objects["acme_kit.Thing"]
    assert thing["bases"] == ["Exception"]
    assert [one["name"] for one in thing["params"]] == ["a", "b"]
    assert "acme_kit.Thing.__init__" not in objects
    assert "acme_kit.Thing._private" not in objects
    assert objects["acme_kit.Thing.attr"]["kind"] == "attribute"
    assert objects["acme_kit.Thing.prop"] == {
        "kind": "attribute",
        "value": "property",
        "deprecated": None,
    }
    assert objects["acme_kit.Client"]["params"] is not None
    assert objects["acme_kit.Thing.Inner"]["params"] is None
    assert [one["name"] for one in objects["acme_kit.Thing.method"]["params"]] == ["a", "b"]
    assert [one["name"] for one in objects["acme_kit.Thing.make"]["params"]] == ["x"]
    assert [one["name"] for one in objects["acme_kit.Thing.build"]["params"]] == ["y"]
    assert "acme_kit.Thing.Inner.f" in objects


def test_what_the_library_says_is_deprecated_is_quoted(kit: Path) -> None:
    objects = worker.surface(kit, "acme_kit")["objects"]
    assert objects["acme_kit.old"]["deprecated"] == "old is deprecated, use {}"
    assert objects["acme_kit.older"]["deprecated"] == "use greet"
    assert objects["acme_kit.oldest"]["deprecated"] == ""
    assert objects["acme_kit.computed"]["deprecated"] == ""
    assert objects["acme_kit.Old"]["deprecated"] == "use Thing"
    assert objects["acme_kit.Warns"]["deprecated"] == "Warns is going"
    assert objects["acme_kit.Warns.legacy"]["deprecated"] == "legacy is going"
    assert objects["acme_kit.greet"]["deprecated"] is None
    assert objects["acme_kit"]["deprecated"] == "kit is deprecated"


def test_a_warning_run_on_import_is_the_modules_and_a_function_s_is_not(tmp_path: Path) -> None:
    root = lib(
        tmp_path,
        {
            "__init__.py": (
                "import warnings\n\ndef f():\n    warnings.warn('x', DeprecationWarning)\n"
            ),
            "sub.py": "import warnings\nwarnings.warn('sub is gone', DeprecationWarning)\n",
        },
        "quiet",
    )
    objects = worker.surface(root, "quiet")["objects"]
    assert objects["quiet"]["deprecated"] is None
    assert objects["quiet.f"]["deprecated"] == "x"
    assert objects["quiet.sub"]["deprecated"] == "sub is gone"


def test_a_namespace_package_is_a_module_with_no_notice_of_its_own(tmp_path: Path) -> None:
    root = lib(tmp_path, {"sub.py": "def f(x):\n    return x\n"}, "spaced")
    objects = worker.surface(root, "spaced")["objects"]
    assert objects["spaced"] == {"kind": "module", "deprecated": None, "lazy": False}
    assert "spaced.sub.f" in objects


def test_a_reader_stops_at_the_depth_and_the_count_it_allows(
    kit: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker, "MAX_DEPTH", 0)
    shallow = worker.surface(kit, "acme_kit")["objects"]
    assert "acme_kit.Thing" in shallow
    assert "acme_kit.Thing.Inner.f" not in shallow
    monkeypatch.setattr(worker, "MAX_OBJECTS", 3)
    cut = worker.surface(kit, "acme_kit")
    assert cut["truncated"] is True
    assert len(cut["objects"]) <= 5


def test_a_class_with_more_members_than_allowed_is_cut_inside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = "class Big:\n" + "".join(f"    def m{n}(self): ...\n" for n in range(6))
    root = lib(tmp_path, {"__init__.py": body}, "big")
    monkeypatch.setattr(worker, "MAX_OBJECTS", 3)
    cut = worker.surface(root, "big")
    assert cut["truncated"] is True
    assert len(cut["objects"]) == 3


def test_something_that_is_not_a_module_is_an_error(
    kit: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert worker.main([str(kit), "acme_kit.Thing"]) == 3
    assert "not a module" in json.loads(capsys.readouterr().out)["error"]
    assert worker.main([str(kit), "nothing_here"]) == 3
    assert "error" in json.loads(capsys.readouterr().out)


def test_the_document_is_printed_for_the_parent(
    kit: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert worker.main([str(kit), "acme_kit"]) == 0
    assert json.loads(capsys.readouterr().out)["module"] == "acme_kit"


# The child process.


def test_a_release_is_read_in_a_child_process(kit: Path) -> None:
    read = surface.read(kit, "acme_kit")
    assert read.module == "acme_kit"
    assert read.objects["acme_kit.greet"].params == (
        Param("name", "positional or keyword", None, True),
        Param("loud", "positional or keyword", "False", False),
        Param("times", "keyword-only", "1", False),
    )
    assert read.relative()["greet"] is read.objects["acme_kit.greet"]
    assert "acme_kit" not in read.relative()
    assert read.truncated is False


def test_a_module_that_is_not_there_is_an_error_with_the_reason(kit: Path) -> None:
    with pytest.raises(SurfaceError, match="nothing_here"):
        surface.read(kit, "nothing_here")


def test_a_read_that_takes_too_long_is_stopped(kit: Path) -> None:
    with pytest.raises(SurfaceError, match="took more than"):
        surface.read(kit, "acme_kit", timeout_s=0.001)


@pytest.mark.parametrize(
    ("stdout", "reason"),
    [(b"junk", "boom"), (b"[]", "no document"), (b'{"objects": 1, "error": "x"}', "x")],
)
def test_output_that_is_not_a_surface_is_an_error(
    kit: Path, monkeypatch: pytest.MonkeyPatch, stdout: bytes, reason: str
) -> None:
    def fake(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess([], 1, stdout, b"warm up\nboom\n")

    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(SurfaceError, match=reason):
        surface.read(kit, "acme_kit")


def test_the_child_sees_none_of_the_environment_but_what_python_needs(
    kit: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, str] = {}

    def fake(*_args: object, **kwargs: dict[str, str]) -> subprocess.CompletedProcess[bytes]:
        seen.update(kwargs["env"])
        return subprocess.CompletedProcess([], 0, b'{"objects": {}}', b"")

    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setattr(subprocess, "run", fake)
    surface.read(kit, "acme_kit")
    assert "OPENAI_API_KEY" not in seen
    assert seen["PYTHONDONTWRITEBYTECODE"] == "1"


def test_the_modules_of_an_unpacked_release_are_found(tmp_path: Path) -> None:
    for path in (
        "src/acme_kit/__init__.py",
        "src/acme_kit/core.py",
        "src/acme_extra.py",
        "src/tests/__init__.py",
        "src/docs/conf.py",
        "src/acme_kit/data.json",
    ):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text("")
    assert surface.modules(tmp_path) == ("acme_extra", "acme_kit")
    flat = tmp_path / "flat"
    (flat / "pkg").mkdir(parents=True)
    (flat / "pkg" / "__init__.py").write_text("")
    (flat / "setup.py").write_text("")
    assert surface.modules(flat) == ("pkg",)


# The diff.


def fn(*params: Param, deprecated: str | None = None, trivial: bool = False) -> Obj:
    return Obj("", "function", params, deprecated=deprecated, trivial=trivial)


def req(name: str, kind: str = "positional or keyword") -> Param:
    return Param(name, kind, None, True)


def opt(name: str, default: str = "1", kind: str = "positional or keyword") -> Param:
    return Param(name, kind, default, False)


def surfaces(
    old: dict[str, Obj], new: dict[str, Obj], module: str = "lib"
) -> tuple[Surface, Surface]:
    def make(objects: dict[str, Obj]) -> Surface:
        return Surface(module, {f"{module}.{path}": one for path, one in objects.items()})

    return make(old), make(new)


def changes(
    old: dict[str, Obj], new: dict[str, Obj], before: tuple[Surface, ...] = ()
) -> list[tuple[str, ...]]:
    found = api.diff(*surfaces(old, new), before=before)
    return [
        (one.type, one.path, one.new_path or one.param or "", one.new_param or "") for one in found
    ]


def test_a_name_that_moved_with_its_signature_is_paired_with_its_new_place() -> None:
    body = fn(req("x"))
    found = changes({"a.f": body}, {"b.f": body})
    assert found == [("moved", "a.f", "b.f", "")]


@pytest.mark.parametrize(
    ("old", "new"),
    [
        pytest.param(fn(req("x"), trivial=True), fn(req("x")), id="a stub says nothing"),
        pytest.param(fn(req("x")), fn(req("y")), id="another signature"),
        pytest.param(fn(req("x")), Obj("", "class", (req("x"),)), id="another kind"),
        pytest.param(
            Obj("", "attribute", value="1"), Obj("", "attribute", value="1"), id="a value"
        ),
    ],
)
def test_a_name_that_cannot_be_told_to_be_the_same_is_removed(old: Obj, new: Obj) -> None:
    assert changes({"a.f": old}, {"b.f": new}) == [("removed", "a.f", "", "")]


def test_a_name_with_two_candidates_is_removed_and_says_so() -> None:
    body = fn(req("x"))
    old, new = surfaces({"a.f": body}, {"b.f": body, "c.f": body})
    [one] = api.diff(old, new)
    assert (one.type, one.detail) == ("removed", "2 candidates")


def test_what_beneath_a_removed_name_is_not_reported_again() -> None:
    cls = Obj("", "class", (req("a"),))
    found = changes({"Gone": cls, "Gone.m": fn(req("a")), "mod": Obj("", "module")}, {})
    assert found == [("removed", "Gone", "", "")]


def test_the_message_the_library_gave_before_it_removed_a_name_is_kept() -> None:
    old, new = surfaces({"f": fn(req("x"))}, {})
    before = surfaces({"f": fn(req("x"), deprecated="use g")}, {})[0]
    [one] = api.diff(old, new, before=[before])
    assert one.message == "use g"


def test_the_newest_release_that_still_has_a_name_is_the_one_whose_words_count() -> None:
    old, new = surfaces({"f": fn(req("x")), "g": fn(req("x"))}, {})
    newest = surfaces({"g": fn(req("x"), deprecated="g will go")}, {})[0]
    older = surfaces(
        {"f": fn(req("x"), deprecated="f will go"), "g": fn(req("x"), deprecated="old")}, {}
    )[0]
    said = {one.path: one.message for one in api.diff(old, new, before=[newest, older])}
    assert said == {"f": "f will go", "g": "g will go"}


def test_a_member_that_moved_up_to_a_base_class_is_still_the_class_s() -> None:
    old = {"C": Obj("", "class", ()), "C.m": fn(req("x")), "C.n": fn(req("x"))}
    new = {"C": Obj("", "class", (), inherited=("m",))}
    assert changes(old, new) == [("removed", "C.n", "", "")]


def test_object_as_a_base_is_what_every_class_has() -> None:
    old = {"C": Obj("", "class", (), bases=("object",)), "D": Obj("", "class", (), bases=("Base",))}
    new = {"C": Obj("", "class", ()), "D": Obj("", "class", (), bases=("Base",))}
    assert changes(old, new) == []


def test_a_name_changing_kind_or_bases_is_reported() -> None:
    base = Obj("", "class", (), bases=("Base", "Mixin"))
    found = changes(
        {"C": base, "D": base, "E": base},
        {
            "C": Obj("", "function", (req("x"),)),
            "D": Obj("", "class", (), bases=("Base",)),
            "E": Obj("", "class", (), bases=("Base", "Mixin", "More")),
        },
    )
    assert found == [("kind_changed", "C", "", ""), ("bases_changed", "D", "", "")]


def test_a_renamed_parameter_is_the_same_place_kind_and_default_under_a_new_name() -> None:
    found = changes({"f": fn(req("a"), opt("b"))}, {"f": fn(req("a"), opt("c"))})
    assert found == [("param_renamed", "f", "b", "c")]


def test_a_parameter_that_left_is_removed_unless_the_new_signature_takes_any_keyword() -> None:
    assert changes({"f": fn(req("a"), req("b"))}, {"f": fn(req("a"))}) == [
        ("param_removed", "f", "b", "")
    ]
    open_ended = fn(req("a"), Param("kwargs", "variadic keyword", None, False))
    assert changes({"f": fn(req("a"), req("b"))}, {"f": open_ended}) == []


def test_a_required_parameter_added_is_reported_and_an_optional_one_is_not() -> None:
    assert changes({"f": fn(req("a"))}, {"f": fn(req("a"), req("b"), opt("c"))}) == [
        ("param_required_added", "f", "b", "")
    ]


def test_a_parameter_that_changed_kind_or_default_is_reported() -> None:
    old = fn(req("a"), opt("b", "1"), opt("c", "1"), opt("d", "1"))
    new = fn(
        req("a", "keyword-only"),
        opt("b", "2"),
        Param("c", "positional or keyword", None, False),
        opt("d", "1"),
    )
    found = changes({"f": old}, {"f": new})
    assert found == [
        ("param_kind_changed", "f", "a", ""),
        ("default_changed", "f", "b", ""),
        ("default_changed", "f", "c", ""),
    ]


def test_a_value_that_changed_is_not_an_api_change() -> None:
    assert (
        changes({"X": Obj("", "attribute", value="1")}, {"X": Obj("", "attribute", value="2")})
        == []
    )


def test_variadic_parameters_are_not_compared() -> None:
    star = Param("args", "variadic positional", None, False)
    assert changes({"f": fn(star, req("a"))}, {"f": fn(req("a"))}) == []
    assert changes({"f": fn(req("a"))}, {"f": fn(req("a"), star)}) == []


def test_a_deprecation_new_to_this_release_or_known_from_the_old_one_is_reported() -> None:
    old = {"f": fn(req("a")), "g": fn(req("a"), deprecated="use h"), "h": fn(req("a"))}
    new = {
        "f": fn(req("a"), deprecated="going"),
        "g": fn(req("a"), deprecated="use h"),
        "h": fn(req("a")),
    }
    [one] = api.diff(*surfaces(old, new))
    assert (one.type, one.path, one.message) == ("deprecated", "f", "going")


def test_a_deprecation_the_old_release_made_and_the_new_one_dropped_is_still_reported() -> None:
    [one] = api.diff(*surfaces({"g": fn(req("a"), deprecated="use h")}, {"g": fn(req("a"))}))
    assert (one.type, one.message) == ("deprecated", "use h")


def test_module_prefixes_are_dropped_so_a_moved_module_compares() -> None:
    old = Surface("oldlib", {"oldlib.f": fn(req("x"))})
    new = Surface("newlib", {"newlib.f": fn(req("x"))})
    assert api.diff(old, new) == ()


def test_a_name_the_librarys_message_says_to_use_is_what_it_was_renamed_to() -> None:
    old = {"old_greet": fn(req("name"), deprecated="old_greet is deprecated, use greet instead")}
    new = {"greet": fn(req("name"))}
    [one] = api.diff(*surfaces(old, new))
    assert (one.type, one.path, one.new_path, one.same_signature) == (
        "renamed",
        "old_greet",
        "greet",
        True,
    )


def test_a_rename_by_message_may_change_the_signature() -> None:
    old = {"f": fn(req("a"), deprecated="f is replaced by g")}
    [one] = api.diff(*surfaces(old, {"g": fn(req("b"))}))
    assert (one.type, one.new_path, one.same_signature) == ("renamed", "g", False)


@pytest.mark.parametrize(
    ("message", "new"),
    [
        pytest.param("f is deprecated", {"g": fn(req("a"))}, id="a warning that names no use"),
        pytest.param("use g or h", {"g": fn(req("a")), "h": fn(req("a"))}, id="two candidates"),
        pytest.param("use g", {"g": Obj("", "class", (req("a"),))}, id="another kind"),
        pytest.param("use g", {"x.g": fn(req("a"))}, id="another place"),
        pytest.param("use something", {"other": fn(req("a"))}, id="a name that is not there"),
        pytest.param(None, {"g": fn(req("a"))}, id="no message"),
    ],
)
def test_a_name_that_no_message_pairs_with_one_is_removed(
    message: str | None, new: dict[str, Obj]
) -> None:
    [one] = api.diff(*surfaces({"f": fn(req("a"), deprecated=message)}, new))
    assert one.type == "removed"


def test_a_module_that_makes_names_when_asked_is_lazy_and_its_hook_is_not_a_name(
    tmp_path: Path,
) -> None:
    root = lib(
        tmp_path,
        {
            "__init__.py": "def __getattr__(name):\n    return globals()[name]\n\n"
            "def __dir__():\n    return []\n\ndef real(x):\n    return x\n",
            "sub.py": "def f(x):\n    return x\n",
        },
        "lazy",
    )
    objects = worker.surface(root, "lazy")["objects"]
    assert objects["lazy"]["lazy"] is True
    assert objects["lazy.sub"]["lazy"] is False
    assert "lazy.__getattr__" not in objects
    assert "lazy.__dir__" not in objects
    assert "lazy.real" in objects


def test_the_module_itself_is_the_empty_path() -> None:
    surface_ = Surface("lib", {"lib": Obj("lib", "module", lazy=True), "lib.f": fn(req("x"))})
    assert set(surface_.relative()) == {"", "f"}
    assert surface_.relative()[""].lazy is True


def test_a_name_missing_from_a_module_that_makes_names_when_asked_is_unseen_not_removed() -> None:
    old = {"f": fn(req("x")), "sub": Obj("", "module"), "sub.g": fn(req("x"))}
    everywhere = {"": Obj("", "module", lazy=True), "sub": Obj("", "module")}
    found = [(one.type, one.path) for one in api.diff(*surfaces(old, everywhere))]
    assert found == [("unseen", "f"), ("unseen", "sub.g")]
    only_below = {"sub": Obj("", "module", lazy=True)}
    found = [(one.type, one.path) for one in api.diff(*surfaces(old, only_below))]
    assert found == [("removed", "f"), ("unseen", "sub.g")]


def test_the_ancestors_of_a_name_are_the_places_it_could_come_from() -> None:
    assert api._ancestors("a.b.C") == ["a.b", "a", ""]
    assert api._ancestors("f") == [""]


def test_a_required_parameter_a_star_args_already_took_is_no_new_requirement() -> None:
    star = Param("args", "variadic positional", None, False)
    old = {"f": fn(star), "g": fn(star)}
    new = {
        "f": fn(req("a"), req("b", "keyword-only"), star),
        "g": fn(req("a")),
    }
    assert changes(old, new) == [("param_required_added", "f", "b", "")]


PRECISE = """
import warnings

_TABLE = {"C": 1, "D": 2}


def New():
    return 1


def __getattr__(name):
    if name == "Old":
        warnings.warn("Old is deprecated, use New instead", DeprecationWarning)
        return New
    if name in ("A", "B"):
        return 1
    if name in _TABLE:
        return _TABLE[name]
    raise AttributeError(f"module has no attribute {name!r}")
"""


def test_a_getattr_that_lists_what_it_makes_makes_those_names_and_no_others(tmp_path: Path) -> None:
    objects = worker.surface(lib(tmp_path, {"__init__.py": PRECISE}, "precise"), "precise")[
        "objects"
    ]
    assert objects["precise"]["lazy"] is False
    assert objects["precise.Old"] == {
        "kind": "name",
        "deprecated": "Old is deprecated, use New instead",
    }
    assert {name for name, one in objects.items() if one["kind"] == "name"} == {
        "precise.Old",
        "precise.A",
        "precise.B",
        "precise.C",
        "precise.D",
    }
    assert objects["precise.A"]["deprecated"] is None


@pytest.mark.parametrize(
    "hook",
    [
        "def __getattr__(name):\n    import importlib\n    return importlib.import_module(name)\n",
        "def __getattr__(name):\n    return globals()[name]\n",
        "def __getattr__(name):\n    if name.startswith('x'):\n        return 1\n    return 2\n",
        "def __getattr__(name):\n    if name != 'x':\n        raise AttributeError(name)\n"
        "    return 1\n",
        "def __getattr__(*args):\n    raise AttributeError\n",
        "if True:\n    def __getattr__(name):\n        return 1\n",
        "__getattr__ = lambda name: 1\n",
    ],
)
def test_a_getattr_that_uses_the_name_in_any_other_way_may_make_any_name(
    tmp_path: Path, hook: str
) -> None:
    objects = worker.surface(lib(tmp_path, {"__init__.py": hook}, "vague"), "vague")["objects"]
    assert objects["vague"]["lazy"] is True


def test_a_getattr_that_looks_names_up_in_a_table_makes_the_names_of_the_table(
    tmp_path: Path,
) -> None:
    source = (
        "_T: dict = {'a': 1}\n_N = [1, 2]\n(_X, _Y) = ('x', 'y')\nimport os\n\n"
        "def __getattr__(name):\n    found = _T.get(name)\n    return found\n"
    )
    objects = worker.surface(lib(tmp_path, {"__init__.py": source}, "tabled"), "tabled")["objects"]
    assert objects["tabled"]["lazy"] is False
    assert objects["tabled.a"]["kind"] == "name"


def test_a_name_a_package_exports_and_defines_nowhere_is_known_and_not_read(tmp_path: Path) -> None:
    source = "__all__ = ['here', 'elsewhere']\n\ndef here():\n    return 1\n"
    objects = worker.surface(lib(tmp_path, {"__init__.py": source}, "declared"), "declared")[
        "objects"
    ]
    assert objects["declared.elsewhere"] == {"kind": "name", "deprecated": None}
    assert objects["declared.here"]["kind"] == "function"


def test_a_name_declared_and_not_read_is_not_compared_but_may_say_it_is_going() -> None:
    old = {"A": fn(req("x")), "B": fn(req("x"), deprecated="B will go"), "C": fn(req("x"))}
    new = {
        "A": Obj("", "name"),
        "B": Obj("", "name", deprecated="B will go"),
        "C": Obj("", "name", deprecated="use D"),
    }
    assert [(one.type, one.path, one.message) for one in api.diff(*surfaces(old, new))] == [
        ("deprecated", "C", "use D")
    ]
    assert changes({"A": Obj("", "name")}, {"A": fn(req("x"))}) == []

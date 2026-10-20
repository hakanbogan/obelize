"""`obelize pack synth`: a pack made from two releases of a library, from the index to a run."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest
import yaml
from packaging.version import Version
from typer.testing import CliRunner

import fakeindex
from obelize import index, libdiff
from obelize.apidiff.diff import ApiChange
from obelize.apidiff.surface import Obj, Param, Surface
from obelize.cli import app
from obelize.net import Fetcher
from obelize.packs import loader
from obelize.packtools import check, synth
from support import committed

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

runner = CliRunner()

V1 = {
    "__init__.py": (
        "from acme_kit.errors import KitError\n"
        "__all__ = ['old_greet', 'removed_fn', 'changed', 'Client', 'keep', 'KitError']\n\n"
        "def old_greet(name):\n    return name\n\n"
        "def removed_fn(x):\n    return x\n\n"
        "def changed(a, b=1):\n    return a\n\n"
        "def keep(x):\n    return x\n\n"
        "class Client:\n    def __init__(self, key, timeout=3):\n        self.key = key\n\n"
        "    def ping(self):\n        return 1\n"
    ),
    "errors.py": "class KitError(Exception):\n    pass\n",
}
V15 = {
    **V1,
    "__init__.py": V1["__init__.py"].replace(
        "def old_greet(name):\n    return name\n",
        "import warnings\n\ndef greet(name):\n    return name\n\n"
        "def old_greet(name):\n"
        "    warnings.warn('old_greet is deprecated, use greet instead', DeprecationWarning)\n"
        "    return greet(name)\n",
    ),
}
V2 = {
    "__init__.py": (
        "__all__ = ['greet', 'changed', 'Client', 'keep', 'KitError']\n\n"
        "class KitError(Exception):\n    pass\n\n"
        "def greet(name):\n    return name\n\n"
        "def changed(a, c=1):\n    return a\n\n"
        "def keep(x):\n    return x\n\n"
        "class Client:\n    def __init__(self, key, timeout=3):\n        self.key = key\n"
    ),
}
APP = (
    "import acme_kit\nfrom acme_kit.errors import KitError\n\n\n"
    "def run(name):\n    try:\n        return acme_kit.removed_fn(name)\n"
    "    except KitError:\n        return acme_kit.changed(1, b=2)\n"
)
OTHER = "import acme_kit\n\n\ndef hello(name):\n    return acme_kit.old_greet(name)\n"


@pytest.fixture(scope="module")
def served() -> Iterator[fakeindex.FakeIndex]:
    for found in fakeindex.FakeIndex().serve():
        for version, source in (("1.0", V1), ("1.5", V15), ("2.0", V2)):
            found.add("acme-kit", version, source, module="acme_kit")
        found.add("acme-kit", "3.0a1", V2, module="acme_kit")
        yield found


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, served: fakeindex.FakeIndex) -> Path:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("OBELIZE_INDEX_URL", served.url)
    monkeypatch.delenv("OBELIZE_OFFLINE", raising=False)
    return tmp_path


def _synth(home: Path, *extra: str) -> object:
    return runner.invoke(
        app, ["pack", "synth", "acme-kit", "--from", "1.0", "--dir", str(home / "packs"), *extra]
    )


# The whole flow.


def test_a_pack_made_from_two_releases_passes_pack_test_and_migrates_a_repository(
    home: Path,
) -> None:
    made = _synth(home, "--to", "2.0")
    assert made.exit_code == 0, made.output  # type: ignore[attr-defined]
    folder = home / "packs" / "acme-kit" / "1-0-to-2-0"
    assert "obelize contacts 127.0.0.1" in made.output  # type: ignore[attr-defined]
    assert "rename-with-calls: 1 name(s)" in made.output  # type: ignore[attr-defined]
    tested = runner.invoke(app, ["pack", "test", str(folder)])
    assert tested.exit_code == 0, tested.output
    repo = committed(
        home / "repo", {"app.py": APP, "other.py": OTHER, "requirements.txt": "acme-kit==1.0\n"}
    )
    scanned = runner.invoke(
        app, ["scan", "--repo", str(repo), "--pack", str(folder / "pack.yaml"), "--json"]
    )
    rows = {
        (row["path"], row["symbol"]): row["scan_status"]
        for row in json.loads(scanned.stdout)["findings"]
    }
    assert rows[("other.py", "acme_kit.old_greet")] == "eligible"
    assert rows[("app.py", "acme_kit.removed_fn")] == "needs_review"
    assert rows[("app.py", "acme_kit.changed")] == "needs_review"


def test_the_release_between_the_two_is_read_for_what_the_library_warned(
    home: Path, served: fakeindex.FakeIndex
) -> None:
    fetcher = Fetcher(index=served.url)
    project = index.project(fetcher, "acme-kit")
    compared = libdiff.compare(fetcher, project, Version("1.0"), Version("2.0"))
    kinds = {(one.type, one.path, one.new_path) for one in compared.changes}
    assert ("renamed", "old_greet", "greet") in kinds
    assert ("moved", "errors.KitError", "KitError") in kinds
    assert ("removed", "removed_fn", None) in kinds
    assert ("removed", "Client.ping", None) in kinds
    assert ("param_renamed", "changed", None) in kinds
    assert compared.module == "acme_kit"
    assert (compared.old.version, compared.new.version) == (Version("1.0"), Version("2.0"))


def test_the_newest_release_that_is_not_a_pre_release_is_the_default_target(home: Path) -> None:
    made = _synth(home)
    assert made.exit_code == 0, made.output  # type: ignore[attr-defined]
    assert (home / "packs" / "acme-kit" / "1-0-to-2-0" / "pack.yaml").is_file()


def test_the_hosts_are_told_before_they_are_reached_and_a_second_run_needs_none(home: Path) -> None:
    _synth(home, "--to", "2.0", "--dir", str(home / "first"))
    again = runner.invoke(
        app,
        [
            "pack",
            "synth",
            "acme-kit",
            "--from",
            "1.0",
            "--to",
            "2.0",
            "--dir",
            str(home / "second"),
            "--offline",
        ],
    )
    assert again.exit_code == 0, again.output


def test_offline_with_nothing_kept_reaches_no_host_and_exits_six(home: Path) -> None:
    result = _synth(home, "--offline")
    assert result.exit_code == 6  # type: ignore[attr-defined]
    assert "not in the cache" in result.output  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["--from", "banana"], "is not a version"),
        (["--from", "9.9"], "has no file that can be read"),
        (["--module", "acme_kit", "--from", "1.0", "--to", "banana"], "is not a version"),
    ],
)
def test_a_request_the_index_cannot_answer_exits_two(
    home: Path, arguments: list[str], message: str
) -> None:
    result = runner.invoke(app, ["pack", "synth", "acme-kit", *arguments, "--dir", str(home)])
    assert result.exit_code == 2
    assert message in result.output


def test_a_library_the_index_does_not_have_exits_two(home: Path) -> None:
    result = runner.invoke(
        app, ["pack", "synth", "nothing-here", "--from", "1.0", "--dir", str(home)]
    )
    assert result.exit_code == 2


def test_an_index_address_that_is_not_one_is_refused(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OBELIZE_INDEX_URL", "ftp://example.com")
    assert _synth(home).exit_code == 2  # type: ignore[attr-defined]


def test_the_user_may_name_the_index_and_go_offline_in_the_config_file(
    home: Path, served: fakeindex.FakeIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OBELIZE_INDEX_URL")
    (home / "config" / "obelize").mkdir(parents=True)
    (home / "config" / "obelize" / "config.yml").write_text(
        f"network:\n  index: {served.url}/\n  offline: true\n"
    )
    result = _synth(home)
    assert result.exit_code == 6  # type: ignore[attr-defined]


def test_a_folder_that_exists_is_never_written_into(home: Path) -> None:
    assert _synth(home, "--to", "2.0").exit_code == 0  # type: ignore[attr-defined]
    again = _synth(home, "--to", "2.0")
    assert again.exit_code == 2  # type: ignore[attr-defined]
    assert "exists already" in again.output  # type: ignore[attr-defined]


def test_two_releases_with_nothing_between_them_make_no_pack(
    home: Path, served: fakeindex.FakeIndex
) -> None:
    served.add("same", "1.0", V2, module="acme_kit")
    served.add("same", "1.1", V2, module="acme_kit")
    result = runner.invoke(
        app, ["pack", "synth", "same", "--from", "1.0", "--to", "1.1", "--dir", str(home)]
    )
    assert result.exit_code == 2
    assert "nothing to synthesize" in result.output


# More than one module.


def test_a_library_with_two_modules_needs_to_be_told_which(
    home: Path, served: fakeindex.FakeIndex
) -> None:
    for version in ("1.0", "2.0"):
        served.add(
            "twin",
            version,
            {
                "one/__init__.py": f"def f(a):\n    return {version[0]}\n",
                "two/__init__.py": "def g(a):\n    return a\n",
            },
            module="",
        )
    arguments = ["pack", "synth", "twin", "--from", "1.0", "--to", "2.0", "--dir", str(home)]
    result = runner.invoke(app, arguments)
    assert result.exit_code == 2
    assert "more than one module" in result.output
    chosen = runner.invoke(app, [*arguments, "--module", "two"])
    assert chosen.exit_code == 2
    assert "nothing to synthesize" in chosen.output


def test_a_library_whose_releases_share_no_module_is_refused(
    home: Path, served: fakeindex.FakeIndex
) -> None:
    served.add("moved", "1.0", {"__init__.py": "def f(a):\n    return a\n"}, module="before")
    served.add("moved", "2.0", {"__init__.py": "def f(a):\n    return a\n"}, module="after")
    result = runner.invoke(
        app, ["pack", "synth", "moved", "--from", "1.0", "--to", "2.0", "--dir", str(home)]
    )
    assert result.exit_code == 2
    assert "no module in common" in result.output


def test_the_module_named_like_the_library_wins_when_two_are_shared(
    home: Path, served: fakeindex.FakeIndex
) -> None:
    for version, name in (("1.0", "old_name"), ("2.0", "new_name")):
        served.add(
            "pair",
            version,
            {
                "pair/__init__.py": f"def {name}(a):\n    return a\n",
                "other/__init__.py": "def g(a):\n    return a\n",
            },
            module="",
        )
    fetcher = Fetcher(index=served.url)
    compared = libdiff.compare(
        fetcher, index.project(fetcher, "pair"), Version("1.0"), Version("2.0")
    )
    assert compared.module == "pair"


# A release that cannot be read.


def test_a_release_whose_bytes_are_not_the_ones_promised_exits_six(
    home: Path, served: fakeindex.FakeIndex
) -> None:
    name = served.add("tampered", "1.0", V2, module="acme_kit")
    served.add("tampered", "2.0", V2, module="acme_kit")
    served.corrupt.add(name)
    result = runner.invoke(
        app, ["pack", "synth", "tampered", "--from", "1.0", "--to", "2.0", "--dir", str(home)]
    )
    assert result.exit_code == 2
    assert "sha256" in result.output


def test_a_library_with_only_withdrawn_releases_has_no_newest(
    home: Path, served: fakeindex.FakeIndex
) -> None:
    served.add("gone", "1.0", V2, module="acme_kit", yanked="broken")
    result = runner.invoke(app, ["pack", "synth", "gone", "--from", "1.0", "--dir", str(home)])
    assert result.exit_code == 2
    assert "not withdrawn" in result.output


def test_a_file_that_is_not_a_distribution_is_refused(
    home: Path, served: fakeindex.FakeIndex
) -> None:
    served.add("junk", "1.0", V2, module="acme_kit")
    served.add("junk", "2.0", V2, module="acme_kit")
    project = served.projects["junk"]
    for release in project.releases.values():
        for name in release.files:
            release.files[name] = b"not a zip"
    result = runner.invoke(
        app, ["pack", "synth", "junk", "--from", "1.0", "--to", "2.0", "--dir", str(home)]
    )
    assert result.exit_code == 2
    assert "sha256" in result.output or "not a zip" in result.output


# What each change becomes.

MODULE = "acme_kit"
REQUEST = synth.Request(
    "acme-kit",
    Version("1.0"),
    Version("2.0"),
    MODULE,
    ">=3.9",
    "https://pypi.org/project/acme-kit/2.0/",
    "0" * 64,
    dt.date(2026, 10, 18),
)


def fn(*params: Param, trivial: bool = False) -> Obj:
    return Obj("", "function", params, trivial=trivial)


def req(name: str, kind: str = "positional or keyword") -> Param:
    return Param(name, kind, None, True)


def old_surface(**objects: Obj) -> Surface:
    return Surface(
        MODULE, {f"{MODULE}.{path.replace('__', '.')}": one for path, one in objects.items()}
    )


WORLD = old_surface(
    sub=Obj("", "module"),
    sub__Thing=Obj("", "class", None, bases=("Exception",)),
    sub__helper=fn(req("x")),
    old_greet=fn(req("name")),
    loud=fn(req("name")),
    Client=Obj("", "class", (req("key"), Param("timeout", "keyword-only", None, True))),
    Client__ping=fn(),
    Client__old_method=fn(),
    gone=fn(req("a")),
    LIMIT=Obj("", "attribute", value="3"),
    stale=fn(req("a")),
    kw=fn(Param("opt", "keyword-only", None, True), Param("rest", "variadic keyword", None, False)),
)


def plan(
    *changes: ApiChange, request: synth.Request = REQUEST, old: Surface = WORLD
) -> synth._Plan:
    return synth._Plan.build(request, old, changes)


def test_every_kind_of_change_becomes_the_part_of_the_pack_that_says_it() -> None:
    made = plan(
        ApiChange("renamed", "old_greet", "greet", same_signature=True),
        ApiChange("renamed", "loud", "shout", same_signature=False),
        ApiChange(
            "renamed",
            "Client.old_method",
            "Client.new_method",
            same_signature=True,
            message="use new_method instead",
        ),
        ApiChange("moved", "sub.Thing", "Thing", same_signature=True),
        ApiChange("moved", "sub.helper", "other.helper", same_signature=True),
        ApiChange("removed", "gone", message="gone is deprecated, use stale"),
        ApiChange("removed", "Client.ping"),
        ApiChange("deprecated", "LIMIT", message="LIMIT is going"),
        ApiChange("deprecated", "stale"),
        ApiChange("kind_changed", "kw", detail="function -> class"),
        ApiChange("param_removed", "kw", param="opt"),
    )
    assert made.with_calls == {"old_greet": "greet"}
    assert made.references == {"loud": "shout"}
    assert made.exports == {"sub.Thing": "Thing"}
    assert made.members == {
        "Client.old_method": synth._Member("new_method", None, "use new_method instead")
    }
    assert sorted(made.flags) == ["Client.ping", "LIMIT", "gone", "kw", "stale", "sub.helper"]
    assert "other.helper" in made.flags["sub.helper"].message
    assert "gone is deprecated, use stale" in made.flags["gone"].message
    assert made.flags["Client.ping"].message == "Removed in acme-kit 2.0."
    assert made.flags["LIMIT"].category == "deprecated"
    assert made.flags["stale"].message == "Deprecated in acme-kit 2.0."
    assert made.flags["kw"].message.count("in acme-kit 2.0") == 2
    assert "acme_kit.sub" in made.symbols
    assert made.dropped == ()


def test_a_rename_that_lands_on_a_name_the_pack_flags_is_flagged_instead() -> None:
    made = plan(
        ApiChange("renamed", "old_greet", "loud", same_signature=True),
        ApiChange("renamed", "gone", "stale", same_signature=True),
        ApiChange("deprecated", "loud", message="loud is going"),
    )
    assert made.with_calls == {"gone": "stale"}
    assert made.flags["old_greet"].category == "moved"
    assert "acme_kit.loud" in made.flags["old_greet"].message


def test_old_names_that_become_one_are_flagged_instead_of_all_renamed() -> None:
    made = plan(
        ApiChange("renamed", "old_greet", "greet", same_signature=True),
        ApiChange("renamed", "loud", "greet", same_signature=True),
        ApiChange("renamed", "gone", "found", same_signature=True),
        ApiChange("moved", "sub.Thing", "Thing", same_signature=True),
        ApiChange("moved", "sub.helper", "Thing", same_signature=True),
    )
    assert made.with_calls == {"gone": "found"}
    assert made.exports == {}
    assert sorted(made.flags) == ["loud", "old_greet", "sub.Thing", "sub.helper"]
    assert made.flags["loud"].category == "moved"
    assert "acme_kit.greet" in made.flags["old_greet"].message


def test_a_fixture_uses_a_sample_of_the_names_of_a_large_library() -> None:
    many = old_surface(**{f"f{n:03}": fn(req("x")) for n in range(synth.FIXTURE_NAMES + 40)})
    made = plan(
        *(ApiChange("removed", f"f{n:03}") for n in range(synth.FIXTURE_NAMES + 40)), old=many
    )
    assert len(made.flags) == synth.FIXTURE_NAMES + 40
    text = made.fixtures()["fixtures/positive/flagged.before.py"]
    assert text.count("acme_kit.f") == synth.FIXTURE_NAMES
    assert len(made.symbols) == synth.FIXTURE_NAMES + 40


def test_a_flag_under_a_flagged_class_is_left_out_and_said_so() -> None:
    made = plan(
        ApiChange("param_removed", "Client", param="key"),
        ApiChange("removed", "Client.ping"),
        ApiChange("removed", "Client.old_method"),
    )
    assert list(made.flags) == ["Client"]
    assert made.dropped == ("Client.old_method", "Client.ping")
    assert "Left out, as a class above them stands for them" in made._sources()
    assert synth._CLASS_NOTE in yaml.safe_load(made._pack())["limitations"]


@pytest.mark.parametrize(
    ("change", "text"),
    [
        (ApiChange("param_renamed", "f", param="a", new_param="b"), "`b` takes its place"),
        (ApiChange("param_removed", "f", param="a"), "`a` was removed"),
        (ApiChange("param_required_added", "f", param="a"), "`a` is required"),
        (
            ApiChange("param_kind_changed", "f", param="a", detail="x -> y"),
            "`a` changed from x -> y",
        ),
        (ApiChange("default_changed", "f", param="a", detail="1 -> 2"), "default of `a` changed"),
        (ApiChange("bases_changed", "f", detail="Base"), "no longer derives from Base"),
        (ApiChange("kind_changed", "f", detail="a -> b"), "changed from a -> b"),
    ],
)
def test_a_signature_change_says_which_parameter_and_how(change: ApiChange, text: str) -> None:
    assert text in synth._signature_text("acme-kit 2.0", change)


def test_a_message_the_library_wrote_is_quoted_with_nothing_that_moves_a_terminal() -> None:
    quoted = synth._quote("it\x1b[31m is   gone\n" + "x" * 400)
    assert "\x1b" not in quoted
    assert "\\x1b" in quoted
    assert len(quoted) == synth._QUOTE_CHARS
    assert quoted.endswith("…")
    assert synth._quote("short  one") == "short one"
    assert len(synth._text("y" * 900)) == 500


def test_a_call_is_written_with_a_zero_for_each_parameter_it_must_take() -> None:
    cls = Obj(
        "",
        "class",
        (
            req("a"),
            Param("b", "keyword-only", None, True),
            Param("c", "positional or keyword", "1", False),
        ),
    )
    assert synth._args(cls) == "0, b=0"
    assert synth._args(WORLD.relative()["kw"]) == "opt=0"
    assert synth._args(Obj("", "class", None)) == ""


def test_the_request_cites_the_file_when_it_is_https_and_the_project_page_when_it_is_not() -> None:
    def compared(url: str, python: str | None) -> libdiff.Comparison:
        file = index.File("a.whl", url, "a" * 64, Version("2.0"), "wheel", requires_python=python)
        return libdiff.Comparison(file, file, "acme_kit", Surface("m"), Surface("m"), ())

    secure = synth.request(
        "Acme_Kit",
        Version("1.0"),
        Version("2.0"),
        compared("https://files.example/a.whl", ">=3.10"),
    )
    assert (secure.url, secure.requires_python, secure.sha256) == (
        "https://files.example/a.whl",
        ">=3.10",
        "a" * 64,
    )
    local = synth.request(
        "Acme_Kit", Version("1.0"), Version("2.0"), compared("http://127.0.0.1:1/a.whl", "banana")
    )
    assert local.url == "https://pypi.org/project/acme-kit/2.0/"
    assert local.requires_python == ">=3.9"
    assert (
        synth.request(
            "x", Version("1"), Version("2"), compared("https://a/b", None)
        ).requires_python
        == ">=3.9"
    )
    assert REQUEST.pack_id == "acme-kit/1-0-to-2-0"
    assert (
        synth.Request(
            "A_b", Version("1.0a1"), Version("2.0+x"), "m", ">=3", "u", "s", dt.date(2026, 1, 1)
        ).pack_id
        == "a-b/1-0a1-to-2-0-x"
    )
    assert REQUEST.target == ">=2.0,<3"


# Failing, and leaving nothing behind.


def test_no_name_that_changed_is_nothing_to_synthesize(tmp_path: Path) -> None:
    with pytest.raises(synth.SynthError, match="nothing to synthesize"):
        synth.make(tmp_path, REQUEST, WORLD, [])


def test_a_pack_that_does_not_load_is_a_defect_and_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(reference: str, *_: object, **__: object) -> loader.LoadedPack:
        raise loader.PackInvalidError(reference, ["a problem"], bundled=False)

    monkeypatch.setattr(loader, "load", refuse)
    with pytest.raises(synth.SynthDefectError, match="a problem"):
        synth.make(tmp_path, REQUEST, WORLD, [ApiChange("removed", "gone")])
    assert not (tmp_path / "acme-kit").exists() or not list((tmp_path / "acme-kit").iterdir())


def test_a_pack_that_fails_its_own_checks_is_a_defect_and_is_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(check, "run", lambda _loaded: (check.Check("a check", ("it is wrong",)),))
    with pytest.raises(synth.SynthDefectError, match="a check: it is wrong"):
        synth.make(tmp_path, REQUEST, WORLD, [ApiChange("removed", "gone")])
    assert not (tmp_path / "acme-kit" / "1-0-to-2-0").exists()


def test_a_rename_the_rules_do_not_write_as_the_comparison_says_is_a_defect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        synth._Plan, "expected", lambda self: {"renamed_calls.before.py": "something else"}
    )
    with pytest.raises(synth.SynthDefectError, match="do not write what the comparison says"):
        synth.make(
            tmp_path,
            REQUEST,
            WORLD,
            [ApiChange("renamed", "old_greet", "greet", same_signature=True)],
        )
    assert not (tmp_path / "acme-kit" / "1-0-to-2-0").exists()


def test_a_pack_with_only_flags_has_a_negative_that_is_some_other_code(tmp_path: Path) -> None:
    made = synth.make(
        tmp_path, REQUEST, WORLD, [ApiChange("removed", "gone"), ApiChange("deprecated", "LIMIT")]
    )
    negative = (made.folder / "fixtures" / "negative" / "already_new.py").read_text()
    assert "import json" in negative
    assert "handler_" in (made.folder / "fixtures" / "positive" / "flagged.before.py").read_text()
    assert set(made.covered) == {"removed-1", "deprecated-1", "dependency-line"}


def test_more_groups_of_one_kind_than_the_limit_are_folded_into_one_that_says_less(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(synth, "MAX_GROUPS", 2)
    made = synth.make(
        tmp_path,
        REQUEST,
        WORLD,
        [
            ApiChange("removed", "gone", message="one"),
            ApiChange("removed", "stale", message="two"),
            ApiChange("removed", "old_greet", message="three"),
            ApiChange("removed", "loud"),
        ],
    )
    assert made.covered["removed-1"] + made.covered["removed-2"] == 4
    assert "removed-3" not in made.covered
    text = (made.folder / "pack.yaml").read_text()
    assert "Removed in acme-kit 2.0." in text


def test_names_moved_up_out_of_a_submodule_and_renamed_ones_are_made_into_a_pack(
    tmp_path: Path,
) -> None:
    made = synth.make(
        tmp_path,
        REQUEST,
        WORLD,
        [
            ApiChange("moved", "sub.Thing", "Thing", same_signature=True),
            ApiChange("renamed", "loud", "shout", same_signature=False),
            ApiChange("renamed", "old_greet", "greet", same_signature=True),
        ],
    )
    assert made.covered == {
        "rename-with-calls": 1,
        "rename-references": 1,
        "move-up": 1,
        "dependency-line": 1,
    }


def test_a_name_flagged_twice_for_one_reason_says_it_once() -> None:
    made = plan(
        ApiChange("param_removed", "kw", param="opt"), ApiChange("param_removed", "kw", param="opt")
    )
    assert made.flags["kw"].message.count("was removed") == 1


def test_names_a_lazy_module_may_still_have_are_counted_and_make_no_flag(tmp_path: Path) -> None:
    only_hidden = [ApiChange("unseen", "gone"), ApiChange("unseen", "stale")]
    with pytest.raises(synth.SynthError, match=r"2 name\(s\) could not be judged"):
        synth.make(tmp_path, REQUEST, WORLD, only_hidden)
    made = synth.make(tmp_path, REQUEST, WORLD, [*only_hidden, ApiChange("removed", "loud")])
    assert made.unseen == 2
    assert "acme_kit.gone" not in (made.folder / "pack.yaml").read_text()


def test_a_pack_made_beside_a_lazy_module_says_how_many_names_it_could_not_judge(
    home: Path, served: fakeindex.FakeIndex
) -> None:
    served.add(
        "lazy-kit",
        "1.0",
        {
            "__init__.py": "def f(x):\n    return x\n\n"
            "def g(x):\n    return x\n\ndef h(a):\n    return a\n"
        },
        module="lazy_kit",
    )
    served.add(
        "lazy-kit",
        "2.0",
        {
            "__init__.py": "def __getattr__(name):\n    return globals()[name]\n\n"
            "def f(x):\n    return x\n\ndef h(b):\n    return b\n"
        },
        module="lazy_kit",
    )
    result = runner.invoke(
        app, ["pack", "synth", "lazy-kit", "--from", "1.0", "--to", "2.0", "--dir", str(home)]
    )
    assert result.exit_code == 0, result.output
    assert "1 name(s) could not be judged" in result.output


def test_the_minor_lines_between_are_read_newest_first_until_every_removed_name_is_found(
    home: Path, served: fakeindex.FakeIndex
) -> None:
    def source(*, warn: bool = False) -> dict[str, str]:
        said = "import warnings\n\n" if warn else ""
        body = "warnings.warn('f is deprecated, use f2', DeprecationWarning)\n    " if warn else ""
        return {"__init__.py": f"{said}def f(x):\n    {body}return x\n\ndef f2(x):\n    return x\n"}

    served.add("lines", "1.0", source(), module="m")
    served.add("lines", "1.2", source(), module="m")
    served.add("lines", "1.3", source(warn=True), module="m")
    served.add("lines", "1.3.1", source(warn=True), module="m")
    served.add("lines", "1.4", source(), module="other")
    served.add("lines", "2.0", {"__init__.py": "def f2(x):\n    return x\n"}, module="m")
    result = runner.invoke(
        app, ["pack", "synth", "lines", "--from", "1.0", "--to", "2.0", "--dir", str(home)]
    )
    assert result.exit_code == 0, result.output
    assert "rename-with-calls: 1 name(s)" in result.output


def test_a_class_flagged_only_for_its_bases_gives_way_to_the_members_flagged_under_it() -> None:
    made = plan(
        ApiChange("bases_changed", "Client", detail="Base"),
        ApiChange("deprecated", "Client.old_method", message="use new_method"),
    )
    assert list(made.flags) == ["Client.old_method"]
    assert made.dropped == ("Client",)
    alone = plan(ApiChange("bases_changed", "Client", detail="Base"))
    assert list(alone.flags) == ["Client"]


def test_the_names_a_removed_one_may_have_become_are_written_beside_the_pack(
    tmp_path: Path,
) -> None:
    new = old_surface(gone_now=fn(req("a")), sub=Obj("", "module"))
    made = synth.make(tmp_path, REQUEST, WORLD, [ApiChange("removed", "gone")], new)
    assert synth.hints_for(str(made.folder / "pack.yaml")) == {
        "acme_kit.gone": (
            "Names acme-kit 2.0 has that the older release did not, closest in spelling first: "
            "acme_kit.gone_now (function)."
        )
    }


def test_there_are_no_hints_without_the_newer_surface_or_a_name_that_could_stand_for_the_old(
    tmp_path: Path,
) -> None:
    bare = synth.make(tmp_path / "a", REQUEST, WORLD, [ApiChange("removed", "gone")])
    assert not (bare.folder / synth.HINTS).exists()
    unlike = old_surface(zzzzz=fn())
    far = synth.make(tmp_path / "b", REQUEST, WORLD, [ApiChange("removed", "gone")], unlike)
    assert not (far.folder / synth.HINTS).exists()


@pytest.mark.parametrize("text", [None, "not json", "[1]", '{"a": 1, "b": "kept"}'])
def test_hints_are_read_only_as_names_with_text(tmp_path: Path, text: str | None) -> None:
    (tmp_path / "pack.yaml").write_text("x")
    if text is not None:
        (tmp_path / synth.HINTS).write_text(text)
    expected = {"b": "kept"} if text and "kept" in text else {}
    assert synth.hints_for(str(tmp_path / "pack.yaml")) == expected
    assert synth.hints_for("py-pdf/pypdf2-to-pypdf") == {}


def test_a_pack_for_the_names_a_repository_uses_holds_those_and_what_they_sit_on() -> None:
    scoped = replace(REQUEST, scope=frozenset({"old_greet", "Client"}))
    made = plan(
        ApiChange("renamed", "old_greet", "greet", same_signature=True),
        ApiChange("renamed", "loud", "shout", same_signature=True),
        ApiChange("removed", "Client.ping"),
        ApiChange("removed", "gone"),
        request=scoped,
    )
    assert made.with_calls == {"old_greet": "greet"}
    assert sorted(made.flags) == ["Client.ping"]
    above = plan(
        ApiChange("removed", "Client"), request=replace(REQUEST, scope=frozenset({"Client.ping"}))
    )
    assert sorted(above.flags) == ["Client"]
    assert (
        plan(ApiChange("removed", "gone"), request=replace(REQUEST, scope=frozenset())).flags == {}
    )


def test_a_pack_for_a_scope_has_an_id_that_says_so_and_one_scope_has_one_id() -> None:
    whole = synth.pack_id("acme-kit", Version("1.0"), Version("2.0"))
    one = synth.pack_id("acme-kit", Version("1.0"), Version("2.0"), frozenset({"a", "b"}))
    same = synth.pack_id("acme-kit", Version("1.0"), Version("2.0"), frozenset({"b", "a"}))
    other = synth.pack_id("acme-kit", Version("1.0"), Version("2.0"), frozenset({"a"}))
    assert one == same != other
    assert one.startswith(f"{whole}-for-")
    assert len(one) == len(whole) + len("-for-") + 8


def test_a_pack_larger_than_a_pack_may_be_is_refused_before_anything_is_written(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(synth, "PACK_BYTES", 10)
    result = _synth(home)
    assert result.exit_code == 2  # type: ignore[attr-defined]
    assert "more than a pack holds" in result.output  # type: ignore[attr-defined]
    assert not any(home.rglob("pack.yaml"))


def test_a_pack_for_the_names_a_folder_uses_is_made_and_a_star_import_is_refused(
    home: Path,
) -> None:
    used = committed(home / "used", {"app.py": "import acme_kit\nacme_kit.old_greet('x')\n"})
    made = _synth(home, "--used-by", str(used))
    assert made.exit_code == 0, made.output  # type: ignore[attr-defined]
    assert "-for-" in made.output  # type: ignore[attr-defined]
    star = committed(home / "star", {"app.py": "from acme_kit import *\n"})
    refused = _synth(home, "--used-by", str(star))
    assert refused.exit_code == 2  # type: ignore[attr-defined]
    assert "star import" in refused.output  # type: ignore[attr-defined]


# Methods of a class that the library renamed.


def use(name: str) -> str:
    """What a library says of a method that went: only which one to use."""
    return f"The method is deprecated; use `{name}` instead."


MEMBERS = old_surface(
    Client=Obj("", "class", None),
    Client__ping=fn(req("host"), Param("timeout", "keyword-only", "1", False)),
    Client__fetch=fn(req("url")),
    Client__send=fn(req("url")),
    Client__sub=fn(),
    old=fn(),
)


def test_a_method_the_library_renamed_becomes_a_member_rename_with_a_derived_class_to_show_it(
    tmp_path: Path,
) -> None:
    made = synth.make(
        tmp_path,
        REQUEST,
        MEMBERS,
        [
            ApiChange(
                "deprecated",
                "Client.ping",
                "Client.probe",
                message=use("probe"),
                same_signature=True,
            ),
            ApiChange(
                "deprecated", "Client.fetch", "Client.get", message=use("get"), takes=("url",)
            ),
            ApiChange(
                "renamed", "Client.send", "Client.post", message=use("post"), same_signature=True
            ),
        ],
    )
    assert made.covered["rename-members"] == 3
    pack = yaml.safe_load((made.folder / "pack.yaml").read_text())
    change = next(one for one in pack["changes"] if one["kind"] == "rename_member")
    assert change["params"] == {
        "members": {
            "acme_kit.Client.fetch": "get",
            "acme_kit.Client.ping": "probe",
            "acme_kit.Client.send": "post",
        },
        "takes": {"acme_kit.Client.fetch": ["url"]},
    }
    assert {"acme_kit.Client.ping", "acme_kit.Client.fetch"} <= set(pack["match"]["symbols"])
    positive = (made.folder / "fixtures" / "positive" / "renamed_members.before.py").read_text()
    assert "class Derived0(acme_kit.Client):" in positive
    assert "Derived0().ping(0)" in positive
    after = (made.folder / "fixtures" / "positive" / "renamed_members.after.py").read_text()
    assert "Derived0().probe(0)" in after
    assert (
        "acme_kit.Client.probe"
        in (made.folder / "fixtures" / "negative" / "already_new.py").read_text()
    )


def test_a_method_the_old_spelling_of_which_the_pack_would_flag_beside_it_is_flagged_instead() -> (
    None
):
    made = plan(
        ApiChange(
            "deprecated",
            "Client.old_method",
            "Client.ping",
            message=use("ping"),
            same_signature=True,
        ),
        ApiChange("deprecated", "Client.ping", message="ping is going"),
    )
    assert made.members == {}
    assert made.flags["Client.old_method"].category == "deprecated"
    assert "use `ping` instead" in made.flags["Client.old_method"].message


def test_methods_that_would_become_one_name_are_flagged_instead_of_all_renamed() -> None:
    made = plan(
        ApiChange(
            "deprecated",
            "Client.old_method",
            "Client.fresh",
            message=use("fresh"),
            same_signature=True,
        ),
        ApiChange(
            "deprecated", "Client.ping", "Client.fresh", message=use("fresh"), same_signature=True
        ),
        ApiChange("renamed", "Client.sub", "Client.next", message=use("next"), same_signature=True),
    )
    assert sorted(made.members) == ["Client.sub"]
    assert sorted(made.flags) == ["Client.old_method", "Client.ping"]


def test_a_method_that_lands_on_another_methods_old_name_is_flagged_instead() -> None:
    made = plan(
        ApiChange(
            "deprecated",
            "Client.old_method",
            "Client.ping",
            message=use("fresh"),
            same_signature=True,
        ),
        ApiChange(
            "deprecated", "Client.ping", "Client.fresh", message=use("fresh"), same_signature=True
        ),
    )
    assert sorted(made.members) == ["Client.ping"]
    assert sorted(made.flags) == ["Client.old_method"]


def test_a_method_under_a_class_flagged_as_a_whole_is_flagged_not_renamed() -> None:
    made = plan(
        ApiChange("param_removed", "Client", param="key"),
        ApiChange(
            "deprecated",
            "Client.old_method",
            "Client.fresh",
            message=use("fresh"),
            same_signature=True,
        ),
    )
    assert made.members == {}
    assert sorted(made.flags) == ["Client"]


def test_a_method_the_signature_changes_of_which_the_rename_replaces_are_not_flagged_too() -> None:
    made = plan(
        ApiChange("param_removed", "Client.old_method", param="loose"),
        ApiChange(
            "deprecated", "Client.old_method", "Client.fresh", message=use("fresh"), takes=()
        ),
        ApiChange(
            "deprecated", "Client.ping", "Client.probe", message=use("fresh"), same_signature=True
        ),
    )
    assert sorted(made.members) == ["Client.old_method", "Client.ping"]
    assert made.flags == {}
    assert made.members["Client.old_method"].takes == ()


def test_a_deprecation_that_names_a_method_a_call_cannot_move_to_is_a_flag_with_the_words() -> None:
    made = plan(ApiChange("deprecated", "Client.ping", "Client.probe", message=use("probe")))
    assert made.members == {}
    assert made.flags["Client.ping"].message.endswith(f"The library said: {use('probe')}")


def test_a_pack_whose_renamed_methods_all_take_what_they_took_has_no_takes_table(
    tmp_path: Path,
) -> None:
    made = synth.make(
        tmp_path,
        REQUEST,
        MEMBERS,
        [
            ApiChange(
                "renamed", "Client.send", "Client.post", message=use("post"), same_signature=True
            )
        ],
    )
    pack = yaml.safe_load((made.folder / "pack.yaml").read_text())
    change = next(one for one in pack["changes"] if one["kind"] == "rename_member")
    assert change["params"] == {"members": {"acme_kit.Client.send": "post"}}


def test_a_renamed_method_whose_message_says_more_than_which_to_use_is_flagged() -> None:
    said = "Call connect() first, then use post instead."
    made = plan(
        ApiChange("renamed", "Client.send", "Client.post", message=said, same_signature=True)
    )
    assert made.members == {}
    assert made.flags["Client.send"].category == "moved"
    assert "acme_kit.Client.post" in made.flags["Client.send"].message

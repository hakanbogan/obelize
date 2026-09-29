"""Build the file-selection fixture tree, and state what a scan must select.

`tests/fixtures/scan/` is a set of committed source files, because what those
fixtures pin is *bytes*. This one pins a *shape*, and the shape cannot be
committed: git will not track a nested `.git`, a symlink loop is not a thing a
checkout can contain, and a directory with no read permission would break every
clone. So the tree is built into a temporary directory by the test, twice --
once as a git repository and once not -- and the table below is its answer key,
in the same spirit as a `ground_truth.yaml`.

`COVERAGE.md` gap 13 was exactly this hole: "no symlink out of the root, no
dangling symlink, no symlink loop, no root under `/tmp`, no `.gitmodules` or
submodule directory". Every one of them is here.

The tree is deliberately awkward:

* two listings disagree about one file, and only about that one -- `git
  ls-files` honours `.gitignore` and the fallback walk cannot;
* the same submodule is refused by two different rules, `not_a_file` where git
  lists it as one path and `submodule` where the walk would descend into it;
* three of the four symlinks are the ones that break a naive containment check:
  one points outside the root, one points nowhere, one points at itself.

Usage from a test:

    build(root)          # the tree, plus a sibling directory outside it
    initialise(root)     # git init + git add, for the git listing

The test then takes the read permission off `sealed/`, after `initialise`, and
gives it back before deleting the tree.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# --- the answer key ---------------------------------------------------------

#: The `.obelize.yml` the table below assumes, written into the tree by `build`.
CONFIGURATION = 'exclude:\n  - "scripts/**"\n'

#: Files a scan reads, under both listings.
SELECTED = (
    "pkg/__init__.py",
    "pkg/app.py",
    "pkg/sub/deep.py",
)

#: The one file the two listings disagree about. git does not list it because
#: `.gitignore` says so, and the fallback walk has no way to know that.
IGNORED_BY_GIT = ("ignored_by_git.py",)

#: Removed by the user's own `exclude`, and therefore named by ADR-010 F-2:
#: excluding a file from the scan does not exclude it from the installation that
#: breaks when the legacy pin is dropped.
EXCLUDED = ("scripts/one_off.py",)

#: A legal POSIX name that Windows reads as a directory and a file.
UNUSABLE = () if sys.platform == "win32" else ("weird\\name.py",)

#: Refused, and why, under the git listing. Only paths `include` would have
#: taken are ever stat-ed, so this is the guard speaking about candidate files.
SKIPPED_BY_GIT = {
    "dangling.py": "symlink",
    "deleted.py": "missing",
    "loop.py": "symlink",
    "outside_link.py": "symlink",
    "pkg/link_to_app.py": "symlink",
    **dict.fromkeys(UNUSABLE, "unusable_name"),
}

#: Refused, and why, under the fallback walk. Three rows are the fallback doing
#: work git did for free: it has to recognise another repository, it has to
#: refuse to follow a linked directory, and it is the only one of the two that
#: can notice a directory it could not read.
SKIPPED_BY_WALK = {
    # `deleted.py` is in a git index and in no working tree, so only a git
    # listing can name it.
    **{path: reason for path, reason in SKIPPED_BY_GIT.items() if path != "deleted.py"},
    "linked_pkg": "symlink",
    "sealed": "unreadable",
    "vendorsub": "submodule",
}

#: `include: "**/*"`. The default glob never names a submodule or a linked
#: directory, so under it the guard is never asked about either; widen the glob
#: and the git listing hands both over. `Path.is_file()` is what drops the
#: gitlink -- git returns a submodule as one ordinary path entry, and a consumer
#: without that check opens a directory (ADR-008, C-14).
EVERYTHING = "**/*"
SKIPPED_BY_GIT_INCLUDING_EVERYTHING = {
    **SKIPPED_BY_GIT,
    "linked_pkg": "symlink",
    "sealed/hidden.txt": "unreadable",
    "vendorsub": "not_a_file",
}

#: Present, listed, and mentioned by neither answer: the always-excluded set
#: swallows the first three and `include` never matched the rest.
INVISIBLE = (
    ".obelize/runs/20260917T142530Z-3f9a1c72/REPORT.md",
    "build/generated.py",
    "venv_like/site.py",
    ".gitignore",
    ".obelize.yml",
    "pkg/notes.md",
    "scripts/helper.md",
    "sealed/hidden.txt",
    "vendorsub/sub_mod.py",
)


#: The directory built *beside* the root, so that a link out of the repository
#: has somewhere real to point. Its name is derived from the root's.
def outside_of(root: Path) -> Path:
    return root.parent / f"{root.name}.outside"


# --- building it ------------------------------------------------------------

_SOURCE = "import google.generativeai as genai\n"

_FILES = {
    ".gitignore": "ignored_by_git.py\nvenv_like/\n",
    ".obelize.yml": CONFIGURATION,
    ".obelize/runs/20260917T142530Z-3f9a1c72/REPORT.md": "# a report from a previous run\n",
    "build/generated.py": _SOURCE,
    "ignored_by_git.py": _SOURCE,
    "pkg/__init__.py": "",
    "pkg/app.py": _SOURCE,
    "pkg/notes.md": "`import google.generativeai` in prose\n",
    "pkg/sub/deep.py": _SOURCE,
    "scripts/helper.md": "not python\n",
    "scripts/one_off.py": _SOURCE,
    "sealed/hidden.txt": "unreadable once sealed\n",
    "venv_like/pyvenv.cfg": "home = /usr/bin\n",
    "venv_like/site.py": _SOURCE,
    **dict.fromkeys(UNUSABLE, _SOURCE),
}

#: link -> target, as written. Relative, because the tree is moved around.
_LINKS = {
    "dangling.py": "nowhere.py",
    "loop.py": "loop.py",
    "outside_link.py": None,  # filled in against the sibling directory
    "linked_pkg": None,
    "pkg/link_to_app.py": "app.py",
}


def build(root: Path) -> None:
    """Create the tree at `root`, and the directory it links out to."""
    outside = outside_of(root)
    _write(outside / "secret.py", _SOURCE)
    _write(outside / "pkg" / "inner.py", _SOURCE)
    for name, text in _FILES.items():
        _write(root / name, text)
    targets = dict(_LINKS)
    targets["outside_link.py"] = f"../{outside.name}/secret.py"
    targets["linked_pkg"] = f"../{outside.name}/pkg"
    for name, target in targets.items():
        assert target is not None
        link = root / name
        # Windows makes a directory link only when told the target is a directory.
        link.symlink_to(target, target_is_directory=(link.parent / target).is_dir())
    # The submodule: a real repository, so that `git add` records a gitlink and
    # the walk finds a `.git` to prune on.
    _write(root / "vendorsub" / "sub_mod.py", _SOURCE)
    _git(root / "vendorsub", "init", "-q", ".")
    _git(root / "vendorsub", "add", "-A")
    _git(root / "vendorsub", "commit", "-qm", "vendored")


def initialise(root: Path) -> None:
    """Make `root` a git repository, so the primary listing answers.

    The last two lines are the ordinary accident: a tracked file removed with
    `rm` rather than `git rm` stays in the index, so the listing names a path the
    working tree does not have. Only the git listing can produce this.
    """
    _git(root, "init", "-q", ".")
    _write(root / "deleted.py", _SOURCE)
    _git(root, "add", "-A")
    (root / "deleted.py").unlink()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _git(cwd: Path, *arguments: str) -> None:
    """git, with the machine's own configuration kept out of the fixture."""
    environment = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "Obelize fixture",
        "GIT_AUTHOR_EMAIL": "fixture@obelize.invalid",
        "GIT_COMMITTER_NAME": "Obelize fixture",
        "GIT_COMMITTER_EMAIL": "fixture@obelize.invalid",
    }
    subprocess.run(
        ["git", "-C", str(cwd), *arguments],
        check=True,
        capture_output=True,
        env=environment,
    )

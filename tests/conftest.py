"""Pin what the suite would otherwise inherit: terminal width, colour and the user's config.

Typer wraps help to `COLUMNS` (pinned wide: unset means the terminal's) and colours it under CI;
an empty `XDG_CONFIG_HOME` keeps the maintainer's `~/.config/obelize/config.yml` out of every test,
and an empty git configuration keeps the machine's `core.autocrlf` out of every test repository.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

# Each makes Typer colour help, splitting a phrase with escape codes; CI runners set the first.
COLOUR_FORCING = ("GITHUB_ACTIONS", "FORCE_COLOR", "PY_COLORS")


@pytest.fixture(autouse=True, scope="session")
def _pinned_environment(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Session-scoped so module-scoped command fixtures run under it too; yields the config home."""
    home = tmp_path_factory.mktemp("xdg-config")
    git_config = tmp_path_factory.mktemp("git-config") / "gitconfig"
    git_config.touch()
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("COLUMNS", "200")
        patch.setenv("XDG_CONFIG_HOME", str(home))
        patch.setenv("GIT_CONFIG_NOSYSTEM", "1")
        patch.setenv("GIT_CONFIG_GLOBAL", str(git_config))
        for forcing in COLOUR_FORCING:
            patch.delenv(forcing, raising=False)
        yield home

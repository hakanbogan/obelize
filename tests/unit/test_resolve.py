"""`obelize.resolve`: flagged places put to a model, each answer checked, in a copy."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from obelize.models import Config, EditProposal
from obelize.packs import loader
from obelize.providers import base
from obelize.resolve import Row, resolve, rows
from obelize.scan import runner as scanner
from support import write_tree

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

PACK = "tests/packs/generic/acme/kit-1-to-2/pack.yaml"
APP = (
    "import acme.kit\n"
    "\n"
    "\n"
    "def alive(client):\n"
    "    first = acme.kit.Client.ping(client)\n"
    "    return acme.kit.Client.ping(client) and first\n"
    "\n"
    "\n"
    "def again(client):\n"
    "    return acme.kit.Client.ping(client)\n"
)


class Scripted:
    """A model that answers each question with the next of its replies."""

    def __init__(self, *replies: Callable[[base.Consultation], base.Reply | Exception]) -> None:
        self.replies = list(replies)
        self.asked: list[base.Consultation] = []

    def request(self, consultation: base.Consultation) -> bytes:
        return b""

    def propose(self, consultation: base.Consultation) -> base.Reply:
        self.asked.append(consultation)
        answer = self.replies.pop(0)(consultation)
        if isinstance(answer, Exception):
            raise answer
        return answer


def propose(
    start: int,
    end: int,
    replaces: str,
    replacement: str,
    *,
    tokens: int = 10,
    imports: tuple[str, ...] = (),
) -> Callable[[base.Consultation], base.Reply]:
    def reply(consultation: base.Consultation) -> base.Reply:
        found = EditProposal(
            path=consultation.context.path,
            start_line=start,
            end_line=end,
            symbol=consultation.symbol,
            replaces=replaces,
            replacement=replacement,
            rationale="Client.health replaces Client.ping.",
            imports=imports,
        )
        return base.Reply(found, tokens, tokens + 1)

    return reply


def nothing(_consultation: base.Consultation) -> base.Reply:
    return base.Reply(None, 5, 1)


@pytest.fixture
def world(tmp_path: Path) -> tuple[Path, loader.LoadedPack, list[Row]]:
    work = write_tree(tmp_path / "work", {"app.py": APP})
    loaded = loader.load(PACK)
    found = scanner.scan(work, Config(), loader.to_scan_spec(loaded), jobs=1).findings
    return work, loaded, rows(found, loaded.pack)


def test_the_flagged_rows_are_the_withheld_ones_a_flag_claims_with_the_flags_words(
    world: tuple[Path, loader.LoadedPack, list[Row]],
) -> None:
    _work, _loaded, flagged = world
    assert [(row.path, row.line, row.symbol) for row in flagged] == [
        ("app.py", 5, "acme.kit.Client.ping"),
        ("app.py", 6, "acme.kit.Client.ping"),
        ("app.py", 10, "acme.kit.Client.ping"),
    ]
    assert flagged[0].note == (
        "Client.ping is gone in acme-kit 2. Call Client.health instead, which returns a bool."
    )


def test_a_row_the_pack_would_rewrite_is_not_a_question(tmp_path: Path) -> None:
    work = write_tree(
        tmp_path / "work",
        {"app.py": APP + "\n\ndef hello():\n    return acme.kit.old_greet('x')\n"},
    )
    loaded = loader.load(PACK)
    found = scanner.scan(work, Config(), loader.to_scan_spec(loaded), jobs=1).findings
    assert any(one.symbol == "acme.kit.old_greet" for one in found)
    assert {row.symbol for row in rows(found, loaded.pack)} == {"acme.kit.Client.ping"}
    assert rows([], loaded.pack) == []


def test_an_accepted_answer_is_written_and_the_rows_it_covers_are_not_asked(
    world: tuple[Path, loader.LoadedPack, list[Row]],
) -> None:
    work, loaded, flagged = world
    model = Scripted(
        propose(
            10,
            10,
            "    return acme.kit.Client.ping(client)",
            "    return acme.kit.Client.health(client)",
            tokens=7,
        ),
        propose(
            5,
            6,
            "    first = acme.kit.Client.ping(client)\n"
            "    return acme.kit.Client.ping(client) and first",
            "    first = acme.kit.Client.health(client)\n"
            "    return acme.kit.Client.health(client) and first",
        ),
    )
    done = resolve(work, flagged, provider=model, pack=loaded.pack, environ={})
    assert [(one.row.line, one.outcome) for one in done.decisions] == [
        (10, "edited"),
        (6, "edited"),
        (5, "covered"),
    ]
    assert len(model.asked) == 2
    assert model.asked[0].note == flagged[0].note
    assert model.asked[0].bail == "flag_only_surface"
    assert done.edited == ("app.py",)
    assert done.left == 0
    assert (done.tokens_in, done.tokens_out) == (17, 19)
    after = (work / "app.py").read_text()
    assert "ping" not in after
    assert after.count("health") == 3


def test_an_answer_that_is_nothing_an_error_or_refused_leaves_the_file_as_it_was(
    world: tuple[Path, loader.LoadedPack, list[Row]],
) -> None:
    work, loaded, flagged = world
    model = Scripted(
        nothing,
        lambda _c: base.ProviderError("endpoint_unreachable", "no answer"),
        propose(
            5,
            5,
            "    first = acme.kit.Client.ping(client)",
            "    import os\n    first = os.getcwd()",
        ),
    )
    done = resolve(work, flagged, provider=model, pack=loaded.pack, environ={})
    assert [(one.row.line, one.outcome) for one in done.decisions] == [
        (10, "nothing"),
        (6, "failed"),
        (5, "refused"),
    ]
    assert done.decisions[1].detail == "endpoint_unreachable: no answer"
    assert done.decisions[2].detail.startswith("import_outside_the_target")
    assert done.edited == ()
    assert done.left == 3
    assert (work / "app.py").read_text() == APP


def test_the_questions_asked_are_limited(world: tuple[Path, loader.LoadedPack, list[Row]]) -> None:
    work, loaded, flagged = world
    model = Scripted(nothing)
    done = resolve(work, flagged, provider=model, pack=loaded.pack, environ={}, limit=1)
    assert [one.outcome for one in done.decisions] == ["nothing", "skipped", "skipped"]
    assert "1 questions were asked already" in done.decisions[1].detail


def test_a_file_that_does_not_parse_is_not_asked_about(tmp_path: Path) -> None:
    work = write_tree(tmp_path / "work", {"app.py": "def broken(:\n"})
    loaded = loader.load(PACK)
    flagged = [Row("app.py", 1, "acme.kit.Client.ping", "gone")]
    done = resolve(work, flagged, provider=Scripted(), pack=loaded.pack, environ={})
    assert [(one.outcome, one.detail) for one in done.decisions] == [
        ("skipped", "the file does not parse")
    ]


def test_a_hint_for_the_name_or_the_longest_name_above_it_is_added_to_the_pack_words(
    world: tuple[Path, loader.LoadedPack, list[Row]],
) -> None:
    work, loaded, _ = world
    found = scanner.scan(work, Config(), loader.to_scan_spec(loaded), jobs=1).findings
    hints = {"acme.kit.Client": "wide", "acme.kit.Client.ping": "close", "acme.kit.Other": "no"}
    notes = {row.note.rsplit(" ", 1)[-1] for row in rows(found, loaded.pack, hints)}
    assert notes == {"close"}
    assert {
        row.note.rsplit(" ", 1)[-1] for row in rows(found, loaded.pack, {"acme.kit": "up"})
    } == {"up"}
    assert all(
        "close" not in row.note for row in rows(found, loaded.pack, {"acme.kit.Other": "no"})
    )


LATE = APP + "\n\ndef late():\n    import acme.kit\n"
PING = "acme.kit.Client.ping"


def tried(tmp_path: Path, source: str) -> tuple[Path, loader.LoadedPack]:
    return write_tree(tmp_path / "work", {"app.py": source}), loader.load(PACK)


def test_an_import_an_answer_adds_moves_the_places_still_waiting(tmp_path: Path) -> None:
    work, loaded = tried(tmp_path, APP)
    flagged = [Row("app.py", 5, PING, "n"), Row("app.py", 10, PING, "n")]
    model = Scripted(
        propose(
            10,
            10,
            "    return acme.kit.Client.ping(client)",
            "    return health(client)",
            imports=("from acme.kit import health",),
        ),
        propose(
            6,
            6,
            "    first = acme.kit.Client.ping(client)",
            "    first = health(client)",
        ),
    )
    done = resolve(work, flagged, provider=model, pack=loaded.pack, environ={})
    assert [(one.row.line, one.outcome) for one in done.decisions] == [
        (10, "edited"),
        (5, "edited"),
    ]
    assert [asked.line for asked in model.asked] == [10, 6]
    after = (work / "app.py").read_text()
    assert after.startswith("import acme.kit\nfrom acme.kit import health\n")
    assert "    first = health(client)\n    return acme.kit.Client.ping(client) and first" in after


def test_the_import_of_a_name_is_covered_once_its_uses_moved_wherever_it_sits(
    tmp_path: Path,
) -> None:
    work, loaded = tried(tmp_path, LATE)
    flagged = [
        Row("app.py", 1, PING, "n", True),
        Row("app.py", 10, PING, "n"),
        Row("app.py", 14, PING, "n", True),
    ]
    model = Scripted(
        propose(
            10,
            10,
            "    return acme.kit.Client.ping(client)",
            "    value = acme.kit.Client.health(client)\n    return value",
        )
    )
    done = resolve(work, flagged, provider=model, pack=loaded.pack, environ={})
    assert [(one.row.line, one.outcome) for one in done.decisions] == [
        (10, "edited"),
        (14, "covered"),
        (1, "covered"),
    ]
    assert len(model.asked) == 1
    assert done.left == 0


def test_the_import_of_a_name_whose_uses_were_not_all_moved_is_asked(tmp_path: Path) -> None:
    work, loaded = tried(tmp_path, APP)
    flagged = [
        Row("app.py", 1, PING, "n", True),
        Row("app.py", 5, PING, "n"),
        Row("app.py", 10, PING, "n"),
    ]
    model = Scripted(
        propose(
            10,
            10,
            "    return acme.kit.Client.ping(client)",
            "    return acme.kit.Client.health(client)",
        ),
        nothing,
        nothing,
    )
    done = resolve(work, flagged, provider=model, pack=loaded.pack, environ={})
    assert [(one.row.line, one.outcome) for one in done.decisions] == [
        (10, "edited"),
        (5, "nothing"),
        (1, "nothing"),
    ]
    assert len(model.asked) == 3


def test_an_import_outside_the_target_makes_the_answer_a_refusal(tmp_path: Path) -> None:
    work, loaded = tried(tmp_path, APP)
    model = Scripted(
        propose(
            10,
            10,
            "    return acme.kit.Client.ping(client)",
            "    return health(client)",
            imports=("from os import getcwd",),
        )
    )
    done = resolve(
        work, [Row("app.py", 10, PING, "n")], provider=model, pack=loaded.pack, environ={}
    )
    assert [one.outcome for one in done.decisions] == ["refused"]
    assert (work / "app.py").read_text() == APP

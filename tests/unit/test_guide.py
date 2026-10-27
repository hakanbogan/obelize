"""`obelize.packtools.guide`: a migration guide read as text, and cut into pieces for a model."""

from __future__ import annotations

import hashlib
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, get_args

import pytest

import fakeindex
from obelize.net import Fetcher, NetworkError
from obelize.packtools import guide
from platforms import posix_only

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


@pytest.fixture(scope="module")
def served() -> Iterator[fakeindex.FakeIndex]:
    yield from fakeindex.FakeIndex().serve()


def text(html: str) -> str:
    return guide.to_text(html, html=True)


# What a page becomes.


def test_headings_lists_and_paragraphs_are_lines() -> None:
    page = (
        "<html><body><h1>Migrating</h1><p>Intro   text\n here.</p><h2>Names</h2>"
        "<ul><li>one</li><li><a href='#x'>two</a> <em>bold</em></li><li> </li></ul></body></html>"
    )
    assert text(page) == "# Migrating\nIntro text here.\n## Names\n- one\n- two bold"


def test_a_table_is_one_line_a_row_with_its_cells_apart() -> None:
    page = (
        "<table><thead><tr><th>V1</th><th>V2</th></tr></thead>"
        "<tbody><tr><td><code>dict()</code></td><td><code>model_dump()</code></td></tr></tbody>"
        "</table>"
    )
    assert text(page) == "V1 | V2\ndict() | model_dump()"


def test_a_code_block_keeps_its_lines_and_is_fenced() -> None:
    page = "<p>Before:</p><pre><code>x = 1\n\n    y = f(x)\n</code></pre><p>After.</p>"
    assert text(page) == "Before:\n```\nx = 1\n\n    y = f(x)\n```\nAfter."


def test_a_code_block_made_of_one_block_a_line_has_its_lines_too() -> None:
    page = "<pre><div>a = 1</div><div>b = 2<br>c = 3</div><p>d</p></pre>"
    assert text(page) == "```\na = 1\nb = 2\nc = 3\nd\n```"


def test_a_fence_is_longer_than_any_run_of_backticks_in_the_code() -> None:
    page = "<pre>```python\nx\n```</pre>"
    assert text(page) == "````\n```python\nx\n```\n````"


def test_what_runs_or_surrounds_the_text_is_left_out_with_all_it_holds() -> None:
    page = (
        "<head><title>t</title></head><nav><a>menu</a><nav>inner</nav>more</nav>"
        "<script>var a = '<p>x</p>';</script><style>p{}</style><svg><title>s</title></svg>"
        "<p>kept</p><select><option>v1</option></select><footer>f</footer><button>b</button>"
    )
    assert text(page) == "kept"


def test_a_page_whose_hidden_element_never_closes_loses_the_rest_of_it() -> None:
    assert text("<p>before</p><nav><p>after</p>") == "before"


def test_an_entity_and_a_non_breaking_space_are_text() -> None:
    assert text("<p>a&nbsp;&lt;b&gt; &amp; c</p><pre>x&nbsp;y</pre>") == "a <b> & c\n```\nx y\n```"


def test_a_stray_close_and_a_break_outside_code_are_harmless() -> None:
    assert text("one<br>two</pre><pre>x<pre>y</pre>") == "one\ntwo\n```\nxy\n```"


def test_a_code_block_left_open_ends_with_the_page() -> None:
    assert text("<pre>never closed") == "```\nnever closed\n```"


def test_a_cell_after_an_empty_one_has_no_separator_before_it() -> None:
    assert text("<table><tr><td></td><td>x</td></tr></table>") == "x"


def test_markdown_and_plain_text_pass_through_with_their_line_ends_made_one() -> None:
    raw = "# Title\r\n\r\n`old()` is now `new()`.\rLast\x00\x07line\ttab\n"
    assert guide.to_text(raw, html=False) == "# Title\n\n`old()` is now `new()`.\nLast line\ttab"


def test_a_space_that_is_not_printable_is_a_space_and_does_not_join_the_words() -> None:
    raw = "old_total\u00a0is\u2002now\u200b\u2009total_of, and  two  spaces"
    assert guide.to_text(raw, html=False) == "old_total is now total_of, and  two  spaces"


# How long a page may take.


def ticking(step: float) -> Callable[[], float]:
    now = [0.0]

    def clock() -> float:
        now[0] += step
        return now[0]

    return clock


def test_a_page_that_takes_longer_than_its_budget_to_read_is_refused() -> None:
    page = "<p>word</p>" * 5000
    assert len(page) > 3 * 16384
    with pytest.raises(guide.GuideError) as raised:
        guide.to_text(page, html=True, clock=ticking(10.0))
    assert raised.value.reason == "unparsable"
    assert guide.to_text(page, html=True, clock=ticking(0.0)).count("word") == 5000


def test_a_page_has_a_couple_of_seconds_and_a_few_more_for_each_megabyte_up_to_a_cap() -> None:
    assert guide.parse_seconds(0) == 2.0
    assert guide.parse_seconds(1 << 20) == 6.0
    assert guide.parse_seconds(100 << 20) == guide.PARSE_SECONDS == 20.0
    assert guide.to_text("<p>x</p>", html=True, clock=ticking(1.0)) == "x"
    with pytest.raises(guide.GuideError):
        guide.to_text("<p>x</p>", html=True, clock=ticking(3.0))


@pytest.mark.parametrize(
    "hostile", ["<a" * 40000, "<p>x</p><!--" + "x" * 80000, "<a href='" * 9000]
)
def test_a_page_that_ends_in_a_tag_that_never_closes_is_refused_at_once(hostile: str) -> None:
    started = time.monotonic()
    with pytest.raises(guide.GuideError, match="never closes") as raised:
        guide.to_text(hostile, html=True)
    assert raised.value.reason == "unparsable"
    assert time.monotonic() - started < 2.0


@pytest.mark.parametrize("open_end", ["<!-- a note", "<a href=", "</p", "<!DOCTYPE", "<![CDATA[y"])
def test_a_comment_or_a_tag_that_is_open_at_the_end_is_not_text(open_end: str) -> None:
    assert guide.to_text("<p>x</p>" + open_end, html=True) == "x"


def test_a_lone_angle_bracket_at_the_end_is_text() -> None:
    assert guide.to_text("<p>x <", html=True) == "x <"


# Where it is read from.


def read_file(path: Path, body: bytes) -> guide.Guide:
    path.write_bytes(body)
    return guide.read(str(path), Fetcher(index="https://pypi.org"))


def test_a_file_is_read_as_bytes_and_called_by_its_name(tmp_path: Path) -> None:
    found = read_file(tmp_path / "MIGRATING.md", b"\xef\xbb\xbf# Move\n\nold is now new.\n")
    assert (found.ref, found.url, found.text) == ("MIGRATING.md", None, "# Move\n\nold is now new.")
    assert found.sha256 == hashlib.sha256(found.text.encode()).hexdigest()
    assert found.flat == "# Move old is now new."
    assert found.chunks == (found.text,)


def test_a_file_is_html_by_its_suffix_and_never_by_its_look(tmp_path: Path) -> None:
    assert read_file(tmp_path / "g.html", b"<p>one</p>").text == "one"
    assert read_file(tmp_path / "g.HTM", b"<p>two</p>").text == "two"
    page = b"<!DOCTYPE html><html><p>three</p></html>"
    assert read_file(tmp_path / "g.md", page).text == page.decode()
    assert read_file(tmp_path / "g.rst", b"<p>four</p>").text == "<p>four</p>"
    assert read_file(tmp_path / "g.markdown", b"five").text == "five"


@pytest.mark.parametrize(
    ("name", "body", "reason"),
    [
        ("g.pdf", b"%PDF", "unsupported_type"),
        (".env", b"KEY=value", "unsupported_type"),
        ("credentials", b"[default]", "unsupported_type"),
        ("g.json", b"{}", "unsupported_type"),
        ("g.md", b"a\x00b", "not_text"),
        ("g.md", b"\xff\xfe", "not_text"),
        ("g.md", b"\n \n", "empty"),
        ("g.html", b"<script>x</script>", "empty"),
    ],
)
def test_a_file_that_is_no_guide_is_refused_for_a_reason(
    tmp_path: Path, name: str, body: bytes, reason: str
) -> None:
    with pytest.raises(guide.GuideError) as raised:
        read_file(tmp_path / name, body)
    assert raised.value.reason == reason
    assert str(tmp_path) not in str(raised.value)


@posix_only("a named pipe")
def test_a_pipe_is_not_read_and_does_not_hang(tmp_path: Path) -> None:
    subprocess.run(["mkfifo", str(tmp_path / "pipe.md")], check=True)
    with pytest.raises(guide.GuideError, match="not a regular file") as raised:
        guide.read(str(tmp_path / "pipe.md"), Fetcher(index="https://pypi.org"))
    assert raised.value.reason == "unreadable"


def test_a_file_that_grows_after_it_is_measured_is_read_no_further_than_the_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "g.md"
    path.write_bytes(b"x" * 20)
    mode = path.stat().st_mode
    small = SimpleNamespace(st_mode=mode, st_size=5)
    monkeypatch.setattr(type(path), "stat", lambda self, **_kw: small)
    with pytest.raises(guide.GuideError, match="over 10 bytes") as raised:
        guide.file_bytes(path, 10)
    assert raised.value.reason == "too_large"


def test_a_file_that_is_missing_or_a_directory_is_unreadable(tmp_path: Path) -> None:
    for name in ("missing.md", "folder.md"):
        (tmp_path / "folder.md").mkdir(exist_ok=True)
        with pytest.raises(guide.GuideError) as raised:
            guide.read(str(tmp_path / name), Fetcher(index="https://pypi.org"))
        assert raised.value.reason == "unreadable"
        assert str(tmp_path) not in str(raised.value)


def test_a_file_over_the_size_or_the_text_over_its_limit_is_refused_and_not_cut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(guide, "FETCH_BYTES", 20)
    with pytest.raises(guide.GuideError) as raised:
        read_file(tmp_path / "big.md", b"x" * 21)
    assert raised.value.reason == "too_large"
    monkeypatch.setattr(guide, "FETCH_BYTES", 1000)
    monkeypatch.setattr(guide, "TEXT_CHARS", 10)
    with pytest.raises(guide.GuideError) as raised:
        read_file(tmp_path / "long.md", b"x" * 11)
    assert raised.value.reason == "too_long"
    assert read_file(tmp_path / "just.md", b"x" * 10).text == "x" * 10


def test_a_page_is_fetched_by_the_rule_of_the_fetcher_and_kept_without_its_query(
    served: fakeindex.FakeIndex,
) -> None:
    served.pages["/guide.html?token=secret"] = (
        "text/html; charset=utf-8",
        b"<!doctype html><html><body><h1>Move</h1><p>old is new.</p></body></html>",
    )
    told: list[str] = []
    fetcher = Fetcher(index=served.url, say=told.append)
    found = guide.read(f"{served.origin}/guide.html?token=secret#part", fetcher)
    assert found.text == "# Move\nold is new."
    assert found.ref == found.url == f"{served.origin}/guide.html"
    assert told == ["obelize contacts 127.0.0.1"]


def test_a_page_is_html_by_the_type_it_was_served_as_and_by_nothing_else(
    served: fakeindex.FakeIndex,
) -> None:
    served.pages["/typed.html"] = ("text/html", b"<h1>Move</h1><p>old is new.</p>")
    served.pages["/typed.xhtml"] = ("application/xhtml+xml", b"<p>one</p>")
    served.pages["/typed.md"] = ("text/markdown", b"```html\n<!doctype html><html></html>\n```\n")
    served.pages["/typed.txt"] = ("text/plain", b"<!doctype html><html><p>two</p></html>")
    fetcher = Fetcher(index=served.url)
    read = {
        name: guide.read(f"{served.origin}/typed.{name}", fetcher).text
        for name in ("html", "xhtml", "md", "txt")
    }
    assert read == {
        "html": "# Move\nold is new.",
        "xhtml": "one",
        "md": "```html\n<!doctype html><html></html>\n```",
        "txt": "<!doctype html><html><p>two</p></html>",
    }


def test_a_page_read_offline_from_the_cache_is_known_by_its_type_as_before(
    served: fakeindex.FakeIndex, tmp_path: Path
) -> None:
    from obelize.net import Cache

    served.pages["/kept.html"] = ("text/html", b"<h1>Kept</h1>")
    url = f"{served.origin}/kept.html"
    guide.read(url, Fetcher(index=served.url, cache=Cache(tmp_path / "c")))
    again = guide.read(url, Fetcher(index=served.url, cache=Cache(tmp_path / "c"), offline=True))
    assert again.text == "# Kept"


def test_a_page_of_markdown_or_plain_text_is_taken_as_it_is(served: fakeindex.FakeIndex) -> None:
    served.pages["/g.md"] = ("text/markdown", b"# One\n\n`a` is now `b`.\n")
    served.pages["/g.txt"] = ("text/plain", b"<p>not html: it says so</p>")
    fetcher = Fetcher(index=served.url)
    assert guide.read(f"{served.origin}/g.md", fetcher).text == "# One\n\n`a` is now `b`."
    assert guide.read(f"{served.origin}/g.txt", fetcher).text == "<p>not html: it says so</p>"


def test_a_page_of_another_type_is_refused_before_it_is_read(served: fakeindex.FakeIndex) -> None:
    served.pages["/g.pdf"] = ("application/pdf", b"%PDF-1.7")
    cache = Fetcher(index=served.url)
    with pytest.raises(NetworkError, match="application/pdf") as raised:
        guide.read(f"{served.origin}/g.pdf", cache)
    assert raised.value.reason == "refused"


def test_a_page_over_the_size_is_refused(
    served: fakeindex.FakeIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    served.pages["/big.md"] = ("text/plain", b"x" * 100)
    monkeypatch.setattr(guide, "FETCH_BYTES", 50)
    with pytest.raises(NetworkError) as raised:
        guide.read(f"{served.origin}/big.md", Fetcher(index=served.url))
    assert raised.value.reason == "too_large"


def test_a_page_that_moved_to_another_host_is_refused_and_says_where_to(
    served: fakeindex.FakeIndex,
) -> None:
    served.moved["/old"] = "https://docs.example.org/new"
    with pytest.raises(NetworkError, match=r"to docs\.example\.org") as raised:
        guide.read(f"{served.origin}/old", Fetcher(index=served.url))
    assert raised.value.reason == "redirected"


def test_offline_a_page_is_read_from_the_cache_or_not_at_all(
    served: fakeindex.FakeIndex, tmp_path: Path
) -> None:
    from obelize.net import Cache

    served.pages["/cached.md"] = ("text/plain", b"kept in the cache for the offline run")
    url = f"{served.origin}/cached.md"
    with pytest.raises(NetworkError) as raised:
        guide.read(url, Fetcher(index=served.url, offline=True, cache=Cache(tmp_path / "c")))
    assert raised.value.reason == "offline"
    guide.read(url, Fetcher(index=served.url, cache=Cache(tmp_path / "c")))
    again = guide.read(url, Fetcher(index=served.url, offline=True, cache=Cache(tmp_path / "c")))
    assert again.text == "kept in the cache for the offline run"


# The pieces.


def test_a_text_is_cut_at_line_ends_into_pieces_under_the_limit() -> None:
    lines = [f"line {n:03}" for n in range(10)]
    pieces = guide.chunks("\n".join(lines), limit=30)
    assert pieces == (
        "line 000\nline 001\nline 002",
        "line 003\nline 004\nline 005",
        "line 006\nline 007\nline 008",
        "line 009",
    )
    assert "\n".join(pieces) == "\n".join(lines)


def test_a_text_that_fits_is_one_piece() -> None:
    assert guide.chunks("a\nb", limit=100) == ("a\nb",)


def test_a_fenced_block_that_fits_a_piece_is_never_cut() -> None:
    block = "```python\n" + "\n".join(f"x{n} = {n}" for n in range(6)) + "\n```"
    assert guide.chunks(f"before\n{block}\nafter", limit=len(block) + 6) == (
        "before",
        block,
        "after",
    )


def test_a_fenced_block_that_does_not_fit_a_piece_is_cut_at_line_ends_like_other_text() -> None:
    lines = [f"x{n:02} = {n}" for n in range(12)]
    block = "\n".join(["```python", *lines, "```"])
    pieces = guide.chunks(f"before\n{block}\nafter", limit=40)
    assert max(len(piece) for piece in pieces) <= 40
    assert "\n".join(pieces) == f"before\n{block}\nafter"
    assert len(pieces) > 3


@pytest.mark.parametrize("fence", ["~~~", "   ```", "````"], ids=["tilde", "indented", "longer"])
def test_every_kind_of_fence_holds_a_block_together(fence: str) -> None:
    close = fence.strip()
    block = f"{fence}\n" + "\n".join("y" * 20 for _ in range(5)) + f"\n{close}"
    assert guide.chunks(f"a\n{block}\nz", limit=len(block) + 2) == ("a", block, "z")


def test_a_fence_closes_on_the_same_mark_and_only_on_a_bare_line() -> None:
    inside = "```\n~~~\n```not a close\n``\n```"
    assert guide.chunks(f"a\n{inside}\nz", limit=len(inside) + 2) == ("a", inside, "z")


def test_a_fence_never_closed_holds_what_fits_a_piece_and_not_the_rest_of_the_text() -> None:
    assert guide.chunks("a\n```\nx\ny", limit=100) == ("a\n```\nx\ny",)
    tail = "\n".join(f"line {n:03}" for n in range(300))
    pieces = guide.chunks(f"intro\n```\n{tail}", limit=500)
    assert max(len(piece) for piece in pieces) <= 500
    assert len(pieces) > 5
    assert "\n".join(pieces) == f"intro\n```\n{tail}"


def test_a_closing_fence_after_a_cut_block_ends_the_block_and_the_next_one_is_whole() -> None:
    long = "\n".join(["```", *[f"row {n:02}" for n in range(30)], "```"])
    short = "```\nz = 1\n```"
    pieces = guide.chunks(f"{long}\ntext\n{short}", limit=60)
    assert pieces[-1].endswith(short)
    assert short in pieces[-1]


def test_a_line_longer_than_a_piece_is_cut_at_a_space_and_a_word_longer_than_it_is_cut() -> None:
    words = " ".join(["word"] * 30)
    pieces = guide.chunks(words, limit=40)
    assert max(len(piece) for piece in pieces) <= 40
    assert " ".join(pieces) == words
    assert guide.chunks("x" * 100, limit=40) == ("x" * 40, "x" * 40, "x" * 20)


def test_a_guide_is_cut_into_pieces_when_it_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(guide, "CHUNK_CHARS", 10)
    found = read_file(tmp_path / "g.md", b"aaaa\nbbbb\ncccc\ndddd")
    assert found.chunks == ("aaaa\nbbbb", "cccc\ndddd")


def test_every_refusal_a_guide_can_have_has_its_word_in_the_cli_page() -> None:
    page = (Path(__file__).resolve().parents[2] / "docs" / "CLI.md").read_text(encoding="utf-8")
    for reason in get_args(guide.Reason):
        assert f"`{reason}`" in page, reason


def made(text: str) -> guide.Guide:
    return guide.Guide("g.md", None, text, "a" * 64, guide.flat(text), (text,))


@pytest.mark.parametrize(
    ("text", "quote", "around"),
    [
        # The lines it touches, flattened; a quote that spans two lines takes both.
        ("one two\nthree four.\nfive", "two three", "one two three four."),
        # A sentence wrapped over lines runs on both ways, up to a stop or a blank line.
        (
            "Start here\nthe middle one\nand an end.\nNext.",
            "middle",
            "Start here the middle one and an end.",
        ),
        ("Done.\nthe middle one\nand an end.\nNext.", "middle", "the middle one and an end."),
        ("Done.\n\nthe middle one\n\nNext.", "middle", "the middle one"),
        (
            'Said "so."\nthe middle one (maybe)\nand the end.',
            "middle",
            "the middle one (maybe) and the end.",
        ),
        # A heading, an item, a quote block, a fence and a table stand alone.
        ("Start here\n# Head words\nafter", "Head", "# Head words"),
        ("Start here\n- an item\n- another", "an item", "- an item"),
        ("Start here\na | b\nc | d", "a | b", "a | b"),
        ("Start here\n| a | b |\nmore", "| a | b |", "| a | b |"),
        ("Start here\n> quoted\nmore", "quoted", "> quoted"),
        ("Start here\n```\ncode\n```\nmore", "code", "code"),
        # Twice in the guide: both places.
        ("same words.\nelse.\nsame words.", "same words", "same words. same words."),
        ("only here.", "not there", ""),
    ],
)
def test_the_lines_around_a_quote_are_the_ones_it_touches_and_the_sentence_they_run_into(
    text: str, quote: str, around: str
) -> None:
    assert guide.lines_around(made(text), quote) == around

"""`obelize.packtools.guide`: a migration guide read as text, and cut into pieces for a model."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

import pytest

import fakeindex
from obelize.net import Fetcher, NetworkError
from obelize.packtools import guide

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


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
    assert guide.to_text(raw, html=False) == "# Title\n\n`old()` is now `new()`.\nLastline\ttab"


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


def test_a_file_that_is_html_is_known_by_its_suffix_and_a_file_without_one_by_its_look(
    tmp_path: Path,
) -> None:
    assert read_file(tmp_path / "g.html", b"<p>one</p>").text == "one"
    assert read_file(tmp_path / "g.txt", b"<!DOCTYPE html><p>two</p>").text == "two"
    assert read_file(tmp_path / "GUIDE", b"<p>three</p>").text == "<p>three</p>"


@pytest.mark.parametrize(
    ("name", "body", "reason"),
    [
        ("g.pdf", b"%PDF", "unsupported_type"),
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


def test_a_fenced_block_is_never_cut_and_alone_when_over_the_limit() -> None:
    block = "```python\n" + "\n".join(f"x{n} = {n}" for n in range(20)) + "\n```"
    pieces = guide.chunks(f"before\n{block}\nafter", limit=40)
    assert pieces == ("before", block, "after")


@pytest.mark.parametrize("fence", ["~~~", "   ```", "````"], ids=["tilde", "indented", "longer"])
def test_every_kind_of_fence_holds_a_block_together(fence: str) -> None:
    close = fence.strip()
    block = f"{fence}\n" + "\n".join("y" * 20 for _ in range(5)) + f"\n{close}"
    assert guide.chunks(f"a\n{block}\nz", limit=50) == ("a", block, "z")


def test_a_fence_closes_on_the_same_mark_and_only_on_a_bare_line() -> None:
    inside = "```\n~~~\n```not a close\n``\n```"
    assert guide.chunks(f"a\n{inside}\nz", limit=10) == ("a", inside, "z")


def test_a_fence_never_closed_holds_the_rest_of_the_text() -> None:
    rest = "```\nx\ny\nz"
    assert guide.chunks(f"a\n{rest}", limit=3) == ("a", rest)


def test_a_guide_is_cut_into_pieces_when_it_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(guide, "CHUNK_CHARS", 10)
    found = read_file(tmp_path / "g.md", b"aaaa\nbbbb\ncccc\ndddd")
    assert found.chunks == ("aaaa\nbbbb", "cccc\ndddd")

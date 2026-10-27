"""A migration guide as text: fetched or read, turned from HTML into lines, and cut into the pieces
a model is asked about (ADR-075).

The page is untrusted data. Nothing here runs it: a script, a style and the navigation are dropped
by tag, and what is kept is text, with a code block kept whole and in its line breaks. The text
is capped, not cut: a guide over the cap is refused, so no claim rests on a part nobody was told
was missing.
"""

from __future__ import annotations

import hashlib
import re
import stat
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal
from urllib.parse import urlsplit, urlunsplit

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from obelize.net import Fetcher

# The most guides one run reads, and the most bytes of one, as fetched or read from a file.
MAX_GUIDES: Final = 3
FETCH_BYTES: Final = 4 << 20
# The most text of one guide, and of one request to a model (about 5,000 tokens).
TEXT_CHARS: Final = 400_000
CHUNK_CHARS: Final = 20_000
TYPES: Final = (
    "text/html",
    "application/xhtml+xml",
    "text/plain",
    "text/markdown",
    "text/x-markdown",
)
_ACCEPT: Final = "text/html, text/markdown, text/plain;q=0.9"
_HTML_TYPES: Final = ("text/html", "application/xhtml+xml")
_HTML_FILES: Final = (".html", ".htm")
_TEXT_FILES: Final = (".md", ".markdown", ".txt", ".rst")
# A page is turned into text in a few seconds a megabyte and no more than this, and ends in no
# more than this of a tag or a comment that never closes: the parser is quadratic on those.
PARSE_SECONDS: Final = 20.0
_SLICE: Final = 16 << 10
_PENDING: Final = 16 << 10
_FENCE: Final = re.compile(r"^ {0,3}(`{3,}|~{3,})")
# Their contents are not the guide: code that runs, styles, the page around the text.
_HIDDEN: Final = frozenset(
    {"script", "style", "noscript", "svg", "template", "head", "nav", "footer", "button", "select"}
    | {"form", "iframe"}
)
_HEADINGS: Final = {f"h{n}": "#" * n + " " for n in range(1, 7)}
_BLOCKS: Final = frozenset(
    {"p", "div", "section", "article", "main", "aside", "ul", "ol", "li", "tr", "table"}
    | {"blockquote", "details", "summary", "figure", "figcaption", "dl", "dt", "dd", "hr"}
    | {"thead", "tbody", *_HEADINGS}
)

Reason = Literal[
    "unsupported_type", "not_text", "too_large", "too_long", "empty", "unreadable", "unparsable"
]


class GuideError(ValueError):
    """A guide that cannot be used, with the closed word for why."""

    def __init__(self, reason: Reason, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True, slots=True)
class Guide:
    """A guide's text, as given to a model, the hash of it and its pieces. `ref` is the address, or
    the name of a file: a path is never recorded. `flat` is the text with its whitespace made one
    space, which a quote is looked for in."""

    ref: str
    url: str | None
    text: str
    sha256: str
    flat: str
    chunks: tuple[str, ...]


def read(ref: str, fetcher: Fetcher) -> Guide:
    """The guide at an https address (through the fetcher's rules), else in a file. Raises
    `GuideError`, or `NetworkError` from the fetcher."""
    if ref.startswith(("https://", "http://")):
        kind, body = fetcher.page(ref, accept=_ACCEPT, max_bytes=FETCH_BYTES, types=TYPES)
        # Recorded and sent without a query or fragment, which can carry a token.
        shown = urlunsplit(urlsplit(ref)._replace(query="", fragment=""))
        return _guide(shown, shown, body, html=kind in _HTML_TYPES)
    path = Path(ref)
    suffix = path.suffix.lower()
    if suffix not in (*_HTML_FILES, *_TEXT_FILES):
        raise GuideError("unsupported_type", f"{path.name} is not a page of text or HTML")
    return _guide(path.name, None, file_bytes(path, FETCH_BYTES), html=suffix in _HTML_FILES)


def file_bytes(path: Path, limit: int) -> bytes:
    """A regular file of at most `limit` bytes, read whole: a pipe or a device would wait for
    ever, and a file that grows is read no further than the limit."""
    try:
        status = path.stat()
        if not stat.S_ISREG(status.st_mode):
            raise GuideError("unreadable", f"{path.name} is not a regular file")
        if status.st_size > limit:
            raise GuideError("too_large", f"{path.name} is over {limit} bytes")
        with path.open("rb") as handle:
            body = handle.read(limit + 1)
    except OSError as error:
        raise GuideError("unreadable", f"{path.name}: {error.strerror or error}") from error
    if len(body) > limit:
        raise GuideError("too_large", f"{path.name} is over {limit} bytes")
    return body


def _guide(ref: str, url: str | None, body: bytes, *, html: bool) -> Guide:
    try:
        raw = body.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise GuideError("not_text", f"{ref} is not UTF-8 text") from error
    if "\0" in raw:
        raise GuideError("not_text", f"{ref} holds a NUL character")
    text = to_text(raw, html=html)
    if not text.strip():
        raise GuideError("empty", f"{ref} holds no text")
    if len(text) > TEXT_CHARS:
        raise GuideError("too_long", f"{ref} has {len(text)} characters, over {TEXT_CHARS}")
    return Guide(
        ref,
        url,
        text,
        hashlib.sha256(text.encode()).hexdigest(),
        flat(text),
        chunks(text, CHUNK_CHARS),
    )


def flat(text: str) -> str:
    return " ".join(text.split())


def lines_around(guide: Guide, quote: str) -> str:
    """The lines of the guide that a flattened quote touches, each flattened, and the lines beside
    them that run into the same sentence (a paragraph wrapped over lines); a line of a table, a
    heading or an item stands alone. Where the quote is in the guide twice, the lines of both."""
    spans, at = [], 0
    for number, line in enumerate(guide.text.split("\n")):
        if words := flat(line):
            spans.append((at, at + len(words), words, number))
            at += len(words) + 1
    around: set[int] = set()
    start = guide.flat.find(quote)
    while start != -1:
        for n, (a, b, _, _) in enumerate(spans):
            if a < start + len(quote) and start < b:
                around |= _sentence(spans, n)
        start = guide.flat.find(quote, start + 1)
    return " ".join(spans[n][2] for n in sorted(around))


def _sentence(spans: list[tuple[int, int, str, int]], n: int) -> set[int]:
    """The lines from `n` that run on into one another: the line before ends with no full stop and
    no blank line is between them."""
    found = {n}
    for step in (-1, 1):
        here = n
        while 0 <= (there := here + step) < len(spans) and spans[there][3] == spans[here][3] + step:
            ends = spans[min(here, there)][2].rstrip("\"'\u2019\u201d)]`")
            if not (_prose(spans[here][2]) and _prose(spans[there][2])) or ends.endswith(_ENDS):
                break
            here = there
            found.add(here)
    return found


_ENDS: Final = (".", "!", "?", ":", ";")


def _prose(words: str) -> bool:
    return not (words.startswith(("#", "|", "- ", "* ", "> ", "```")) or " | " in words)


def to_text(raw: str, *, html: bool, clock: Callable[[], float] = time.monotonic) -> str:
    """The lines of a page, or of a Markdown or plain file with its line ends made `\\n` and each
    run of other control and space characters one space. A page that takes longer than
    `PARSE_SECONDS` (by `clock`) to read, or ends in a tag that never closes, is `unparsable`."""
    if html:
        raw = _page(raw, clock)
    text, odd = [], False
    for c in raw.replace("\r\n", "\n").replace("\r", "\n"):
        if c in "\n\t" or c.isprintable():
            text.append(c)
            odd = False
        elif not odd:
            text.append(" ")
            odd = True
    return "".join(text).strip("\n")


def parse_seconds(size: int) -> float:
    """What a page of `size` characters may take to read: a couple of seconds and a few more for
    each megabyte, to `PARSE_SECONDS`."""
    return min(PARSE_SECONDS, 2.0 + 4.0 * size / (1 << 20))


def _page(raw: str, clock: Callable[[], float]) -> str:
    page = _Page()
    deadline = clock() + parse_seconds(len(raw))
    for start in range(0, len(raw), _SLICE):
        if clock() > deadline:
            raise GuideError("unparsable", "the page takes too long to read")
        page.feed(raw[start : start + _SLICE])
    if len(page.rawdata) > _PENDING:
        raise GuideError("unparsable", "the page ends in a tag or a comment that never closes")
    if page.rawdata.startswith("<") and len(page.rawdata) > 1:
        page.rawdata = ""  # open at the end is not text; older parsers would flush it as text
    page.close()
    return page.text()


class _Page(HTMLParser):
    """HTML as lines: a block ends a line, a heading, list item and table cell say so, a code block
    is fenced and keeps its lines, and what is hidden (`_HIDDEN`) is left out with all it holds."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._lines: list[str] = []
        self._line: list[str] = []
        self._code: list[str] | None = None
        self._hidden: str | None = None
        self._depth = 0

    def text(self) -> str:
        self._end_line()
        if self._code is not None:
            self._end_code()
        return "\n".join(self._lines)

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if self._hidden:
            self._depth += tag == self._hidden
        elif tag in _HIDDEN:
            self._hidden, self._depth = tag, 1
        elif self._code is not None:
            if tag == "br":
                self._code.append("\n")
        elif tag == "pre":
            self._end_line()
            self._code = []
        elif tag == "br":
            self._end_line()
        elif tag in _BLOCKS:
            self._end_line()
            self._line.append(_HEADINGS.get(tag, "- " if tag == "li" else ""))
        elif tag in ("td", "th") and "".join(self._line).strip():
            self._line.append(" | ")

    def handle_endtag(self, tag: str) -> None:
        if self._hidden:
            self._depth -= tag == self._hidden
            self._hidden = self._hidden if self._depth else None
        elif tag == "pre" and self._code is not None:
            self._end_code()
        elif self._code is not None:
            if tag in _BLOCKS and self._code and not self._code[-1].endswith("\n"):
                self._code.append("\n")
        elif tag in _BLOCKS:
            self._end_line()

    def handle_data(self, data: str) -> None:
        if self._hidden:
            return
        (self._line if self._code is None else self._code).append(data.replace("\xa0", " "))

    def _end_line(self) -> None:
        text = " ".join("".join(self._line).split())
        self._line = []
        if text.strip("-# "):
            self._lines.append(text)

    def _end_code(self) -> None:
        block = "".join(self._code or []).strip("\n")
        self._code = None
        longest = max((len(run) for run in re.findall(r"^`+", block, re.MULTILINE)), default=0)
        fence = "`" * max(3, longest + 1)
        self._lines += [fence, *block.split("\n"), fence]


def chunks(text: str, limit: int) -> tuple[str, ...]:
    """The text in pieces of at most `limit` characters, each ending at the end of a line (a longer
    line is cut at a space) and not inside a fenced code block that fits a piece; one that does
    not, closed or not, is cut at line ends like any other text."""
    pieces: list[str] = []
    held: list[str] = []
    size = 0
    for unit in _units(text, limit):
        if held and size + len(unit) + 1 > limit:
            pieces.append("\n".join(held))
            held, size = [], 0
        held.append(unit)
        size += len(unit) + 1
    return (*pieces, "\n".join(held)) if held else tuple(pieces)


def _units(text: str, limit: int) -> Iterator[str]:
    """Each line, and each fenced block that fits `limit` as one."""
    opening, block, size, spilling = "", [], 0, False
    for line in text.split("\n"):
        mark = _FENCE.match(line)
        if not opening:
            if mark:
                opening, block, size = mark[1], [line], len(line) + 1
            else:
                yield from _wrap(line, limit)
            continue
        closes = (
            mark is not None
            and mark[1][0] == opening[0]
            and len(mark[1]) >= len(opening)
            and not line.strip().strip(opening[0])
        )
        if spilling:
            yield from _wrap(line, limit)
        else:
            block.append(line)
            size += len(line) + 1
            if size > limit:
                yield from (cut for one in block for cut in _wrap(one, limit))
                spilling = True
            elif closes:
                yield "\n".join(block)
        if closes:
            opening, spilling = "", False
    if opening and not spilling:
        yield "\n".join(block)


def _wrap(line: str, limit: int) -> Iterator[str]:
    """A line, cut at a space into pieces of at most `limit` characters if it is longer."""
    while len(line) > limit:
        at = line.rfind(" ", 0, limit)
        at = at if at > 0 else limit
        yield line[:at]
        line = line[at:].lstrip(" ")
    yield line


__all__ = [
    "CHUNK_CHARS",
    "FETCH_BYTES",
    "MAX_GUIDES",
    "PARSE_SECONDS",
    "TEXT_CHARS",
    "TYPES",
    "Guide",
    "GuideError",
    "chunks",
    "file_bytes",
    "flat",
    "lines_around",
    "parse_seconds",
    "read",
    "to_text",
]

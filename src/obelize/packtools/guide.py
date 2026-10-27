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
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal
from urllib.parse import urlsplit, urlunsplit

if TYPE_CHECKING:
    from collections.abc import Iterator

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
_HTML_FILES: Final = (".html", ".htm", ".xhtml")
_TEXT_FILES: Final = (".md", ".markdown", ".txt", ".rst", "")
_HTML: Final = re.compile(r"<(?:!doctype\s+html|html[\s>])", re.IGNORECASE)
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

Reason = Literal["unsupported_type", "not_text", "too_large", "too_long", "empty", "unreadable"]


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
        body = fetcher.get(ref, accept=_ACCEPT, max_bytes=FETCH_BYTES, types=TYPES)
        # Recorded and sent without a query or fragment, which can carry a token.
        shown = urlunsplit(urlsplit(ref)._replace(query="", fragment=""))
        return _guide(shown, shown, body, html=None)
    path = Path(ref)
    if path.suffix.lower() not in (*_HTML_FILES, *_TEXT_FILES):
        raise GuideError("unsupported_type", f"{path.name} is not a page of text or HTML")
    try:
        with path.open("rb") as handle:
            body = handle.read(FETCH_BYTES + 1)
    except OSError as error:
        raise GuideError("unreadable", f"{path.name}: {error.strerror or error}") from error
    if len(body) > FETCH_BYTES:
        raise GuideError("too_large", f"{path.name} is over {FETCH_BYTES} bytes")
    return _guide(path.name, None, body, html=path.suffix.lower() in _HTML_FILES or None)


def _guide(ref: str, url: str | None, body: bytes, *, html: bool | None) -> Guide:
    try:
        raw = body.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise GuideError("not_text", f"{ref} is not UTF-8 text") from error
    if "\0" in raw:
        raise GuideError("not_text", f"{ref} holds a NUL character")
    text = to_text(raw, html=bool(_HTML.search(raw[:2000])) if html is None else html)
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


def to_text(raw: str, *, html: bool) -> str:
    """The lines of a page, or of a Markdown or plain file with its line ends made `\\n` and any
    other control character dropped."""
    if html:
        page = _Page()
        page.feed(raw)
        page.close()
        raw = page.text()
    kept = (
        c for c in raw.replace("\r\n", "\n").replace("\r", "\n") if c in "\n\t" or c.isprintable()
    )
    return "".join(kept).strip("\n")


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
    """The text in pieces of at most `limit` characters, each ending at the end of a line and never
    inside a fenced code block, which is one piece alone if it is over the limit."""
    pieces: list[str] = []
    held: list[str] = []
    size = 0
    for unit in _units(text):
        if held and size + len(unit) + 1 > limit:
            pieces.append("\n".join(held))
            held, size = [], 0
        held.append(unit)
        size += len(unit) + 1
    return (*pieces, "\n".join(held)) if held else tuple(pieces)


def _units(text: str) -> Iterator[str]:
    """Each line, and each fenced block as one."""
    block: list[str] = []
    opening = ""
    for line in text.split("\n"):
        mark = _FENCE.match(line)
        if not block:
            if mark:
                block, opening = [line], mark[1]
            else:
                yield line
            continue
        block.append(line)
        if (
            mark
            and mark[1][0] == opening[0]
            and len(mark[1]) >= len(opening)
            and not (line.strip().strip(opening[0]))
        ):
            yield "\n".join(block)
            block = []
    if block:
        yield "\n".join(block)


__all__ = [
    "CHUNK_CHARS",
    "FETCH_BYTES",
    "MAX_GUIDES",
    "TEXT_CHARS",
    "TYPES",
    "Guide",
    "GuideError",
    "chunks",
    "flat",
    "read",
    "to_text",
]

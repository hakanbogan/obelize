"""MkDocs hooks: publish the repository's changelog, and point links out of the site at GitHub."""

import posixpath
import re
from pathlib import Path

from mkdocs.structure.files import File

BLOB = "https://github.com/hakanbogan/obelize/blob/main/"
TREE = "https://github.com/hakanbogan/obelize/tree/main/"
LINK = re.compile(r"\]\((?![A-Za-z][A-Za-z0-9+.-]*:|#|//)([^)\s#]+)(#[^)\s]*)?\)")


def on_files(files, config):
    source = Path(config.config_file_path).parent / "CHANGELOG.md"
    files.append(File.generated(config, "CHANGELOG.md", content=source.read_text(encoding="utf-8")))
    return files


def on_page_markdown(markdown, page, **_):
    here = posixpath.dirname(page.file.src_uri)
    changelog = page.file.src_uri == "CHANGELOG.md"

    def point(match):
        path, fragment = match.group(1), match.group(2) or ""
        target = posixpath.normpath(posixpath.join("" if changelog else "docs", here, path))
        if target.startswith("docs/") and not path.endswith("/"):
            if not changelog:
                return match.group(0)
            return f"]({posixpath.relpath(target.removeprefix('docs/'), here or '.')}{fragment})"
        if target == "CHANGELOG.md":
            return f"]({posixpath.relpath(target, here or '.')}{fragment})"
        base = TREE if path.endswith("/") else BLOB
        return f"]({base}{target}{fragment})"

    return LINK.sub(point, markdown)

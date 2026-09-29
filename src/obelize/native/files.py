"""The file primitives the path guard and the run folder open, rename and delete through.

Below `root`, every name is opened relative to an open parent directory and never through a link,
so nothing is resolved by path again between a check and its use. `root` follows a link, and
`open_path` guards only the last component. A `Handle` is an open directory, passed only back to
this module; the files it opens are descriptors.
"""

import sys

if sys.platform == "win32":
    from obelize.native.files_windows import (  # pragma: windows-only
        Handle,
        close,
        create,
        directory,
        make_directory,
        open_at,
        open_path,
        remove_tree,
        rename,
        reserved,
        root,
        set_mode,
        status,
        unlink,
    )
else:
    from obelize.native.files_posix import (  # pragma: posix-only
        Handle,
        close,
        create,
        directory,
        make_directory,
        open_at,
        open_path,
        remove_tree,
        rename,
        reserved,
        root,
        set_mode,
        status,
        unlink,
    )

__all__ = [
    "Handle",
    "close",
    "create",
    "directory",
    "make_directory",
    "open_at",
    "open_path",
    "remove_tree",
    "rename",
    "reserved",
    "root",
    "set_mode",
    "status",
    "unlink",
]

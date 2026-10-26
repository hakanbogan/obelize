# Sources for `setuptools/pkg-resources-to-importlib`

One section per `changes[].id`, in pack order (held equal to the pack by
`tests/packs/test_all_packs.py`; rules in `docs/PACK_SPEC.md`, *Source
provenance*).

## The retrieved pages

| Source | URL | `retrieved_at` | sha256 of the page as retrieved |
|---|---|---|---|
| Package Discovery and Resource Access using pkg_resources (the pack's `source`) | <https://setuptools.pypa.io/en/latest/deprecated/pkg_resources.html> | 2026-10-24 | `8493b6bc69cd788cea335876352e9641e302a1ab232634b4e60ad70aeef54522` |
| setuptools, History | <https://setuptools.pypa.io/en/latest/history.html> | 2026-10-24 | `61b2944204309b370929f10d5ab154a28ac0761b15a9df0d49b0f52a4728df0f` |
| importlib_metadata, Migration guide | <https://importlib-metadata.readthedocs.io/en/latest/migration.html> | 2026-10-24 | `2862bcb2713f7d49288919ec9c292f967f3f59e5ea67daabceb49e9957ce0111` |
| Python documentation, importlib.metadata | <https://docs.python.org/3/library/importlib.metadata.html> | 2026-10-24 | `33dad4f1c230d55f8f737cea54ba11c4cfa1a59f21dae7052894dbe55b19e61a` |
| Python documentation, importlib.resources | <https://docs.python.org/3/library/importlib.resources.html> | 2026-10-24 | `5f6c19b3f1d9baf7f37b5f3bd2c927dc7062ec936e47d429f1d65eba56fd3c3c` |
| What's New In Python 3.12 | <https://docs.python.org/3/whatsnew/3.12.html> | 2026-10-24 | `bc1ab5402bf32240db0da103113feced72ab8e1dbd94bf368d161c1eb0874abc` |
| packaging, Version Handling | <https://packaging.pypa.io/en/stable/version.html> | 2026-10-27 | `b92f7402af83212958243262adfaecec6eda031c8eb493d70eea01c165931bcc` |
| packaging, Requirements | <https://packaging.pypa.io/en/stable/requirements.html> | 2026-10-27 | `b40760bb039301352554d2e631f95aefadc4434864801650aa4bf600fcdb45e3` |
| packaging, Markers | <https://packaging.pypa.io/en/stable/markers.html> | 2026-10-27 | `04963f74cc8e3dd26049733810c1698cd6c52ab5f8725197f099f022d46ef850` |
| PEP 420, Implicit Namespace Packages | <https://peps.python.org/pep-0420/> | 2026-10-27 | `f7ab12b76762116d49ef9c8fc0e99c6430953512afaf19186556d480b57d12ef` |

The hash is of the page body as served. obelize never requests the URL. Where a sentence of a flag
text is not in a page above, the section for that flag says it is mine.

## The measurement, and why it outranks the page

"Measured" means checked on setuptools 81.0.0, the last release that ships `pkg_resources`, and on
82.0.0, which does not (PyPI upload times 2026-02-06 and 2026-02-08), each installed alone on CPython
3.12 with no other library:

    uv run --isolated --no-project --python 3.12 --with setuptools==81.0.0 \
        python -I tests/packs/pkg_resources_check.py

It prints each claim that does not hold and exits 1 if there is one; it holds on 81.0.0, and on
82.0.0 it finds `import pkg_resources` raising `ModuleNotFoundError`, which is why `from.version` is
`<82`. The standard-library side is checked by `tests/packs/test_runtime_facts.py` on the Python that
runs the tests. The pages say what was removed and what replaces it in outline; they do not say that
the replacements differ in the ways below, so the pack follows the measurement and rewrites nothing.

Measured on setuptools 81.0.0: `pkg_resources.get_distribution('x').version` and
`importlib.metadata.version('x')` give the same string for an installed `x`, and nothing else about
them is the same. For a distribution that is not installed, `get_distribution` raises
`DistributionNotFound` (a `ResolutionError`) and `version` raises `PackageNotFoundError` (a
`ModuleNotFoundError`), two classes with no base in common but `Exception`. `get_distribution('setuptools>=1')`
answers and `version('setuptools>=1')` raises `PackageNotFoundError`, since a requirement string is
no name; `get_distribution('setuptools>=1000')` raises `VersionConflict`. A `pkg_resources` entry
point has `require`, `resolve` and `dist`; an `importlib.metadata` one has `dist`, `value`, `group`,
`name` and `load` and neither of the first two. `resource_filename` returns a `str`, and
`importlib.resources.files(...) / name` a `pathlib.Path` here and a `Traversable` in general;
`resource_string` and `read_bytes()` read the same bytes. `parse_version` returns a
`packaging.version.Version`.

---

## flag-distributions

- importlib_metadata, Migration guide: "importlib_metadata aims to replace the following
  pkg_resources APIs: `pkg_resources.iter_entry_points()`, `pkg_resources.require()` convenience
  functions, `pkg_resources.find_distributions()`, `pkg_resources.get_distribution()`." And for
  `require()`: "importlib_metadata does not provide support for dynamically discovering or
  requiring distributions nor does it provide any support for managing the 'working set'."
- Python documentation, importlib.metadata: `version(distribution_name)` "Raises
  `PackageNotFoundError` if the named distribution package is not installed"; `PackageNotFoundError`
  is a "Subclass of `ModuleNotFoundError`".
- Measured: the errors, the requirement string and `VersionConflict` above.

## flag-entry-points

- importlib_metadata, Migration guide: "Compatibility note: entry points provided by
  importlib_metadata do not have the following implicit behaviors found in those from
  pkg_resources: Each EntryPoint is not automatically validated to match [...] When invoking
  EntryPoint.load(), no checks are performed to ensure the declared extras are installed."
- Python documentation, importlib.metadata: `entry_points(**select_params)` "Returns a
  `EntryPoints` instance"; keywords such as `group` and `name` select. Measured: the keyword form
  runs on CPython 3.10 to 3.15, and `entry_points()` of 3.9 takes no keyword, which is why
  `to.python` is `>=3.10`.
- Measured: the members of the two kinds of entry point, above.

## flag-resources

- Python documentation, importlib.resources: `files(anchor)` "Returns a `Traversable` object
  representing the resource container [...] Added in version 3.9". `as_file(traversable)` "Use
  `as_file` when the `Traversable` methods (`read_text`, etc) are insufficient and an actual file or
  directory on the file system is required. Added in version 3.9."
- Package Discovery and Resource Access using pkg_resources, 'Resource Extraction':
  "`resource_filename(package_or_requirement, resource_name)` [...] If the resource is in an archive
  distribution (such as a zipped egg), it will be extracted to a cache directory, and the filename
  within the cache will be returned."
- setuptools, History, v82.0.0: "Most common uses of `pkg_resources` have been superseded by the
  `importlib.resources` and `importlib.metadata` projects."
- Measured: `resource_filename` returns a `str` path, `files()` a `Traversable`.

## flag-requirements

- importlib_metadata, Migration guide: "Other functionality from pkg_resources is replaced by other
  packages such as importlib_resources and packaging." The guide names the project, not the
  functions: that `parse_version` is `packaging.version.parse`, `Requirement` is
  `packaging.requirements.Requirement` and `evaluate_marker` is `packaging.markers.Marker(...).evaluate()`
  is my reading of the three packaging pages above, whose usage sections show `parse`, `Requirement(...)`
  and `Marker(...).evaluate()`.
- Measured on setuptools 81.0.0: `pkg_resources.parse_version('1.0')` is a `packaging.version.Version`;
  `pkg_resources.Requirement` has `key`, `project_name`, `specs`, `specifier` and `name`, and
  `packaging.requirements.Requirement` only the last two; `invalid_marker("python_version >")`
  returns the error text where `Marker("python_version >")` raises. `safe_name('My_Pkg.X')` is
  `My-Pkg.X`, `to_filename('my-pkg')` is `my_pkg`, `safe_version('1.0-x y')` is `1.0-x.y` and
  `safe_extra('Foo Bar')` is `foo_bar`, while `packaging.utils.canonicalize_name('My_Pkg.X')` is
  `my-pkg-x`: none of the four has a counterpart, which the suggestion says. `packaging` is not in the
  standard library.

## flag-namespaces

- setuptools, History, v82.0.0 (2026-02-08): "`pkg_resources` has been removed from Setuptools. Most
  common uses of `pkg_resources` have been superseded by the `importlib.resources` and
  `importlib.metadata` projects. Projects and environments relying on `pkg_resources` for namespace
  packages or other behavior should depend on older versions of setuptools."
- PEP 420: "Namespace packages have no `__init__.py` module." That the answer to a `declare_namespace`
  is a package without one is my reading of it; the setuptools page on namespace packages was not
  retrieved.

## flag-indirect-use

- Package Discovery and Resource Access using pkg_resources: "Deprecated since version v67.5.0:
  `pkg_resources` issued official deprecation warnings as early as setuptools v67.5.0. Removed in
  version v82.0.0". A string or a dynamic import of the module is read by shape, not followed.
- What's New In Python 3.12: "Do not pre-install setuptools in virtual environments created with
  venv. This means that distutils, setuptools, pkg_resources, and easy_install will no longer be
  available by default".

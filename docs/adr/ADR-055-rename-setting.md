# ADR-055: Rename a setting

## Status

Accepted.

## Decision

A library that keeps its module can move a module-level setting to another name, and a pack states
that with a `rename_setting` change. `openai.api_base = value` becomes `openai.base_url = value`,
which is the one setting of the `openai` pack (ADR-053) with an exact counterpart. The kind is the
seventh, and the registry of ADR-006 lists it.

### D1. The assignment is rewritten and every other use is refused

`settings` maps a legacy dotted attribute to the name it takes on the same module. A finding the
scan reports for it is rewritten only when it is the one target of a plain `Assign`, and the root
stays the name the file bound the module to (`oa.api_base = x` becomes `oa.base_url = x`). A read,
`+=`, `del`, a tuple or chained target, an annotated assignment and a loop or `with` target are
`attribute_removed`: the new release has no attribute under the old name, so a read raises and an
assignment that is kept sets nothing. `from openai import api_base` is a row no rule claims and so
reads `usage_unmapped`. Reading the setting is refused even in a file that also assigns it, because
the assignment no longer sets the name that is read. A file that already uses the new name is
`alias_collision`: its own write of it would lack the ending, and the two would set one setting.

The scan cannot tell a store from a load, so the pack lists the setting in `match.symbols` and in
no `flag_only` change, and the rule decides at fix time, as `rewrite_call` does for a result.

### D2. The value is held to what the new name demands

`value_ends_with` is one character the new setting needs its value to end with. The module client
joins a route onto `openai.base_url` as it stands, so `http://host/v1` sends to `/v1chat/completions`
and answers 404, where 0.28.1 built the address as `"%s%s" % (api_base, route)` with a route that
began with `/`. The rule therefore writes:

- a string literal lacking the character with it added (`"http://h/v1"` becomes `"http://h/v1/"`),
  and one that has it unchanged; a bytes literal is not one;
- any other value as `("%s" % (value,)).rstrip("/") + "/"`. That formats the value as 0.28.1's
  `"%s%s" % (api_base, route)` did, with exactly one separator, so the address is the one it formed
  for any value that formatted as a URL. A value that was no URL (`None`, `""`, `"/"`) fails at the
  first call on both sides, and the bare rename of `None` would not: it sends the call to
  `api.openai.com`. An unparenthesised tuple or `yield` is parenthesised.

The wrapper names no builtin, so a file that rebinds `str` (an assignment, a parameter, a match
capture, a walrus, an import) is rewritten like any other. It is a `%` format and not `str(...)` for
that reason, at the cost of a line a reader has to look at twice. The character is one visible ASCII
character that is neither a quote, a backslash nor a digit, so it ends a literal as written (a digit
would join an octal escape) and `rstrip`, which takes a set of characters, takes exactly one.

The address is formed once, at the assignment, where 0.28.1 formed it at each request: a value
object whose `str` changes afterwards is not followed. A base with leading whitespace worked on
0.28.1, where `requests` trims it, and fails on the new releases; both are limitations.

### D3. The rewrite is one statement

`Rewrites.set_statement` replaces the assignment, and the writer visits the replacement again as it
does for an expression statement, so a rewrite of another rule inside the value (a call, a string
key read) is applied inside the wrapper. The layout engine is not asked: a wrapped value can pass
the user's line width, which a formatter fixes.

### D4. What validation checks

The kind is for a module that keeps its name, so a pack with `match.shared` false is refused: a
module that moves is renamed by `rename_import`. Every setting is under `match.symbols`, so the rule
can fire. The new name is not under `match.symbols`, or the rewritten file would be a finding again.
No other change claims or refuses a setting this one renames. A setting is a dotted path, keeps no
name it already had, does not rename onto another key, and is not a keyword (`PlainName` now
refuses every keyword, which also closes it for the `symbol_map` of `rename_import`). Each refusal
has a negative pack.

### D5. What was measured

On 0.28.1 and on 1.109.1, 2.0.0, 2.54.0 and 3.0.0, against a local server: both settings are plain
module attributes read at each call, so assigning again moves the next call; neither release defines
the other's name; the old release sent `http://host/v1` and `http://host/v1/` to `/v1/chat/completions`
and `/v1//chat/completions`, and the new ones sent them to `/v1chat/completions` and
`/v1/chat/completions`. A `None`, an empty string and `"/"` fail on 0.28.1 and on the new ones
(`Invalid URL`, `UnsupportedProtocol`), the wrapped `None` among them, and a bare `None` reaches
`api.openai.com`. The `api_base` fixture prints the same on all five for an assignment from the
environment, one that already ends in a slash, a literal and a name, and a bare rename fails the
same check. `tests/packs/test_openai_facts.py` holds the new side's half.

**Rejected:** renaming alone. It is the edit that reads as obvious, and it sends every request to a
404 for the value that is the common case. **Rejected:** a literal-only rule. By GitHub code search
counts, about one assignment in four is a string literal and the rest read an environment variable,
a name or a setting, so a rule for literals would leave most of the files that set it. **Rejected:**
keeping `api_base` in `flag_only`. A person told to do by hand what the tool can do exactly keeps the
repository on the pack's list, because the pack writes nothing while any row of it is withheld.

## Consequences

- About one file in ten that calls `ChatCompletion.create` also sets `openai.api_base` (7.9 thousand
  of 78.6 thousand by GitHub code search), most to point at a local server or a gateway. They no
  longer hold the repository back by that line, and a repository that reads the setting still does.
- `OPENAI_API_BASE` is read by 0.28.1 and not by the new releases, which read `OPENAI_BASE_URL`.
  The rule does not see an environment variable set outside the code or written into
  `os.environ`; the pack's limitations say so. Nor does it see a write through `exec`,
  `globals()`, `sys.modules` or `setattr`.
- A setting whose new name differs in more than its spelling (`openai.proxy`, `ca_bundle_path`) is
  not this kind: they become an `http_client`, which is a client the file must build.
- The kind is for one real use. A second pack with a renamed module setting will say whether
  `value_ends_with` should become a list of conditions on the value.

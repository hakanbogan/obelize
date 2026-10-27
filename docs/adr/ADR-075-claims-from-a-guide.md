# ADR-075: Claims from a guide

## Status

Accepted.

## Decision

A pack made from two releases (ADR-063) finds what moved or went. It cannot find what a library's
authors say only in prose: "`copy()` is now `model_copy()`", "`validate_arguments` is now
`validate_call`". A migration guide holds such changes. `pack synth --guide` and `upgrade --guide`
let a model draft **claims** from a guide, and code decides which become part of the pack. The model
is never believed: its words are checked against the guide's text and the two releases' APIs, the
page is untrusted data, and nothing of any repository goes to the model. A claim is a report by
default and a rewrite only where the quote says in a known shape that the new name replaces the old
one, nothing in its lines takes that back, and the API diff supports it (D5).

### D1. The claim: a closed shape of seven fields and four kinds

`obelize.providers.claims.Claim` is `kind`, `legacy`, `new`, `keywords`, `before`, `after` and
`quote`, with no other field and a bound on each. `legacy` and `new` are dotted names starting with
the module compared. The kinds are the ones the checks can hold a claim to:

- `rename_symbol`: a function or class of the module is now spelled another way, in the same place.
- `rename_member`: a method of a class is now spelled another way, on the same class.
- `rewrite_pattern`: a call is written another way, as the two templates of ADR-069 say.
- `flag`: the guide says a name was removed or now takes or does something else; `keywords` are the
  keyword arguments that changed, so the report is about the calls that pass one (ADR-073).

A reply is read strictly: one JSON object with only a `claims` key, no key written twice, and at
most 60 claims, or it is refused whole and counted. Inside a good reply a claim that is not the shape
is counted as `malformed` and the rest are kept. Nothing is repaired. What is tolerated is exactly
this: white space around the object, or one code fence that is the whole reply. Words around the
object, a byte order mark, a second object and a key written twice are refused (`claims.read`; the
reader is its own, so what `propose` accepts is not changed). The replies kept from the real runs
were all a bare object or a whole-reply fence, so nothing looser was needed.

### D2. Reading a guide (`packtools/guide.py`)

A URL goes through `net.Fetcher` with the rules it has for the index: https (or http to this
machine), no credential, a redirect only to the same scheme, host and port, the environment's proxy,
a size and a time, the host printed first, and the cache. Three things are new in `Fetcher`:
`types`, the media types accepted (`text/html`, `application/xhtml+xml`, `text/plain`,
`text/markdown`; anything else is refused before the body is read and so never cached, and the
type is kept with the body so a cached page is judged by the type it came with), the host a refused
redirect pointed at, in the message, and a check of the length: an answer that declares a
`Content-Length` and ends short is an error and not a short page. An answer longer than it declares
cannot be seen, since the standard library reads only the declared length; that is decided, not
found, and the text is judged as it was read. With no length, or a chunked answer, the body is read
to its end within the size limit. The second matters at once: pydantic's guide at
`docs.pydantic.dev/latest/migration/` answers 301 to `pydantic.dev`, and the message now says so
instead of an HTTP status. The brief this was built from named the old address; the address is the
user's to type, and nothing follows a redirect to a host they did not name.

A file is read as bytes, by its name, up to 4 MiB, and only if it is a regular file (a named pipe
or a device is refused by `stat` before anything is read, so it cannot wait for ever) with one of
the suffixes `.md`, `.markdown`, `.txt`, `.rst`, `.html` or `.htm`; any other, such as `.env` or
a file with no suffix, is `unsupported_type`. Only the name is ever recorded, never the path, and a
query or fragment of an address is dropped before it is recorded or sent, in the offline message too.
Whether a page is HTML is decided by the media type it was served with, or the suffix of a file,
and never by what its first bytes look like. HTML becomes lines with `html.parser`: `script`, `style`, `noscript`, `svg`, `template`, `head`, `nav`, `footer`,
`button`, `select`, `form` and `iframe` are dropped with what they hold, a heading, a list item and a
table cell say so, a link keeps its text, and `pre` is kept with its line breaks between fences
(longer than any run of backticks inside). Markdown and plain text pass through with their line ends
made one; every run of characters that do not print (control characters, the marks that reverse
a line, a zero-width space) becomes one space, so two words are not glued into a name that is in
neither. `html.parser` does its work on a construct that is never closed in a time that grows with
the square of the size, so the page is fed in slices of 16 KiB under a time limit (2 seconds and 4
more for each MiB, 20 at most), and a page that leaves more than 16 KiB open at once is refused. The
refusals are a closed list: `unsupported_type`, `not_text` (NUL, or not UTF-8), `too_large` (4 MiB),
`too_long` (400,000 characters of text), `unparsable` (the parse took too long or never closed),
`empty` and `unreadable`. A guide over the limit is refused and not cut: no claim rests on a part
nobody was told was missing.

The text is cut in parts of at most 20,000 characters (about 5,000 tokens) at line ends and never
inside a fenced block that fits a part; a block, or a fence never closed, that is longer is cut at
line ends (and a line over the limit at a space), so a part cannot be bigger than the limit. The cache key is the one `Fetcher` has
(the release of obelize and the address). The sha256 the pack records is of the **text the model was
given**, which also names the pack: the id of a pack made with guides ends with `-with-` and twelve
characters of the digest of those hashes, so another guide, or another version of the page, is
another pack, and `upgrade` keeps and finds it as it does a pack for the names a repository uses.

### D3. The model: the same adapters, a second answer type, and consent in the configuration

`ModelProvider` answers about a place in a file with a proposal. A second answer exists beside it,
`TextModel.complete(system, user) -> Completion`: any question, the words back, the tokens counted.
`OpenAICompat` and `ClaudeCode` implement it with the code `propose` runs on, so the limits are the
same (no redirect and no proxy for the endpoint; for the agent every tool off, an empty directory, a
cleaned environment, no session, and refused if the program lacks the restrictions).

The model is the one in the user's own configuration: the endpoint in `model` if `provider` is not
`none`, else the agent in `agent`, as `fix` and `upgrade --agent` use them. A repository can set
neither. This is the consent: ADR-003 rule 5 is about writing a model's edit into a repository,
which this never does, and the user has chosen where text may go by setting the model up and by
typing `--guide`. With none set up, the option is skipped with one line before anything is read or
sent, and the pack is made from the two releases alone, never an error that stops the API-diff pack.
`--offline` skips it the same way, with the line "offline: the guide was not read or sent", since
asking either kind of model is reaching a host (an endpoint, or the login of the agent) that
`--offline` promises not to; only `--guide-replay` goes on, which asks no one.
`--guide-replay` takes the answers from the `guide.json` of an earlier run (by the hash of each
guide, and the same number of parts), asks no one, and makes the pack with the day that run read the
guide (`retrieved_at` in the record), so the pack is the same on any day. The folder the pack goes in
is checked before the model is asked. `upgrade` decides the pack first: a known pack is used and the
line says the guide is not used, and the guide is read, and a model asked, only if a pack is to be
made.

The question is a fixed system prompt that says the text is data and shows the closed shape, and a
user message of five facts (the library, the two releases, the module, the address or file name)
and the text between two markers, which are removed from the text so it cannot end its own data.
Nothing from the repository's code is in it. `upgrade --guide` reads the repository's manifests, as
`upgrade` does, to know which distribution is moved and from which release, so the request holds the
name of that dependency and the release it is pinned to, and no other word from the repository.
The host or program and the number of parts are printed first. The model is asked once per part, in
order, and a part it fails is said and left empty. After two parts one after another that fail, or once the
guide has taken 30 minutes, the rest are not asked: they are counted, with the word `failures` or
`deadline`, in the line printed and in `guide.json`, and the pack is made from what was drafted.

### D4. The checks, in code, in this order

`guided.accept` holds each claim to these, and the first it fails is its one reason. The reasons are
a closed list (`guided.REASONS`, which PACK_SPEC names, tested): `quote_missing` (the quote, whitespace
aside and case kept, is not in the guide), `malformed` (the fields do not fit the kind), `legacy_unknown`
and `new_unknown` (not in the release, or not below the module), `quote_weak` (under 30 characters, or
not naming both names as words), `quote_reused` (more than three claims on one passage of the guide: quotes that overlap in the
guide are one, however each is cut), `keyword_unknown`
(not a parameter of the old name, unless it takes any keyword), `out_of_scope` (with `--used-by`),
`pattern_refused` (the templates are held to `RewritePatternParams` as a pack's are, and to being a
call of `legacy`, a method of a class for a receiver, and spelling only names beside it or in the
closed list of modules, and none the pack looks for, and no name with two underscores at both ends), `params_refused` (the change it would become
fails the pack's schema), `contradicts_diff` and `in_the_diff` (D5), `repeated` (an earlier claim is
about the name or one around it), `too_many` (a pack keeps 60), and `pack_failed` (D6). Every
rejection is counted, written with its detail to `guide.json` and printed as a count by reason.

### D5. What a claim becomes: a report, unless the diff supports a rewrite on its own

A kept claim is at least a `flag_only` change named `guide-N`, whose message is "The migration guide
says:" and the quote and whose suggestion is the replacement or the two templates. A name the diff
already reports with no more than its removal or deprecation (`view.plain`) already has such a
report, so a claim about it adds nothing unless it becomes a rewrite; it is a rewrite only where all
of these hold, and the model decides none of them:

- the quote says, in one of the shapes of a short closed table in `guided.py`, that the new name
  takes the place of the old one: a table line `old | new`, `old -> new` (or `=>` or an arrow
  sign), `old is now new`, `old is renamed to new`, `old is replaced by new`, `old becomes new`
  and the forms of those, or `use new instead of old` (`in place of`). Only quote marks,
  backticks, an at sign, brackets and the brackets of a call stand beside a name, the old name
  comes first except in the `use` shape, and nothing stands between a name and the words;
- the lines of the guide the quote touches, with the lines beside them that run into the same
  sentence, hold none of the words that limit or take a replacement back (`not`, `no`, `never`,
  `without`, `different`, `unlike`, `but`, `however`, `rather`, `except`, `unless`, `only`,
  `although`, `though`, `whereas`, `nor`, `neither`, `cannot`, `n't` and a few forms of those), so
  that "old is now new, but not for lists" and "do not use new in place of old" are reports. The
  list is a heuristic and errs towards the report;
- the name is one the pack reports only because the library removed or deprecated it, so the
  claim replaces that report and not a better one;
- the new name is in the new release and is not itself deprecated, and is written as the old one
  was: the marks `async`, `staticmethod`, `classmethod`, `property` and `cached` that the worker
  reads from the source are the same on both, since a function that became a coroutine or a static
  method is not called as before;
- for `rename_symbol`: in the same place with the same kind, a function whose signature takes every
  call of the old one (`accepts`) has its calls rewritten too, a class or another signature only its
  references; for `rename_member`: a method of the same class, with the keywords the new one takes
  where it takes fewer (`takes`), and none where they would not move; for `rewrite_pattern`:
  `after` spells the new name (as a word, so a pattern cannot be made to write another), every call
  it writes resolves (to a name, to a method of a class it builds or to a method of the receiver's
  class that the new release has, and not to something that is only inherited or on a value the
  pattern does not name), has the marks the old name had, and is one the new release's signature
  takes; a call that cannot be resolved is a refusal and not a pass.

A claim's own example passing its own pattern shows nothing, and is not looked at. A claim about a
name the diff already renames, moves or reports is dropped (`in_the_diff`), as is one that does not
reach a rewrite (the report the diff already makes stays), one that pairs it with another name than
the diff does is `contradicts_diff`, and a claim about a name the diff left alone or could not read
(`unseen`) is a report. What a page can reach is therefore this: a report that quotes it, or a
rewrite of a name the library removed or deprecated and the page says in a known shape is replaced
by a name the library has, in the same marks, with nothing said against it in its sentence. The one
question this cannot settle, that the new call means what the old one did, is the repository's
tests', as for every pack made from two releases; the limitations of such a pack say so. A sentence
that says "now" of two names, in the shape and with no limiting word, can still be false or
misleading; that is open (KNOWN_ISSUES.md, "Migration guides").

The pairs the API diff itself makes (a name moved, renamed or deprecated for another) are not held
to the marks: `synth` pairs them as before. Measured with the marks the worker now records, none of
the 247 pairs on the four frames (pydantic 1.10.26 to 2.12.5, SQLAlchemy 1.4.54 to 2.0.55, urllib3
1.26.20 to 2.8.0, pandas 2.3.3 to 3.1.0) joins names with different marks, so the hole is open and
costs nothing there.

### D6. Where it lands, and what the pack records

Accepted claims enter `_Plan.build` as ordinary entries of its tables, so its own rules about two
names landing on one, a new name that is a legacy one and a class above a member apply unchanged, and
`pack test` and every step after it see an ordinary pack. Each is its own change (`guide-rename-N`,
`guide-member-N`, `guide-pattern-N`, `guide-N`) with `citation` the address and the quote, and the
pack's `source` stays `api_diff`. A change also carries its own `source` (`PackSource`, now allowed
on any change) when the guide has an https address a pack may cite: `official_guide` when the
guide's host is the host of an address the distribution lists for itself on the index (`Homepage`,
`Documentation` and the rest) and its path is below that address's path, `guide` otherwise, a new
member of the closed `SourceType`. Host and path, so that `github.com/evil/repo` is not the vendor's
because `github.com/vendor/repo` is; no guess from a name. A file has no address and cites its name.
Neither type is bundled: `tests/packs/test_all_packs.py` holds every change of every bundled pack to
the two that review admits. `SOURCES.md` gains a table of the guides with the hash and whether each
is the vendor's, and `pack test` checks that a change's own source is named there.

If the pack made with the claims fails its own checks, it is made without them and every claim it
kept is counted as `pack_failed`, in the counts and in the record of each claim: a guide never blocks
the API-diff pack. That pack is made under the id of a pack made with no guide, since it holds
nothing from the guide, and is not presented as one made with it (`upgrade` finds it as it finds any
pack of those releases; a folder that exists is not written into). `guide.json` beside the pack holds
the day the guide was read, the provider, the model, the tokens, the counts, where it stopped asking
if it did, the answers and what became of each claim, and, when the pack was made without the
claims, says so in the id it names.

## Consequences

- Run on pydantic 1.10.26 to 2.12.5 with its migration guide and the user's `claude`, three parts
  went in about 21,000 tokens and the model drafted 47 claims in about 8,000 (41 in a run before):
  31 were kept (30 reports and one rewrite, `BaseModel.copy` to `model_copy`, which the diff supports
  and which leaves a call that passes `include` or `exclude` to a person), 10 were `in_the_diff`, 5
  had a quote too short to carry a claim and one named a method pydantic 1 does not have. A first
  prompt returned 13 claims from the same guide, so recall is the model's, and the prompt asks for
  every change and a claim for each table row. `--guide-replay` made the same pack again, byte for
  byte, with no model set up. The guide is at `pydantic.dev` now, and the project lists
  `docs.pydantic.dev`, so its changes are `guide` and not `official_guide`.
- After the review of the first version (a page that says a name "is not a replacement" or that the
  new one is `async` could still be made a rewrite, since the quote was never read for what it
  says), the recorded answers of that run were fed back through the changed code, with no model:
  the same 47 claims, the same 31 kept (one rewrite, 30 reports) and the same rejections. None of
  the 31 lost its status: the one rewrite, `BaseModel.copy` to `model_copy`, is a line of the
  guide's table, `copy() | model_copy()`, which is the first shape, with no limiting word in its
  line; the 10 `in_the_diff` were that before the change. So the checks added cost this guide
  nothing, and they are there for a page that does not tell the truth.
- Nothing of a repository's code can reach the model through this. A page can reach a report the
  person reads, with the page's own words, and a rewrite of a name the library removed or deprecated
  where its sentence says in a known shape that a name the library has takes its place, with the
  same marks and no limiting word; D5 has the whole list. What it can still do is make a model say
  something true to the page and misleading, or write that sentence of a name for which it is
  false; that is open (KNOWN_ISSUES.md, "Migration guides").
- `Fetcher.get` takes `types`, `pattern` has `receiver` and `metavariable`, `apidiff.diff` has a
  public `takes`, and the schema gains `guide` and a `source` on every change: `pack.schema.json`
  changed with it. A pack without one reads as it did.
- Four modules: `packtools/guide.py` (reading), `packtools/guided.py` (drafting and the checks),
  `providers/claims.py` (the question and the reading of the reply) and `Completion` beside the
  providers. `upgrade` asks for the guide once, after it has found that no pack is known and only
  then; `Obj` has the marks (`labels`) that the worker reads for a function.
- Not done: other agent programs, a guide for `pack new`, a guide that is a set of pages or is built
  in the browser, a measurement over many libraries, and a claim kind for what a function does.

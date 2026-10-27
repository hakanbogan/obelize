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
default and a rewrite only where the API diff supports it on its own (D5).

### D1. The claim: a closed shape of seven fields and four kinds

`obelize.providers.claims.Claim` is `kind`, `legacy`, `new`, `keywords`, `before`, `after` and
`quote`, with no other field and a bound on each. `legacy` and `new` are dotted names starting with
the module compared. The kinds are the ones the checks can hold a claim to:

- `rename_symbol`: a function or class of the module is now spelled another way, in the same place.
- `rename_member`: a method of a class is now spelled another way, on the same class.
- `rewrite_pattern`: a call is written another way, as the two templates of ADR-069 say.
- `flag`: the guide says a name was removed or now takes or does something else; `keywords` are the
  keyword arguments that changed, so the report is about the calls that pass one (ADR-073).

A reply is read strictly: one JSON object with only a `claims` key and at most 60 claims, or it is
refused whole and counted. Inside a good reply a claim that is not the shape is counted as
`malformed` and the rest are kept. Nothing is repaired. The one leniency is the fenced block around a
JSON object that every adapter already reads (`openai_compat._object`).

### D2. Reading a guide (`packtools/guide.py`)

A URL goes through `net.Fetcher` with the rules it has for the index: https (or http to this
machine), no credential, a redirect only within one host, the environment's proxy, a size and a time,
the host printed first, the cache, and `--offline` from the cache only. Two things are new in
`Fetcher`: `types`, the media types accepted (`text/html`, `application/xhtml+xml`, `text/plain`,
`text/markdown`; anything else is refused before the body is read and so never cached), and the
host a refused redirect pointed at, in the message. The second matters at once: pydantic's guide at
`docs.pydantic.dev/latest/migration/` answers 301 to `pydantic.dev`, and the message now says so
instead of an HTTP status. The brief this was built from named the old address; the address is the
user's to type, and nothing follows a redirect to a host they did not name.

A file is read as bytes, by its name, up to 4 MiB; only the name is ever recorded, never the path,
and a query or fragment of an address is dropped before it is recorded or sent. HTML becomes lines
with `html.parser`: `script`, `style`, `noscript`, `svg`, `template`, `head`, `nav`, `footer`,
`button`, `select`, `form` and `iframe` are dropped with what they hold, a heading, a list item and a
table cell say so, a link keeps its text, and `pre` is kept with its line breaks between fences
(longer than any run of backticks inside). Markdown and plain text pass through with their line ends
made one. The refusals are a closed list: `unsupported_type`, `not_text` (NUL, or not UTF-8),
`too_large` (4 MiB), `too_long` (400,000 characters of text), `empty` and `unreadable`. A guide over
the limit is refused and not cut: no claim rests on a part nobody was told was missing.

The text is cut in parts of at most 20,000 characters (about 5,000 tokens) at line ends and never
inside a fenced block, which stands alone if it is longer. The cache key is the one `Fetcher` has
(the release of obelize and the address). The sha256 the pack records is of the **text the model was
given**, which also names the pack: the id of a pack made with guides ends with `-with-` and eight
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
`--guide-replay` takes the answers from the `guide.json` of an earlier run (by the hash of each
guide, and the same number of parts) and asks no one.

The question is a fixed system prompt that says the text is data and shows the closed shape, and a
user message of five facts (the library, the two releases, the module, the address or file name)
and the text between two markers, which are removed from the text so it cannot end its own data.
Nothing from the repository is in it: `upgrade --guide` reads no file of the repository before the
question is asked, and the names are those of the index. The host or program and the number of parts
are printed first. The model is asked once per part, in order, and a part it fails is said and left
empty.

### D4. The checks, in code, in this order

`guided.accept` holds each claim to these, and the first it fails is its one reason. The reasons are
a closed list (`guided.REASONS`, which PACK_SPEC names, tested): `quote_missing` (the quote, whitespace
aside and case kept, is not in the guide), `malformed` (the fields do not fit the kind), `legacy_unknown`
and `new_unknown` (not in the release, or not below the module), `quote_weak` (under 30 characters, or
not naming both names as words), `quote_reused` (more than three claims on one quote), `keyword_unknown`
(not a parameter of the old name, unless it takes any keyword), `out_of_scope` (with `--used-by`),
`pattern_refused` (the templates are held to `RewritePatternParams` as a pack's are, and to being a
call of `legacy`, a method of a class for a receiver, and spelling only names beside it or in the
closed list of modules, and none the pack looks for), `params_refused` (the change it would become
fails the pack's schema), `contradicts_diff` and `in_the_diff` (D5), `repeated` (an earlier claim is
about the name or one around it), `too_many` (a pack keeps 60), and `pack_failed` (D6). Every
rejection is counted, written with its detail to `guide.json` and printed as a count by reason.

### D5. What a claim becomes: a report, unless the diff supports a rewrite on its own

A kept claim is at least a `flag_only` change named `guide-N`, whose message is "The migration guide
says:" and the quote and whose suggestion is the replacement or the two templates. It is a rewrite
instead only where the diff, which the claim cannot alter, shows all of these:

- the name is one the pack reports only because the library removed or deprecated it (`view.plain`),
  so the claim replaces that report and not a better one;
- the new name is in the new release and is not itself deprecated;
- for `rename_symbol`: in the same place with the same kind, a function whose signature takes every
  call of the old one (`accepts`) has its calls rewritten too, a class or another signature only its
  references; for `rename_member`: a method of the same class, with the keywords the new one takes
  where it takes fewer (`takes`), and none where they would not move; for `rewrite_pattern`: every
  call `after` writes that can be resolved (a name, a method of a class it builds, a method of the
  receiver's class) is one the new release's signature takes, and at least one can be.

A claim's own example passing its own pattern shows nothing, and is not looked at. A claim about a name the diff already renames, moves or reports is dropped (`in_the_diff`), one
that pairs it with another name than the diff does is `contradicts_diff`, and a claim about a name
the diff left alone or could not read (`unseen`) is a report. The one question the diff cannot
settle, that the new call means what the old one did, is the repository's tests', as for every pack
made from two releases; the limitations of such a pack say so.

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
kept is counted as `pack_failed`: a guide never blocks the API-diff pack. `guide.json` beside the
pack holds the provider, the model, the tokens, the counts, the answers and what became of each claim.

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
- Nothing of a repository can reach the model through this, and a page can reach only a report
  the person reads, with the page's own words. What it can still do is make a model say something
  true to the page and misleading; that is open (KNOWN_ISSUES.md, "Migration guides").
- `Fetcher.get` takes `types`, `pattern` has `receiver` and `metavariable`, `apidiff.diff` has a
  public `takes`, and the schema gains `guide` and a `source` on every change: `pack.schema.json`
  changed with it. A pack without one reads as it did.
- Four modules: `packtools/guide.py` (reading), `packtools/guided.py` (drafting and the checks),
  `providers/claims.py` (the question and the reading of the reply) and `Completion` beside the
  providers. `upgrade` asks for the guide once, before the pack is made and only then.
- Not done: other agent programs, a guide for `pack new`, a guide that is a set of pages or is built
  in the browser, a measurement over many libraries, and a claim kind for what a function does.

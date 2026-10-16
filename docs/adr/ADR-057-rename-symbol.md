# ADR-057: Rename a symbol

## Status

Accepted.

## Decision

A library that keeps its package can move a name out of one of its submodules, and a pack states
that with a `rename_symbol` change. `openai.error.RateLimitError` becomes `openai.RateLimitError`,
and the three classes of `openai.error` that a local server shows to be raised for the same
responses on both sides are the ones the `openai` pack (ADR-053) renames. The kind is the eighth,
and the registry of ADR-006 lists it.

### D1. A class is renamed only where the same responses raise it

`symbols` maps a legacy dotted path in a submodule to the name it takes in the package above it, and
`now_caught_by` lists what the new class derives from and the old one did not. A pack lists a class
only when a handler for the old one runs for exactly the responses a handler for the new one does:
the old class is raised for a set of responses, and the new class, with its bases, is caught for the
same set. That is measured, not read off the guide, against a local server that answers 0.28.1 and
the new releases alike (`tests/packs/openai_legacy_check.py` for the old side, held in
`tests/packs/openai_legacy_surface.json`, and `tests/packs/test_openai_facts.py` for the new):

| Response | 0.27.0 and 0.28.1 | 1.109.1 and later |
|---|---|---|
| status 400, 404, 415 | `InvalidRequestError` | `BadRequestError`, `NotFoundError`, `APIStatusError` |
| status 401 | `AuthenticationError` | `AuthenticationError` |
| status 403 | `PermissionError` | `PermissionDeniedError` |
| status 429 | `RateLimitError` | `RateLimitError` |
| status 500 | `APIError` | `InternalServerError` |
| status 503 | `ServiceUnavailableError` | `InternalServerError` |
| an empty 200 body | `APIError` | `json.JSONDecodeError` |
| no API key | `AuthenticationError` | `OpenAIError` (up to 2.0), `TypeError` (from 2.54) |
| a read timeout | `Timeout` | `APITimeoutError` |
| a refused connection | `APIConnectionError` | `APIConnectionError` |

`RateLimitError`, `PermissionError` (as `PermissionDeniedError`) and `Timeout` (as `APITimeoutError`)
pass. `AuthenticationError` and `OpenAIError` do not: a missing key was an `AuthenticationError`, so
an `OpenAIError`, and is a bare `OpenAIError` or a `TypeError` now, which no `AuthenticationError`
handler catches and, for the `TypeError`, no `OpenAIError` handler either, and an empty 200 body was
an `APIError`, so an `OpenAIError`, and is a `json.JSONDecodeError`. `InvalidRequestError` is three
classes, `ServiceUnavailableError` is a part of one, and `APIError` and `APIConnectionError` are
bases that catch more. `TryAgain` was raised only for a call with a timeout argument, and
`InvalidAPIType` and `SignatureVerificationError` have no counterpart. Each of them stays in a
`flag_only` change whose message says what it became, and `tests/packs/test_openai_facts.py` asserts
for each that no class of the new release is raised for exactly its responses, so the refusal stays
true when a release changes.

**Rejected:** renaming `OpenAIError` and `AuthenticationError` and listing the missing key as a
limitation. They are the classes most handlers name (eighteen of fifty-eight rows), and the pack
refuses the same thing elsewhere: a handler that stops running for a failure it handled is what
keeps `Image.create(response_format=...)` out of `rewrite_call`. **Rejected:** mapping a class to a
tuple of the new ones, which would add classes a handler never caught.

### D2. What is written

A reference loses the submodule, and a class that takes another name takes it:

- `openai.error.RateLimitError` is `openai.RateLimitError`, through whatever name the file bound the
  package to (`oa.error.PermissionError` is `oa.PermissionDeniedError`).
- `import openai.error` binds the package, so it becomes `import openai`, and
  `import openai.error as faults` becomes `import openai as faults`: the alias is kept and
  `faults.RateLimitError` needs no other change. A line of several statements becomes one line each.
- `from openai.error import RateLimitError as Limited` becomes
  `from openai import RateLimitError as Limited`. Without an alias a class that takes another name is
  renamed where the file reads it (`PermissionError` is `PermissionDeniedError`), unless the file
  already binds that name.

The rule claims the finding of a reference and of the import of a submodule it renames. The import
statement is replaced through the import plan (ADR-025) and a reference through `Rewrites.set`, so
the two are one pass with the other rules'. A reference the scan found is a chain or a bound name; a
string annotation is a mention only, which is no usage.

### D3. What is refused

No new bail code: each of these is a code the vocabulary has, with a wider row.

- `error_class_changed`: a class that is called, raised or derived from, since a new status class is
  built from `message`, the `response` and the `body` and a timeout from the `request`, where an old
  one took the message and the body, status and headers.
- `error_class_changed`: a handler ahead of a renamed class in the same `try` (an `except*` too)
  that names a class in `now_caught_by` (`openai.APIError`, which 0.28.1 has as a sibling and the new
  releases as the base of every status class) or one the rule cannot tell: a name bound in the file,
  a call, an attribute of `self`. A builtin, a name imported from another module and a class the same
  change renames pass: the last is a sibling of the new class, and a name another of your modules
  re-exports from `openai` is not seen, as for every rule of a shared module.
- `attribute_removed`: an `except` clause that reads an attribute of its bound name, in the body or
  any function in it. The new classes have `status_code`, `body` and `message` where the old had
  `http_status`, `json_body` and `user_message`, and an attribute of one name may mean another.
  Passing the exception on (`print(error)`, `raise Wrapper(error) from error`) reads nothing.
- `from_import_unmigrated_symbol`: a `from openai.error import` that names a class the change does not
  rename, `from openai import error`, and an import in a one-line suite.
- `alias_collision`: a class that takes another name where the file binds that name.

### D4. What the scan reports

`openai.error` leaves the symbols a `flag_only` change refuses, and each class the change does not
rename is listed by name in a `flag_only` change whose message says what it became. A rename
under a refused prefix would never fire, since the scan grades a refused symbol first, so a pack
that has one is refused. The import of the submodule is an eligible row of the new change; a use of
the module that is no listed class (`errors = openai.error`, `openai.error.helper`) is an eligible
row nothing claims, which withholds the file as `usage_unmapped`, as an unlisted use did.

### D5. What validation checks

The kind is for a package that keeps its name, so a pack with `match.shared` false is refused: a
package that moves is renamed by `rename_import`. Every symbol is a path of three names or more and
under `match.symbols`, none is named by two changes, renamed onto a keyword or onto one the pack
lists as legacy, and no two land on one name. `now_caught_by` is sorted and de-duplicated. Each
refusal has a negative pack.

### D6. What was not measured, and is a limitation

- The text of an exception changes: `str(error)` was the API's message, with `Request <id>: ` before
  it for a response that had one, and is `Error code: <status> - <body>` now. A handler that parses
  it sees the message inside the body.
- A response that is no API error (a proxy's HTML page, an object with no `error` key) was an
  `APIError` on 0.28.1 whatever its status, and is the class of its status on the new releases, so a
  handler for a renamed class catches a response it did not.
- A handler for `openai.APIError`, which both sides define and the pack does not report, catches
  every status class on the new releases and caught the 5xx and malformed responses alone on 0.28.1.
  The rule reads the handlers of one `try`; one in a caller, or reached by a name, is not seen.
- A mock given the class, not an instance (`Mock(side_effect=openai.error.RateLimitError)`), raises
  it with no arguments, which the new class refuses with a `TypeError`: a test fails loudly where
  0.28.1's passed. `getattr(error, "http_status")` and `vars(error)` on a bound name read an
  attribute the rule does not see.
- `import openai` beside `import openai.error` is a name bound by two imports, which the scan reads
  as `conditional_binding` and withholds, as it did before the rename.

## Consequences

- A handler or a decorator argument for one of three classes no longer holds the repository back by
  that line. A repository that names `OpenAIError`, `AuthenticationError`, `InvalidRequestError` or
  `APIError` still does, with a message that names what each became.
- The kind is for one real use. A second pack with a package that moved its classes will say whether
  `now_caught_by` should be a table per class.

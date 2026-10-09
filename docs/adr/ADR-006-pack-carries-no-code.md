# ADR-006: Pack carries no code

## Status

Accepted; amended by ADR-050, ADR-053 and ADR-055.

## Decision

**Packs are declarative YAML. All behaviour lives in Python.** A pack's
`changes[]` entries select a rule **`kind`** from the registry in
`src/obelize/transforms/registry.py` and supply parameters validated by that
kind's pydantic `Params` model (a discriminated union on `kind`). A pack never
carries code, evaluated templates, shell strings or regular expressions that
drive behaviour; symbol fields accept a qualified-symbol pattern only. A pack is untrusted data (threat model boundary B1), and anything
evaluated in it would be code execution inside a tool that edits the user's tree.

**The v0 kind registry, in full:**

| kind | What it does |
|---|---|
| `rename_import` | rewrite import statements and module paths, with alias and submodule mapping |
| `configure_to_client` | turn a module-level `configure(...)` into a client construction |
| `generative_model_calls` | the model constructor and its methods, including config and safety merging |
| `rewrite_call` | a single legacy call to a new dotted call under the client, or under the module the author wrote, with argument mapping and the reads of its result that carry |
| `rename_setting` | the plain assignment of a shared module's setting under the name the new release gives it, with the value ending as that name demands |
| `flag_only` | report a surface, never rewrite it |
| `manifest_dependency` | rewrite or report a dependency declaration in a manifest |

Adding a kind is a code change in this repository, with tests and review. It is
not something a pack can do.

**Fail-closed is a rule, not a preference.** An ambiguous or unsupported pattern
becomes **`needs_review`** or **`unsupported`** with a closed-vocabulary reason
code and a suggested snippet, never a guessed fix. A rule that cannot prove what it
needs raises `BailError(reason)`; that group is demoted and the file's other
groups still apply.

### Schema additions

- **`pack_version`**: semver, independent of the tool's version.
- **`changes[].citation`**: the section of the official migration guide, or of
  the API reference where the guide is silent, that justifies the change. A rule
  with no citable source does not ship.
- **`changes[].fixtures`**: at least one positive and one negative fixture per
  change; `tests/packs/test_all_packs.py` checks them against their answer keys
  and that applying twice equals applying once.
- **`source.sha256`**: the optional hash of the retrieved guide page, beside
  `source.url` and `retrieved_at`. `SOURCES.md` holds the URL, date, hash and a
  short quotation, never the full page.

Validation is closed-world (`extra="forbid"`). A pack is rejected for an unknown
field, a `from`/`to` range that is not PEP 440 or contradicts itself, a duplicate
change id, a missing `source.url` or `retrieved_at`,
`language != python` or an empty `match.imports`; a negative pack under
`tests/packs/_negative/` proves each rejection, a smuggled shell string included.

### The closed-world binding rule

A method call is rewritten only when its receiver is bound in a closed world
obelize can see:

| Binding kind | Pattern | v0 |
|---|---|---|
| `name` | `model = genai.GenerativeModel(...)` -- single Name target, single assignment, uses in the same scope, assignment before use | automatic |
| `module_const` | module-level assignment, used in functions or methods of the same file, never reassigned in an inner scope | automatic |
| `self_attr` | `self.model = genai.GenerativeModel(...)` in `__init__` (first parameter `self`, direct expression), used as `self.model.<m>(...)` in methods of the same class | automatic, with the closed-world guard |
| `class_attr` | assignment in a class body | `needs_review` (`class_attr_binding`) |

Nothing else may reach the binding: every write to an instance attribute counts
toward `multiple_assignments`, and a model another module imports or reads is
`model_object_read_elsewhere`.

**The escape rule.** An **escape** is any reference to the bound name that is not
the receiver of a supported method (`generate_content`, `generate_content_async`,
`count_tokens`, `start_chat`): an argument, a return value, a store elsewhere, an
attribute read such as `model.model_name`, `del`, `global`, a tuple target, a
walrus, an augmented or second assignment, a module constant listed in
`__all__`, or an attribute reached through anything but the class's own first
parameter.

With an escape the **binding group is atomic**: the constructor *and* every use
become `needs_review` (`model_object_escapes` or `multiple_assignments`), and a
reference the rewrite would leave behind refuses the group at the rule, because a
half-rewritten group breaks working code. Chat objects use the same mechanism for
`send_message` and `send_message_async`.

## Consequences

- A hostile pack cannot execute anything; a bad rewrite it describes must still
  survive the rule, `parse` plus `compile` and the user's tests.
- The pack sha256 is recorded in the run evidence; a remote pack would need
  signing and a trust policy.
- `verification.suggestions` in a pack is display-only (ADR-007).

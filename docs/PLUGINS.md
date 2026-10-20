# Writing a plugin

A plugin is a rule that obelize does not ship: a distribution you install provides it, and a
[pack](PACK_SPEC.md) can name it. Use one when a change is too particular for the kinds a pack can
say, and keep to a pack when it is not: a plugin is **code that runs in obelize's process with your
rights**, and it sees every file the run reads. obelize does not contain it.

## Allow it

Nothing is imported until you allow the distribution and the entry point it provides, in your own
`~/.config/obelize/config.yml`:

```yaml
plugins:
  - distribution: acme-fixer
    name: fixer
```

A repository's `.obelize.yml` may not set `plugins`, and a bundled pack never asks for one. A pack
that requires a plugin you have not allowed stops before any file is read, with exit code `7`.

## Write it

The distribution registers an object in the entry point group `obelize.kinds`:

```toml
[project.entry-points."obelize.kinds"]
fixer = "acme_fixer:KIND"
```

The object has `api = 1`, a `params` model and a `rule` method:

```python
import libcst as cst

from obelize.plugin import API, Edit, Params, Tree


class Settings(Params):
    word: str


class Rewriter:
    kind = "plugin"
    consumes = frozenset()
    client_readers = frozenset()

    def __init__(self, change_id, word):
        self.id, self.word = change_id, word

    def claims(self, finding):
        return finding.kind == "call" and finding.symbol == "acme.old"

    def apply(self, context):
        tree = Tree(context)
        done = []
        for finding in context.plan.findings:
            if finding.scan_status == "eligible" and self.claims(finding):
                call = tree.call((finding.line, finding.column))
                renamed = call.func.with_changes(attr=cst.Name(self.word))
                context.rewrites.set(call, call.with_changes(func=renamed))
                done.append(
                    Edit(path=context.path, line=finding.line, status="auto", rule_id=self.id)
                )
        return tuple(done)


class Kind:
    api = API
    params = Settings

    def rule(self, change_id, params):
        return Rewriter(change_id, params.word)


KIND = Kind()
```

`claims` says which findings the rule rewrites: the scan finds a name when the pack lists it in
`match.symbols`, and a rule rewrites what it claims. `apply` records the edits in
`context.rewrites` and returns what it did. A rule that cannot rewrite a finding returns an
`Edit` with status `needs_review` and a reason (raise `BailError` with a code from
[the scan vocabulary](SCAN_VOCABULARY.md#4-bail-codes-editreason) in a helper that decides one);
its file is then left as it was. What a rule writes goes through the same checks as any rule's:
it must parse and bind no name the file did not.

`obelize.plugin` is the interface (`Params`, `Rule`, `RuleContext`, `Edit`, `Finding`, `Tree`,
`BailError` and `API`). Rules read and write libcst nodes, so the range of libcst that obelize
installs is part of it. Names in `obelize.plugin` do not change in 0.x without a line in the
[changelog](../CHANGELOG.md).

## Use it from a pack

```yaml
requires_plugins:
  - name: fixer
    version: ">=1,<2"
changes:
  - id: fix
    kind: plugin
    plugin: fixer
    citation: "Acme notes, 'Renamed calls'"
    params:
      word: new_call
    fixtures:
      - fixtures/negative/already_new.py
      - fixtures/positive/old.before.py
```

`requires_plugins` names the entry point and the releases of its distribution the pack was written
against; each change that uses a plugin names it, and the two lists must agree. The `params` are read
by the plugin's own model, when it is loaded, so a mistyped key stops the run.

## What a run records

The run folder records each plugin a pack required: its entry point, distribution, release and the
sha256 of the distribution's `RECORD`, which lists a hash for each file it installed
([the run folder](RUN_FOLDER.md)). `obelize pack validate` reads a pack without loading its plugins,
and says so; `obelize pack test` loads them.

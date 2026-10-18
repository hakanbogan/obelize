# ADR-060: Rename a name in its own module

## Status

Accepted.

## Decision

`rename_symbol` gains a second shape. Until now it moved a class a submodule defined to the package
above it (`openai.error.RateLimitError` is `openai.RateLimitError`). A library whose new release
keeps a module and spells a function or class another way (`acme.kit.old_greet` is
`acme.kit.greet`) is the commonest breaking change after a module that moved, and no kind
expressed it, so a pack for it could only report every use.

### D1. `renamed` is a field of the same change

`renamed` maps a legacy dotted path of two names or more to the name it takes in that module. It sits
beside `symbols` in one change, because both are a rename of a name of a kept package and the
checks that bind them (a name is claimed once, lands clear of the legacy names, is not refused) are
the same. A name in both is refused, and so is a rename onto itself.

### D2. What changes where it is written

A reference to the old name, through the module or through an alias of it, takes the new name. On
a `from module import old` line the name changes and an alias on that line keeps its own name, so
uses of the alias need no edit; uses of the bound name change with it. The module's own import never
changes. A new name the file already binds is `alias_collision`, the code the other shape uses.

### D3. A call is the pack author's claim

A call of a moved error class is refused, because the new class is built from other arguments. A
function renamed in place usually takes the arguments it took, and only the author knows. `calls`
is `refused` by default, which keeps every existing pack as it was, and `allowed` states that
the names in this change take the arguments they took. A pack that is wrong about it is wrong for
the reason it cited, and the fixtures and the verification are where that shows.

### D4. Packs for the test suite

The three bundled packs use each kind in one way. `tests/packs/generic/` holds packs over invented
libraries that exercise a kind another way, and they are held to the same checks as a pack of your
own (`obelize pack test`), so a kind's other shapes are tested as a pack would use them.

## Consequences

The pack schema, `docs/PACK_SPEC.md` and the negative corpus describe and refuse the new fields.
Other generalisations a pack-less migration needs (a call that keeps its name, a `from` import of a
function, a keyword dropped because its value was the old default) are left to the release that
needs them.

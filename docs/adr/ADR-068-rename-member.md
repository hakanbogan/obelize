# ADR-068: Rename a member of a class

## Status

Accepted.

## Decision

A library that spells a method or an attribute of its class another way (`BaseModel.dict` is
`model_dump`) is the commonest breaking change that no kind could express. The names are
rarely written through the library: a program derives its own class from the library's and reads
the member off an instance of it, so a scan that looks for the library's names finds nothing to
change. A new kind, `rename_member`, renames the member where the scan can tell what the receiver
is.

### D1. The change names a class and its members

`members` maps a legacy dotted path of three names or more (module, class and member) to the name
the member takes on that class. The schema refuses a member that keeps its name, one renamed again,
two onto one name, a new name `match.symbols` lists as legacy, a member another change claims and a
member under a symbol a `flag_only` change refuses. The members are listed in `match.symbols`, since
they are also read through the library's own module (`acme.shapes.Shape.old_area(item)`), which the
scan already finds and the rule renames the same way.

Only the name changes. The pack asserts that the member takes the arguments it took, as `calls:
allowed` does for `rename_symbol` (ADR-060 D3); a member whose arguments change is `rewrite_call`'s.
There is no switch, because a rename that moved the arguments too is a different change.

### D2. A receiver is typed from what the file says

The scan types an expression where the file shows its class: a call of a class defined in the file
that derives, directly or through others, from a class the pack names; the class itself
(`Square.to_dict`); a name every assignment of which is one of these; `self` and `cls` in a method of
one (not a static method); a parameter or a variable annotated as one, including `Optional[X]`,
`X | None` and a string naming a class the file defines once. A name with an assignment that is none of
these is not typed, so `shape = Square(); shape = make()` is left alone.

A class name that an import binds is the class only if imports are all that bind it: a name something
else rebinds, in a branch or a `try`, is none. A name a `match` pattern binds is none, and so is
`*items: Square`, which is a tuple. Typing is by class and never by the member's name: `response.json()` is not `BaseModel.json`
because both are called `json`. A receiver nothing types is not reported and not guessed at, so a
pack lists it among its `limitations`; a pack must already say what it does not handle. This differs
from the receivers of `generative_model_calls`, which hold the whole object (a constructor, every use
and its escapes) because the new SDK replaces the object; here the object stays and only a name on it
changes, so what else the program does with the value does not matter.

### D3. A member the repository defines is not the library's

If a class defines the member, by any statement and in any branch (a method, an assignment, an
annotated field, an import, a `for` target, a definition under an `if`), the new name would run
another function. The row is `member_overridden`, a new code of the binding rung, and the file stays
as it was like any other withheld file. It counts when a class between the receiver's class and the
library's defines it, when a class of the repository that sits in the base list beside the library's
does (a mixin of this file or of another, which can come first in the method resolution order), and
when a class *below* the receiver's class defines it: the receiver may be an instance of that class,
so the member is no more the library's wherever the repository derives a class that defines it. A
mixin the repository does not define, from another library, is not read.

### D4. The projection

`ScanSpec.member_classes` carries each class and its members. It is not `supported_methods`: that
table names the receivers a rewrite replaces, and it makes every method call of one a use of the
client. A spec with no member class reads as it did, so the digest of every pack that has none is
unchanged.

A new reason, `receiver_typed_by_class`, says how a receiver was known when it was a class, an
annotation, `self` or `cls`; a name bound to a call keeps `receiver_bound_same_scope` or
`receiver_bound_module_const`. A row is positioned at the member's own name, so that a call
(`Square().old_area()`) and the receiver it starts with are not one position.

### D5. A class of another file

A program rarely defines its model and uses it in one file. Before any file is analysed, the scan
reads the class headers of every Python file with a regular expression, finds the names whose bases
may lead to a class a pack names (by what the bases spell, and what an import calls them with `as`),
and reads the files that define one with `ast`, which is far cheaper than the analysis. The result,
an index of the derived classes with what each defines, goes to every worker beside the pack's
projection. It is not part of `ScanSpec`, whose digest is a property of the pack.

A class is found by the name an import gives it and the module the import comes from: the module
must run through the dotted path of the file that defines the class, so that a package that
re-exports it and a relative import both reach it. A name the repository defines more than once is
a class only if every definition the import could mean derives from the same library class; one that
derives from nothing, or from another, makes it none. A module that binds the name any other way as
well (a second class, an assignment, a definition, a `del`) gives no class of it. A file that names a derived class is parsed
whether or not it names the library, so a scan may parse more files than it did. The index reads the
module level of each file: a class defined in a function, or made by `type(...)`, is not found, nor is
one defined in a file the walk does not select. This changes ADR-005's "no `FullRepoManager`" only
by this one input, and no pack without member classes pays for it.

### D6. A call the new spelling does not take

A method often takes fewer keywords than the one it replaces (`dict(skip_defaults=...)` is
`model_dump(...)`, which has no `skip_defaults`). `takes` names, for such a member, the keywords the
new spelling takes. A call that passes another keyword, or a `*` or `**` argument, is
`unsupported_kwarg` and left for a person; a member read that is not a call, and a member with no
entry, are renamed whatever it is called with. Calls that pass nothing the new spelling lacks are
the ones a rename moves safely, and are most of them.

### D7. What `pack synth` writes

A class member that the library deprecated, or removed after saying so, with a message that says no
more than which method to use (`use `model_dump` instead`), is a `rename_member` when a call of the
old one can move to the new: its positional parameters keep their places, nothing is newly required,
and every parameter that went was optional, a keyword and not a splat (then `takes` is written).
A message that adds anything (`set `from_attributes=True` and use `model_validate``, `see the
docstring for `include``) names a step the rename would not take, and the member is flagged with the
library's words as before, as is a member another method's rename would land on. What the pack
flags on a class it renames members of is also read off a typed receiver, so a method that stays
flagged (`copy`) holds the file as it does when it is read through the library's module.

### D8. A pack for the test suite

`tests/packs/generic/acme/shapes-1-to-2` is an invented library that derives classes the way
programs do. It uses the kind in every receiver shape and in the refused one, and is held to the
checks `obelize pack test` runs. No bundled pack needs the kind, so the test that every kind is used
reads the generic packs as well.

## Consequences

The pack schema, `docs/PACK_SPEC.md`, `docs/SCAN_VOCABULARY.md`, the JSON schemas and the negative
corpus describe and refuse the new fields.

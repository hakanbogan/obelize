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

Typing is by class and never by the member's name: `response.json()` is not `BaseModel.json`
because both are called `json`. A receiver nothing types is not reported and not guessed at, so a
pack lists it among its `limitations`; a pack must already say what it does not handle. This differs
from the receivers of `generative_model_calls`, which hold the whole object (a constructor, every use
and its escapes) because the new SDK replaces the object; here the object stays and only a name on it
changes, so what else the program does with the value does not matter.

### D3. A member the repository defines is not the library's

If a class of the file defines the member (a method, an assignment or an annotated field), or a
class between it and the library's class does, the new name would run another function. The row is
`member_overridden`, a new code of the binding rung, and the file stays as it was like any other
withheld file. A class of the file that does not derive from the library's but sits in a base list
beside it counts too, since it can come first in the method resolution order.

### D4. The projection

`ScanSpec.member_classes` carries each class and its members. It is not `supported_methods`: that
table names the receivers a rewrite replaces, and it makes every method call of one a use of the
client. A spec with no member class reads as it did, so the digest of every pack that has none is
unchanged.

A new reason, `receiver_typed_by_class`, says how a receiver was known when it was a class, an
annotation, `self` or `cls`; a name bound to a call keeps `receiver_bound_same_scope` or
`receiver_bound_module_const`. A row is positioned at the member's own name, so that a call
(`Square().old_area()`) and the receiver it starts with are not one position.

### D5. A pack for the test suite

`tests/packs/generic/acme/shapes-1-to-2` is an invented library that derives classes the way
programs do. It uses the kind in every receiver shape and in the refused one, and is held to the
checks `obelize pack test` runs. No bundled pack needs the kind, so the test that every kind is used
reads the generic packs as well.

## Consequences

The pack schema, `docs/PACK_SPEC.md`, `docs/SCAN_VOCABULARY.md`, the JSON schemas and the negative
corpus describe and refuse the new fields. A class defined in another file of the repository is not
found by this decision alone.

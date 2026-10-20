# Sources for `acme/shapes-1-to-2`

An invented library, for the test suite. One section per `changes[].id`.

## The retrieved page

| Source | URL | `retrieved_at` |
|---|---|---|
| The pack's `source` | <https://example.invalid/acme-shapes/migrating> | 2026-10-20 |

---

## rename-members

acme-shapes 2 renamed `Shape.old_area` to `Shape.area` and `Shape.to_dict` to `Shape.as_dict`,
with the arguments they took, except that `to_dict` takes only `indent` of the keywords the old
one did.

## flag-retired

acme-shapes 2 dropped `Shape.retired`.

## dependency-line

acme-shapes 2 is the same distribution, so the major version is the migration.

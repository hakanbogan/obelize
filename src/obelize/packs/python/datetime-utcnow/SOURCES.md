# Sources for `python/datetime-utcnow`

One section per `changes[].id`, in pack order (held equal to the pack by
`tests/packs/test_all_packs.py`; rules in `docs/PACK_SPEC.md`, *Source
provenance*).

## The retrieved pages

| Source | URL | `retrieved_at` | sha256 of the page as retrieved |
|---|---|---|---|
| Python documentation, datetime (the pack's `source`) | <https://docs.python.org/3/library/datetime.html> | 2026-10-24 | `4fb1fd805b875839309d39382da562f179ae425ef66933a24fcf96731bc99fda` |
| What's New In Python 3.12 | <https://docs.python.org/3/whatsnew/3.12.html> | 2026-10-24 | `bc1ab5402bf32240db0da103113feced72ab8e1dbd94bf368d161c1eb0874abc` |

The hash is of the page body as served. obelize never requests the URL.

## The measurement, and why it outranks the page

"Measured" means run on CPython 3.9.6, 3.10.14, 3.11.11, 3.12.9, 3.13.5, 3.14.7 and 3.15.0rc2 on
macOS, with no library but the standard one: 20,000 seeded timestamps between -1e10 and 1e11 and 19
edge values (zero, one, negative and fractional values, the ends of the supported range, 5e-7,
`2**31`, `2**32`, 1e20, nan and infinity) each went through `utcfromtimestamp(t)` and through
`fromtimestamp(t, timezone.utc).replace(tzinfo=None)`. The value, the class of the result and the
exception for what the platform cannot convert were the same on all seven, and the result is naive
(`tzinfo` is `None`). `tests/packs/test_runtime_facts.py` repeats it with 2,000 timestamps on the
Python that runs the tests, and CI runs that file on every Python from 3.12 to 3.15. The page says
the same of the timestamp ("To get an aware datetime object, call `fromtimestamp()`:
`datetime.fromtimestamp(timestamp, timezone.utc)`") and the measurement is what makes
`.replace(tzinfo=None)` the same value as the old call, not the aware one the page recommends.

Measured on the same Pythons: a subclass of `datetime` is a subclass from both spellings
(`Moment.utcnow()` and `Moment.now(timezone.utc).replace(tzinfo=None)`), and `utcnow()` and the new
spelling read the same clock within a second. Both calls exist on all seven, and warn with
`DeprecationWarning` from 3.12 on, which the pack's `from.python` records.

---

## utcnow

- Python documentation, datetime: "`classmethod datetime.utcnow()` Return the current UTC date and
  time, with `tzinfo` `None`. This is like `now()`, but returns the current UTC date and time, as a
  naive `datetime` object. An aware current UTC datetime can be obtained by calling
  `datetime.now(timezone.utc)`." And: "Deprecated since version 3.12: Use `datetime.now()` with
  UTC instead."
- What's New In Python 3.12: "`datetime.datetime`'s `utcnow()` and `utcfromtimestamp()` are
  deprecated and will be removed in a future version. Instead, use timezone-aware objects to
  represent datetimes in UTC: respectively, call `now()` and `fromtimestamp()` with the `tz`
  parameter set to `datetime.UTC`."
- Measured: `datetime.UTC` (3.11) is `datetime.timezone.utc` (3.2: "class `datetime.timezone` ... Added
  in version 3.2"), so the pack writes the older spelling, which every Python the gate admits has.
- Why the zone is dropped: the documentation calls `now(timezone.utc)` "aware", and measured, an
  aware and a naive value cannot be subtracted or ordered (`TypeError`), so `now(timezone.utc)` alone
  would change what a program that compares the result with another naive value does. The pack keeps
  the value the call gave; moving to aware values is a choice for a person.
- Not measured: a program that patches `datetime` in a module of its own (the limitation says so),
  Windows, and any Python below 3.9.

## utcfromtimestamp

- Python documentation, datetime: "`classmethod datetime.utcfromtimestamp(timestamp)` Return the
  UTC `datetime` corresponding to the POSIX timestamp, with `tzinfo` `None`. (The resulting object
  is naive.) [...] To get an aware `datetime` object, call `fromtimestamp()`: `datetime.fromtimestamp(timestamp,
  timezone.utc)`". And: "Deprecated since version 3.12: Use `datetime.fromtimestamp()` with UTC
  instead."
- Measured (see above): the same value, class and error as `fromtimestamp(timestamp,
  timezone.utc).replace(tzinfo=None)` for every timestamp tried, including the ones the platform
  refuses (`OverflowError`, `OSError`, `ValueError` alike). The page's "Changed in version 3.15:
  Accepts any real number as timestamp" applies to both calls.

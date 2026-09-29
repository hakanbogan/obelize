"""A double of the `google` namespace, so a fixture needs no installed SDK.

`_vendor/` is in obelize's always-excluded set, so nothing here is scanned,
reported or migrated. It exists to make the fixture's check script runnable
offline: the harness installs no distribution in `--fixtures-only` mode, and a
check that cannot import the module it checks is not a baseline.

A regular package rather than a namespace one, on purpose. `_vendor` goes on
`sys.path` in front of everything else, and a regular package found first wins
over the real `google` namespace portions that the dev environment installs --
which is what keeps the fixture's answer independent of what is installed.
"""

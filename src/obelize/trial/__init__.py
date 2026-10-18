"""Try an upgrade where it can do no harm: a copy of the repository, two environments, the tests.

The copy is byte for byte what git lists, outside the repository. One environment has the release in
use, one the release moved to; the repository's own tests run in the first before the migration is
written to the copy and in the second after. Installing runs the build scripts of what is
installed, and the tests run the repository's code, so a trial happens only when the person asked
for one (`obelize upgrade --apply`).
"""

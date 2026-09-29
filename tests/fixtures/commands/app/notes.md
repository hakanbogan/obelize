# Notes

A tracked file no migration touches. `dirty/` and `allowed/` append a line to
it, which is how a working tree becomes dirty without changing anything the
plan reads: an untracked file does not count, so creating one would have
tested nothing.

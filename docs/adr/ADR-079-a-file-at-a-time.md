# ADR-079: A file at a time

## Status

Accepted. Amends, for `upgrade` only, ADR-053 (D6, where one distribution makes the files and the
pin one unit), ADR-025 (D1, a file a run writes) and ADR-065 (Consequences).

## Decision

`obelize upgrade` writes a file at a time where one distribution holds both APIs, in the dry run, in
the trial's own migration and in the write that follows a passing trial. `fix`, `scan` and a pack
named with `--pack` keep the rule they had: a repository of one distribution is written whole or not
at all.

The rule existed because a half-migrated repository installs neither way: a file written for the new
API fails on the old pin, and a file left behind fails on the new one. `fix` has nothing to tell a
person which half they have. `upgrade --apply` has: the trial installs both releases and writes only
if no test that passed before fails after (ADR-065), so a half that breaks what the tests cover is
caught where it is made. The 0.9.0 measurement is why now: of 33 repositories held over 80, 32 were
held by a place the pack could only flag, and the 78 places a rule would have rewritten were all in
repositories where nothing was written.

### D1. Scope

One option on `commands.fix.Request` (`by_file`), passed to `codemod.run`, whose default is the rule
above. `upgrade` sets it for all three of its runs of the rules, so a dry run, a trial and the real
write agree on the files written. Every pack that is its own target is concerned when it is reached
through `upgrade`, the two bundled ones (`openai/openai-0-to-1`, `numpy/numpy-1-to-2`) among them:
`upgrade numpy` writes the files with no place left, where 0.9.0 wrote none while one was left.
Through `fix --pack` they are as they were, and so are the three bundled packs' fixtures and hashes.

With `--agent` the rule is off. The agent is asked about the flagged places only when the first run
of the rules writes nothing, which a pack of one distribution did until each place had moved; with a
file written at a time the first run would write the clean files, the agent would not be asked, and a
move of those would pass with the places it was set up for never put to it.

### D2. A file is left as it was exactly when it holds a place of its own

A file with a withheld row stays as it was, and its ready rows read `file_not_fully_migrated`, the
file's code and not the repository's. A file with none is written as the rules write it. A file
whose rows a `configure` that another module runs on withholds (`configure_consumed_elsewhere`) holds
one, so it is left. The unit stays the file: a file with a flagged place is never half written.

### D3. The pins follow the files written

A pin used to wait while any file used the legacy API; now a file left for its own place does not
hold it, and a pin that was ready is written with the files. The repository is held whole, as it was,
in the cases where a pin cannot go with the files:

- no file is written, so nothing moves and the rows read as they did;
- a manifest row is itself withheld: a line the rule cannot write (extras the new release does not
  list, a URL, a hash, an editable requirement, a constraints file), a module only the legacy
  distribution installed that no manifest declares, or a notebook or an unreadable file that may call
  the old API (a pack the repository rules out writes nothing at all, by the gate before this rule);
- a pin line sits in a file that is left (`setup.py` with a place of its own).

### D4. What was checked to compose

`codemod._elsewhere` runs before the choice and is unchanged. `reach.read_elsewhere` withholds the
file that defines a result another module reads, which is a file with a place of its own. An external
fixer runs only over a file whose rules left no place in it, so a held file is never given to a tool.
A file the rules and the manifest pass both edit (`setup.py`) is one outcome, written once. A name
the pack adds to a written file is its own import, from the new release, so no written file imports
something a held file has to supply. The files that stay on the old API meet the new release once the
pin moves; that is the half-migration the trial judges, and where no test reaches those files it does
not.

### D5. A partial result does not read as a whole one

The summary says how many files were written and which are left; `REPORT.md` has a section, Held
back, naming each file and the places in it; `run.json` carries them as it always did (`file_edits`
for the files written, `withheld` for the places left, each held file's ready rows under
`file_not_fully_migrated`), and gains nothing; `trial.json` records the files held beside the ones
written (`held`); the commit message of `--branch` and the pull request text of the action name them,
and say that a passing trial means the tests that passed before still pass, which does not show that
the rest has moved. The exit codes keep their meaning, and `4` is the one that says it: after a
passing trial the write ends as `fix --apply` ends, `0` where nothing is left for you and `4` where
places are, whether or not a verification command of the person's ran. The write has none of its
own, which ends `6` and which `upgrade` maps to `0`: that mapping used to hide the places left, so a
partial move ended `0` with no such command and `4` with one, and now ends `4` in both. A move to
another distribution (`PyPDF2` to `pypdf`) that leaves places ends the same way, where 0.9.0 ended
`0` without such a command. With `--branch` the command ends `0` after the commit, so the action's gate
cannot tell a partial move from a whole one by the code, which is why the files are in the text; a
distinct code for it would be a decision of its own.

### D6. The trial is not weakened

A migration that writes no file is `inconclusive`, as before, and a partial write that passes is
written to the working tree or the branch like any other. What the trial proves is what it always did:
the tests that passed before pass after. It does not prove that the rest of the move is done, that
code the tests do not reach works on the new release, or that a dry run's plan is safe to write.

## Consequences

- A real repository can now end with some of its places moved and the rest listed. The person still
  has to move what is listed, and until they do those files run on the new release.
- `bench/upgrade_collect.py` records the unit a plan is written by, and `bench/upgrade_score.py`
  says which rule a record is of. The 0.9.0 records name none and are read as whole-repository
  records, so they and the page that publishes them are unchanged; a new measurement would call a
  repository with a file written and a place left `partial`, where 0.9.0 called it `held`.
- Applying the rule where a pack has no trial to follow it is a decision of its own: `fix` has none.

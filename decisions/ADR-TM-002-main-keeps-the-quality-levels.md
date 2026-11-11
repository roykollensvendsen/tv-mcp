# ADR-TM-002: Main keeps the quality levels, so a pull request never records them

## Status

Accepted 2026-11-10: the owner accepted rule 16 of the voice plugins' shared
standard (claude-voice docs/plugin-standard.md) that day, and this follows it.
It takes over claude-voice's
[ADR-CV-009](https://github.com/roykollensvendsen/claude-voice/blob/main/decisions/ADR-CV-009-main-keeps-the-quality-levels.md),
accepted there the same day, and adapts it to this repository.

## Context

Until now nothing here noticed the code slowly getting worse. The gates pass or
fail: a suite that loses tests, coverage that drifts down, a function that grows
more tangled with each change all stay green. claude-voice, the project this
server plugs into, has a quality ratchet that refuses exactly that: a change may
leave each level as it is or make it better, and makes one worse only when its
pull request says why.

claude-voice first kept the levels in a file that every pull request had to
update with the exact levels it reached. That made the file a queue. On
2026-11-10 four of its open pull requests failed for one reason: another had
merged first, so the number of tests each had recorded was stale. Each had to
be rebased and measured again. ADR-CV-009 is how it got out of that, and this
repository can start where it ended.

What holds here:

- The useful part of the check is that nothing gets worse than main. Recording
  the exact level in the pull request only exists so the next comparison has a
  floor.
- `main` is protected: every change arrives by pull request, rebased, with every
  check green.
- A pull request's check runs on the pull request merged onto main, so the first
  parent of what it checks is exactly the main it would land on.
- Measuring is cheap here: the suite takes seconds, and the mutation check, which
  switches each rule off in turn, about a minute.

## Options considered

- **Do nothing.** The gates stay pass-or-fail and slow decay goes unseen. Not
  taken: the ratchet already exists and is proven next door.
- **Keep the levels in a file each pull request updates**, as claude-voice first
  did. Every merge breaks every other open pull request. Not taken.
- **Measure main and the pull request in every check.** Simple, with nothing
  stored, but every check takes twice as long. Not taken, except as the
  fallback below.
- **Main keeps its measured levels with each of its runs; a pull request
  compares with them.** **Chosen.**

## Decision

After every push to main, continuous integration measures the levels and keeps
them with that run as `quality-levels`. A pull request's check takes the levels
main measured for the commit it is merged onto, and fails only when a level is
worse, unless a `Ratchet-Exception:` line in the pull request names it. When
those levels are missing, for a run that was cancelled or has expired, the check
measures that commit itself in a copy of it: slower, and never skipped.
`quality.json` keeps only the suite's time budget, a limit set by hand rather
than a level, so no pull request needs to change it to pass. Main only
measures; it does not compare, because every change on it already passed the
check against the main before it.

## Consequences

- Merging one pull request never breaks another, and a contributor never runs
  the ratchet to fix a number.
- The ratchet runs `scripts/mutate.py` itself, for the mutation level, so a
  separate job that runs the same script spends that minute twice.
- **Worse:** the levels do not show in a pull request's diff. They are in the
  check's output and in main's runs.
- **Worse:** the check depends on GitHub keeping main's run results, 90 days by
  default. Past that, or when a run is missing, it measures the base, which
  doubles the job's time.
- **Worse:** a pull request whose check ran before main moved on is not checked
  again until it changes.
- **Neutral:** the layers among the modules are a level here too, as in
  claude-voice, so that the code-health page shows them (added 2026-11-11). It
  stays at nought, because `tests/test_layers.py` refuses a breach outright.

## Related

claude-voice's ADR-CV-009, `scripts/ratchet.py`, `quality.json`, the `quality`
job in `.github/workflows/checks.yml`, and "The quality ratchet" in
[`CONTRIBUTING.md`](../CONTRIBUTING.md#the-quality-ratchet).

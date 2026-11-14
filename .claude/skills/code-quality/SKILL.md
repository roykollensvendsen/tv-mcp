---
name: code-quality
description: Make tv-mcp's measures on the code-health page green, and keep them there - coverage, rules proven by a test, the most tangled function, layers, copied code, the time the tests take and the checks on main. Use when the page shows a measure in amber or red for this repository, before a pull request that adds or splits code, when someone asks how good the code is or how to raise a number, or when a measure seems impossible to meet and an exemption is tempting.
---

# Keeping the code-health page green

The claude-voice bridge has a software page (`http://127.0.0.1:8811/ui/`, read
from `GET /api/v1/health/software`) with one row per repository and one cell
per measure; this repository is one of the rows. The numbers come from the
levels main's checks keep after every merge, so a pull request turns a cell
green only once it has landed. This skill is the routine: read the page,
measure the same thing locally, fix the worst cell test-first, land it.

## 1. What the page measures, and when it is green

| Cell | Green | Amber | Red |
| --- | --- | --- | --- |
| Test coverage | 80 % or more | 60 - 80 % | under 60 % |
| Rules proven by a test (mutations killed) | every one | 90 % or more | fewer |
| Most tangled function (McCabe) | 15 or less | up to 25 | above 25 |
| Modules in their layers | 0 imports out of order | | any |
| Copied code | under 3 % of lines | up to 6 % | more |
| Lint and type errors | 0 | | any |
| Import cycles | 0 | any | |
| Time the tests take | inside the budget | inside budget plus tolerance | over |
| Checks on main | passing | running | failed |

The limits live in the bridge, not here: `MEASURES` in claude-voice's
`src/claude_voice/software.py`. Read them there if this table and the page ever
disagree, and fix the table.

A cell can also read **exempt** (section 4). Exempt is never green, and nothing
in this skill makes a cell exempt by itself.

## 2. Measure it locally

Run these from the repository root, after `uv sync --all-extras`: without the
extras the suite cannot import the package, and the ratchet stops with "The
suite fails". The long ones go in the background; never put a time limit on
them, because a cut-off mutation run reports rules as unproven that are not.

<!-- not run: the full measure runs the suite and every mutation -->
```
uv run python scripts/ratchet.py measure --out /tmp/levels.json   # every level, as main's checks measure it
uv run python scripts/ratchet.py check --base origin/main         # what your branch made worse than main
uv run python scripts/mutate.py                                   # each rule switched off in turn
```

For one cell at a time:

<!-- not run: examples of measuring one cell -->
```
uv run pytest -q --cov --cov-report=term-missing        # coverage, with the lines no test runs
uv run pytest -q --durations=15                         # the slowest tests
uv run ruff check . && uv run mypy src                  # lint and type errors
uv run pytest -q tests/test_layers.py                   # the layers
```

The complexity, cycle, layer and duplication counts are functions in
`scripts/ratchet.py` (`complexity`, `cycles`, `layer_breaches`, `duplication`).
The `measure` output lists the worst function's score per module, so open the
module with the highest number first. The layer count is there for the page
and stays at nought: `tests/test_layers.py` refuses any breach outright, so one
turns the suite red. The time budget is the one thing in
`quality.json`, and it changes only by hand, with the owner's yes.

## 3. Fix the worst cell, test-first

Work on one cell per pull request, the reddest first. Everything here follows
CONTRIBUTING.md: a failing test before the code, one logical change per pull
request, commits through the `write-commit` skill.

**Checks on main red.** Fix that before anything else: every other number is
measured by those checks, so while they fail the page stops moving.

**Coverage under 80.** Open the lines `term-missing` lists and ask what the
person using the code would notice if each were wrong. Write a test of that
behaviour, through the module's public functions, and see it red: for code that
already exists, break the line by hand (or with `mutate.py`), watch the test
fail, then put the line back. A test that passed the first time it ran proves
nothing. A driver takes its client in its constructor, so a test passes an
`httpx.MockTransport` and a recorded answer, never a real TV. Never test a
private helper just to lift the number, and never mark code as excluded from
coverage to get past the limit; that is an exemption, and section 4 applies.

**A rule nobody proves.** `mutate.py` names each rule whose removal no test
noticed. A rule is a line marked `# RULE: what it says`; it needs a row in
`scripts/mutations/<its file>/<its words>.toml` and a test named in the rule's own words
(`# RULE: a spoken reply is capped` wants `test_a_spoken_reply_is_capped`).
Write that test, run the mutation, see that very test go red, and keep the row.
Never loosen a row or point it at something easier to make the count go up; if
a row has to change, the pull request says why. Do not edit the tree while
`mutate.py` runs.

**A function above 15.** Split it without changing what it does:

1. Run the module's tests and see them green. If nothing covers the function's
   branches yet, write those tests first, as a pull request of their own.
2. Pull one decision out at a time: a guard clause that returns early, a
   lookup table in place of a chain of `if`s, one helper per branch of a
   `match`, a loop body as a function. Each helper does one thing and is named
   for it.
3. Run the same tests and see them green again, unchanged. A split that needs
   a test edited has changed behaviour, and is not a split.
4. Commit it as `refactor:`, with no behaviour change in the same commit.

A nested function counts on its own, not towards the function around it, so
hiding branches in a closure is not a fix the page will reward; give the helper
a name at module level. A new module may have no function above 15 at all; the
ratchet refuses it.

**An import out of its layer.** The map of the layers is `layer()` in
`scripts/ratchet.py`, with `CORE`, `TOP` and `ALLOWED` beside it: the core knows
no brand of TV and no MCP, a driver knows the core, a tool knows the core and
other tools but never a driver, and only `server` and `cli` put drivers and
tools together. A module with no layer counts as a breach too. Move the shared
code down into the core, or pass the thing in as an argument. Hiding the import
inside a function does not help, because every import in the file is counted. A
new core module gets its name in `CORE` in the same pull request.

**Copied code at 3 % or more.** A block counts when six or more lines in a row
appear more than once in `src/`, ignoring indentation. Put the block in one
function both places call, with the tests green before and after, as
`refactor:`.

**Tests over their budget.** Find the slowest with `--durations=15`. The usual
cause is a real wait: a sleep, a timeout, a subprocess. Make the wait
injectable and pass a fake clock or a short timeout in the test. Raising the
budget is the owner's decision, not a fix.

**Lint, type errors or a cycle.** Fix them as they are reported; a cycle is
broken the same way as a layer breach, by moving shared code down.

Before you push, run the gates in CONTRIBUTING.md (they end with the ratchet
against main). The ratchet refuses anything worse than main; a pull request
that must make a measure worse says why on a `Ratchet-Exception:` line, and
that is the owner's call too. Examples in a test or a skill use the
documentation addresses (192.0.2.x, 00:00:5E:00:53:xx) and no name from the
owner's home; `scripts/private_data_scan.py` refuses the rest.

## 4. Exemptions

Sometimes a cell should stay outside its limit: a function that is one long
match on a tool's name, a generated table, a test that has to wait for real
hardware. Such a cell may be marked exempt, and only like this:

- **A written reason**, saying why meeting the limit would make the code worse,
  not that it would take long.
- **The owner's yes.** Ask through the manager session (claude-voice-work)
  with the exact entry and your recommendation; never add one on your own
  judgement, and never count silence as a yes.
- **In this repository's own `quality.toml`**, in a pull request of its own,
  one entry per measure, with the measure's id as the page names it:

<!-- not run: an example entry -->
```toml
[[exempt]]
measure = "complexity"
reason = "the tool table is one long match on the tool's name"
approved = "Roy, 2026-11-11, in pull request #212"
```

The bridge reads `quality.toml` from its clone of this repository. The page
then shows that cell as exempt, with the reason, never as green. An entry
without both a reason and an approval is ignored, and a measure back inside its
limit is green again whatever the file says, so delete the entry then. The ids
are `coverage`, `mutation`, `tests`, `problems`, `cycles`, `layers`,
`duplication`, `complexity` and `test_time`.

## 5. Land it

Push your own branch, open the pull request, and once every check is green
merge it with `gh pr merge --rebase`. Then wait for main's checks to finish:
only their kept levels move the page, and the page itself refreshes every ten
minutes. Look at the cell again; if it is still not green, start again at
section 3 with what it now says.

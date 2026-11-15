#!/usr/bin/env python3
"""Turn every rule off in turn and see which tests notice.

Green on a first run proves nothing: a test that has never been red tests
nothing. Where a rule is written before its test, the test is run red first.
Where a rule already exists, this is the substitute. Every rule has one row,
in a file of its own under scripts/mutations/. Run it from the repository root:

    uv run python scripts/mutate.py [--json mutations.json]
    uv run python scripts/mutate.py --repair-only

One run at a time holds the checkout; a second stops at once and says so. A stop
(Ctrl-C, a cancelled CI job, a closed terminal) puts the mutated source back before the
run ends. `--repair-only` puts back a source a killed run left mutated, and does nothing
else.

`--json` writes the run's figures for the checks to keep; in a check, the
readable table goes to the run's summary page. Neither is ever committed.

A kill is not enough on its own. A mutation breaks whatever it breaks, and it
can break a test for an incidental reason — a documented example whose output
happened to change — leaving a rule looking guarded when nothing guards it. So
this also checks that the test named after the rule is one of the ones that went
red, and fails the run when it is not. `tests/test_rules_have_evidence.py` is
what requires that test to exist in the first place.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import pathlib
import re
import signal
import subprocess
import sys
import tempfile
import tomllib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

# Its neighbour in scripts/, found wherever this script is loaded from.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import held_folder

ROOT = pathlib.Path(__file__).resolve().parent.parent
#: One row per file: scripts/mutations/<the row's `file`, extension included>/<the
#: rule's words>.toml. Every pull request that added a row at the end of one shared
#: table collided with every other; a file per row only meets another pull request
#: adding the same rule.
ROWS = ROOT / "scripts/mutations"
#: Where the one mutated file is recorded while it is mutated. A `finally` does
#: not run when the process is killed, so without this a hard stop leaves a
#: source file switched off and the next person wondering why the suite is red.
RECOVERY = ROOT / "scripts/.mutate-recovery.json"
#: Where each suite run keeps its temporary files, one folder per run, removed when it
#: ends. Outside the checkout, where a test making a git repository of its own would
#: find this one instead; named after the checkout, so two never sweep each other's.
MUTATE_TMP = pathlib.Path(tempfile.gettempdir()) / (
    "tv-mcp-mutate-" + hashlib.sha256(str(ROOT).encode()).hexdigest()[:8]
)


#: A comment marking a rule; the marker in a string, as here, is not one.
MARKER = re.compile(r"(?:^|\s)# RULE: \S")


def marked_lines() -> list[str]:
    """Every line marking a rule, in the source and in this repository's own scripts."""
    sources = [*sorted((ROOT / "src").rglob("*.py")), *sorted((ROOT / "scripts").glob("*.py"))]
    return [line for path in sources for line in path.read_text().splitlines() if MARKER.search(line)]


def _no_rows() -> int:
    """With no rows, a run passes only when no rule is marked either."""
    print(f"no rules in {ROWS.relative_to(ROOT)} yet; add one file per rule the code enforces")  # noqa: T201
    # No rows but marked rules is a check that would pass on nothing.
    marked = len(marked_lines())
    # RULE: rules marked with no rows fail the run
    if marked:
        print(  # noqa: T201
            f"{marked} rule{'s are' if marked > 1 else ' is'} marked, so this run fails."
            f" Give each one a row file under {ROWS.relative_to(ROOT)}, or, if the rows were deleted"
            " by mistake, put them back with"
            f" `git checkout -- {ROWS.relative_to(ROOT)}`."
        )
        return 1
    return 0


def test_name_for(rule: str) -> str:
    """The test name a rule requires: its own words, as an identifier.

    Imported by ``tests/test_rules_have_evidence.py`` so the rule is written
    once. A rule named "a spoken reply is capped" wants a test called
    ``test_a_spoken_reply_is_capped``.
    """
    words = re.sub(r"[^a-z0-9]+", "_", rule.lower())
    return "test_" + re.sub(r"_+", "_", words).strip("_")


def row_path(rule: dict[str, Any]) -> pathlib.PurePosixPath:
    """Where a rule's row belongs, under ``ROWS``: its source file's whole path, its own words.

    A rule in ``src/tv_mcp/server.py`` named "a power change asks first" belongs at
    ``src/tv_mcp/server.py/a-power-change-asks-first.toml``.
    """
    words = re.sub(r"[^a-z0-9]+", "-", str(rule["name"]).lower()).strip("-")
    if not words:
        msg = f"the rule {rule['name']!r} has no letter or digit to file its row under; reword it"
        raise SystemExit(msg)
    return pathlib.PurePosixPath(rule["file"]) / f"{words}.toml"


def _rows_in(path: pathlib.Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = tomllib.loads(path.read_text()).get("rule", [])
    return rows


def all_rows(folder: pathlib.Path | None = None) -> list[dict[str, Any]]:
    """Every row, one file each, in path order."""
    folder = ROWS if folder is None else folder
    found: list[tuple[str, dict[str, Any]]] = []
    for path in sorted(folder.rglob("*.toml")) if folder.is_dir() else []:
        found += [(f"{folder.name}/{path.relative_to(folder).as_posix()}", rule) for rule in _rows_in(path)]
    where: dict[str, str] = {}
    for place, rule in found:
        if rule["name"] in where:
            msg = (
                f"the rule {rule['name']!r} has two rows, in {where[rule['name']]} and in {place};"
                f" delete one and keep {folder.name}/{row_path(rule)}"
            )
            raise SystemExit(msg)
        where[rule["name"]] = place
    return [rule for _, rule in found]


def misfiled(folder: pathlib.Path | None = None) -> list[str]:
    """Row files that hold other than one row, or sit where their rule does not put them."""
    folder = ROWS if folder is None else folder
    found = []
    for path in sorted(folder.rglob("*.toml")) if folder.is_dir() else []:
        here = pathlib.PurePosixPath(path.relative_to(folder).as_posix())
        rows = _rows_in(path)
        if len(rows) != 1:
            found.append(f"{here} holds {len(rows)} rows; give each rule a file of its own")
        elif here != (belongs := row_path(rows[0])):
            found.append(f"{here} should be {belongs}; move it there")
    return found


def line_of(text: str, pattern: str, occurrence: int) -> int:
    """Find the one line a rule lives on, by pattern rather than by number."""
    seen = 0
    for i, line in enumerate(text.splitlines()):
        if re.search(pattern, line):
            seen += 1
            if seen == occurrence:
                return i
    msg = f"no line {occurrence} matching {pattern!r}"
    raise SystemExit(msg)


def sweep() -> None:
    """Remove what earlier runs, killed before they could clean up, left; never a run's still going."""
    # RULE: a killed run's temporary files are swept at the next start
    held_folder.sweep(held_folder.ours(MUTATE_TMP), "run-")


STOPS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


def stop_cleanly() -> None:
    """Let a run told to stop put the tree back and remove its files first.

    By default a signal ends Python at once, with no `finally` run. Ctrl-C (SIGINT), a
    closed terminal (SIGHUP) and `kill` or GitHub's cancel (SIGTERM, after a SIGINT)
    each end the run here through `finally` instead. The first signal ignores the
    rest, so a second one cannot land inside the cleanup and cut it short.

    Ctrl-C still ends the run as KeyboardInterrupt, so it reads as Ctrl-C to whatever
    ran the script; SIGTERM and SIGHUP end it with 128 plus the signal's number, as a
    shell would report.
    """

    def stop(signum: int, _frame: object) -> None:
        for each in STOPS:
            # RULE: a second signal cannot cut the cleanup short
            signal.signal(each, signal.SIG_IGN)
        if signum == signal.SIGINT:
            # RULE: ctrl-c stops a run as an interrupt
            raise KeyboardInterrupt
        raise SystemExit(128 + signum)

    for each in STOPS:
        # RULE: a stopped run puts the tree back
        signal.signal(each, stop)


def _tidy() -> None:
    """Remove the run's temporary folder once nothing is left in it."""
    with contextlib.suppress(OSError):
        MUTATE_TMP.rmdir()


def repair() -> None:
    """Put back a file an earlier run was killed in the middle of mutating."""
    if not RECOVERY.is_file():
        return
    kept = json.loads(RECOVERY.read_text())
    path = ROOT / kept["file"]
    if path.read_text() == kept["mutated"]:
        path.write_text(kept["original"])
        print(f"repaired {kept['file']}, left mutated by a run that was killed")  # noqa: T201
    else:
        print(f"{kept['file']} was left mutated and has since changed; not touching it")  # noqa: T201
    RECOVERY.unlink()


def restore(path: pathlib.Path, original: str, mutated: str) -> bool:
    """Put a file back, unless somebody else changed it while the suite ran."""
    if path.read_text() != mutated:
        # Restoring now would overwrite an edit made while this was running,
        # which is a silent way to lose somebody's work.
        # RULE: a file changed during the run is never restored over
        return False
    path.write_text(original)
    return True


#: Colour codes pytest writes around FAILED, which a line-anchored pattern
#: would otherwise never match.
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def run_suite() -> tuple[int, list[str]]:
    """Run the tests and give back how many failed, and which ones."""
    # Two mutations that replace equal-length text leave files of identical
    # size, and CPython validates a cached .pyc from the source's modification
    # time and size -- both at one-second resolution. Inside the same second
    # the next run would import the previous mutation's bytecode and measure
    # the wrong rule, so no bytecode is written at all.
    # RULE: two mutations never share a bytecode cache
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    # Locked while the suite runs, so a sweep started meanwhile leaves it alone. Its
    # programs' temporary files go in it too, and pytest's in a folder inside it: pytest
    # empties its basetemp first, and would take the lock with it.
    held = held_folder.HeldFolder("run-", held_folder.ours(MUTATE_TMP))
    env["TMPDIR"] = held.name
    try:
        r = subprocess.run(  # noqa: S603 - this interpreter, pytest, and a folder this script made
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--tb=no",
                "--color=no",
                "-p",
                "no:cacheprovider",
                f"--basetemp={held.path / 'pytest'}",
            ],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
            env=env,
        )
    finally:
        # RULE: a suite run leaves no temporary files behind
        held.remove()
    # --color=no covers the usual run; stripping covers a configuration that
    # turns colour back on, which would otherwise make every kill unattributable.
    # RULE: a coloured failure line is still attributed
    plain = ANSI.sub("", r.stdout)
    m = re.search(r"(\d+) (?:failed|error)", plain)
    failed = re.findall(r"^FAILED (\S+)", plain, re.MULTILINE)
    return int(m.group(1)) if m else 0, [f.split("::")[-1].split("[")[0] for f in failed]


def same_checkout(run: Callable[..., str]) -> None:
    """Stop unless the tests would import this checkout's own package.

    Two worktrees that shared one environment once had `uv run` in one reinstall the
    package from the other's source in the middle of a run, so every rule showed the same
    failing tests. Asked in a subprocess, with the interpreter and environment the suite
    will get, since this script must never import the package itself: the ratchet runs
    one tree's scripts in another tree's environment.
    """
    for package in sorted((ROOT / "src").glob("*/__init__.py")):
        name, own = package.parent.name, package.parent.resolve()
        found = pathlib.Path(run("-c", f"import {name}; print({name}.__file__)").strip()).resolve()
        # RULE: the rule check never measures another checkout's code
        if own not in found.parents:
            msg = (
                f"The tests here would import {name} from {found.parent}, not from this"
                f" checkout's {own}: the environment belongs to another copy of the project."
                f" Run `uv sync` in {ROOT} and start again."
            )
            raise SystemExit(msg)


def _python(*args: str) -> str:
    """What this interpreter prints, run as the suite will be run."""
    done = subprocess.run(  # noqa: S603 - this interpreter, with arguments this script names
        [sys.executable, *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return done.stdout


def hold_the_checkout() -> int:
    """Take this checkout for the run, or stop: a second run would repair the first's mutation.

    The lock is on the checkout's folder itself, so there is no lock file to leave behind,
    and it is let go when the process ends, however it ends (easee-mcp #13's form).
    """
    held = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY)
    try:
        # RULE: one mutation run per checkout
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(held)
        msg = (
            f"A mutation run is already running in {ROOT}; let it end, or stop it, before"
            " starting another. Two at once would put back each other's switched-off rules."
        )
        raise SystemExit(msg) from None
    return held


def main() -> int:
    """Mutate every rule in turn, restore the tree, and report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=pathlib.Path, help="write the run's figures here, for the checks")
    parser.add_argument(
        "--repair-only", action="store_true", help="only put back a source a killed run left mutated"
    )
    args = parser.parse_args()

    stop_cleanly()
    held = hold_the_checkout()
    try:
        return _run(args)
    finally:
        os.close(held)


def _run(args: argparse.Namespace) -> int:
    """The run itself, once this checkout is held."""
    repair()
    if args.repair_only:
        # RULE: a repair-only run only repairs
        return 0
    sweep()
    same_checkout(_python)
    # RULE: an empty rule table is not a crash
    # A scaffolded repository starts with a table of comments and no rows.
    rules = all_rows()
    if not rules:
        return _no_rows()
    results = []
    lost: list[str] = []
    standing: tuple[pathlib.Path, str, str] | None = None
    try:
        for rule in rules:
            path = ROOT / rule["file"]
            # Read each file as it is now, not as it was when the run began: a
            # bulk snapshot taken up front is restored over anything edited
            # since, and losing an edit that way costs more than the run.
            text = path.read_text()
            lines = text.splitlines()
            i = line_of(text, rule["find"], rule.get("occurrence", 1))
            # Keep the line's own indentation: a replacement that carries its own
            # would have to be kept in step with the source, and silently would not be.
            indent = lines[i][: len(lines[i]) - len(lines[i].lstrip())]
            lines[i] = indent + rule["replace"].strip()
            mutated = "\n".join(lines) + "\n"
            RECOVERY.write_text(json.dumps({"file": rule["file"], "original": text, "mutated": mutated}))
            path.write_text(mutated)
            standing = (path, text, mutated)
            count, failed = run_suite()
            if not restore(path, text, mutated):
                lost.append(rule["file"])
            standing = None
            RECOVERY.unlink(missing_ok=True)
            # A kill by some other test is not evidence about this rule.
            own = test_name_for(rule["name"])
            by_its_own = own in failed
            results.append((rule["name"], rule["file"], count, own, by_its_own))
            verdict = "KILLED  " if by_its_own else ("BY LUCK " if count else "SURVIVED")
            print(f"{verdict} {rule['name']}: {count}")  # noqa: T201
    finally:
        if standing is not None:
            restore(*standing)
        RECOVERY.unlink(missing_ok=True)
        _tidy()

    survived = [name for name, _, count, _, _ in results if count == 0]
    lucky = [name for name, _, count, _, own in results if count and not own]
    # Written before a failing run exits: a run where a rule survived is exactly
    # what the checks' page has to show, not the last run that passed.
    publish(args.json, results, survived, lucky)
    proven = len(results) - len(survived) - len(lucky)
    print(f"\n{proven}/{len(results)} rules turned off the test that names them")  # noqa: T201
    if survived:
        print("SURVIVED, so nothing protects them:", ", ".join(survived))  # noqa: T201
    if lucky:
        print("KILLED BY ANOTHER TEST, so the evidence is not about them:", ", ".join(lucky))  # noqa: T201
    if lost:
        print("CHANGED WHILE MUTATED, so left as they are:", ", ".join(sorted(set(lost))))  # noqa: T201
        print("Edit the tree while this runs and the result is not about your code.")  # noqa: T201
    return 1 if survived or lucky or lost else 0


Result = tuple[str, str, int, str, bool]


def publish(to: pathlib.Path | None, results: list[Result], survived: list[str], lucky: list[str]) -> None:
    """Give the run to the checks: its figures to `to`, its table to the run's summary page."""
    if to:
        to.write_text(json.dumps(figures(results), indent=2) + "\n")
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with pathlib.Path(summary).open("a") as page:
            page.write(report(results, survived, lucky))


def figures(results: list[Result]) -> dict[str, Any]:
    """The run as numbers: per rule, its name, file, tests gone red and whether its own was one."""
    rules = [
        {"name": name, "file": file, "tests_red": count, "own_test_red": own_red}
        for name, file, count, _, own_red in results
    ]
    return {"killed": sum(rule["own_test_red"] for rule in rules), "total": len(rules), "rules": rules}


def report(results: list[Result], survived: list[str], lucky: list[str]) -> str:
    """Render the run as a readable table, for the checks' summary page."""
    rows = "\n".join(
        f"| {name} | {count} | `{own}` | {'yes' if by_own else 'NO'} |"
        for name, _, count, own, by_own in results
    )
    proven = len(results) - len(survived) - len(lucky)
    verdict = (
        f"**Result: {proven} of {len(results)} rules turned off the test that names them.**"
        + (" None survived." if not survived else f" Survived: {', '.join(survived)}.")
        + ("" if not lucky else f" Killed only by other tests: {', '.join(lucky)}.")
    )
    return f"""# Every rule, turned off in turn

*Run {dt.datetime.now(dt.UTC).date()} by `python scripts/mutate.py`, which is
how to repeat it. The script restores every file it touched before it exits.*

Green on a first run proves nothing: a test that has never been red tests
nothing. Where a rule is written before its test, the test is run red first.
Where a rule already exists, this is the substitute. Each rule is disabled in
turn, by replacing its one line with something that can never hold, and the
suite is run. A rule whose removal breaks no test is a rule nothing protects.

{verdict}

| Rule turned off | Tests that went red | The test that names it | Did that one go red? |
|---|---|---|---|
{rows}

## What this does not prove

That the rules are the right rules, or that a rule catches every case of what
it names. It proves each rule is load-bearing: switch it off and a named test
says so. The last column is why that is worth more than a count: a mutation can
break a test for an incidental reason, and a `NO` there fails this script even
though something went red. A new rule follows the order in `CONTRIBUTING.md`
instead, a failing test first, and gets a row of its own under `scripts/mutations/`,
which `tests/test_rules_have_evidence.py` requires.
"""


if __name__ == "__main__":
    sys.exit(main())

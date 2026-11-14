"""The mutation run's figures go to the checks, never into the repository.

`scripts/mutate.py --json mutations.json` writes, per rule, its name, file, how
many tests went red and whether its own test was one of them, plus the totals.
On a push to main the `mutation` job uploads that file as `quality-mutations`.
A run where a rule survived is exactly what that page has to show, so the file
is written before the run exits with a failure.
"""

import importlib.util
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).parent.parent


def _mutate():
    spec = importlib.util.spec_from_file_location("mutate_report", ROOT / "scripts/mutate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(tmp_path, monkeypatch, red, *args):
    """mutate.py over one rule in a scratch tree, with `red` as what the suite reports."""
    mutate = _mutate()
    (tmp_path / "src").mkdir()
    (tmp_path / "src/rule.py").write_text("if guarded:\n    pass\n")
    rows = tmp_path / "scripts/mutations"
    (rows / "src/rule.py").mkdir(parents=True)
    (rows / "src/rule.py/a-guard-holds.toml").write_text(
        '[[rule]]\nname = "a guard holds"\nfile = "src/rule.py"\n'
        "find = 'if guarded:'\nreplace = 'if True:'\n"
    )
    monkeypatch.setattr(mutate, "ROOT", tmp_path)
    monkeypatch.setattr(mutate, "ROWS", rows)
    monkeypatch.setattr(mutate, "RECOVERY", tmp_path / "scripts/.mutate-recovery.json")
    monkeypatch.setattr(mutate, "run_suite", lambda: (len(red), red))
    monkeypatch.setattr(sys, "argv", ["mutate.py", *args])
    return mutate.main()


def test_a_failing_mutation_run_still_writes_its_report(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    report = tmp_path / "mutations.json"
    assert _run(tmp_path, monkeypatch, [], "--json", str(report)) == 1
    assert json.loads(report.read_text()) == {
        "killed": 0,
        "total": 1,
        "rules": [{"name": "a guard holds", "file": "src/rule.py", "killed": 0, "own_test_red": False}],
    }


def test_a_passing_mutation_run_reports_each_rule_killed_by_its_own_test(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    report = tmp_path / "mutations.json"
    assert _run(tmp_path, monkeypatch, ["test_a_guard_holds"], "--json", str(report)) == 0
    figures = json.loads(report.read_text())
    assert (figures["killed"], figures["total"]) == (1, 1)
    assert figures["rules"][0]["own_test_red"] is True


def test_the_readable_table_goes_to_the_check_s_summary(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    _run(tmp_path, monkeypatch, ["test_a_guard_holds"])
    table = summary.read_text()
    assert "| a guard holds | 1 | `test_a_guard_holds` | yes |" in table
    assert "1 of 1 rules" in table


def test_the_mutation_report_is_never_committed():
    assert "mutations.json" in (ROOT / ".gitignore").read_text().splitlines()

# SPDX-License-Identifier: GPL-3.0-or-later
"""The mutation runner's own rules: the tool that checks every rule is checked too.

Each test loads a fresh copy of the runner and points it at temporary paths, so
none of them touches the real recovery file or starts a real suite.
"""

import fcntl
import importlib.util
import json
import os
import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _runner(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("mutate_under_test", ROOT / "scripts/mutate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(
        module, "same_checkout", lambda _ask: None
    )  # a stand-in tree, with no package to check
    monkeypatch.setattr(module, "RECOVERY", tmp_path / ".mutate-recovery.json")
    monkeypatch.setattr(module, "ROWS", tmp_path / "mutations")
    # Its own: the real one holds the temporary files of the mutation run this may be inside.
    monkeypatch.setattr(module, "MUTATE_TMP", tmp_path / "mutate-tmp")
    return module


def _suite_says(monkeypatch, runner, stdout):
    """Make the runner's suite run print `stdout`, and keep what it was started with."""
    seen = {}

    def fake_run(command, **kwargs):
        seen.update(kwargs)
        return subprocess.CompletedProcess(command, 1, stdout=stdout, stderr="")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    return seen


def test_a_file_changed_during_the_run_is_never_restored_over(monkeypatch, tmp_path):
    runner = _runner(monkeypatch, tmp_path)
    source = tmp_path / "source.py"
    source.write_text("edited by somebody\n")
    assert runner.restore(source, "original\n", "mutated\n") is False
    assert source.read_text() == "edited by somebody\n"
    source.write_text("mutated\n")
    assert runner.restore(source, "original\n", "mutated\n") is True
    assert source.read_text() == "original\n"


def test_two_mutations_never_share_a_bytecode_cache(monkeypatch, tmp_path):
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    runner = _runner(monkeypatch, tmp_path)
    seen = _suite_says(monkeypatch, runner, "1 failed\nFAILED tests/test_x.py::test_a\n")
    runner.run_suite()
    assert seen["env"].get("PYTHONDONTWRITEBYTECODE") == "1"


def test_a_coloured_failure_line_is_still_attributed(monkeypatch, tmp_path):
    runner = _runner(monkeypatch, tmp_path)
    red, plain = "\x1b[31m", "\x1b[0m"
    _suite_says(
        monkeypatch, runner, f"{red}FAILED{plain} tests/test_x.py::test_a - boom\n{red}1 failed{plain}\n"
    )
    assert runner.run_suite() == (1, ["test_a"])


def test_an_empty_rule_table_is_not_a_crash(monkeypatch, tmp_path, capsys):
    runner = _runner(monkeypatch, tmp_path)
    (tmp_path / "mutations").mkdir()
    monkeypatch.setattr("sys.argv", ["mutate.py"])
    assert runner.main() == 0
    assert "no rules in" in capsys.readouterr().out


def test_rules_marked_with_no_rows_fail_the_run(monkeypatch, tmp_path, capsys):
    """No rows at all would otherwise pass, which is the check failing open."""
    runner = _runner(monkeypatch, tmp_path)
    (tmp_path / "mutations").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src/code.py").write_text("x = 1  # RULE: a rule with no row\n")
    monkeypatch.setattr("sys.argv", ["mutate.py"])
    assert runner.main() == 1
    said = capsys.readouterr().out
    assert "1 rule is marked, so this run fails" in said
    assert "git checkout -- mutations" in said


@pytest.fixture
def real():
    """The runner as it is, with its real rows: read, never run."""
    spec = importlib.util.spec_from_file_location("mutate_as_it_is", ROOT / "scripts/mutate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


#: The function a killed run repairs with. A rule there would be switched off while it repairs.
UNPROVABLE = "repair"

REPAIR_WITH_A_RULE = '''
def repair():
    """Put back a file a killed run left mutated."""
    # RULE: a repaired file is the original
    if kept:
        write(kept)


def sweep():
    # RULE: a swept folder is gone
    remove()
'''


def _inside_repair(text, rows, runner):
    """The rules marked, or switched off by a row, in `repair()` or any function it calls by name."""
    import ast  # noqa: PLC0415

    defs = (ast.FunctionDef, ast.AsyncFunctionDef)
    functions = {f.name: f for f in ast.parse(text).body if isinstance(f, defs)}
    assert UNPROVABLE in functions, (
        f"no {UNPROVABLE}() in the runner; if it was renamed, rename UNPROVABLE too"
    )
    reached, waiting = set(), [UNPROVABLE]
    while waiting:  # repair() and everything it calls, however deep, within this file
        name = waiting.pop()
        reached.add(name)
        calls = [
            c for c in ast.walk(functions[name]) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
        ]
        called = {c.func.id for c in calls}
        waiting += [c for c in called if c in functions and c not in reached]
    lines = text.splitlines()
    inside = {i for name in reached for i in range(functions[name].lineno - 1, functions[name].end_lineno)}
    marked = [lines[i].split("# RULE:")[1].strip() for i in sorted(inside) if "# RULE:" in lines[i]]
    rowed = [
        r["name"] for r in rows if runner.line_of(text, r["find"], int(r.get("occurrence", 1))) in inside
    ]
    return sorted(set(marked + rowed))


def test_a_rule_inside_repair_is_found(real):
    """The guard below is only worth something if it sees a rule where one has been put."""
    rows = [
        {"name": "a swept folder is gone", "find": r"^\s*remove\(\)$"},
        {"name": "kept", "find": r"if kept:"},
    ]
    assert _inside_repair(REPAIR_WITH_A_RULE, rows, real) == ["a repaired file is the original", "kept"]


def test_no_rule_lives_inside_repair(real):
    """A killed run repairs with the code it left switched off, so a rule in repair() cannot be proven."""
    text = (ROOT / "scripts/mutate.py").read_text(encoding="utf-8")
    rows = [r for r in real.all_rows() if r["file"] == "scripts/mutate.py"]
    assert rows, "the runner's own rows are missing"
    assert _inside_repair(text, rows, real) == []


REPAIR_CALLING_A_RULE = """
def write(kept):
    # RULE: a repaired file is written whole
    path.write_text(kept)


def repair():
    write(kept)
"""


def test_a_rule_in_what_repair_calls_is_found(real):
    """A helper repair() calls runs switched off too, so its rule cannot be proven either."""
    assert _inside_repair(REPAIR_CALLING_A_RULE, [], real) == ["a repaired file is written whole"]


def test_a_runner_with_no_repair_is_refused_by_name(real):
    """Renamed, repair() would leave the guard checking nothing; it says what it looked for."""
    with pytest.raises(AssertionError, match=r"no repair\(\) in"):
        _inside_repair("def mend():\n    pass\n", [], real)


REPAIR_AWAITING_A_RULE = """
async def write(kept):
    # RULE: an awaited repair is written whole
    path.write_text(kept)


def repair():
    run(write(kept))
"""


def test_a_rule_in_an_async_helper_repair_calls_is_found(real):
    """An `async def` helper runs switched off too, once repair() calls it."""
    assert _inside_repair(REPAIR_AWAITING_A_RULE, [], real) == ["an awaited repair is written whole"]


def _left_mutated(monkeypatch, tmp_path, *args):
    """A checkout whose source a killed run left mutated, with its row; no suite may start."""
    runner = _runner(monkeypatch, tmp_path)
    source = tmp_path / "rule.py"
    source.write_text("x = 2\n")
    (tmp_path / ".mutate-recovery.json").write_text(
        json.dumps({"file": "rule.py", "original": "x = 1\n", "mutated": "x = 2\n"})
    )
    rows = tmp_path / "mutations/rule.py"
    rows.mkdir(parents=True)
    (rows / "x-is-one.toml").write_text(
        '[[rule]]\nname = "x is one"\nfile = "rule.py"\nfind = "x = 1"\nreplace = "x = 2"\n'
    )
    suites = []
    monkeypatch.setattr(runner, "run_suite", lambda: suites.append(1) or (0, []))
    monkeypatch.setattr("sys.argv", ["mutate.py", *args])
    return runner, source, suites


def test_one_mutation_run_per_checkout(monkeypatch, tmp_path):
    """A second run would repair the first one's live mutation, and both would measure nonsense."""
    runner, source, suites = _left_mutated(monkeypatch, tmp_path)
    first = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(first, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(SystemExit, match="already running"):
            runner.main()
    finally:
        os.close(first)
    assert source.read_text() == "x = 2\n"  # the first run's mutation, untouched
    assert (tmp_path / ".mutate-recovery.json").exists()
    assert suites == []


def test_a_repair_only_run_only_repairs(monkeypatch, tmp_path):
    runner, source, suites = _left_mutated(monkeypatch, tmp_path, "--repair-only")
    monkeypatch.setattr(runner, "same_checkout", lambda _ask: None)
    assert runner.main() == 0
    assert source.read_text() == "x = 1\n"
    assert not (tmp_path / ".mutate-recovery.json").exists()
    assert suites == []

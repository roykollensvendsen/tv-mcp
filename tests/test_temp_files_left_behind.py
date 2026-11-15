# SPDX-License-Identifier: GPL-3.0-or-later
"""The rule check and the ratchet leave nothing in the machine's temporary folder.

On 2026-11-15 the manager deleted 579 folders (3.1 GB) under /tmp, left there by
test, mutation and ratchet runs across the repositories. Each test here points
the temporary folder at a fresh one of its own, runs the tool, and checks that
nothing is left in it: not after a finished run, and not after a run that was
told to stop.
"""

import importlib.util
import json
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _load(name, path, monkeypatch, temp):
    """A fresh copy of a script, whose temporary folder is `temp`."""
    monkeypatch.setenv("TMPDIR", str(temp))
    monkeypatch.setattr(tempfile, "tempdir", None)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GUARDED = "if guarded:\n    pass\n"
ROW = (
    "[[rule]]\nname = \"a guard holds\"\nfile = \"src/rule.py\"\nfind = 'if guarded:'\nreplace = 'if True:'\n"
)


def _project(tmp_path, test):
    """A tiny project with one rule, its row, and `test` as the rule's own test."""
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src/rule.py").write_text(GUARDED)
    (project / "tests").mkdir()
    (project / "tests/test_guard.py").write_text(test)
    rows = project / "scripts/mutations/src/rule.py"
    rows.mkdir(parents=True)
    (rows / "a-guard-holds.toml").write_text(ROW)
    return project


HOLDS = """
import pathlib

def test_a_guard_holds():
    assert "if guarded:" in pathlib.Path("src/rule.py").read_text()
"""


def test_a_mutation_run_leaves_the_temporary_folder_empty(tmp_path, monkeypatch):
    temp = tmp_path / "tmp"
    temp.mkdir()
    mutate = _load("mutate_leaves", ROOT / "scripts/mutate.py", monkeypatch, temp)
    project = _project(tmp_path, HOLDS)
    monkeypatch.setattr(mutate, "ROOT", project)
    monkeypatch.setattr(mutate, "ROWS", project / "scripts/mutations")
    monkeypatch.setattr(mutate, "RECOVERY", project / "scripts/.mutate-recovery.json")
    monkeypatch.setattr(sys, "argv", ["mutate.py"])
    assert mutate.main() == 0
    assert list(temp.iterdir()) == []


WAITS = """
import time

def test_a_guard_holds():
    time.sleep(60)
"""

DRIVER = """
import importlib.util, pathlib, sys
project = pathlib.Path(sys.argv[2])
spec = importlib.util.spec_from_file_location("mutate", sys.argv[1])
mutate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mutate)
mutate.ROOT, mutate.ROWS = project, project / "scripts/mutations"
mutate.RECOVERY = project / "scripts/.mutate-recovery.json"
sys.argv = ["mutate.py"]
sys.exit(mutate.main())
"""


def test_a_mutation_run_told_to_stop_leaves_nothing_behind(tmp_path):
    temp = tmp_path / "tmp"
    temp.mkdir()
    project = _project(tmp_path, WAITS)
    (tmp_path / "driver.py").write_text(DRIVER)
    run = subprocess.Popen(
        [sys.executable, str(tmp_path / "driver.py"), str(ROOT / "scripts/mutate.py"), str(project)],
        env={**os.environ, "TMPDIR": str(temp)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 30
        while not list(temp.rglob("run-*")) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert list(temp.rglob("run-*")), "the run never started its suite"
        time.sleep(0.5)  # into the suite, so the mutated file is standing
        run.send_signal(signal.SIGTERM)
        assert run.wait(timeout=30) != 0
    finally:
        run.kill()
    assert list(temp.iterdir()) == []
    assert (project / "src/rule.py").read_text() == GUARDED


def _ratchet(monkeypatch, temp):
    return _load("ratchet_leaves", ROOT / "scripts/ratchet.py", monkeypatch, temp)


def _leaves_a_file(env):
    """What a child does that keeps its temporary files: one left where it was told to put them."""
    folder = pathlib.Path((env or {}).get("TMPDIR") or tempfile.gettempdir())
    (folder / "left-by-a-child").write_text("x")


def test_measuring_the_base_leaves_nothing_in_the_temporary_folder(tmp_path, monkeypatch):
    temp = tmp_path / "tmp"
    temp.mkdir()
    ratchet = _ratchet(monkeypatch, temp)

    def run(*command, cwd=None, env=None):
        if command[:3] == ("git", "worktree", "add"):
            pathlib.Path(command[-2]).mkdir()
        if "measure" in command:
            _leaves_a_file(env)
            out = pathlib.Path(command[command.index("--out") + 1])
            out.write_text(json.dumps({"tests": 1}))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(ratchet, "_run", run)
    assert ratchet.measure_at("origin/main") == {"tests": 1}
    assert list(temp.iterdir()) == []


def test_measuring_the_tree_leaves_nothing_in_the_temporary_folder(tmp_path, monkeypatch):
    temp = tmp_path / "tmp"
    temp.mkdir()
    ratchet = _ratchet(monkeypatch, temp)

    def run(*command, cwd=None, env=None):
        stdout = ""
        if "pytest" in command:
            _leaves_a_file(env)
            report = next(a for a in command if a.startswith("--cov-report=json:")).split(":", 1)[1]
            pathlib.Path(report).write_text(json.dumps({"totals": {"percent_covered": 90.0}}))
            stdout = "3 passed"
        if "scripts/mutate.py" in command:
            _leaves_a_file(env)
            stdout = "\n1/1 rules turned off the test that names them\n"
        if "ruff" in command:
            stdout = "[]"
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(ratchet, "_run", run)
    assert ratchet.measure()["tests"] == 3
    assert list(temp.iterdir()) == []


def test_a_test_that_starts_pytest_gives_it_a_temporary_folder_of_its_own():
    """A pytest started by a test would otherwise keep its folders in the machine's /tmp."""
    for test in ("test_real_recovery_file_is_guarded.py",):
        assert "--basetemp" in (ROOT / "tests" / test).read_text(), test

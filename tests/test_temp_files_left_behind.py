# SPDX-License-Identifier: GPL-3.0-or-later
"""The rule check and the ratchet leave nothing in the machine's temporary folder.

On 2026-11-15 the manager deleted 579 folders (3.1 GB) under /tmp, left there by
test, mutation and ratchet runs across the repositories. Each test here points
the temporary folder at a fresh one of its own, runs the tool, and checks that
nothing is left in it: not after a finished run, and not after a run that was
told to stop.
"""

import contextlib
import importlib.util
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time

import pytest
from bounded import WITHIN

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
    monkeypatch.setattr(
        mutate, "same_checkout", lambda _ask: None
    )  # a stand-in tree, with no package to check
    monkeypatch.setattr(mutate, "ROWS", project / "scripts/mutations")
    monkeypatch.setattr(mutate, "RECOVERY", project / "scripts/.mutate-recovery.json")
    monkeypatch.setattr(sys, "argv", ["mutate.py"])
    assert mutate.main() == 0
    assert list(temp.iterdir()) == []


WAITS = """
import time

import pytest

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
mutate.same_checkout = lambda _ask: None  # a stand-in tree, with no package to check
if len(sys.argv) > 3:  # a slow cleanup, so a second signal can be sent in the middle of it
    import time
    restore, cleaning = mutate.restore, pathlib.Path(sys.argv[3])

    def slow_restore(*args):
        cleaning.write_text("")
        time.sleep(2)
        return restore(*args)

    mutate.restore = slow_restore
sys.argv = ["mutate.py"]
sys.exit(mutate.main())
"""


def _git(project, *command):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *command],
        cwd=project,
        capture_output=True,
        text=True,
        check=True,
        timeout=WITHIN,
    ).stdout


def _stopped_mid_mutation(tmp_path, *, then_terminated=False):
    """A project kept in git, and a mutation run of it told to stop mid-suite.

    Stopped with SIGTERM; or, as GitHub cancels a job, with SIGINT and then, once the
    cleanup has begun, SIGTERM.
    """
    cleaning = tmp_path / "cleaning"
    temp = tmp_path / "tmp"
    temp.mkdir()
    project = _project(tmp_path, WAITS)
    _git(project, "init", "-q")
    _git(project, "add", ".")
    _git(project, "commit", "-q", "-m", "the project as it is")
    (tmp_path / "driver.py").write_text(DRIVER)
    run = subprocess.Popen(
        [
            sys.executable,
            str(tmp_path / "driver.py"),
            str(ROOT / "scripts/mutate.py"),
            str(project),
            *([str(cleaning)] if then_terminated else []),
        ],
        env={**os.environ, "TMPDIR": str(temp)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + WITHIN
        while not list(temp.rglob("run-*")) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert list(temp.rglob("run-*")), "the run never started its suite"
        time.sleep(0.5)  # into the suite, so the mutated file is standing
        assert (project / "src/rule.py").read_text() != GUARDED, "the rule was not switched off yet"
        if then_terminated:
            run.send_signal(signal.SIGINT)
            while not cleaning.exists() and run.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            assert cleaning.exists(), "the cleanup never began"
        run.send_signal(signal.SIGTERM)
        assert run.wait(timeout=WITHIN) != 0
    finally:
        run.kill()
    return temp, project


def test_a_mutation_run_told_to_stop_puts_the_source_back_as_git_has_it(tmp_path):
    """The worst of what a stopped run can leave: a rule switched off in the source."""
    _, project = _stopped_mid_mutation(tmp_path)
    assert _git(project, "status", "--porcelain") == ""
    assert (project / "src/rule.py").read_text() == GUARDED


def test_a_second_signal_cannot_cut_the_cleanup_short(tmp_path):
    """SIGINT, then SIGTERM in the middle of the cleanup: the second must not cut it short."""
    temp, project = _stopped_mid_mutation(tmp_path, then_terminated=True)
    assert _git(project, "status", "--porcelain") == ""
    assert list(temp.iterdir()) == []


def test_a_mutation_run_told_to_stop_leaves_nothing_behind(tmp_path):
    temp, _ = _stopped_mid_mutation(tmp_path)
    assert list(temp.iterdir()) == []


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
        if "measure" in command:
            _leaves_a_file(env)
            out = pathlib.Path(command[command.index("--out") + 1])
            out.write_text(json.dumps({"tests": 1}))
        return subprocess.CompletedProcess(command, 0, stdout="0123abc\n", stderr="")

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
    monkeypatch.setattr(ratchet, "same_checkout", lambda _ask: None)  # its steps are stand-ins here
    assert ratchet.measure()["tests"] == 3
    assert list(temp.iterdir()) == []


def test_a_test_that_starts_pytest_gives_it_a_temporary_folder_of_its_own():
    """A pytest started by a test would otherwise keep its folders in the machine's /tmp."""
    for test in ("test_real_recovery_file_is_guarded.py",):
        assert "--basetemp" in (ROOT / "tests" / test).read_text(), test


STOPS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


@contextlib.contextmanager
def _handlers_kept():
    """Give the test run its own signal handlers back afterwards."""
    before = {each: signal.getsignal(each) for each in STOPS}
    try:
        yield
    finally:
        for each, handler in before.items():
            signal.signal(each, handler)


def _stops_on_every_signal(script, monkeypatch, tmp_path):
    module = _load(script.stem + "_signals", script, monkeypatch, tmp_path)
    with _handlers_kept():
        for each in STOPS:  # none of its own beforehand, so only stop_cleanly can install one
            signal.signal(each, signal.SIG_DFL)
        module.stop_cleanly()
        handlers = {each: signal.getsignal(each) for each in STOPS}
    assert all(callable(handlers[each]) for each in STOPS), handlers


def _ignores_a_second_signal(script, monkeypatch, tmp_path):
    module = _load(script.stem + "_twice", script, monkeypatch, tmp_path)
    with _handlers_kept():
        for each in STOPS:  # none of its own beforehand, so only stop_cleanly can install one
            signal.signal(each, signal.SIG_DFL)
        module.stop_cleanly()
        with pytest.raises(SystemExit) as ended:
            # SIGTERM: a run with no handler of its own for SIGINT would end the test run here.
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        assert ended.value.code == 128 + signal.SIGTERM
        assert all(signal.getsignal(each) == signal.SIG_IGN for each in STOPS)


def test_a_stopped_run_puts_the_tree_back(tmp_path, monkeypatch):
    """Not only SIGTERM: a closed terminal sends SIGHUP, and Ctrl-C or GitHub sends SIGINT."""
    _stops_on_every_signal(ROOT / "scripts/mutate.py", monkeypatch, tmp_path)


def test_the_first_signal_ignores_the_rest(tmp_path, monkeypatch):
    """GitHub sends SIGINT and then SIGTERM; the second must not land inside the first's cleanup."""
    _ignores_a_second_signal(ROOT / "scripts/mutate.py", monkeypatch, tmp_path)


def _interrupted_as_ctrl_c(script, monkeypatch, tmp_path):
    module = _load(script.stem + "_ctrl_c", script, monkeypatch, tmp_path)
    with _handlers_kept():
        for each in STOPS:
            signal.signal(each, signal.SIG_DFL)
        module.stop_cleanly()
        with pytest.raises(KeyboardInterrupt):
            signal.getsignal(signal.SIGINT)(signal.SIGINT, None)


def test_ctrl_c_stops_a_run_as_an_interrupt(tmp_path, monkeypatch):
    """Ctrl-C still reads as Ctrl-C to whatever runs the script: an interrupt, not an exit."""
    _interrupted_as_ctrl_c(ROOT / "scripts/mutate.py", monkeypatch, tmp_path)


def test_ctrl_c_stops_a_measurement_as_an_interrupt(tmp_path, monkeypatch):
    _interrupted_as_ctrl_c(ROOT / "scripts/ratchet.py", monkeypatch, tmp_path)


def test_a_stopped_measurement_removes_its_copy(tmp_path, monkeypatch):
    _stops_on_every_signal(ROOT / "scripts/ratchet.py", monkeypatch, tmp_path)


def test_a_second_signal_cannot_cut_the_cleanup_short_of_a_measurement(tmp_path, monkeypatch):
    _ignores_a_second_signal(ROOT / "scripts/ratchet.py", monkeypatch, tmp_path)


STEP = """
import pathlib, signal, sys, time
here = pathlib.Path(sys.argv[1])
stops = []
signal.signal(signal.SIGINT, lambda _signum, _frame: stops.append(1))
(here / "started").write_text("")
deadline = time.monotonic() + 30  # a step never told to stop ends by itself
while not stops and time.monotonic() < deadline:
    time.sleep(0.05)
time.sleep(1.5)  # a step that takes a moment to put things back; a second stop lands here
(here / "stops").write_text(str(len(stops)))
(here / "cleaned").write_text("")
"""

#: How the ratchet starts its own steps: through uv, which passes a Ctrl-C on to its child.
THROUGH_UV = ("uv", "run", "--no-project", "python")

MEASURING = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ratchet", sys.argv[1])
ratchet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ratchet)
ratchet.stop_cleanly()
ratchet._run(*sys.argv[2:])
"""


def _stop_a_step_under_uv(tmp_path):
    """Run a real `uv run` step under the ratchet, stop the ratchet once, and wait for both."""
    if shutil.which("uv") is None:
        # In CI the proof must never drop out unseen, so there a missing uv fails.
        if os.environ.get("CI"):
            pytest.fail(
                "uv is not on PATH in CI, so the proof that a stopped step hears Ctrl-C"
                " once cannot run: install uv in the workflow, see CONTRIBUTING.md"
            )
        pytest.skip("needs uv, which the ratchet starts its steps through: install uv to run it")
    (tmp_path / "step.py").write_text(STEP)
    (tmp_path / "measuring.py").write_text(MEASURING)
    run = subprocess.Popen(
        [
            sys.executable,
            str(tmp_path / "measuring.py"),
            str(ROOT / "scripts/ratchet.py"),
            *THROUGH_UV,
            str(tmp_path / "step.py"),
            str(tmp_path),
        ],
        env={**os.environ, "TMPDIR": str(tmp_path)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + WITHIN
        while not (tmp_path / "started").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert (tmp_path / "started").exists(), "the step never started"
        run.send_signal(signal.SIGINT)
        assert run.wait(timeout=WITHIN) != 0
    finally:
        run.kill()
    return tmp_path


def test_a_stopped_measurement_stops_its_step_and_waits_for_it(tmp_path):
    """Ctrl-C on the ratchet reaches its step through the ratchet, which then waits."""
    here = _stop_a_step_under_uv(tmp_path)
    assert (here / "stops").exists(), "the ratchet never passed the stop on to its step"
    assert (here / "stops").read_text() != "0", "the ratchet never passed the stop on to its step"
    assert (here / "cleaned").exists(), "the ratchet ended before its step had cleaned up"


def test_a_stop_goes_to_the_step_alone_never_its_whole_group(tmp_path):
    """The Python under `uv run` hears the stop exactly once, passed on to it by uv.

    Sent to uv's whole process group instead, the stop would reach that Python twice, once
    from the ratchet and once through uv, and a second Ctrl-C cuts pytest's cleanup short.
    """
    here = _stop_a_step_under_uv(tmp_path)
    assert (here / "stops").read_text() == "1", "the Python under uv was not stopped exactly once"


class _Stopped(Exception):  # noqa: N818 - a stand-in for Ctrl-C that cannot stop the test run
    """What breaks the step's wait here: KeyboardInterrupt itself would end pytest's run."""


class _EndedJustAsStopped:
    """A step whose wait is broken by a stop, and whose process group is already gone."""

    pid = 4_000_000

    def __init__(self, *_args, **_kwargs):
        self.waits = 0

    def wait(self):
        self.waits += 1
        if self.waits == 1:
            raise _Stopped
        return 0

    def poll(self):
        return 0 if self.waits else None  # it ended as the stop broke the first wait


def test_a_step_that_has_just_ended_does_not_hide_the_stop(tmp_path, monkeypatch):
    ratchet = _load("ratchet_ended", ROOT / "scripts/ratchet.py", monkeypatch, tmp_path)
    steps = []
    monkeypatch.setattr(
        ratchet.subprocess, "Popen", lambda *a, **k: steps.append(_EndedJustAsStopped()) or steps[-1]
    )

    def gone(_pid, _signum):
        raise ProcessLookupError

    monkeypatch.setattr(ratchet.os, "kill", gone)
    with pytest.raises(_Stopped):
        ratchet._run("uv", "run", "python", "scripts/mutate.py")  # noqa: SLF001 - the step runner itself
    assert steps[0].waits == 2, "the step was not waited for after the stop"


class _StillRunning(_EndedJustAsStopped):
    """A step started with no session of its own: alive, with no process group to stop."""

    def poll(self):
        return None


def test_a_step_still_running_is_never_left_unstopped(tmp_path, monkeypatch):
    ratchet = _load("ratchet_running", ROOT / "scripts/ratchet.py", monkeypatch, tmp_path)
    monkeypatch.setattr(ratchet.subprocess, "Popen", lambda *a, **k: _StillRunning())

    def gone(_pid, _signum):
        raise ProcessLookupError

    monkeypatch.setattr(ratchet.os, "kill", gone)
    with pytest.raises(ProcessLookupError):
        ratchet._run("uv", "run", "python", "scripts/mutate.py")  # noqa: SLF001 - the step runner itself


def test_a_step_runs_in_a_session_of_its_own(tmp_path, monkeypatch):
    """So Ctrl-C in a terminal reaches it once, through the ratchet, and the ratchet can stop all of it."""
    ratchet = _load("ratchet_session", ROOT / "scripts/ratchet.py", monkeypatch, tmp_path)
    done = ratchet._run(sys.executable, "-c", "import os; print(os.getsid(0) == os.getpid())")  # noqa: SLF001
    assert done.stdout.strip() == "True"

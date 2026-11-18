# SPDX-License-Identifier: GPL-3.0-or-later
"""A held folder is locked while in use, and a sweep removes only what a killed holder left.

These are points 1 to 4 of the voice plugins' cleanup checklist, in `scripts/held_folder.py`.
"""

import fcntl
import importlib.util
import os
import pathlib
import sys
import tempfile
import time

import pytest
from bounded import run_bounded

ROOT = pathlib.Path(__file__).parent.parent
spec = importlib.util.spec_from_file_location("held_folder", ROOT / "scripts/held_folder.py")
held_folder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(held_folder)


def _killed(prefix, place):
    """A held folder whose holder died: its lock is there, and nobody holds it."""
    held = held_folder.HeldFolder(prefix, place)
    os.close(held._lock)  # noqa: SLF001 - a holder killed: its lock goes, its folder stays
    held._lock = None  # noqa: SLF001
    return held.path


def _aged(path, seconds):
    then = time.time() - seconds
    os.utime(path, (then, then))


def test_a_held_folder_is_locked_while_it_is_held(tmp_path):
    held = held_folder.HeldFolder("run-", tmp_path)
    other = os.open(held.path / held_folder.LOCK, os.O_RDONLY)
    try:
        with pytest.raises(BlockingIOError):
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(other)
        held.remove()
    assert not held.path.exists()


def test_a_held_folder_still_in_use_is_never_removed(tmp_path):
    held = held_folder.HeldFolder("run-", tmp_path)
    try:
        _aged(held.path, 2 * held_folder.GRACE_SECONDS)
        assert held_folder.sweep(tmp_path, "run-") == []
        assert held.path.is_dir()
    finally:
        held.remove()


def test_a_held_folder_a_killed_holder_left_is_removed_by_the_next_sweep(tmp_path):
    left = _killed("run-", tmp_path)
    (left / "shut").mkdir()
    (left / "shut/inside.txt").write_text("x")
    (left / "shut").chmod(0)
    assert held_folder.sweep(tmp_path, "run-") == [left.name]
    assert not left.exists()


def test_the_sweep_never_makes_a_lock(tmp_path):
    """A lock made by the sweep would stand in a new holder's folder before the holder locks it."""
    starting = tmp_path / "run-just-made"
    starting.mkdir()
    held_folder.sweep(tmp_path, "run-")
    assert list(starting.iterdir()) == []


def test_a_folder_with_no_lock_is_left_alone_for_an_hour(tmp_path):
    young, old = tmp_path / "run-young", tmp_path / "run-old"
    young.mkdir()
    old.mkdir()
    _aged(old, held_folder.GRACE_SECONDS + 60)
    assert held_folder.sweep(tmp_path, "run-") == ["run-old"]
    assert young.is_dir()


def test_a_sweep_passes_over_what_is_not_a_folder_of_its_own(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "kept.txt").write_text("x")
    _aged(outside, 2 * held_folder.GRACE_SECONDS)
    (tmp_path / "run-a-link").symlink_to(outside)
    (tmp_path / "run-a-file").write_text("x")
    other = _killed("other-", tmp_path)
    assert held_folder.sweep(tmp_path, "run-") == []
    assert (outside / "kept.txt").exists()
    assert other.is_dir()


def test_a_shared_folder_that_is_not_ours_stops_the_run(tmp_path):
    shared = tmp_path / "tv-mcp-mutate-12345678"
    shared.mkdir(mode=0o700)
    assert held_folder.ours(shared) == shared
    shared.chmod(0o777)
    with pytest.raises(SystemExit, match="chmod 700"):
        held_folder.ours(shared)


def test_an_older_folder_of_ours_is_closed_to_others_not_refused(tmp_path):
    """A folder made before this check, at 0755, keeps working: it is closed to 0700."""
    older = tmp_path / "tv-mcp-mutate-12345678"
    older.mkdir(mode=0o700)
    older.chmod(0o755)
    assert held_folder.ours(older) == older
    assert older.stat().st_mode & 0o777 == 0o700


def test_a_folder_of_ours_others_may_write_is_still_refused(tmp_path):
    """Others may already have put entries in it, so it is never taken over by closing it."""
    shared = tmp_path / "tv-mcp-mutate-12345678"
    shared.mkdir(mode=0o700)
    shared.chmod(0o775)
    with pytest.raises(SystemExit, match="chmod 700"):
        held_folder.ours(shared)
    assert shared.stat().st_mode & 0o777 == 0o775


def test_a_shared_folder_that_is_a_link_stops_the_run(tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(mode=0o700)
    (tmp_path / "tv-mcp-mutate-12345678").symlink_to(elsewhere)
    with pytest.raises(SystemExit, match="not a private folder of yours"):
        held_folder.ours(tmp_path / "tv-mcp-mutate-12345678")


def test_a_missing_shared_folder_is_made_private(tmp_path):
    made = held_folder.ours(tmp_path / "tv-mcp-mutate-12345678")
    assert made.stat().st_mode & 0o777 == 0o700


def _ratchet(monkeypatch, temp):
    monkeypatch.setenv("TMPDIR", str(temp))
    monkeypatch.setattr(tempfile, "tempdir", None)
    spec = importlib.util.spec_from_file_location("ratchet_sweep", ROOT / "scripts/ratchet.py")
    ratchet = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ratchet)
    ran = []
    monkeypatch.setattr(ratchet, "_run", lambda *command, **_: ran.append(command))
    return ratchet, ran


def test_a_killed_measurement_s_copy_is_swept_at_the_next_start(tmp_path, monkeypatch):
    ratchet, ran = _ratchet(monkeypatch, tmp_path)
    left = _killed(ratchet.HELD, tmp_path)
    (left / "base").mkdir()
    ratchet.sweep()
    assert not left.exists()
    assert ran == []  # no git command: the copy is a repository of its own, with no record here


def test_a_measurement_still_going_is_never_swept(tmp_path, monkeypatch):
    ratchet, ran = _ratchet(monkeypatch, tmp_path)
    with held_folder.HeldFolder(ratchet.HELD, tmp_path) as going:
        ratchet.sweep()
        assert pathlib.Path(going).is_dir()
    assert ran == []


def test_this_test_run_keeps_its_temporary_files_in_a_folder_it_holds():
    """tests/conftest.py gives each run a held folder, so a run started meanwhile leaves it alone."""
    here = pathlib.Path(tempfile.gettempdir())
    assert here.name.startswith("tv-mcp-tests-"), here
    assert (here / held_folder.LOCK).is_file()
    assert not held_folder.left_behind(here)


CHECKS_ITS_FOLDER = """
import pathlib, tempfile

def test_it_runs_in_a_held_folder():
    here = pathlib.Path(tempfile.gettempdir())
    assert here.name.startswith("tv-mcp-tests-") and (here / ".in-use").is_file()
"""


@pytest.mark.parametrize("sabotaged", [False, True], ids=["as it is", "its held folder switched off"])
def test_the_conftest_is_what_gives_a_run_its_held_folder(tmp_path, sabotaged):
    """Proof from outside, as mutate.py does not mutate tests/: without its step, a run has none."""
    conftest = (ROOT / "tests/conftest.py").read_text(encoding="utf-8")
    if sabotaged:
        conftest = conftest.replace("def pytest_configure(", "def _switched_off(")
    (tmp_path / "tests").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tests/conftest.py").write_text(conftest)
    (tmp_path / "tests/test_scratch.py").write_text(CHECKS_ITS_FOLDER)
    (tmp_path / "scripts/held_folder.py").write_text(
        (ROOT / "scripts/held_folder.py").read_text(encoding="utf-8")
    )
    temp = tmp_path / "tmp"
    temp.mkdir()
    done = run_bounded(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(tmp_path), "tests"],
        cwd=tmp_path,
        env={**os.environ, "TMPDIR": str(temp)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (done.returncode != 0) == sabotaged, done.stdout
    if not sabotaged:
        assert list(temp.iterdir()) == [], "the run's held folder was left behind"


def _script(name, path, monkeypatch, root):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", root)
    return module


def _checkout(tmp_path):
    root = tmp_path / "checkout"
    (root / "src/tv_mcp").mkdir(parents=True)
    (root / "src/tv_mcp/__init__.py").write_text("")
    return root


ELSEWHERE = "/somewhere/else/tv-mcp/src/tv_mcp/__init__.py\n"


def test_the_rule_check_never_measures_another_checkout_s_code(tmp_path, monkeypatch):
    root = _checkout(tmp_path)
    mutate = _script("mutate_checkout", ROOT / "scripts/mutate.py", monkeypatch, root)
    with pytest.raises(SystemExit, match="uv sync") as refused:
        mutate.same_checkout(lambda *_: ELSEWHERE)
    assert "/somewhere/else/tv-mcp/src/tv_mcp" in str(refused.value)
    assert str(root / "src/tv_mcp") in str(refused.value)
    mutate.same_checkout(lambda *_: str(root / "src/tv_mcp/__init__.py"))


def test_the_ratchet_never_measures_another_checkout_s_code(tmp_path, monkeypatch):
    root = _checkout(tmp_path)
    ratchet = _script("ratchet_checkout", ROOT / "scripts/ratchet.py", monkeypatch, root)
    with pytest.raises(SystemExit, match="uv sync"):
        ratchet.same_checkout(lambda *_: ELSEWHERE)
    ratchet.same_checkout(lambda *_: str(root / "src/tv_mcp/__init__.py"))


def _empty_checkout(tmp_path):
    root = tmp_path / "checkout"
    (root / "src").mkdir(parents=True)
    return root


def test_a_rule_check_refuses_a_checkout_with_no_package(tmp_path, monkeypatch):
    root = _empty_checkout(tmp_path)
    mutate = _script("mutate_empty", ROOT / "scripts/mutate.py", monkeypatch, root)
    with pytest.raises(SystemExit, match="no package") as refused:
        mutate.same_checkout(lambda *_: pytest.fail("there was nothing to ask about"))
    assert str(root / "src") in str(refused.value)


def test_a_measurement_refuses_a_checkout_with_no_package(tmp_path, monkeypatch):
    root = _empty_checkout(tmp_path)
    ratchet = _script("ratchet_empty", ROOT / "scripts/ratchet.py", monkeypatch, root)
    with pytest.raises(SystemExit, match="no package") as refused:
        ratchet.same_checkout(lambda *_: pytest.fail("there was nothing to ask about"))
    assert str(root / "src") in str(refused.value)


def test_this_checkout_s_tests_import_its_own_package():
    """Asked as the rule check asks it, in a subprocess: the real environment passes."""
    mutate = importlib.util.module_from_spec(
        spec := importlib.util.spec_from_file_location("mutate_here", ROOT / "scripts/mutate.py")
    )
    spec.loader.exec_module(mutate)
    mutate.same_checkout(mutate._python)  # noqa: SLF001 - the check as the run does it

# SPDX-License-Identifier: GPL-3.0-or-later
"""A mutation run, and the test suite itself, leave no temporary files behind.

`scripts/mutate.py` runs the whole suite once per rule, and every run made its
own pytest folder of temporary files. Over a day of runs those folders filled
the machine's temporary space until no program could start a command. Each run
now gets a folder of its own, outside the checkout, removed when the run ends;
whatever a killed run left is swept away at the next start.
"""

import importlib.util
import os
import pathlib
import sys

import pytest
from bounded import WITHIN

ROOT = pathlib.Path(__file__).parent.parent

LEAVES_FILES = """
import os

def test_it_writes_files_it_cannot_delete(tmp_path):
    (tmp_path / "plain.txt").write_text("x")
    (tmp_path / "locked.txt").write_text("x")
    os.chmod(tmp_path / "locked.txt", 0)
    (tmp_path / "shut").mkdir()
    (tmp_path / "shut" / "inside.txt").write_text("x")
    os.chmod(tmp_path / "shut", 0)
"""


def _mutate(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("mutate_temp", ROOT / "scripts/mutate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    project = tmp_path / "project"
    (project / "tests").mkdir(parents=True)
    (project / "tests" / "test_leaves_files.py").write_text(LEAVES_FILES)
    monkeypatch.setattr(module, "ROOT", project)
    monkeypatch.setattr(module, "MUTATE_TMP", tmp_path / "mutate-tmp")
    return module


def test_a_suite_run_leaves_no_temporary_files_behind(tmp_path, monkeypatch):
    mutate = _mutate(tmp_path, monkeypatch)
    failed, _ = mutate.run_suite(timeout=WITHIN)
    assert failed == 0
    assert list(mutate.MUTATE_TMP.iterdir()) == []


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows needs extra rights to make a link, and has no 0755"
)
def test_removing_a_run_s_files_never_changes_a_folder_it_links_to(tmp_path, monkeypatch):
    mutate = _mutate(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    outside.mkdir()
    outside.chmod(0o755)
    (outside / "kept.txt").write_text("x")
    (mutate.ROOT / "tests" / "test_links_out.py").write_text(
        f"def test_it_links_out(tmp_path):\n    (tmp_path / 'link').symlink_to({str(outside)!r})\n"
    )
    failed, _ = mutate.run_suite(timeout=WITHIN)
    assert failed == 0
    assert (outside.stat().st_mode & 0o777, (outside / "kept.txt").exists()) == (0o755, True)


def _held(mutate):
    """A run's folder in the rule check's own temporary folder, locked as a running one is."""
    return mutate.held_folder.HeldFolder("run-", mutate.held_folder.ours(mutate.MUTATE_TMP))


def test_a_killed_run_s_temporary_files_are_swept_at_the_next_start(tmp_path, monkeypatch):
    mutate = _mutate(tmp_path, monkeypatch)
    held = _held(mutate)
    (held.path / "shut").mkdir()
    (held.path / "shut" / "inside.txt").write_text("x")
    (held.path / "shut").chmod(0)
    os.close(held._lock)  # noqa: SLF001 - killed: the lock goes with the process, the folder stays
    mutate.sweep()
    assert not held.path.exists()


def test_a_sweep_never_removes_the_folder_of_a_run_still_going(tmp_path, monkeypatch):
    """Two rule checks of one checkout, or one started while another runs, used to do this."""
    mutate = _mutate(tmp_path, monkeypatch)
    held = _held(mutate)
    try:
        mutate.sweep()
        assert held.path.is_dir()
    finally:
        held.remove()


def test_a_rule_check_stops_at_a_shared_folder_that_is_not_its_own(tmp_path, monkeypatch):
    mutate = _mutate(tmp_path, monkeypatch)
    mutate.MUTATE_TMP.mkdir(mode=0o700)
    mutate.MUTATE_TMP.chmod(0o777)
    with pytest.raises(SystemExit, match=str(mutate.MUTATE_TMP)):
        mutate.sweep()


def test_the_temporary_files_live_outside_the_checkout():
    """Inside it, a test that makes a git repository of its own would find this one instead."""
    spec = importlib.util.spec_from_file_location("mutate_where", ROOT / "scripts/mutate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert ROOT.resolve() not in module.MUTATE_TMP.resolve().parents


def test_a_passing_test_keeps_no_temporary_files():
    settings = (ROOT / "pyproject.toml").read_text()
    assert 'tmp_path_retention_policy = "failed"' in settings
    assert "tmp_path_retention_count = 1" in settings

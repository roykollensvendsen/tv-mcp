# SPDX-License-Identifier: GPL-3.0-or-later
"""The ratchet measures main in a repository of its own, never in a worktree of this clone.

A worktree shares every branch of the clone, and git keeps a record of it that a killed run
leaves behind; pruning those records takes other sessions' with them. The bridge's form (#304).
"""

import importlib.util
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).parent.parent
WHO = ("-c", "user.name=t", "-c", "user.email=t@example.invalid")


def _ratchet(monkeypatch, root):
    spec = importlib.util.spec_from_file_location("ratchet_copy", ROOT / "scripts/ratchet.py")
    ratchet = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ratchet)
    monkeypatch.setattr(ratchet, "ROOT", root)
    return ratchet


def _git(where, *args):
    return subprocess.run(
        ["git", *args], cwd=where, capture_output=True, text=True, check=True
    ).stdout.strip()


def _clone(tmp_path, *messages):
    here = tmp_path / "clone"
    here.mkdir()
    _git(here, "init", "-q", "-b", "main")
    for message in messages:
        _git(here, *WHO, "commit", "-q", "--allow-empty", "-m", message)
    return here


def test_the_base_is_measured_where_no_other_branch_can_be_seen(monkeypatch, tmp_path):
    here = _clone(tmp_path, "base")
    _git(here, "branch", "under-review")
    ratchet = _ratchet(monkeypatch, here)
    copy = tmp_path / "copy"
    ratchet.copy_of("main", copy)
    assert _git(copy, "rev-parse", "HEAD") == _git(here, "rev-parse", "main")
    assert _git(copy, "for-each-ref") == ""
    assert _git(here, "worktree", "list").count("\n") == 0  # no record of the copy in the clone


def test_the_base_may_be_a_commit_no_branch_points_at(monkeypatch, tmp_path):
    """CI's base is main's commit when the pull request began, which main may have moved on from.

    git's newer protocol fetches such a commit by its id; the older one refuses it, so the test
    sets the older one, as an old git or a person's own settings would.
    """
    settings = tmp_path / "gitconfig"
    settings.write_text("[protocol]\n\tversion = 0\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(settings))
    here = _clone(tmp_path, "base", "later")
    behind = _git(here, "rev-parse", "main~1")
    ratchet = _ratchet(monkeypatch, here)
    copy = tmp_path / "copy"
    ratchet.copy_of(behind, copy)
    assert _git(copy, "rev-parse", "HEAD") == behind


def test_the_ratchet_never_prunes_this_clone_s_worktrees():
    """Another session's worktree, in a folder this process cannot see, would lose its record."""
    assert "prune" not in (ROOT / "scripts/ratchet.py").read_text()

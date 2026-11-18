# SPDX-License-Identifier: GPL-3.0-or-later
"""The bounded waits fail a test on time, and leave nothing of a stopped child running."""

import os
import subprocess
import sys
import time

import pytest
from bounded import line_within, run_bounded


def _gone(pid, within=10):
    """Whether `pid` has ended (and been reaped) within `within` seconds."""
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def test_a_child_that_overruns_fails_the_test_and_leaves_no_grandchild_running(tmp_path):
    """The grandchild holds stdout open, as a shell's or uv's child does, and is still stopped.

    Its own pid is what is checked: the shell's pid, or the group alone, would pass even
    with the grandchild still running.
    """
    said = tmp_path / "grandchild"
    started = time.monotonic()
    with pytest.raises(pytest.fail.Exception, match="still running after 1 s"):
        run_bounded(["sh", "-c", f"sleep 600 & echo $! > {said}; wait"], within=1, capture_output=True)
    assert time.monotonic() - started < 30
    assert _gone(int(said.read_text())), "the grandchild was left running"


def test_a_child_that_ends_in_time_gives_back_what_it_wrote():
    done = run_bounded([sys.executable, "-c", "print('hello')"], capture_output=True, text=True)
    assert (done.returncode, done.stdout) == (0, "hello\n")


def test_a_child_that_never_writes_a_line_fails_within_the_bound():
    with subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(600)"], stdout=subprocess.PIPE, text=True
    ) as child:
        try:
            started = time.monotonic()
            with pytest.raises(pytest.fail.Exception, match="no line came within 1 s"):
                line_within(child.stdout, 1)
            assert time.monotonic() - started < 30
        finally:
            child.kill()


def test_two_lines_written_at_once_are_both_read():
    """The second is already in the stream's buffer, where select() would not see it."""
    with subprocess.Popen(
        [sys.executable, "-c", "import sys, time; print('one\\ntwo', flush=True); time.sleep(600)"],
        stdout=subprocess.PIPE,
        text=True,
    ) as child:
        try:
            assert line_within(child.stdout, 10) == "one\n"
            assert line_within(child.stdout, 10) == "two\n"
        finally:
            child.kill()

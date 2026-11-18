# SPDX-License-Identifier: GPL-3.0-or-later
"""Waits a test sets a bound on itself, so a hang fails that test instead of the whole run.

A mutant that makes a program never end, or never write the line a test waits for, must
count as killed, the way a mutant that crashes does. So every child a test starts, and
every line it waits to read from one, has a bound the test sets, and running out fails
the test. The mutation run itself has no time limit, and never gets one.

`run_bounded` is about what is left behind, not about overrunning: `subprocess.run`'s own
`timeout=` kills only the child it started, and a grandchild (a shell's, or the Python
under `uv run`) keeps running into the next tests. So the child gets a process group of
its own, and the whole group is killed with SIGKILL, which cannot be caught and so is
never handled twice.
"""

import os
import queue
import signal
import subprocess
import threading
from typing import IO

import pytest

#: One bound for every wait a test makes: generous, so it fires only on a real hang.
WITHIN = 300


def run_bounded(cmd, within=WITHIN, **kwargs) -> subprocess.CompletedProcess:
    """`subprocess.run(cmd, **kwargs)`, but a child still running after `within` seconds fails the test.

    The child and everything it started are killed first, and what they wrote is in the failure.
    """
    check = kwargs.pop("check", False)
    if kwargs.pop("capture_output", False):
        kwargs["stdout"] = kwargs["stderr"] = subprocess.PIPE
    with subprocess.Popen(cmd, start_new_session=True, **kwargs) as child:
        try:
            out, err = child.communicate(timeout=within)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            out, err = child.communicate()
            pytest.fail(
                f"{cmd[0]} was still running after {within} s, so it and what it started were"
                f" stopped. It wrote:\n{out or ''}\n{err or ''}"
            )
    done = subprocess.CompletedProcess(child.args, child.returncode, out, err)
    if check:
        done.check_returncode()
    return done


def line_within(stream: IO[str], seconds: float = WITHIN) -> str:
    """The next line of a running child's `stream`; a failure, not a hang, if none comes in `seconds`.

    `readline()` runs on a thread of its own and is waited for through a queue. `select()`
    is not used: it sees the pipe, not the text already read into the stream's buffer, so
    it can wait for a line that has arrived. A thread left waiting ends when the test's
    cleanup stops the child, and as a daemon it never holds the run open.
    """
    lines: queue.Queue[str] = queue.Queue()
    threading.Thread(target=lambda: lines.put(stream.readline()), daemon=True).start()
    try:
        return lines.get(timeout=seconds)
    except queue.Empty:
        pytest.fail(f"no line came within {seconds} s")

# SPDX-License-Identifier: GPL-3.0-or-later
"""Checks and folders that hold over the whole test session, not one test.

Each run keeps every temporary file its tests make in one folder of its own: pytest's
folders, anything made with `tempfile`, and anything a program the tests start makes
under $TMPDIR. The run holds a lock on that folder while it lasts and removes it when it
ends; a killed run never gets that far, so the next run removes any such folder whose
lock nobody holds (`scripts/held_folder.py`). pytest's own sweep is not relied on: it
works on a folder every project on the machine shares.

The run also fails if a test changed the rule check's real recovery file.

`scripts/mutate.py` keeps the file it is mutating there while the suite runs. A
test that ran the runner without its own `RECOVERY` would overwrite or remove it,
and in the middle of a mutation run the original would be lost. Proven by
`tests/test_real_recovery_file_is_guarded.py`.
"""

import importlib.util
import os
import pathlib
import signal
import tempfile

import pytest

ROOT = pathlib.Path(__file__).parent.parent
RECOVERY = ROOT / "scripts/.mutate-recovery.json"
BEFORE = pytest.StashKey[bytes | None]()
#: This run's held folder, and $TMPDIR and tempfile's folder from before it.
RUN = pytest.StashKey[tuple[object, str | None, str | None]]()
PREFIX = "tv-mcp-tests-"
_spec = importlib.util.spec_from_file_location("held_folder", ROOT / "scripts/held_folder.py")
held_folder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(held_folder)


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    if config.option.basetemp:  # a run told where to keep them, as the rule check's are, keeps them there
        return
    before, cached = os.environ.get("TMPDIR"), tempfile.tempdir  # gettempdir() fills tempdir in
    temp = pathlib.Path(tempfile.gettempdir())
    held_folder.sweep(temp, PREFIX)
    held = held_folder.HeldFolder(PREFIX, temp)
    config.stash[RUN] = (held, before, cached)
    os.environ["TMPDIR"] = held.name
    tempfile.tempdir = held.name
    # A folder inside it: pytest empties its basetemp first, which would take the lock too.
    config.option.basetemp = str(held.path / "pytest")


def pytest_unconfigure(config: pytest.Config) -> None:
    run = config.stash.get(RUN, None)
    if run is None:
        return
    held, before, cached = run
    if before is None:
        os.environ.pop("TMPDIR", None)
    else:
        os.environ["TMPDIR"] = before
    tempfile.tempdir = cached
    held.remove()


def _now() -> bytes | None:
    return RECOVERY.read_bytes() if RECOVERY.is_file() else None


def pytest_sessionstart(session: pytest.Session) -> None:
    session.config.stash[BEFORE] = _now()


def pytest_sessionfinish(session: pytest.Session) -> None:
    if _now() != session.config.stash[BEFORE]:
        print(  # noqa: T201
            "\nA test changed scripts/.mutate-recovery.json, the rule check's real recovery file. "
            "A test that runs scripts/mutate.py must point RECOVERY at its own temporary file."
        )
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.fixture(autouse=True)
def _signal_handlers_kept():
    """A test that runs a script's `main()` installs its stop handlers in this process.

    Put the test run's own back afterwards, so Ctrl-C still stops pytest and a later
    test of those handlers starts from a process that has none.
    """
    stops = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    before = {each: signal.getsignal(each) for each in stops}
    yield
    for each, handler in before.items():
        signal.signal(each, handler)

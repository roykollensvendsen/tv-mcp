# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail the whole run if a test changed the rule check's real recovery file.

`scripts/mutate.py` keeps the file it is mutating there while the suite runs. A
test that ran the runner without its own `RECOVERY` would overwrite or remove it,
and in the middle of a mutation run the original would be lost. Proven by
`tests/test_real_recovery_file_is_guarded.py`.
"""

import pathlib

import pytest

ROOT = pathlib.Path(__file__).parent.parent
RECOVERY = ROOT / "scripts/.mutate-recovery.json"
BEFORE = pytest.StashKey[bytes | None]()


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

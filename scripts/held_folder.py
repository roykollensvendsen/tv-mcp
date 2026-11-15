# SPDX-License-Identifier: GPL-3.0-or-later
# ruff: noqa: INP001 - a module the scripts beside it import, not a package
"""A folder in the temporary folder, locked for as long as its holder runs.

A kill runs no cleanup, so whatever a killed holder was working in stays behind. Each holder
therefore keeps a lock open inside its folder, and whoever starts next sweeps away every
folder of its kind whose lock nobody holds. A lock is held by an open file, not by a process
number, so a holder in another process namespace, or a reused number, never fools the sweep.

Copied from the bridge's `src/claude_voice/held_folder.py`, the reference for every voice
plugin's cleanup (point 1 to 4 of the cleanup checklist in new-plugin-v8.md). `ours()` is
point 4, which the bridge does not need: a fixed-name folder in the shared temporary area
is checked to be this user's own before anything is put in it or swept from it.

The test run (`tests/conftest.py`), the rule check and the ratchet all work this way.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import shutil
import stat
import tempfile
import time
from pathlib import Path

#: The lock a held folder keeps open while it is in use.
LOCK = ".in-use"
#: How old a folder with no lock must be before it counts as left by a killed holder. A guess:
#: long enough for any holder to have gone from making its folder to locking it.
GRACE_SECONDS = 60 * 60


class HeldFolder:
    """A new folder named `prefix` and some letters, locked until `remove`."""

    def __init__(self, prefix: str, dir: Path | None = None) -> None:  # noqa: A002 - tempfile's name for it
        """Make the folder in `dir`, or in the temporary folder, and lock it."""
        self.path = Path(tempfile.mkdtemp(prefix=prefix, dir=dir))
        self.name = str(self.path)
        # Locked under another name, then renamed, so the lock's name never stands unlocked.
        starting = self.path / (LOCK + "-starting")
        self._lock: int | None = os.open(starting, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
        # RULE: a held folder is locked while it is held
        fcntl.flock(self._lock, fcntl.LOCK_EX)
        starting.rename(self.path / LOCK)

    def remove(self) -> bool:
        """Let go of the lock and remove the folder; say whether it is gone."""
        if self._lock is not None:
            os.close(self._lock)
            self._lock = None
        return remove(self.path)

    def __enter__(self) -> str:
        """Give the folder's name, as TemporaryDirectory does."""
        return self.name

    def __exit__(self, *_exc: object) -> None:
        """Remove the folder."""
        self.remove()


def left_behind(path: Path) -> bool:
    """Whether `path` is a held folder of this user's whose lock nobody holds."""
    try:
        # The first look is the one used: another sweep may remove the folder after it.
        found = path.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISDIR(found.st_mode) or found.st_uid != os.getuid():
        return False  # a link is never followed, and another user's folder never touched
    try:
        # Only a lock that is there is opened: one made here would stand in a new holder's
        # folder before the holder locks it, and its own rename onto it would then fail.
        # RULE: the sweep never makes a lock
        lock = os.open(path / LOCK, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        # Made before the lock existed, or by a holder killed between making it and locking it.
        # RULE: a folder with no lock is left alone for an hour
        return time.time() - found.st_mtime > GRACE_SECONDS
    except OSError:
        return False
    try:
        # RULE: a held folder still in use is never removed
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    finally:
        os.close(lock)
    return True


def sweep(place: Path, prefix: str) -> list[str]:
    """Remove every folder in `place` named `prefix`... whose holder is gone; name each one."""
    removed = []
    for path in sorted(place.glob(prefix + "*")):
        # RULE: a held folder a killed holder left is removed by the next sweep
        if left_behind(path):
            remove(path)
            removed.append(path.name)
    return removed


def remove(folder: Path) -> bool:
    """Delete a folder, giving back the rights to any part its holder shut; say whether it is gone."""
    for place, folders, _ in os.walk(folder):
        for name in folders:
            inner = Path(place) / name
            if not inner.is_symlink():
                with contextlib.suppress(OSError):
                    inner.chmod(inner.stat().st_mode | stat.S_IRWXU)
    shutil.rmtree(folder, ignore_errors=True)
    return not folder.exists()


def ours(folder: Path) -> Path:
    """Make `folder` if it is missing, and stop unless it is a private folder of this user's.

    It stands in the temporary area every user shares, under a name anyone can guess, so
    someone else could have put a link or a folder of their own there first. It is opened
    without following a link and checked as opened, so it cannot be swapped in between.
    """
    with contextlib.suppress(FileExistsError):
        folder.mkdir(mode=0o700)
    try:
        opened = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError:
        found = None
    else:
        try:
            found = os.fstat(opened)
        finally:
            os.close(opened)
    # RULE: a shared folder that is not ours stops the run
    if found is None or found.st_uid != os.getuid() or found.st_mode & 0o077:
        msg = (
            f"{folder} is not a private folder of yours: it is a link, someone else's, or open"
            " to other users, so nothing is put in it or removed from it. Look at it with"
            f" `ls -ld {folder}`. If it is yours, close it with `chmod 700 {folder}`; if not,"
            " remove it, or ask whoever owns it to, and run this again."
        )
        raise SystemExit(msg)
    return folder

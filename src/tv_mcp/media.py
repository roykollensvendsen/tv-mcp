# SPDX-License-Identifier: GPL-3.0-or-later
"""What the core asks of a media library such as Jellyfin: the library interface.

A library finds films and episodes, lists the apps connected to it (its
sessions), and tells one of them to play something. The core reaches it only
through this interface; ``drivers/jellyfin.py`` is the first implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class MediaItem:
    """A film or an episode."""

    id: str
    title: str
    year: int | None
    kind: str
    position: float | None = None  # seconds in, where it was stopped
    runtime: float | None = None  # seconds long
    last_played: str | None = None  # the date, as YYYY-MM-DD


@dataclass(frozen=True)
class Session:
    """An app connected to the library, such as Jellyfin on a TV."""

    id: str
    address: str | None
    client: str
    controllable: bool
    now_playing: str | None = None  # the title playing, if any
    position: float | None = None  # seconds in
    runtime: float | None = None  # seconds long
    paused: bool = False


@dataclass(frozen=True)
class CastLogin:
    """What a cast device needs to fetch films from the library as one of its users."""

    server: str  # an address the device itself can reach
    token: str  # a user's own login, not the server's key
    user_id: str
    server_id: str
    version: str | None = None


class MediaLibrary(Protocol):
    """A library of films and episodes that can start one on a connected app."""

    async def search(self, term: str) -> list[MediaItem]:
        """Items whose title matches `term`, best first; empty when the library does not answer."""
        ...

    async def sessions(self) -> list[Session]:
        """The apps connected to the library now."""
        ...

    async def play(self, session_id: str, item_id: str, start: float = 0.0) -> None:
        """Start `item_id` at once in the app with `session_id`, `start` seconds in."""
        ...

    async def control(self, session_id: str, command: str) -> None:
        """Send `command` (one of COMMANDS) to what the app is playing."""
        ...


#: What can be done to something playing.
COMMANDS = ("pause", "resume", "stop")


def spoken_time(seconds: float) -> str:
    """A length of time as it is said: "1 h 12 min", "49 min"."""
    minutes = int(seconds // 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if hours else f"{minutes} min"

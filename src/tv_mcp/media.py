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


@dataclass(frozen=True)
class Session:
    """An app connected to the library, such as Jellyfin on a TV."""

    id: str
    address: str | None
    client: str
    controllable: bool


class MediaLibrary(Protocol):
    """A library of films and episodes that can start one on a connected app."""

    async def search(self, term: str) -> list[MediaItem]:
        """Items whose title matches `term`, best first; empty when the library does not answer."""
        ...

    async def sessions(self) -> list[Session]:
        """The apps connected to the library now."""
        ...

    async def play(self, session_id: str, item_id: str) -> None:
        """Start `item_id` at once in the app with `session_id`."""
        ...

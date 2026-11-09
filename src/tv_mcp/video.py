# SPDX-License-Identifier: GPL-3.0-or-later
"""What the core asks of a video site such as YouTube: finding videos and starting one.

The core reaches YouTube only through these interfaces; ``drivers/youtube.py``
is the implementation. A TV driver that can show YouTube says so by having
``youtube_screen`` (tv_mcp.driver.ShowsYouTube).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")


@dataclass(frozen=True)
class Video:
    """A video on the site."""

    id: str
    title: str
    channel: str | None
    duration: float | None  # seconds long


def is_video_id(words: str) -> bool:
    """Whether `words` is a video's id rather than words to search for."""
    return bool(_VIDEO_ID.fullmatch(words)) and not words.isalpha()


class VideoSearch(Protocol):
    """Finds videos by words."""

    async def search(self, words: str) -> list[Video]:
        """Videos matching `words`, best first; empty when nothing was found."""
        ...


class Lounge(Protocol):
    """Starts a video in the YouTube app on a screen, as the phone app does."""

    async def play(self, tv_key: str, screen_id: str, video_id: str) -> bool:
        """Start `video_id` on the screen; True only once the screen says it plays it."""
        ...

# SPDX-License-Identifier: GPL-3.0-or-later
"""What the core asks of a media library such as Jellyfin: the library interface.

A library finds films and episodes, lists the apps connected to it (its
sessions), and tells one of them to play something. The core reaches it only
through this interface; ``drivers/jellyfin.py`` is the first implementation.
"""

from __future__ import annotations

import re
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
    item_id: str | None = None  # the id of what is playing, if any


@dataclass(frozen=True)
class Cue:
    """One subtitle: when it shows, and its words on one line."""

    start: float  # seconds in
    end: float
    text: str


@dataclass(frozen=True)
class Chapter:
    """A chapter of a film: where it starts, and its name."""

    start: float  # seconds in
    name: str


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

    async def seek(self, session_id: str, seconds: float) -> None:
        """Move what the app is playing to `seconds` from its start."""
        ...

    async def subtitles(self, item_id: str) -> list[Cue] | None:
        """The item's subtitles, from a track for the hard of hearing when it has one; None without any."""
        ...

    async def cast(self, item_id: str) -> list[tuple[str, str]]:
        """Each character in the item with the actor who plays them."""
        ...

    async def chapters(self, item_id: str) -> list[Chapter]:
        """The item's chapters, in order; empty when it has none."""
        ...


#: What can be done to something playing.
COMMANDS = ("pause", "resume", "stop")


def spoken_time(seconds: float) -> str:
    """A length of time as it is said: "1 h 12 min", "49 min"."""
    minutes = int(seconds // 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if hours else f"{minutes} min"


_TIME = re.compile(r"(\d+):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d+):(\d{2}):(\d{2})[,.](\d{3})")
_MARKUP = re.compile(r"<[^>]+>|\{[^}]*\}")

#: How much subtitle text a scene gives at most, so the voice sums it up
#: rather than reading dialogue aloud.
SCENE_LIMIT = 1200


def _at(hours: str, minutes: str, seconds: str, millis: str) -> float:
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def parse_srt(text: str) -> list[Cue]:
    """The cues of an SRT file, in order, with markup taken out and lines joined."""
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = block.split("\n")
        for index, line in enumerate(lines):
            if found := _TIME.search(line):
                words = " ".join(_MARKUP.sub("", w).strip() for w in lines[index + 1 :])
                if words.strip():
                    groups = found.groups()
                    cues.append(Cue(_at(*groups[:4]), _at(*groups[4:]), " ".join(words.split())))
                break
    return cues


def _clock(seconds: float) -> str:
    minutes, rest = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{rest:02}" if hours else f"{minutes}:{rest:02}"


def scene_lines(cues: list[Cue], position: float, window: float, limit: int = SCENE_LIMIT) -> list[str]:
    """The cues within `window` seconds either side of `position`, each with its time.

    When they come to more than `limit` characters, those nearest the position are kept.
    """
    near = [c for c in cues if position - window <= c.start <= position + window]
    kept: list[Cue] = []
    size = 0
    for cue in sorted(near, key=lambda c: abs(c.start - position)):
        line = f"{_clock(cue.start)} {cue.text}"
        if size + len(line) > limit:
            break
        kept.append(cue)
        size += len(line)
    return [f"{_clock(c.start)} {c.text}" for c in sorted(kept, key=lambda c: c.start)]


_NUMBERED = re.compile(r"(chapter|kapittel|scene)?\s*\d+", re.IGNORECASE)
#: How long a stretch of a film one line of its outline covers, and the outline's size.
OUTLINE_EVERY = 300
OUTLINE_LIMIT = 3000


def named(chapters: list[Chapter]) -> bool:
    """Whether the chapters have names that say something, not "Chapter 3"."""
    return any(c.name.strip() and not _NUMBERED.fullmatch(c.name.strip()) for c in chapters)


def outline(cues: list[Cue], every: float = OUTLINE_EVERY, limit: int = OUTLINE_LIMIT) -> list[str]:
    """One line per stretch of `every` seconds: its start, and its first words, `limit` characters in all."""
    if not cues:
        return []
    stretches = int(max(c.start for c in cues) // every) + 1
    room = limit // stretches
    lines = []
    for index in range(stretches):
        words = " ".join(c.text for c in cues if index * every <= c.start < (index + 1) * every)
        if not words:
            continue
        line = f"{_clock(index * every)} {words}"
        lines.append(line[:room].rstrip())
    return lines

# SPDX-License-Identifier: GPL-3.0-or-later
"""A simulated home with one Frame TV, for tests and for a first try by voice.

It uses the addresses set aside for documentation, so nothing here is anyone's
real network, and it never touches the network.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, ClassVar

from tv_mcp.driver import TvInfo
from tv_mcp.media import Chapter, Cue, MediaItem, Session
from tv_mcp.service import TvService
from tv_mcp.settings import Settings, Tv

if TYPE_CHECKING:
    from collections.abc import Callable

FRAME_ADDRESS = "192.0.2.10"
SIMULATED_TVS = (Tv(key="living-room", names=("the living room", "The Frame"), address=FRAME_ADDRESS),)
FRAME = TvInfo(
    name="Samsung The Frame 55 (simulated)",
    model="QE55LS03BAUXXC",
    year=2022,
    platform="Tizen 6.5",
    power="on",
    art_mode_capable=True,
    developer_mode=True,
)


class SimulatedTv:
    """A driver for one simulated Frame; the fake TV a contributor's tests can use too."""

    key = "samsung-tizen"
    ssdp_target = "urn:example:simulated-tv"

    apps: ClassVar[dict[str, str]] = {"jellyfin": "sim.Jellyfin"}
    #: What the simulated Frame says its power is; switching changes it.
    power = "on"

    async def switch(self, tv: Tv, *, on: bool) -> bool:
        """Pretend to switch the TV, when it has an address to reach."""
        if tv.address is None:
            return False
        self.power = "on" if on else "standby"
        return True

    async def open_app(self, address: str, app_id: str) -> bool:  # noqa: ARG002 - nothing to open
        """Pretend to open the app."""
        return True

    async def close_app(self, address: str, app_id: str, *, tv_key: str | None = None) -> bool:  # noqa: ARG002 - nothing to close
        """Pretend to close the app."""
        return True

    def recognises(self, announcement: bytes) -> bool:  # noqa: ARG002 - the simulated TV is always heard
        """Every announcement counts."""
        return True

    async def read_info(self, address: str) -> TvInfo | None:
        """The simulated Frame, at its one address."""
        return replace(FRAME, power=self.power) if address == FRAME_ADDRESS else None


class SimulatedLibrary:
    """A simulated Jellyfin with a few films, connected to the simulated Frame."""

    items = (
        MediaItem(id="sim-4", title="Star Wars: Episode IV - A New Hope", year=1977, kind="Movie"),
        MediaItem(
            id="sim-5", title="Star Wars: Episode V - The Empire Strikes Back", year=1980, kind="Movie"
        ),
        MediaItem(id="sim-r1", title="Rogue One: A Star Wars Story", year=2016, kind="Movie"),
    )

    def __init__(self) -> None:
        """Nothing played yet."""
        self.played: list[tuple[str, str]] = []

    async def search(self, term: str) -> list[MediaItem]:
        """Items whose title holds every word of `term`."""
        words = term.casefold().split()
        return [i for i in self.items if all(w in i.title.casefold() for w in words)]

    async def sessions(self) -> list[Session]:
        """Jellyfin open on the simulated Frame."""
        return [
            Session(id="sim-session", address=FRAME_ADDRESS, client="Jellyfin for Tizen", controllable=True)
        ]

    async def seek(self, session_id: str, seconds: float) -> None:
        """Remember where it was moved to."""
        self.played.append((session_id, f"seek {seconds}"))

    async def subtitles(self, item_id: str) -> list[Cue] | None:  # noqa: ARG002 - one film's lines for all
        """A couple of made-up lines."""
        return [Cue(60.0, 62.0, "Hello there."), Cue(90.0, 92.0, "General Kenobi.")]

    async def chapters(self, item_id: str) -> list[Chapter]:  # noqa: ARG002 - one film's chapters for all
        """Two made-up chapters."""
        return [Chapter(0.0, "Opening"), Chapter(60.0, "The cantina")]

    async def cast(self, item_id: str) -> list[tuple[str, str]]:  # noqa: ARG002 - one cast for all
        """A made-up cast."""
        return [("Ben", "Example Actor")]

    async def play(self, session_id: str, item_id: str, start: float = 0.0) -> None:  # noqa: ARG002 - the simulator starts at the top
        """Remember what was played."""
        self.played.append((session_id, item_id))

    async def control(self, session_id: str, command: str) -> None:
        """Remember the command."""
        self.played.append((session_id, command))


async def _listen(recognises: Callable[[bytes], bool], target: str | None) -> list[str]:  # noqa: ARG001
    return [FRAME_ADDRESS]


def simulated_service() -> TvService:
    """The service wired to the simulated Frame."""
    return TvService(
        Settings(tvs=SIMULATED_TVS),
        drivers={"samsung-tizen": SimulatedTv()},
        listen=_listen,
        library=SimulatedLibrary(),
    )

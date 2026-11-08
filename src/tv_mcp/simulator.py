# SPDX-License-Identifier: GPL-3.0-or-later
"""A simulated home with one Frame TV, for tests and for a first try by voice.

It uses the addresses set aside for documentation, so nothing here is anyone's
real network, and it never touches the network.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from tv_mcp.driver import TvInfo
from tv_mcp.media import MediaItem, Session
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

    async def switch(self, tv: Tv, *, on: bool) -> bool:  # noqa: ARG002 - nothing to switch
        """Pretend to switch the TV."""
        return True

    async def close_app(self, address: str, app_id: str) -> bool:  # noqa: ARG002 - nothing to close
        """Pretend to close the app."""
        return True

    def recognises(self, announcement: bytes) -> bool:  # noqa: ARG002 - the simulated TV is always heard
        """Every announcement counts."""
        return True

    async def read_info(self, address: str) -> TvInfo | None:
        """The simulated Frame, at its one address."""
        return FRAME if address == FRAME_ADDRESS else None


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

    async def play(self, session_id: str, item_id: str) -> None:
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

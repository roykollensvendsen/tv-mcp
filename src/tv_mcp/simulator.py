# SPDX-License-Identifier: GPL-3.0-or-later
"""A simulated home with one Frame TV, for tests and for a first try by voice.

It uses the addresses set aside for documentation, so nothing here is anyone's
real network, and it never touches the network.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tv_mcp.driver import TvInfo
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

    def recognises(self, announcement: bytes) -> bool:  # noqa: ARG002 - the simulated TV is always heard
        """Every announcement counts."""
        return True

    async def read_info(self, address: str) -> TvInfo | None:
        """The simulated Frame, at its one address."""
        return FRAME if address == FRAME_ADDRESS else None


async def _listen(recognises: Callable[[bytes], bool], target: str | None) -> list[str]:  # noqa: ARG001
    return [FRAME_ADDRESS]


def simulated_service() -> TvService:
    """The service wired to the simulated Frame."""
    return TvService(Settings(tvs=SIMULATED_TVS), drivers={"samsung-tizen": SimulatedTv()}, listen=_listen)

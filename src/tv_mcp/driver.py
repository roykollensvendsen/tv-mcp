# SPDX-License-Identifier: GPL-3.0-or-later
"""What the core asks of a TV, whatever its brand: the driver interface.

A driver is the one place that knows a brand or platform (Samsung Tizen, and
later LG webOS, Google TV or Roku). The core, meaning every module under
``tv_mcp/`` except ``drivers/`` and the ``cli`` that wires them together, only
ever sees this interface. It never imports a driver;
``tests/test_layers.py`` refuses a change that does.

Every method only reads, and none may make a sound, show anything on the
screen or ask the owner to allow a connection. The methods that will change
something come with the slices that need them, each with its own safety rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TvInfo:
    """What a TV says about itself, in the core's words."""

    name: str | None
    model: str | None
    year: int | None
    platform: str | None  # for example "Tizen 6.5"
    power: str  # "on", "standby" or "unknown"
    art_mode_capable: bool = False
    developer_mode: bool = False


class Driver(Protocol):
    """One brand or platform of TV."""

    #: The value of ``driver`` in the settings file that picks this driver.
    key: str
    #: The SSDP service a full search asks for, so only this driver's TVs answer.
    ssdp_target: str

    def recognises(self, announcement: bytes) -> bool:
        """Whether an SSDP announcement or answer comes from a TV this driver handles."""
        ...

    async def read_info(self, address: str) -> TvInfo | None:
        """The TV's own description of itself, or None when it does not answer."""
        ...

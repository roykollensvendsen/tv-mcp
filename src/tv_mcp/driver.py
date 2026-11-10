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
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping

    from tv_mcp.media import MediaItem
    from tv_mcp.settings import Tv


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
    #: The TV's own lasting id, which tells two TVs of one model apart.
    device_id: str | None = None
    brand: str | None = None
    product_line: str | None = None  # for example "The Frame"


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


class ClosesApps(Protocol):
    """A driver that can also close an app on its TV."""

    #: The apps it knows, by lower-case spoken name, with the TV's id for each.
    apps: Mapping[str, str]

    async def close_app(self, address: str, app_id: str, *, tv_key: str | None = None) -> bool:
        """Close the app; False when the TV did not do it."""
        ...


class OpensApps(Protocol):
    """A driver that can also open an app on its TV."""

    #: The apps it knows, by lower-case spoken name, with the TV's id for each.
    apps: Mapping[str, str]

    async def open_app(self, address: str, app_id: str) -> bool:
        """Open the app; False when the TV did not do it."""
        ...


class Casts(Protocol):
    """A driver whose device plays library items itself, as a Chromecast does."""

    async def cast(self, address: str, item: MediaItem, start: float) -> bool:
        """Start `item`, `start` seconds in; False when it did not start."""
        ...

    async def cast_control(self, address: str, command: str) -> bool:
        """Pause, resume or stop it (tv_mcp.media.COMMANDS); False when it did not."""
        ...

    async def cast_seek(self, address: str, seconds: float) -> bool:
        """Move it to `seconds` from its start; False when it did not."""
        ...


class Switches(Protocol):
    """A driver that can switch its TV on or off."""

    async def switch(self, tv: Tv, *, on: bool) -> bool:
        """Switch `tv` on or off; False when it did not answer."""
        ...


#: The inputs a TV can be asked to show, each with how it is said aloud.
INPUTS = {"hdmi1": "HDMI 1", "hdmi2": "HDMI 2", "hdmi3": "HDMI 3", "hdmi4": "HDMI 4", "tv": "the aerial"}


@runtime_checkable
class ChangesInput(Protocol):
    """A driver that can change which input its TV shows."""

    async def show_input(self, tv: Tv, source: str) -> bool:
        """Show `source`, one of ``INPUTS``, on `tv`; False when it did not answer."""
        ...


@runtime_checkable
class WakesScreen(Protocol):
    """A device in a TV, such as a Chromecast, that wakes the TV over HDMI (HDMI-CEC)."""

    async def wake_screen(self, address: str) -> bool:
        """Ask the TV it is in to switch on; False when the device did not answer."""
        ...

    async def screen_on(self, address: str) -> bool | None:
        """Whether that TV is on, as HDMI tells the device; None when it does not know."""
        ...


@runtime_checkable
class ShowsYouTube(Protocol):
    """A driver whose TVs can show YouTube."""

    async def youtube_screen(self, address: str) -> str | None:
        """Open YouTube on the TV and give its screen id, or None when it did not open."""
        ...


@runtime_checkable
class HasSound(Protocol):
    """A driver that can mute its TVs and set their volume, 0 to 100."""

    async def volume(self, address: str) -> int | None:
        """The volume now, or None when the TV does not say."""
        ...

    async def muted(self, address: str) -> bool | None:
        """Whether the sound is off, or None when the TV does not say."""
        ...

    async def set_volume(self, address: str, level: int) -> bool:
        """Set the volume; False when the TV did not take it."""
        ...

    async def set_mute(self, address: str, *, on: bool) -> bool:
        """Mute or unmute; False when the TV did not take it."""
        ...


@dataclass(frozen=True)
class Playing:
    """What plays on a TV, in whatever app is in front."""

    app: str | None
    title: str | None = None
    position: float | None = None  # seconds in
    runtime: float | None = None  # seconds long
    paused: bool = False


#: What a player says to a command: done, the app cannot do it, or no answer.
DONE, UNSUPPORTED, NO_ANSWER = "done", "unsupported", "no answer"


@runtime_checkable
class HasPlayer(Protocol):
    """A driver that can see and control what plays in any app, not only Jellyfin."""

    async def playing(self, address: str) -> Playing | None:
        """What plays in the app in front, or None when nothing does."""
        ...

    async def player(self, tv: Tv, command: str, seconds: float | None = None) -> str:
        """Pause, resume, stop, or seek to `seconds` on `tv`: DONE, UNSUPPORTED or NO_ANSWER."""
        ...

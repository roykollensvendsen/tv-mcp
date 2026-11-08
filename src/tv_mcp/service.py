# SPDX-License-Identifier: GPL-3.0-or-later
"""What the tools do, in words that know no brand of TV.

Each TV is reached through the driver its settings name (tv_mcp.driver), and
the network is passed in, so the tests need neither a TV nor a network.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from tv_mcp.settings import AmbiguousTvError, Settings, Tv, UnknownTvError, find_tv

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from tv_mcp.driver import Driver, TvInfo

LEFT_ALONE = "left alone"


class Listen(Protocol):
    """Addresses of the TVs `recognises` accepts; `target` set also searches for that service."""

    async def __call__(self, recognises: Callable[[bytes], bool], target: str | None) -> list[str]: ...  # noqa: D102


class TvService:
    """Status and discovery for the TVs in the settings."""

    def __init__(self, settings: Settings, *, drivers: Mapping[str, Driver], listen: Listen) -> None:
        """Reach each TV through `drivers`, by key, and find TVs with `listen`."""
        self.settings, self.drivers, self._listen = settings, drivers, listen

    async def _read(self, tv: Tv) -> dict[str, Any]:
        # RULE: a hands-off TV is never contacted
        if tv.hands_off or tv.address is None:
            return {"tv": tv.spoken, "state": LEFT_ALONE if tv.hands_off else "no address set"}
        driver = self.drivers.get(tv.driver)
        if driver is None:
            return {"tv": tv.spoken, "state": "refused", "say": f"No driver {tv.driver!r} is switched on."}
        return _report(tv, await driver.read_info(tv.address))

    async def status(self, name: str | None) -> list[dict[str, Any]]:
        """One report per TV, or for the one named."""
        if name is None:
            return [await self._read(tv) for tv in self.settings.tvs]
        try:
            tv = find_tv(self.settings, name)
        except (UnknownTvError, AmbiguousTvError) as refusal:
            return [{"tv": name, "state": "refused", "say": str(refusal)}]
        return [await self._read(tv)]

    async def discover(self, *, full: bool) -> dict[str, Any]:
        """The TVs in the settings, and any others that announced themselves."""
        known = {tv.address for tv in self.settings.tvs if tv.address}
        reports = [await self._read(tv) for tv in self.settings.tvs]
        for driver in self.drivers.values():
            heard = await self._listen(driver.recognises, driver.ssdp_target if full else None)
            for address in dict.fromkeys(heard):
                if address not in known:
                    known.add(address)
                    reports.append(_report(None, await driver.read_info(address)))
        return {"searched": full, "tvs": reports}


def _report(tv: Tv | None, info: TvInfo | None) -> dict[str, Any]:
    name = tv.spoken if tv else None
    if info is None:
        return {"tv": name, "state": "off or not reachable"}
    state = info.power
    if state == "standby" and info.art_mode_capable:
        state = "standby or art mode"
    return {
        "tv": name,
        "state": state,
        "model": info.model,
        "year": info.year,
        "platform": info.platform,
        "developer_mode": info.developer_mode,
    }

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
    from tv_mcp.media import MediaItem, MediaLibrary

LEFT_ALONE = "left alone"


class Listen(Protocol):
    """Addresses of the TVs `recognises` accepts; `target` set also searches for that service."""

    async def __call__(self, recognises: Callable[[bytes], bool], target: str | None) -> list[str]: ...  # noqa: D102


class TvService:
    """Status and discovery for the TVs in the settings."""

    def __init__(
        self,
        settings: Settings,
        *,
        drivers: Mapping[str, Driver],
        listen: Listen,
        library: MediaLibrary | None = None,
    ) -> None:
        """Reach each TV through `drivers`, by key, find TVs with `listen`, and films in `library`."""
        self.settings, self.drivers, self._listen, self.library = settings, drivers, listen, library

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

    async def search(self, term: str) -> dict[str, Any]:
        """Films and episodes matching `term`."""
        if self.library is None:
            return {"items": [], "say": NO_LIBRARY}
        found = await self.library.search(term)
        return {"items": [{"title": i.title, "year": i.year, "kind": i.kind} for i in found]}

    async def play(self, title: str, name: str) -> dict[str, Any]:
        """Start `title` on the TV called `name`, through Jellyfin on that TV."""
        try:
            tv = find_tv(self.settings, name)
        except (UnknownTvError, AmbiguousTvError) as refusal:
            return _refused(str(refusal))
        if tv.hands_off:
            return _refused(f"{tv.spoken} is left alone; nothing is sent to it.")
        if self.library is None:
            return _refused(NO_LIBRARY)
        found = await self.library.search(title)
        chosen = _choose(title, found)
        if not isinstance(chosen, str):
            return chosen
        session = next(
            (s for s in await self.library.sessions() if s.address == tv.address and s.controllable), None
        )
        if session is None:
            return _refused(f"Jellyfin is not open on {tv.spoken}. Open it there first.")
        item = next(i for i in found if i.id == chosen)
        await self.library.play(session.id, item.id)
        return {"outcome": "playing", "say": f"Playing {_spoken(item)} on {tv.spoken}."}


NO_LIBRARY = "Jellyfin is not set up: the settings file has no [jellyfin] url and api_key."


def _refused(say: str) -> dict[str, Any]:
    return {"outcome": "refused", "say": say}


def _spoken(item: MediaItem) -> str:
    return f"{item.title} ({item.year})" if item.year else item.title


def _choose(title: str, found: list[MediaItem]) -> str | dict[str, Any]:
    """The id of the one item meant, or a refusal that says what there is."""
    if not found:
        return _refused(f"Found nothing called {title!r}.")
    exact = [i for i in found if i.title.casefold() == title.casefold()]
    if len(exact) == 1:
        return exact[0].id
    if len(found) == 1:
        return found[0].id
    options = "; ".join(_spoken(i) for i in found[:3])
    # RULE: a title that matches several items is refused, naming them
    return _refused(f"{title!r} could be: {options}. Which one?")


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

# SPDX-License-Identifier: GPL-3.0-or-later
"""What the tools do, in words that know no brand of TV.

Each TV is reached through the driver its settings name (tv_mcp.driver), and
the network is passed in, so the tests need neither a TV nor a network.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Protocol, cast

from tv_mcp.media import COMMANDS, spoken_time
from tv_mcp.settings import AmbiguousTvError, Settings, Tv, UnknownTvError, find_tv

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from tv_mcp.driver import Casts, ClosesApps, Driver, OpensApps, TvInfo
    from tv_mcp.media import MediaItem, MediaLibrary, Session

LEFT_ALONE = "left alone"
ANOTHER_TV = "another TV answers there"


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
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Reach each TV through `drivers`, by key, find TVs with `listen`, and films in `library`."""
        self.settings, self.drivers, self._listen, self.library = settings, drivers, listen, library
        self._sleep = sleep

    async def _read(self, tv: Tv) -> dict[str, Any]:
        # RULE: a hands-off TV is never contacted
        if tv.hands_off or tv.address is None:
            return {**_known(tv), "state": LEFT_ALONE if tv.hands_off else "no address set"}
        driver = self.drivers.get(tv.driver)
        if driver is None:
            return {"tv": tv.spoken, "state": "refused", "say": f"No driver {tv.driver!r} is switched on."}
        info = await driver.read_info(tv.address)
        # RULE: a TV that answers as another device is not acted on
        if info is not None and tv.device_id and info.device_id != tv.device_id:
            return {"tv": tv.spoken, "state": ANOTHER_TV, "say": _another(tv)}
        return _report(tv, info)

    async def _itself(self, tv: Tv) -> dict[str, Any] | None:
        """A refusal when another TV answers at `tv`'s address; None when it is `tv` or cannot tell."""
        if not tv.device_id:
            return None
        report = await self._read(tv)
        return _refused(_another(tv)) if report["state"] == ANOTHER_TV else None

    async def status(self, name: str | None) -> list[dict[str, Any]]:
        """One report per TV, or for the one named."""
        if name is None:
            tvs = list(self.settings.tvs)
        else:
            try:
                tvs = [find_tv(self.settings, name)]
            except (UnknownTvError, AmbiguousTvError) as refusal:
                return [{"tv": name, "state": "refused", "say": str(refusal)}]
        reports = [await self._read(tv) for tv in tvs]
        sessions = await self.library.sessions() if self.library else []
        for tv, report in zip(tvs, reports, strict=True):
            watching = next((s for s in sessions if s.address == tv.address and s.now_playing), None)
            if watching and not tv.hands_off:
                report["playing"] = _playing(watching)
        return reports

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
        return {"items": [_found(i) for i in found]}

    def _target(self, name: str) -> Tv | dict[str, Any]:
        """The TV to act on, or a refusal: unknown, ambiguous, left alone, or no library."""
        try:
            tv = find_tv(self.settings, name)
        except (UnknownTvError, AmbiguousTvError) as refusal:
            return _refused(str(refusal))
        # RULE: a hands-off TV is never played on or controlled
        if tv.hands_off:
            return _refused(f"{tv.spoken} is left alone; nothing is sent to it.")
        if self.library is None:
            return _refused(NO_LIBRARY)
        return tv

    def _caster(self, tv: Tv) -> Casts | None:
        """The driver, when its device plays films itself (a Chromecast)."""
        driver = self.drivers.get(tv.driver)
        return cast("Casts", driver) if callable(getattr(driver, "cast", None)) else None

    async def _cast(self, caster: Casts, tv: Tv, item: MediaItem) -> dict[str, Any]:
        """Cast `item` to `tv`, from where it was stopped."""
        if not await caster.cast(tv.address or "", item, item.position or 0.0):
            return _refused(f"I could not cast to {tv.spoken}. Is the Chromecast on?")
        where = f" from {spoken_time(item.position)}" if item.position else ""
        return {"outcome": "playing", "say": f"Playing {_spoken(item)} on {tv.spoken}{where}."}

    async def _session(self, tv: Tv) -> Session | None:
        assert self.library is not None  # noqa: S101 - _target checked it
        return next(
            (s for s in await self.library.sessions() if s.address == tv.address and s.controllable), None
        )

    def _app(self, app: str, name: str, method: str) -> tuple[Tv, Any, str] | dict[str, Any]:
        """The TV, its driver and the app's id, or a refusal naming the apps that driver knows."""
        try:
            tv = find_tv(self.settings, name)
        except (UnknownTvError, AmbiguousTvError) as refusal:
            return _refused(str(refusal))
        # RULE: a hands-off TV never has an app opened or closed
        if tv.hands_off or not tv.address:
            return _refused(f"{tv.spoken} is left alone; nothing is sent to it.")
        driver = self.drivers.get(tv.driver)
        apps: Mapping[str, str] = (
            getattr(driver, "apps", {}) if callable(getattr(driver, method, None)) else {}
        )
        # "NRK TV" is how the owner says the app called "nrk".
        spoken = app.casefold().strip()
        app_id = apps.get(spoken) or apps.get(spoken.removesuffix(" tv"))
        if app_id is None:
            known = ", ".join(a.capitalize() for a in apps) or "none"
            return _refused(
                f"I cannot {method.removesuffix('_app')} {app!r} on {tv.spoken}. Apps I know: {known}."
            )
        return tv, driver, app_id

    async def open_app(self, app: str, name: str) -> dict[str, Any]:
        """Open `app` on the TV called `name`."""
        found = self._app(app, name, "open_app")
        if isinstance(found, dict):
            return found
        tv, driver, app_id = found
        if wrong := await self._itself(tv):
            return wrong
        if not await cast("OpensApps", driver).open_app(tv.address or "", app_id):
            return _refused(f"{tv.spoken.capitalize()} did not open {app}. Is it on?")
        return {"outcome": "done", "say": f"Opened {app} on {tv.spoken}."}

    async def close_app(self, app: str, name: str) -> dict[str, Any]:
        """Close `app` on the TV called `name`."""
        found = self._app(app, name, "close_app")
        if isinstance(found, dict):
            return found
        tv, driver, app_id = found
        if wrong := await self._itself(tv):
            return wrong
        if not await cast("ClosesApps", driver).close_app(tv.address or "", app_id):
            return _refused(f"{tv.spoken} did not close {app}.")
        return {"outcome": "done", "say": f"Closed {app} on {tv.spoken}."}

    async def _open_jellyfin(self, tv: Tv) -> Session | None:
        """Open Jellyfin on `tv` and wait for it to connect to the library."""
        opened = await self.open_app("jellyfin", tv.key)
        if opened["outcome"] != "done":
            return None
        for _ in range(int(OPEN_WAIT)):
            await self._sleep(1.0)
            session = await self._session(tv)
            if session is not None:
                return session
        return None

    async def control(self, command: str, name: str) -> dict[str, Any]:
        """Pause, resume or stop what is playing on the TV called `name`."""
        if command not in COMMANDS:
            return _refused(f"I can {', '.join(COMMANDS)}; not {command!r}.")
        tv = self._target(name)
        if not isinstance(tv, Tv):
            return tv
        if wrong := await self._itself(tv):
            return wrong
        caster = self._caster(tv)
        if caster is not None:
            sent = await caster.cast_control(tv.address or "", command)
        else:
            session = await self._session(tv)
            if session is None or self.library is None:
                return _refused(f"Jellyfin is not open on {tv.spoken}.")
            await self.library.control(session.id, command)
            sent = True
        if not sent:
            return _refused(f"{_capital(tv.spoken)} did not answer.")
        done = {"pause": "Paused", "resume": "Resumed", "stop": "Stopped"}[command]
        return {"outcome": "done", "say": f"{done} on {tv.spoken}."}

    async def seek(self, name: str, seconds: float, *, relative: bool) -> dict[str, Any]:
        """Move what plays on the TV called `name` to `seconds`, or by `seconds` when relative."""
        tv = self._target(name)
        if not isinstance(tv, Tv):
            return tv
        if wrong := await self._itself(tv):
            return wrong
        assert self.library is not None  # noqa: S101 - _target checked it
        watching = next(
            (s for s in await self.library.sessions() if s.address == tv.address and s.now_playing), None
        )
        if watching is None:
            return _refused(f"Nothing is playing on {tv.spoken}.")
        target = (watching.position or 0.0) + seconds if relative else seconds
        target = max(0.0, min(target, watching.runtime or target))
        caster = self._caster(tv)
        if caster is not None:
            if not await caster.cast_seek(tv.address or "", target):
                return _refused(f"{_capital(tv.spoken)} did not answer.")
        else:
            session = await self._session(tv)
            if session is None:
                return _refused(f"Jellyfin is not open on {tv.spoken}.")
            await self.library.seek(session.id, target)
        return {
            "outcome": "done",
            "say": f"Jumped to {spoken_time(target)} in {watching.now_playing} on {tv.spoken}.",
        }

    async def play(self, title: str, name: str, *, from_start: bool = False) -> dict[str, Any]:
        """Start `title` on the TV called `name`, where it was stopped unless `from_start`."""
        tv = self._target(name)
        if not isinstance(tv, Tv):
            return tv
        if wrong := await self._itself(tv):
            return wrong
        assert self.library is not None  # noqa: S101 - _target checked it
        found = await self.library.search(title)
        chosen = _choose(title, found)
        if not isinstance(chosen, str):
            return chosen
        item = next(i for i in found if i.id == chosen)
        if from_start:
            item = replace(item, position=None)
        caster = self._caster(tv)
        if caster is not None:
            return await self._cast(caster, tv, item)
        session = await self._session(tv) or await self._open_jellyfin(tv)
        if session is None:
            return _refused(
                f"Jellyfin is not open on {tv.spoken}, and I could not open it. Open it there first."
            )
        if item.position:
            await self.library.play(session.id, item.id, start=item.position)
            where = f" from {spoken_time(item.position)}"
        else:
            await self.library.play(session.id, item.id)
            where = ""
        return {"outcome": "playing", "say": f"Playing {_spoken(item)} on {tv.spoken}{where}."}


#: How long play waits, in seconds, for Jellyfin it opened to connect.
OPEN_WAIT = 15.0

NO_LIBRARY = "Jellyfin is not set up: the settings file has no [jellyfin] url and api_key."


def _found(item: MediaItem) -> dict[str, Any]:
    found: dict[str, Any] = {"title": item.title, "year": item.year, "kind": item.kind}
    if item.position:
        found["stopped_at"] = spoken_time(item.position)
    if item.last_played:
        found["last_watched"] = item.last_played
    return found


def _playing(session: Session) -> dict[str, Any]:
    playing: dict[str, Any] = {"title": session.now_playing}
    if session.position is not None:
        playing["at"] = spoken_time(session.position)
    if session.position is not None and session.runtime:
        playing["left"] = spoken_time(max(session.runtime - session.position, 0))
    playing["paused"] = session.paused
    return playing


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:]


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


def _another(tv: Tv) -> str:
    return f"Another TV answers at the address set for {tv.spoken}, so nothing is sent to it."


def _known(tv: Tv | None) -> dict[str, Any]:
    """What the settings say about `tv`, without asking the TV."""
    if tv is None:
        return {"tv": None}
    said = {"tv": tv.spoken, "description": tv.description, "brand": tv.brand, "model": tv.model}
    return {k: v for k, v in said.items() if v is not None or k == "tv"}


def _report(tv: Tv | None, info: TvInfo | None) -> dict[str, Any]:
    known = _known(tv)
    if info is None:
        return {**known, "state": "off or not reachable"}
    state = info.power
    if state == "unknown":
        state = "reachable"  # it answers, but cannot tell whether its screen is on
    if state == "standby" and info.art_mode_capable:
        state = "standby or art mode"
    told = {
        "brand": info.brand,
        "product_line": info.product_line,
        "model": info.model,
        "device_name": info.name,
    }
    return {
        **known,
        **{k: v for k, v in told.items() if v is not None},
        "state": state,
        "year": info.year,
        "platform": info.platform,
        "developer_mode": info.developer_mode,
    }

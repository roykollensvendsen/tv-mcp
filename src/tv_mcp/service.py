# SPDX-License-Identifier: GPL-3.0-or-later
"""What the tools do, in words that know no brand of TV.

Each TV is reached through the driver its settings name (tv_mcp.driver), and
the network is passed in, so the tests need neither a TV nor a network.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Protocol, cast

from tv_mcp.driver import DONE, UNSUPPORTED, HasPlayer, HasSound, ShowsYouTube
from tv_mcp.media import COMMANDS, named, outline, scene_lines, spoken_time
from tv_mcp.settings import AmbiguousTvError, Settings, Tv, UnknownTvError, find_tv
from tv_mcp.video import Video, is_video_id

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from tv_mcp.driver import Casts, ClosesApps, Driver, OpensApps, Playing, TvInfo
    from tv_mcp.media import MediaItem, MediaLibrary, Session
    from tv_mcp.video import Lounge, VideoSearch

LEFT_ALONE = "left alone"
ANOTHER_TV = "another TV answers there"


class Listen(Protocol):
    """Addresses of the TVs `recognises` accepts; `target` set also searches for that service."""

    async def __call__(self, recognises: Callable[[bytes], bool], target: str | None) -> list[str]: ...  # noqa: D102


#: How many more times to look for a film that seems to have gone, a second apart.
LOOK_AGAIN = 3
#: For how many seconds after a seek the TV's own report of the position is not believed.
FRESH = 20.0

#: The loudest the voice may set a TV, out of 100, so a misheard number is never deafening.
LOUDEST = 50
#: What the voice says when YouTube is not switched on.
NO_YOUTUBE = "YouTube is not set up. Add 'youtube' to the features in the settings."
#: How many videos a YouTube search reads out.
YOUTUBE_RESULTS = 5

#: How many of a film's cast a scene names, in the order the library bills them.
CAST_LIMIT = 15


class TvService:
    """Status and discovery for the TVs in the settings."""

    def __init__(  # noqa: PLR0913 - the parts a home has, each optional
        self,
        settings: Settings,
        *,
        drivers: Mapping[str, Driver],
        listen: Listen,
        library: MediaLibrary | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
        videos: VideoSearch | None = None,
        lounge: Lounge | None = None,
    ) -> None:
        """Reach each TV through `drivers`, by key, find TVs with `listen`, and films in `library`.

        `videos` and `lounge` are YouTube, when the owner switched it on.
        """
        self.settings, self.drivers, self._listen, self.library = settings, drivers, listen, library
        self._sleep, self._clock = sleep, clock
        #: Where each TV was last sent, and when: the TV reports it late.
        self._moved: dict[str, tuple[float, float]] = {}
        self.videos, self.lounge = videos, lounge

    async def _watching(self, tv: Tv, again: int = LOOK_AGAIN) -> Session | None:
        """What plays on `tv` in Jellyfin, asked `again` more times when it seems gone."""
        if self.library is None:
            return None
        for attempt in range(again + 1):
            sessions = await self.library.sessions()
            watching = next((s for s in sessions if s.address == tv.address and s.now_playing), None)
            if watching is not None:
                return replace(watching, position=self._position(tv, watching))
            if attempt < again:
                await self._sleep(1.0)
        return None

    async def _add_playing(self, tv: Tv, report: dict[str, Any], sessions: list[Session]) -> None:
        """Add to `report` what plays on `tv`: Jellyfin's film, or else whatever its app plays."""
        watching = next((s for s in sessions if s.address == tv.address and s.now_playing), None)
        driver = self.drivers.get(tv.driver)
        if watching:
            report["playing"] = _playing(replace(watching, position=self._position(tv, watching)))
        elif isinstance(driver, HasPlayer) and tv.address and (now := await driver.playing(tv.address)):
            report["playing"] = _in_app(now)

    async def _films_playing(self, tv: Tv) -> bool:
        return await self._watching(tv, again=0) is not None

    async def _any_app(
        self, driver: HasPlayer, tv: Tv, command: str, seconds: float | None = None, *, relative: bool = False
    ) -> dict[str, Any]:
        """`command` for whatever plays on `tv`, through the driver, in any app."""
        address = tv.address or ""
        playing = await driver.playing(address)
        if playing is None:
            return _refused(f"Nothing is playing on {tv.spoken}.")
        target = None
        if command == "seek":
            wanted = (playing.position or 0.0) + (seconds or 0.0) if relative else (seconds or 0.0)
            target = max(0.0, min(wanted, playing.runtime or wanted))
        answer = await driver.player(tv, command, target)
        app = playing.app or "The app"
        if answer == UNSUPPORTED:
            return _refused(f"{app} on {tv.spoken} cannot {command}.")
        if answer != DONE:
            return _refused(f"{_capital(tv.spoken)} did not answer.")
        if target is not None:
            self._moved[tv.key] = (target, self._clock())
            title = playing.title or "it"
            return {"outcome": "done", "say": f"Jumped to {spoken_time(target)} in {title} on {tv.spoken}."}
        done = {"pause": "Paused", "resume": "Resumed", "stop": "Stopped"}[command]
        return {"outcome": "done", "say": f"{done} {app} on {tv.spoken}."}

    def _position(self, tv: Tv, watching: Session) -> float | None:
        """Where the film is: where it was just sent, if that was moments ago, or else what the TV says."""
        moved = self._moved.get(tv.key)
        if moved is None or self._clock() - moved[1] > FRESH:
            return watching.position
        target, when = moved
        return target if watching.paused else target + (self._clock() - when)

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
            if not tv.hands_off:
                await self._add_playing(tv, report, sessions)
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

    def _tv(self, name: str) -> Tv | dict[str, Any]:
        """The TV to act on, or a refusal: unknown, ambiguous, or left alone."""
        try:
            tv = find_tv(self.settings, name)
        except (UnknownTvError, AmbiguousTvError) as refusal:
            return _refused(str(refusal))
        # RULE: a hands-off TV is never played on or controlled
        if tv.hands_off:
            return _refused(f"{tv.spoken} is left alone; nothing is sent to it.")
        return tv

    async def search_youtube(self, words: str) -> dict[str, Any]:
        """Videos on YouTube matching `words`, as the voice reads them."""
        if self.videos is None:
            return {"items": [], "say": NO_YOUTUBE}
        found = (await self.videos.search(words))[:YOUTUBE_RESULTS]
        if not found:
            return {"items": [], "say": f"Found nothing on YouTube for {words!r}."}
        items = [_video(v) for v in found]
        listed = "; ".join(
            f"{i['title']}"
            + (f" by {i['channel']}" if i["channel"] else "")
            + (f", {i['length']}" if i["length"] else "")
            for i in items
        )
        return {"items": items, "say": f"On YouTube: {listed}."}

    async def play_youtube(self, words: str, name: str) -> dict[str, Any]:  # noqa: PLR0911 - one refusal per reason
        """Start the YouTube video `words` names (its id, or words for the best match) on `name`."""
        if self.videos is None or self.lounge is None:
            return _refused(NO_YOUTUBE)
        tv = self._tv(name)
        if not isinstance(tv, Tv):
            return tv
        driver = self.drivers.get(tv.driver)
        if not isinstance(driver, ShowsYouTube):
            return _refused(f"{_capital(tv.spoken)} cannot show YouTube from here.")
        if wrong := await self._itself(tv):
            return wrong
        if is_video_id(words):
            video = await self.videos.video(words) or Video(
                id=words, title="the video", channel=None, duration=None
            )
        else:
            found = await self.videos.search(words)
            if not found:
                return _refused(f"Found nothing on YouTube for {words!r}.")
            video = found[0]
        screen = await driver.youtube_screen(tv.address or "")
        if screen is None:
            return _refused(f"YouTube did not open on {tv.spoken}.")
        if not await self.lounge.play(tv.key, screen, video.id):
            return _refused(f"YouTube opened on {tv.spoken}, but {video.title} did not start.")
        advert = " after an advert" if getattr(self.lounge, "advert", False) else ""
        return {
            "outcome": "playing",
            "say": f"Playing {video.title} on {tv.spoken}{advert}.",
            "video": _video(video),
        }

    def _target(self, name: str) -> Tv | dict[str, Any]:
        """The TV to act on, or a refusal: unknown, ambiguous, left alone, or no library."""
        tv = self._tv(name)
        if not isinstance(tv, Tv):
            return tv
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

    async def control(self, command: str, name: str) -> dict[str, Any]:  # noqa: PLR0911 - one refusal per reason
        """Pause, resume or stop what is playing on the TV called `name`."""
        if command not in COMMANDS:
            return _refused(f"I can {', '.join(COMMANDS)}; not {command!r}.")
        tv = self._target(name)
        if not isinstance(tv, Tv):
            return tv
        if wrong := await self._itself(tv):
            return wrong
        driver = self.drivers.get(tv.driver)
        caster = self._caster(tv)
        films = await self._session(tv) if caster is None and self.library else None
        if isinstance(driver, HasPlayer) and not (films and await self._films_playing(tv)):
            return await self._any_app(driver, tv, command)
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

    async def scene(self, name: str, *, minutes: float, chapters: bool = False) -> dict[str, Any]:
        """The subtitle lines within `minutes` of where the film on `name` is, with its cast.

        With `chapters`, also the film's named chapters, or else an outline
        from its subtitles, so a scene can be found and seeked to.
        """
        tv = self._target(name)
        if not isinstance(tv, Tv):
            return tv
        if wrong := await self._itself(tv):
            return wrong
        assert self.library is not None  # noqa: S101 - _target checked it
        watching = await self._watching(tv)
        if watching is None or watching.item_id is None:
            return _refused(f"Nothing is playing on {tv.spoken}.")
        cues = await self.library.subtitles(watching.item_id)
        if not cues:
            return _refused(f"{watching.now_playing} has no subtitles to go by.")
        position = watching.position or 0.0
        found: dict[str, Any] = {}
        if chapters:
            listed = await self.library.chapters(watching.item_id)
            if named(listed):
                found["chapters"] = [f"{_clock(c.start)} {c.name}" for c in listed]
            else:
                found["outline"] = outline(cues)
        return {
            **found,
            "outcome": "done",
            "say": f"{watching.now_playing}, {spoken_time(position)} in.",
            "title": watching.now_playing,
            "at": spoken_time(position),
            "lines": scene_lines(cues, position, minutes * 60),
            "cast": [
                f"{role}: {actor}" for role, actor in (await self.library.cast(watching.item_id))[:CAST_LIMIT]
            ],
        }

    async def sound(  # noqa: PLR0911 - one refusal per reason
        self, command: str, name: str, *, level: int | None = None, relative: bool = False
    ) -> dict[str, Any]:
        """Mute, unmute, or set the volume (0 to 100, or by `level` when relative) on the TV called `name`."""
        tv = self._tv(name)
        if not isinstance(tv, Tv):
            return tv
        driver = self.drivers.get(tv.driver)
        if not isinstance(driver, HasSound):
            return _refused(f"I cannot change the sound on {tv.spoken}.")
        if wrong := await self._itself(tv):
            return wrong
        address = tv.address or ""
        if command in {"mute", "unmute"}:
            if not await driver.set_mute(address, on=command == "mute"):
                return _refused(f"{_capital(tv.spoken)} did not answer.")
            return {"outcome": "done", "say": f"{'Muted' if command == 'mute' else 'Unmuted'} {tv.spoken}."}
        if level is None:
            return _refused("Say how loud, or how much louder or quieter.")
        now = await driver.volume(address) if relative else 0
        if now is None:
            return _refused(f"{_capital(tv.spoken)} did not say its volume.")
        wanted = now + level if relative else level
        target = max(0, min(wanted, LOUDEST))
        if not await driver.set_volume(address, target):
            return _refused(f"{_capital(tv.spoken)} did not answer.")
        capped = f", at most {LOUDEST}" if wanted > LOUDEST else ""
        return {"outcome": "done", "say": f"Volume {target} on {tv.spoken}{capped}.", "volume": target}

    async def seek(self, name: str, seconds: float, *, relative: bool) -> dict[str, Any]:  # noqa: PLR0911 - one refusal per reason
        """Move what plays on the TV called `name` to `seconds`, or by `seconds` when relative."""
        tv = self._target(name)
        if not isinstance(tv, Tv):
            return tv
        if wrong := await self._itself(tv):
            return wrong
        assert self.library is not None  # noqa: S101 - _target checked it
        driver = self.drivers.get(tv.driver)
        if isinstance(driver, HasPlayer):
            watching = await self._watching(tv, again=0)
            if watching is None or self._caster(tv) is not None:
                return await self._any_app(driver, tv, "seek", seconds, relative=relative)
        else:
            watching = await self._watching(tv)
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
        self._moved[tv.key] = (target, self._clock())
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


def _clock(seconds: float) -> str:
    minutes, rest = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{rest:02}" if hours else f"{minutes}:{rest:02}"


def _video(video: Video) -> dict[str, Any]:
    return {
        "id": video.id,
        "title": video.title,
        "channel": video.channel,
        "length": spoken_time(video.duration) if video.duration else None,
    }


def _in_app(playing: Playing) -> dict[str, Any]:
    """What plays in an app other than Jellyfin, as status reports it."""
    report: dict[str, Any] = {"app": playing.app, "title": playing.title}
    if playing.position is not None:
        report["at"] = spoken_time(playing.position)
    if playing.runtime and playing.position is not None:
        report["left"] = spoken_time(max(playing.runtime - playing.position, 0))
    report["paused"] = playing.paused
    return report

# SPDX-License-Identifier: GPL-3.0-or-later
"""What the tools do, in words that know no brand of TV.

Each TV is reached through the driver its settings name (tv_mcp.driver), and
the network is passed in, so the tests need neither a TV nor a network.
"""

from __future__ import annotations

import asyncio
import math
import re
import time
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Protocol, cast

from tv_mcp.driver import (
    DONE,
    INPUTS,
    UNSUPPORTED,
    ChangesInput,
    HasPlayer,
    HasSound,
    KnowsOnScreen,
    ListsInputs,
    ReadsArtMode,
    ReadsInput,
    SeesApps,
    ShowsYouTube,
)
from tv_mcp.media import COMMANDS, named, outline, scene_lines, spoken_time
from tv_mcp.settings import AmbiguousTvError, Settings, Tv, UnknownTvError, find_tv, input_key
from tv_mcp.video import Video, is_video_id

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from tv_mcp.driver import Casts, ClosesApps, Driver, InputSent, OpensApps, Playing, TvInfo
    from tv_mcp.media import Cue, MediaItem, MediaLibrary, Session
    from tv_mcp.video import Lounge, VideoSearch

LEFT_ALONE = "left alone"
#: The state of a TV that did not answer: off, or not on the network.
UNREACHABLE = "off or not reachable"
ANOTHER_TV = "another TV answers there"


class Listen(Protocol):
    """Addresses of the TVs `recognises` accepts; `target` set also searches for that service."""

    async def __call__(self, recognises: Callable[[bytes], bool], target: str | None) -> list[str]: ...  # noqa: D102


#: How many more times to look for a film that seems to have gone, a second apart.
#: Parts of a title this short are not searched on their own.
SHORTEST_PART = 2
LOOK_AGAIN = 3
#: For how many seconds after a seek the TV's own report of the position is not believed.
FRESH = 20.0

#: The loudest the voice may set a TV, out of 100, so a misheard number is never deafening.
LOUDEST = 50
#: What the voice says when YouTube is not switched on.
NO_YOUTUBE = (
    "YouTube is not set up. Add 'youtube' to features in ~/.config/tv-mcp/config.toml,"
    " then restart the TV plugin."
)
#: How many videos a YouTube search reads out.
YOUTUBE_RESULTS = 5

#: How many of a film's cast a scene names, in the order the library bills them.
CAST_LIMIT = 15

#: claude-voice gives a tool 30 seconds. Work that can take longer is left
#: running after these many seconds, and the voice is told it is on its way.
#: How long a scene waits for subtitles that have to be pulled out of the film.
SUBTITLE_WAIT = 5.0
#: How long playing a YouTube video waits for the search and for the screen to play it.
YOUTUBE_WAIT = 8.0
#: How many films' subtitles are kept once pulled out, for the next question.
SUBTITLES_KEPT = 4
#: How long status waits for a TV to come on or go off, when asked to: inside
#: server.ANSWER_WITHIN, so the voice hears the outcome and can ask to wait again.
WAIT_WITHIN = 10.0
#: How long status waits to hear which input a TV shows, before saying what it knows.
INPUT_READ_WAIT = 3.0
#: Seconds after a wake through the Chromecast in which it may still take the screen; the
#: garage TV takes about a minute to come on (2026-11-10), and the Chromecast takes it after.
GRAB_WITHIN = 180.0
#: Seconds to wait before looking again whether the Chromecast took the screen back.
GRAB_LOOK = 2.0
#: Seconds the second look and the second send get together, so the voice still has its answer.
GRAB_BUDGET = 8.0
#: The states in which a TV's own screen is off.
SCREEN_OFF = {"off", "standby", "standby or art mode", "showing art", UNREACHABLE}


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
        #: Subtitles being pulled out, or pulled out, by the film's id.
        self._subtitles: dict[str, asyncio.Task[list[Cue] | None]] = {}
        #: Work left running after the voice was answered, kept until it ends.
        self._running: set[asyncio.Task[Any]] = set()
        #: When each TV was last woken through the Chromecast in it, which may then take the screen.
        self._woken: dict[str, float] = {}

    def woken_by_hdmi(self, tv: Tv) -> None:
        """Note that `tv` was just woken through the device in it."""
        self._woken[tv.key] = self._clock()

    def just_woken(self, tv: Tv) -> bool:
        """Whether `tv` was woken through the device in it so lately that it may still take the screen."""
        woken = self._woken.get(tv.key)
        return woken is not None and self._clock() - woken <= GRAB_WITHIN

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

    async def _in_jellyfin(self, driver: HasPlayer, tv: Tv) -> bool:
        """Whether the TV says Jellyfin is the app in front."""
        now = await driver.playing(tv.address) if tv.address else None
        return now is not None and now.app == "Jellyfin"

    async def _find(self, title: str) -> list[MediaItem]:
        """Items matching `title`, also when it is said in other words than the library uses.

        "Star Wars: A New Hope" finds "Star Wars: Episode IV - A New Hope": each
        part of the title is searched, and an item is kept when its title has
        every word that was said.
        """
        assert self.library is not None  # noqa: S101 - callers checked it
        found = await self.library.search(title)
        if found:
            return found
        said = set(_words(title))
        seen: dict[str, MediaItem] = {}
        for part in re.split(r"\s*[:\-\u2013]\s*", title):
            if len(part) > SHORTEST_PART and part != title:
                for item in await self.library.search(part):
                    if said <= set(_words(item.title)):
                        seen.setdefault(item.id, item)
        return list(seen.values())

    async def _add_playing(self, tv: Tv, report: dict[str, Any], sessions: list[Session]) -> None:
        """Add to `report` what plays on `tv`: Jellyfin's film, or else whatever its app plays."""
        watching = next((s for s in sessions if s.address == tv.address and s.now_playing), None)
        driver = self.drivers.get(tv.driver)
        if watching:
            report["playing"] = _playing(replace(watching, position=self._position(tv, watching)))
        elif isinstance(driver, HasPlayer) and tv.address and (now := await driver.playing(tv.address)):
            report["playing"] = _in_app(now)

    async def _add_sound(self, tv: Tv, report: dict[str, Any]) -> None:
        """Add to `report` how loud `tv` is and whether it is muted, when the TV says."""
        if report.get("state") in {ANOTHER_TV, "refused"}:
            return
        for driver, address, _ in self._speakers(tv):
            if address and (level := await driver.volume(address)) is not None:
                report["volume"] = level
                report["muted"] = await driver.muted(address)
                return

    def _speakers(self, tv: Tv) -> list[tuple[HasSound, str, bool]]:
        """What can change `tv`'s sound, and at which address: the TV itself first.

        The flag says it is the TV itself; a device in it, such as a Chromecast,
        reaches only the sound of what it plays, not of the TV's other inputs.
        """
        found: list[tuple[HasSound, str, bool]] = []
        power = self.drivers.get(tv.power_driver) if tv.power_driver else None
        # RULE: the sound goes to the TV itself before the device that plays through it
        if isinstance(power, HasSound) and tv.power_address:
            found.append((power, tv.power_address, True))
        own = self.drivers.get(tv.driver)
        if isinstance(own, HasSound):
            found.append((own, tv.address or "", tv.power_driver is None))
        return found

    async def _films_playing(self, tv: Tv) -> bool:
        return await self._watching(tv, again=0) is not None

    async def _any_app(
        self, driver: HasPlayer, tv: Tv, command: str, seconds: float | None = None, *, relative: bool = False
    ) -> dict[str, Any]:
        """`command` for whatever plays on `tv`, through the driver, in any app."""
        address = tv.address or ""
        playing = await driver.playing(address)
        if playing is None:
            return _refused(f"Nothing is playing on {tv.spoken}. Start something first.")
        target = None
        if command == "seek":
            wanted = (playing.position or 0.0) + (seconds or 0.0) if relative else (seconds or 0.0)
            target = max(0.0, min(wanted, playing.runtime or wanted))
        answer = await driver.player(tv, command, target)
        app = playing.app or "The app"
        if answer == UNSUPPORTED:
            return _refused(f"{app} on {tv.spoken} cannot {command}. Try the TV's own remote.")
        if answer != DONE:
            return _refused(f"{_capital(tv.spoken)} did not answer. Check that it is on, and try again.")
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
            # RULE: a TV that does not answer is not asked what it plays or how loud it is
            if not tv.hands_off and report["state"] != UNREACHABLE:
                await self._add_playing(tv, report, sessions)
                await self._add_sound(tv, report)
            await self._add_screen(tv, report)
            if not tv.hands_off:
                await self._add_art(tv, report)
            if not tv.hands_off:
                await self._add_input(tv, report)
        return reports

    async def wait_for(self, name: str | None, wanted: str) -> dict[str, Any]:
        """Status of the TV called `name`, looked at once a second until it is `wanted`, for a while."""
        if name is None:
            return {
                "reached": False,
                "tvs": [{"tv": None, "state": "refused", "say": "Say which TV to wait for."}],
            }
        until = self._clock() + WAIT_WITHIN
        reports: list[dict[str, Any]] = []
        # RULE: a wait for a TV ends within the voice time
        for _ in range(math.ceil(until - self._clock())):
            if (left := until - self._clock()) <= 0:
                break
            try:
                reports = await asyncio.wait_for(self.status(name), left)
            except TimeoutError:
                break
            if any(r["state"] == "refused" for r in reports):
                return {"reached": False, "tvs": reports}
            if all(_shows(r, wanted) for r in reports):
                return {"reached": True, "tvs": reports}
            if until - self._clock() <= 1:
                break
            await self._sleep(1.0)
        return {"reached": False, "tvs": reports}

    async def _add_art(self, tv: Tv, report: dict[str, Any]) -> None:
        """Say whether a Frame in "standby or art mode" shows art, when it can tell."""
        driver = self.drivers.get(tv.driver)
        if report["state"] != "standby or art mode" or not isinstance(driver, ReadsArtMode):
            return
        art = await driver.art_mode(tv)
        if art is not None:
            report["state"] = "showing art" if art else "standby"

    async def _add_input(self, tv: Tv, report: dict[str, Any]) -> None:
        """Add which input the TV shows and what is on its inputs; the TV is asked only while it is on."""
        # The screen's own state when another device plays to it, so a TV in standby is not asked.
        on = report.get("screen", report.get("state")) == "on"
        shown, plugged = await asyncio.gather(self._shown(tv, on=on), self._plugged(tv, on=on))
        if shown:
            report["input"] = shown
        entries = _entries(tv, plugged)
        if entries:
            report["inputs"] = entries
        if entry := next((e for e in entries if e["input"] == shown and e["device"]), None):
            report["input_device"], report["input_device_from"] = entry["device"], entry["from"]

    async def _shown(self, tv: Tv, *, on: bool) -> str | None:
        """The input the TV says it shows; None when it is off, cannot say, or is slow to."""
        found = self._input_driver(tv, ReadsInput) if on else None
        if found is None:
            return None
        driver, target = found
        try:
            return await asyncio.wait_for(cast("ReadsInput", driver).input_shown(target), INPUT_READ_WAIT)
        except TimeoutError:
            return None  # just woken, it may not say yet; status answers with what it knows

    async def _plugged(self, tv: Tv, *, on: bool) -> dict[str, str | None] | None:
        """The inputs the TV lists as in use; None when it is off, cannot list them, or is slow to."""
        found = self._input_driver(tv, ListsInputs) if on else None
        if found is None:
            return None
        driver, target = found
        try:
            return await asyncio.wait_for(cast("ListsInputs", driver).inputs_plugged(target), INPUT_READ_WAIT)
        except TimeoutError:
            return None

    async def _add_screen(self, tv: Tv, report: dict[str, Any]) -> None:
        """Add whether the TV itself is on, when another device (a Chromecast) plays to it.

        Only silent reads: which of the TV's own ports answer.
        """
        driver = self.drivers.get(tv.power_driver) if tv.power_driver else None
        if driver is None or not tv.power_address:
            return
        info = await driver.read_info(tv.power_address)
        report["screen"] = "on" if info is not None and info.power == "on" else "off"

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
        found = await self._find(term)
        return {"items": [_found(i) for i in found]}

    def _tv(self, name: str) -> Tv | dict[str, Any]:
        """The TV to act on, or a refusal: unknown, ambiguous, or left alone."""
        try:
            tv = find_tv(self.settings, name)
        except (UnknownTvError, AmbiguousTvError) as refusal:
            return _refused(str(refusal))
        # RULE: a hands-off TV is never played on or controlled
        if tv.hands_off:
            return _refused(
                f"{tv.spoken} is left alone; nothing is sent to it."
                " Remove hands_off in the settings to use it."
            )
        return tv

    async def search_youtube(self, words: str) -> dict[str, Any]:
        """Videos on YouTube matching `words`, as the voice reads them."""
        if self.videos is None:
            return {"items": [], "say": NO_YOUTUBE}
        found = (await self.videos.search(words))[:YOUTUBE_RESULTS]
        if not found:
            return {"items": [], "say": f"Found nothing on YouTube for {words!r}. Try other words."}
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
            return _refused(f"{_capital(tv.spoken)} cannot show YouTube from here. Try another TV.")
        if wrong := await self._itself(tv):
            return wrong
        clock = asyncio.get_running_loop().time
        deadline = clock() + YOUTUBE_WAIT
        try:
            video = await asyncio.wait_for(self._video(words), YOUTUBE_WAIT)
        except TimeoutError:
            return _refused(
                f"YouTube did not answer the search for {words!r} in time. Try again in a moment."
            )
        if video is None:
            return _refused(f"Found nothing on YouTube for {words!r}. Try other words.")
        starting = asyncio.ensure_future(self._open_and_start(driver, tv, video))
        self._running.add(starting)
        starting.add_done_callback(self._running.discard)
        try:
            refusal = await asyncio.wait_for(asyncio.shield(starting), max(deadline - clock(), 0.0))
        except TimeoutError:
            return {
                "outcome": "starting",
                "say": f"I asked {tv.spoken} to play {video.title}; it is still starting.",
                "video": _video(video),
            }
        if refusal:
            return refusal
        advert = " after an advert" if getattr(self.lounge, "advert", False) else ""
        return {
            "outcome": "playing",
            "say": f"Playing {video.title} on {tv.spoken}{advert}.",
            "video": _video(video),
        }

    async def _video(self, words: str) -> Video | None:
        """The video `words` names: its id, or the best match for them."""
        assert self.videos is not None  # noqa: S101 - play_youtube checked it
        if is_video_id(words):
            return await self.videos.video(words) or Video(
                id=words, title="the video", channel=None, duration=None
            )
        found = await self.videos.search(words)
        return found[0] if found else None

    async def _open_and_start(self, driver: ShowsYouTube, tv: Tv, video: Video) -> dict[str, Any] | None:
        """Open YouTube on `tv` and start `video`; None once it plays, or the refusal to say."""
        try:
            screen = await driver.youtube_screen(tv.address or "")
        except Exception:  # noqa: BLE001 - whatever the TV does, the voice gets a sentence
            screen = None
        if screen is None:
            return _refused(f"YouTube did not open on {tv.spoken}. Check that it is on, and try again.")
        return await self._start_video(tv, screen, video)

    async def _start_video(self, tv: Tv, screen: str, video: Video) -> dict[str, Any] | None:
        """Start `video` on the screen; None once it plays, or the refusal to say."""
        assert self.lounge is not None  # noqa: S101 - play_youtube checked it
        try:
            started = await self.lounge.play(tv.key, screen, video.id)
        except Exception:  # noqa: BLE001 - whatever the screen does, the voice gets a sentence
            started = False
        if not started and getattr(self.lounge, "refusal", None) == "kids":
            return _refused(
                f"YouTube on {tv.spoken} is waiting for someone to pick a profile, or has a children's "
                "profile, which takes no videos sent from here. Pick a profile on the TV, and ask again."
            )
        if not started:
            return _refused(
                f"YouTube opened on {tv.spoken}, but {video.title} did not start."
                " Try again, or pick another video."
            )
        return None

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
            return _refused(
                f"I could not cast to {tv.spoken}. Check that its Chromecast is on, then try again."
            )
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
            return _refused(
                f"{tv.spoken} is left alone; nothing is sent to it."
                " Remove hands_off in the settings to use it."
            )
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
                f"I cannot {method.removesuffix('_app')} {app!r} on {tv.spoken}. Name one I know: {known}."
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
        until = self._clock() + OPEN_IN_FRONT_WITHIN
        if not await cast("OpensApps", driver).open_app(tv.address or "", app_id):
            return _refused(
                f"{tv.spoken.capitalize()} did not open {app}. Check that it is on, then try again."
            )
        if await self._comes_to_front(driver, tv, app_id, until) is False:
            return {
                "outcome": "unverified",
                "say": f"I asked {tv.spoken} to open {app}, but it is not in front yet."
                " Ask me in a moment what is on it.",
            }
        return {"outcome": "done", "say": f"Opened {app} on {tv.spoken}."}

    async def _comes_to_front(self, driver: object, tv: Tv, app_id: str, until: float) -> bool | None:
        """Whether `app_id` came to the front on `tv` by `until`, looked at once a second.

        None when the TV cannot say which app is in front.
        """
        # RULE: an app is said open only once it is in front
        if not isinstance(driver, SeesApps):
            return None
        for _ in range(math.ceil(OPEN_IN_FRONT_WITHIN)):
            if (left := until - self._clock()) <= 0:
                break
            try:
                front = await asyncio.wait_for(driver.in_front(tv.address or "", app_id), left)
            except TimeoutError:
                break
            if front is not False:
                return front
            if until - self._clock() <= 1:
                break
            await self._sleep(1.0)
        return False

    async def show_input(self, source: str, name: str) -> dict[str, Any]:
        """Show the input `source`, such as "HDMI 1", on the TV called `name`."""
        tv = self._tv(name)
        if not isinstance(tv, Tv):
            return tv
        wanted = _named_input(tv, source)
        if isinstance(wanted, dict):
            return wanted
        found = self._input_driver(tv, ChangesInput)
        if found is None:
            return _refused(f"{_capital(tv.spoken)} cannot change input from here. Use the TV's own remote.")
        driver, target = found
        if wrong := await self._itself(tv) or await self._screen_off(tv, driver, target):
            return wrong
        sent = await cast("ChangesInput", driver).show_input(target, wanted)
        if sent is None:
            return _refused(f"{_capital(tv.spoken)} did not answer. Check that it is on, then try again.")
        if self.just_woken(tv):
            try:
                sent = await asyncio.wait_for(self._against_grab(driver, target, wanted, sent), GRAB_BUDGET)
            except TimeoutError:
                sent = replace(sent, shown=None)
        return _input_answer(tv, sent)

    async def _against_grab(self, driver: Any, target: Tv, wanted: str, sent: InputSent) -> InputSent:  # noqa: ANN401
        """Look again, and send once more if the Chromecast took the screen as the TV woke."""
        if sent.unplugged or sent.shown is None:
            return sent
        if sent.shown == sent.said and isinstance(driver, ReadsInput):
            await self._sleep(GRAB_LOOK)
            sent = replace(sent, shown=await driver.input_shown(target))
        # RULE: an input the Chromecast took right after a wake is sent again
        if sent.shown is None or sent.shown == sent.said:
            return sent
        return await cast("ChangesInput", driver).show_input(target, wanted) or sent

    @staticmethod
    async def _screen_off(tv: Tv, driver: Any, target: Tv) -> dict[str, Any] | None:  # noqa: ANN401
        """A refusal unless the screen says it is on: a remote key sent in standby may wake it."""
        info = await driver.read_info(target.address or "")
        # RULE: an input is changed only while the screen is on
        if info is not None and info.power == "on":
            return None
        return _refused(
            f"{_capital(tv.spoken)} is not on, so its input was left alone. "
            "Switch it on first, then ask again."
        )

    def _input_driver(self, tv: Tv, kind: type) -> tuple[Any, Tv] | None:
        """The driver that does `kind` for `tv`, at the address it uses: its own, or its power driver."""
        driver = self.drivers.get(tv.driver)
        if isinstance(driver, kind):
            return driver, tv
        power = self.drivers.get(tv.power_driver) if tv.power_driver else None
        if isinstance(power, kind):
            return power, replace(tv, address=tv.power_address)
        return None

    async def close_app(self, app: str, name: str) -> dict[str, Any]:
        """Close `app` on the TV called `name`."""
        found = self._app(app, name, "close_app")
        if isinstance(found, dict):
            return found
        tv, driver, app_id = found
        if wrong := await self._itself(tv):
            return wrong
        if not await cast("ClosesApps", driver).close_app(tv.address or "", app_id, tv_key=tv.key):
            return _refused(f"{tv.spoken} did not close {app}. Try again, or close it with the TV's remote.")
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
            return _refused(f"I cannot {command!r}. Choose one of: {', '.join(COMMANDS)}.")
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
                return _refused(f"Jellyfin is not open on {tv.spoken}. Open it there first.")
            await self.library.control(session.id, command)
            sent = True
        if not sent:
            return _refused(f"{_capital(tv.spoken)} did not answer. Check that it is on, and try again.")
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
            return _refused(f"Nothing is playing on {tv.spoken}. Start something first.")
        try:
            cues = await asyncio.wait_for(
                asyncio.shield(self._pull_subtitles(watching.item_id)), SUBTITLE_WAIT
            )
        except TimeoutError:
            return {
                "outcome": "pending",
                "say": f"I am reading the subtitles of {watching.now_playing}. Ask again in half a minute.",
            }
        if not cues:
            return _refused(
                f"{watching.now_playing} has no subtitles to go by. Say a time to jump to instead."
            )
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

    def _pull_subtitles(self, item_id: str) -> asyncio.Task[list[Cue] | None]:
        """The subtitles of `item_id` being pulled out, started anew when the last try failed."""
        assert self.library is not None  # noqa: S101 - scene checked it
        task = self._subtitles.get(item_id)
        if task is None or (task.done() and (task.cancelled() or task.exception() or not task.result())):
            task = asyncio.ensure_future(self.library.subtitles(item_id))
            self._subtitles.pop(item_id, None)
            self._subtitles[item_id] = task
            while len(self._subtitles) > SUBTITLES_KEPT:
                del self._subtitles[next(iter(self._subtitles))]
        return task

    async def sound(
        self, command: str, name: str, *, level: int | None = None, relative: bool = False
    ) -> dict[str, Any]:
        """Mute, unmute, or set the volume (0 to 100, or by `level` when relative) on the TV called `name`."""
        tv = self._tv(name)
        if not isinstance(tv, Tv):
            return tv
        speakers = self._speakers(tv)
        if not speakers:
            return _refused(f"I cannot change the sound on {tv.spoken}. Use the TV's own remote.")
        if wrong := await self._itself(tv):
            return wrong
        if command not in {"mute", "unmute"} and level is None:
            return _refused("Say how loud, or how much louder or quieter.")
        answer: dict[str, Any] = {}
        for driver, address, itself in speakers:
            answer = await self._set_sound(tv, driver, address, command, level, relative=relative)
            if answer["outcome"] == "done":
                return (
                    answer if itself else await self._device_only(tv, driver, address, answer, len(speakers))
                )
        return answer

    async def _set_sound(  # noqa: PLR0913 - the command and where it goes
        self, tv: Tv, driver: HasSound, address: str, command: str, level: int | None, *, relative: bool
    ) -> dict[str, Any]:
        """Change the sound through `driver` at `address`."""
        if command in {"mute", "unmute"}:
            if not await driver.set_mute(address, on=command == "mute"):
                return _refused(f"{_capital(tv.spoken)} did not answer. Check that it is on, and try again.")
            return {"outcome": "done", "say": f"{'Muted' if command == 'mute' else 'Unmuted'} {tv.spoken}."}
        now = await driver.volume(address) if relative else 0
        if now is None:
            return _refused(f"{_capital(tv.spoken)} did not say its volume. Say a level instead, such as 20.")
        wanted = now + (level or 0) if relative else (level or 0)
        target = max(0, min(wanted, LOUDEST))
        if not await driver.set_volume(address, target):
            return _refused(f"{_capital(tv.spoken)} did not answer. Check that it is on, and try again.")
        capped = f", at most {LOUDEST}" if wanted > LOUDEST else ""
        return {"outcome": "done", "say": f"Volume {target} on {tv.spoken}{capped}.", "volume": target}

    async def _device_only(
        self, tv: Tv, driver: HasSound, address: str, answer: dict[str, Any], tried: int
    ) -> dict[str, Any]:
        """`answer`, unless the device in `tv` took a change the TV's other inputs do not hear."""
        in_front = await driver.on_screen(address) if isinstance(driver, KnowsOnScreen) else None
        # RULE: a sound change only the Chromecast took says so
        if in_front:
            return answer
        device = "Chromecast" if tv.driver == "chromecast" else "player"
        if "volume" in answer:
            done = f"set its {device} only, to volume {answer['volume']}"
        else:
            done = f"{answer['say'].split()[0].lower()} its {device} only"
        lead = f"{_capital(tv.spoken)} did not answer, so I" if tried > 1 else "I"
        if in_front is False:
            say = (
                f"{lead} {done}. {_capital(tv.spoken)} shows another input, so that sound is unchanged."
                " Use the TV's own remote for it."
            )
        else:
            say = f"{lead} {done}. Use the TV's own remote for its sound if {tv.spoken} shows another input."
        return {**answer, "outcome": "unverified", "say": say}

    async def seek(self, name: str, seconds: float, *, relative: bool) -> dict[str, Any]:
        """Move what plays on the TV called `name` to `seconds`, or by `seconds` when relative."""
        tv = self._target(name)
        if not isinstance(tv, Tv):
            return tv
        if wrong := await self._itself(tv):
            return wrong
        watching = await self._what_plays(tv, seconds, relative=relative)
        if isinstance(watching, dict):
            return watching
        target = (watching.position or 0.0) + seconds if relative else seconds
        target = max(0.0, min(target, watching.runtime or target))
        if refused := await self._jump(tv, target):
            return refused
        self._moved[tv.key] = (target, self._clock())
        return {
            "outcome": "done",
            "say": f"Jumped to {spoken_time(target)} in {watching.now_playing} on {tv.spoken}.",
        }

    async def _what_plays(self, tv: Tv, seconds: float, *, relative: bool) -> Session | dict[str, Any]:
        """The film a jump on `tv` moves, or the answer: another app took the jump, or nothing plays."""
        driver = self.drivers.get(tv.driver)
        if isinstance(driver, HasPlayer):
            watching = await self._watching(tv, again=0)
            if watching is None and self._caster(tv) is None and await self._in_jellyfin(driver, tv):
                # Jellyfin's report can lag a moment; the TV says Jellyfin is in front.
                watching = await self._watching(tv)
            if watching is None or self._caster(tv) is not None:
                return await self._any_app(driver, tv, "seek", seconds, relative=relative)
        else:
            watching = await self._watching(tv)
        if watching is None:
            return _refused(f"Nothing is playing on {tv.spoken}. Start something first.")
        return watching

    async def _jump(self, tv: Tv, target: float) -> dict[str, Any] | None:
        """Move the film on `tv` to `target`, by its Chromecast or by Jellyfin; a refusal when it cannot."""
        assert self.library is not None  # noqa: S101 - _target checked it
        caster = self._caster(tv)
        if caster is not None:
            if not await caster.cast_seek(tv.address or "", target):
                return _refused(f"{_capital(tv.spoken)} did not answer. Check that it is on, and try again.")
            return None
        session = await self._session(tv)
        if session is None:
            return _refused(f"Jellyfin is not open on {tv.spoken}. Open it there first.")
        await self.library.seek(session.id, target)
        return None

    async def play(self, title: str, name: str, *, from_start: bool = False) -> dict[str, Any]:
        """Start `title` on the TV called `name`, where it was stopped unless `from_start`."""
        tv = self._target(name)
        if not isinstance(tv, Tv):
            return tv
        if wrong := await self._itself(tv):
            return wrong
        assert self.library is not None  # noqa: S101 - _target checked it
        found = await self._find(title)
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
#: Seconds an opened app is watched for until it is in front, counted from asking the TV.
OPEN_IN_FRONT_WITHIN = 8.0

NO_LIBRARY = (
    "Jellyfin is not set up: ~/.config/tv-mcp/config.toml has no [jellyfin] url and api_key."
    " Add them there, then restart the TV plugin."
)


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


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold())


def _choose(title: str, found: list[MediaItem]) -> str | dict[str, Any]:
    """The id of the one item meant, or a refusal that says what there is."""
    if not found:
        return _refused(f"Found nothing called {title!r}. Try other words, or part of the title.")
    exact = [i for i in found if i.title.casefold() == title.casefold()]
    if len(exact) == 1:
        return exact[0].id
    if len(found) == 1:
        return found[0].id
    options = "; ".join(_spoken(i) for i in found[:3])
    # RULE: a title that matches several items is refused, naming them
    return _refused(f"{title!r} could be: {options}. Say which one.")


def _another(tv: Tv) -> str:
    return (
        f"Another TV answers at the address set for {tv.spoken}, so nothing is sent to it."
        " Check its address in the settings."
    )


def _known(tv: Tv | None) -> dict[str, Any]:
    """What the settings say about `tv`, without asking the TV."""
    if tv is None:
        return {"tv": None}
    said = {"tv": tv.spoken, "description": tv.description, "brand": tv.brand, "model": tv.model}
    return {k: v for k, v in said.items() if v is not None or k == "tv"}


def _entries(tv: Tv, plugged: Mapping[str, str | None] | None) -> list[dict[str, Any]]:
    """Every input with a device on it, in order, saying whether the TV found it or the owner named it."""
    found = {
        key: {"input": INPUTS[key], "device": name, "from": "detected"}
        for key, name in (plugged or {}).items()
    }
    by_hand = {
        key: {"input": INPUTS[key], "device": name, "from": "set by hand"} for key, name in tv.inputs.items()
    }
    # RULE: a name set by hand wins over a detected one
    entries = found | by_hand
    return [entries[key] for key in INPUTS if key in entries]


def _named_input(tv: Tv, source: str) -> str | dict[str, Any]:
    """The key in ``INPUTS`` for `source`, an input or a device on `tv`; else a refusal."""
    if (key := input_key(source)) in INPUTS:
        return key
    fits = tv.inputs_for(source)
    # RULE: a device name that fits two inputs is refused
    if len(fits) == 1:
        return fits[0]
    if fits:
        both = " or ".join(tv.inputs[k] for k in fits)
        return _refused(f"{source!r} could be {both} on {tv.spoken}. Say which one.")
    devices = " or ".join(tv.inputs.values())
    choices = f"a device: {devices}; or HDMI 1 to HDMI 4, or TV" if devices else "HDMI 1 to HDMI 4, or TV"
    return _refused(f"{_capital(tv.spoken)} has no {source!r}. Say {choices}.")


def _labelled(tv: Tv, said: str) -> str:
    """An input said aloud, with the device on it when the owner named one: "HDMI 3, the Game Box,"."""
    device = tv.device_on(said)
    return f"{said}, the {device}," if device else said


def _input_answer(tv: Tv, sent: InputSent) -> dict[str, Any]:
    """What to say once an input was sent: seen, not seen, or not knowable."""
    if sent.unplugged:
        now = f"; it still shows {sent.shown}" if sent.shown else ""
        return _refused(
            f"Nothing is plugged into {sent.said} on {tv.spoken}{now}."
            " Plug something in, or pick another input."
        )
    if sent.shown is None:
        return {"outcome": "unverified", "say": _unconfirmed(tv, sent)}
    if sent.shown == sent.said:
        return {"outcome": "done", "say": f"{_capital(tv.spoken)} shows {_labelled(tv, sent.said)} now."}
    return {
        "outcome": "unverified",
        "say": (
            f"I asked {tv.spoken} for {sent.said}, but it still shows {sent.shown}."
            " Try again, or use the TV's own remote."
        ),
    }


def _unconfirmed(tv: Tv, sent: InputSent) -> str:
    """What a TV that cannot say its input did show: an app leaving the screen, or staying on it."""
    # RULE: an input change the TV cannot confirm is never done
    if sent.left:
        return (
            f"I sent {sent.said} to {tv.spoken}. {sent.left} left the screen,"
            " but this TV cannot say which input is on screen. Look at the screen to be sure."
        )
    if sent.stayed:
        return (
            f"I sent {sent.said} to {tv.spoken}, but {sent.stayed} is still on the screen."
            " Nothing may be connected there, or it is off. Check it, or use the TV's own remote."
        )
    if sent.accepted:
        device = tv.device_on(sent.said)
        named = f"{sent.said} ({device})" if device else sent.said
        return (
            f"{_capital(tv.spoken)} accepted the switch to {named}, but can't confirm the picture."
            " Look at the screen to be sure."
        )
    return (
        f"I sent {sent.said} to {tv.spoken}, but this TV cannot say which input is on screen,"
        " so it is not confirmed. Look at the screen to be sure."
    )


def _shows(report: dict[str, Any], wanted: str) -> bool:
    """Whether the TV in `report` is `wanted`, "on" or "off", by its own screen when known."""
    now = report.get("screen") or report["state"]
    return now == "on" if wanted == "on" else now in SCREEN_OFF


def _report(tv: Tv | None, info: TvInfo | None) -> dict[str, Any]:
    known = _known(tv)
    if info is None:
        return {**known, "state": UNREACHABLE}
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
    if playing.behind:
        report["behind"] = list(playing.behind)
    return report

# SPDX-License-Identifier: GPL-3.0-or-later
"""YouTube: finding videos with yt-dlp or YouTube's Data API, and starting one on a screen.

A video is started through YouTube's "Lounge", the remote-control service the
YouTube phone app uses to cast to a TV's YouTube app, with pyytlounge. Each
TV is paired once from the screen id its YouTube app gives, and the pairing is
kept in a file beside the settings, readable only by the owner.

Neither yt-dlp nor the Lounge is an official YouTube interface: YouTube can
change them, and its terms do not allow them. The Data API is the official
route for search, used when the owner gives a key. Both libraries come with
the optional ``youtube`` extra.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
from typing import TYPE_CHECKING, Any

from tv_mcp.video import Video

if TYPE_CHECKING:
    import pathlib

    import httpx

    from tv_mcp.video import VideoSearch

#: How many videos a search asks for.
SEARCH_SIZE = 8
#: Videos this short are taken for Shorts, which the Lounge cannot start.
SHORTEST = 61
#: How long to wait for a screen to say it plays the video, and how many times to ask.
START_WAIT = 30.0
START_TRIES = 2
API = "https://www.googleapis.com/youtube/v3"
_ISO = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def _video(video_id: str, title: str, channel: str | None, duration: float | None) -> Video | None:
    if not video_id or not title or duration is None or duration < SHORTEST:
        return None
    return Video(id=video_id, title=title, channel=channel or None, duration=float(duration))


def videos_from_search(entries: list[dict[str, Any]]) -> list[Video]:
    """The videos in yt-dlp's flat search results, without live streams and Shorts."""
    found = []
    for entry in entries:
        if entry.get("live_status") in {"is_live", "is_upcoming"}:
            continue
        video = _video(
            entry.get("id") or "", entry.get("title") or "", entry.get("channel"), entry.get("duration")
        )
        if video:
            found.append(video)
    return found


def video_from_page(page: dict[str, Any]) -> Video | None:
    """The video one video's page describes, without the Shorts and length checks of a search."""
    if not page.get("id") or not page.get("title"):
        return None
    duration = page.get("duration")
    return Video(
        id=str(page["id"]),
        title=str(page["title"]),
        channel=page.get("channel") or page.get("uploader") or None,
        duration=float(duration) if duration else None,
    )


class StartWatch:
    """Watches a screen's reports until it says it is playing one video.

    The screen names the video as soon as it starts loading it; leaving then
    stops it, so only "Playing" counts (2026-11-09, on the garage Chromecast).
    """

    def __init__(self, video_id: str) -> None:
        """Wait for `video_id`."""
        self._video_id = video_id
        self._current: str | None = None
        self.started, self.advert = asyncio.Event(), False

    def now_playing(self, video_id: str | None, state: str) -> None:
        """The screen changed video; `state` is the name of its playing state."""
        self._current = video_id
        self.playback(state)

    def playback(self, state: str) -> None:
        """The screen's playing state changed; an advert before the video counts as started."""
        if self._current == self._video_id and state in {"Playing", "Advertisement"}:
            self.advert = self.advert or state == "Advertisement"
            self.started.set()


def _seconds(iso: str) -> float | None:
    match = _ISO.fullmatch(iso or "")
    if not match or not any(match.groups()):
        return None
    days, hours, minutes, seconds = (int(g or 0) for g in match.groups())
    return float(((days * 24 + hours) * 60 + minutes) * 60 + seconds)


def videos_from_api(search: dict[str, Any], details: dict[str, Any]) -> list[Video]:
    """The videos in a Data API search, with their lengths from a second call."""
    lengths = {
        d["id"]: _seconds(d.get("contentDetails", {}).get("duration", "")) for d in details.get("items", [])
    }
    found = []
    for item in search.get("items", []):
        snippet, video_id = item.get("snippet", {}), item.get("id", {}).get("videoId", "")
        if snippet.get("liveBroadcastContent", "none") != "none":
            continue
        video = _video(video_id, snippet.get("title", ""), snippet.get("channelTitle"), lengths.get(video_id))
        if video:
            found.append(video)
    return found


class YtDlpSearch:
    """Search with yt-dlp, which reads YouTube's own search page: no key, no quota."""

    async def search(self, words: str) -> list[Video]:  # pragma: no cover - reaches YouTube
        """The videos YouTube's search page lists for `words`."""
        import yt_dlp  # type: ignore[import-not-found,import-untyped,unused-ignore]  # noqa: PLC0415 - the optional youtube extra

        def run() -> list[dict[str, Any]]:
            options = {
                "quiet": True,
                "no_warnings": True,
                "extract_flat": "in_playlist",
                "skip_download": True,
            }
            with yt_dlp.YoutubeDL(options) as site:
                page = site.extract_info(f"ytsearch{SEARCH_SIZE}:{words}", download=False)
            return list((page or {}).get("entries") or [])

        return videos_from_search(await asyncio.to_thread(run))

    async def video(self, video_id: str) -> Video | None:  # pragma: no cover - reaches YouTube
        """The video's own page, read without downloading anything."""
        import yt_dlp  # type: ignore[import-not-found,import-untyped,unused-ignore]  # noqa: PLC0415

        def run() -> dict[str, Any]:
            options = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True}
            with yt_dlp.YoutubeDL(options) as site:
                url = f"https://www.youtube.com/watch?v={video_id}"
                return dict(site.extract_info(url, download=False, process=False) or {})

        return video_from_page(await asyncio.to_thread(run))


class DataApiSearch:
    """Search with YouTube's Data API: official, needs a key, 100 searches a day."""

    def __init__(self, key: str, client: httpx.AsyncClient) -> None:
        """Ask with `key`, over `client`."""
        self._key, self._client = key, client

    async def search(self, words: str) -> list[Video]:
        """The videos the API finds for `words`, with their lengths."""
        search = await self._get(
            "/search", {"part": "snippet", "q": words, "type": "video", "maxResults": str(SEARCH_SIZE)}
        )
        ids = [i["id"]["videoId"] for i in search.get("items", []) if i.get("id", {}).get("videoId")]
        if not ids:
            return []
        details = await self._get("/videos", {"part": "contentDetails", "id": ",".join(ids)})
        return videos_from_api(search, details)

    async def video(self, video_id: str) -> Video | None:
        """The video with `video_id`, with its length."""
        page = await self._get("/videos", {"part": "snippet,contentDetails", "id": video_id})
        for item in page.get("items", []):
            snippet = item.get("snippet", {})
            return video_from_page(
                {
                    "id": item.get("id"),
                    "title": snippet.get("title"),
                    "channel": snippet.get("channelTitle"),
                    "duration": _seconds(item.get("contentDetails", {}).get("duration", "")),
                }
            )
        return None

    async def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        response = await self._client.get(API + path, params={**params, "key": self._key}, timeout=10)
        response.raise_for_status()
        page: dict[str, Any] = response.json()
        return page


class FirstThatAnswers:
    """One search, and another when the first fails or finds nothing."""

    def __init__(self, first: VideoSearch, then: VideoSearch | None) -> None:
        """Ask `first`, then `then`."""
        self._first, self._then = first, then

    async def search(self, words: str) -> list[Video]:
        """What the first search finds, or else what the second does."""
        try:
            found = await self._first.search(words)
        except Exception:  # noqa: BLE001 - any failure of a search means trying the other
            found = []
        if found or self._then is None:
            return found
        try:
            return await self._then.search(words)
        except Exception:  # noqa: BLE001
            return []

    async def video(self, video_id: str) -> Video | None:
        """The video as the first search knows it, or else as the second does."""
        for search in (self._first, self._then):
            if search is None:
                continue
            try:
                if found := await search.video(video_id):
                    return found
            except Exception:  # noqa: BLE001, S112 - any failure means trying the other
                continue
        return None


class PyYtLounge:  # pragma: no cover - reaches YouTube and a real screen
    """Start a video on a screen through YouTube's Lounge, pairing once per TV."""

    def __init__(self, folder: pathlib.Path) -> None:
        """Keep each TV's pairing in `folder`."""
        self._folder = folder
        #: Whether the last video started with an advert.
        self.advert = False

    async def play(self, tv_key: str, screen_id: str, video_id: str) -> bool:
        """Start `video_id`; True only once the screen says it is playing it."""
        from pyytlounge import EventListener, YtLoungeApi  # type: ignore[import-untyped,unused-ignore]  # noqa: PLC0415 - the optional youtube extra

        watch = StartWatch(video_id)

        class Watch(EventListener):  # type: ignore[misc,unused-ignore]
            async def now_playing_changed(self, event: Any) -> None:  # noqa: ANN401 - pyytlounge's event
                watch.now_playing(getattr(event, "video_id", None), getattr(event.state, "name", ""))

            async def playback_state_changed(self, event: Any) -> None:  # noqa: ANN401 - pyytlounge's event
                watch.playback(getattr(event.state, "name", ""))

        file = self._folder / f"{tv_key}-youtube"
        async with YtLoungeApi("tv-mcp", Watch()) as api:
            if file.is_file():
                with contextlib.suppress(ValueError, KeyError, TypeError):
                    api.load_auth_state(json.loads(file.read_text()))
            paired = api.auth.screen_id == screen_id and await api.refresh_auth()
            if not paired and not await api.pair_with_screen_id(screen_id):
                return False
            file.touch(mode=0o600)
            file.write_text(json.dumps(api.store_auth_state()))
            if not await api.connect():
                return False
            listening = asyncio.create_task(api.subscribe())
            try:
                for _ in range(START_TRIES):
                    if not await api.play_video(video_id):
                        continue
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(watch.started.wait(), START_WAIT)
                    if watch.started.is_set():
                        self.advert = watch.advert
                        # One video was asked for: do not run on into the next.
                        with contextlib.suppress(Exception):
                            await api.set_auto_play_mode(enabled=False)
                        return True
                return False
            finally:
                # Only stop listening. pyytlounge's disconnect() tells the screen the
                # user stopped casting, and the screen then stops the video
                # (2026-11-09, on the garage Chromecast).
                listening.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await listening

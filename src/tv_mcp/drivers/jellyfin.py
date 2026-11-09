# SPDX-License-Identifier: GPL-3.0-or-later
"""The Jellyfin server, through its own HTTP API: search, sessions, and play.

Three calls are all that is needed, so this speaks the API directly rather than
through a client library: ``GET /Items``, ``GET /Sessions`` and
``POST /Sessions/{id}/Playing``. The API key is the one the owner made under
Dashboard → API Keys, read from the settings file.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from tv_mcp.media import CastLogin, Chapter, Cue, MediaItem, Session, parse_srt

if TYPE_CHECKING:
    from collections.abc import Callable

TIMEOUT = 5.0
#: A subtitle track inside the film is pulled out of it first, which takes longer.
SUBTITLE_TIMEOUT = 30.0
SEARCH_LIMIT = 5


class Jellyfin:
    """One Jellyfin server."""

    def __init__(self, url: str, api_key: str, client: httpx.AsyncClient) -> None:
        """Reach the server at `url` with `api_key`, over `client`."""
        self._url, self._client = url.rstrip("/"), client
        self._headers = {"Authorization": f'MediaBrowser Token="{api_key}"'}
        self._user: str | None = None

    async def _user_id(self) -> str | None:
        """The library's first user, whose saved positions are read; None when it cannot be told."""
        if self._user is None:
            try:
                users = await self._get("/Users")
                self._user = str(users[0]["Id"])
            except (httpx.HTTPError, ValueError, LookupError, TypeError):
                return None
        return self._user

    async def _get(self, path: str, params: dict[str, str] | None = None) -> Any:  # noqa: ANN401 - JSON
        response = await self._client.get(
            self._url + path, params=params, headers=self._headers, timeout=TIMEOUT
        )
        response.raise_for_status()
        return response.json()

    async def search(self, term: str) -> list[MediaItem]:
        """Films and episodes whose title matches `term`."""
        params = {
            "searchTerm": term,
            "IncludeItemTypes": "Movie,Episode",
            "Recursive": "true",
            "Limit": str(SEARCH_LIMIT),
            "Fields": "ProductionYear",
        }
        try:
            if user := await self._user_id():
                params["userId"] = user
            page = await self._get("/Items", params)
        except (httpx.HTTPError, ValueError):
            return []
        return [_item(i) for i in page.get("Items", [])]

    async def sessions(self) -> list[Session]:
        """The apps connected now, each with the address it connected from."""
        try:
            page = await self._get("/Sessions")
        except (httpx.HTTPError, ValueError):
            return []
        return [_session(s) for s in page]

    async def play(self, session_id: str, item_id: str, start: float = 0.0) -> None:
        """Start `item_id` at once in the session, `start` seconds in."""
        params = {"playCommand": "PlayNow", "itemIds": item_id}
        if start > 0:
            params["startPositionTicks"] = str(int(start * TICKS))
        response = await self._client.post(
            f"{self._url}/Sessions/{session_id}/Playing",
            params=params,
            headers=self._headers,
            timeout=TIMEOUT,
        )
        response.raise_for_status()

    async def _details(self, item_id: str) -> dict[str, Any] | None:
        params = {"ids": item_id, "Fields": "MediaSources,People,Chapters"}
        try:
            if user := await self._user_id():
                params["userId"] = user
            page = await self._get("/Items", params)
        except (httpx.HTTPError, ValueError):
            return None
        items = page.get("Items") or []
        return items[0] if items else None

    async def subtitles(self, item_id: str) -> list[Cue] | None:
        """The item's subtitles as cues, preferring a track for the hard of hearing."""
        details = await self._details(item_id)
        sources = (details or {}).get("MediaSources") or []
        if not sources:
            return None
        tracks = [s for s in sources[0].get("MediaStreams", []) if s.get("Type") == "Subtitle"]
        if not tracks:
            return None
        track = min(tracks, key=lambda s: 0 if _for_the_hard_of_hearing(s) else 1)
        try:
            response = await self._client.get(
                f"{self._url}/Videos/{item_id}/{sources[0]['Id']}/Subtitles/{track['Index']}/0/Stream.srt",
                headers=self._headers,
                timeout=SUBTITLE_TIMEOUT,
            )
            response.raise_for_status()
        except httpx.HTTPError:
            return None
        return parse_srt(response.text)

    async def cast(self, item_id: str) -> list[tuple[str, str]]:
        """Each character with the actor who plays them, in the library's order."""
        details = await self._details(item_id) or {}
        return [
            (p["Role"], p["Name"])
            for p in details.get("People") or []
            if p.get("Type") == "Actor" and p.get("Role") and p.get("Name")
        ]

    async def chapters(self, item_id: str) -> list[Chapter]:
        """The item's chapters with their start times."""
        details = await self._details(item_id) or {}
        return [
            Chapter(start=_seconds(c.get("StartPositionTicks")) or 0.0, name=str(c.get("Name") or ""))
            for c in details.get("Chapters") or []
        ]

    async def seek(self, session_id: str, seconds: float) -> None:
        """Move what the session is playing to `seconds` from its start."""
        response = await self._client.post(
            f"{self._url}/Sessions/{session_id}/Playing/Seek",
            params={"seekPositionTicks": str(int(seconds * TICKS))},
            headers=self._headers,
            timeout=TIMEOUT,
        )
        response.raise_for_status()

    async def control(self, session_id: str, command: str) -> None:
        """Pause, resume or stop what the session is playing."""
        response = await self._client.post(
            f"{self._url}/Sessions/{session_id}/Playing/{JELLYFIN_COMMANDS[command]}",
            headers=self._headers,
            timeout=TIMEOUT,
        )
        response.raise_for_status()


#: Jellyfin counts time in ticks of 100 nanoseconds.
TICKS = 10_000_000

#: Jellyfin's name for each command in tv_mcp.media.COMMANDS.
JELLYFIN_COMMANDS = {"pause": "Pause", "resume": "Unpause", "stop": "Stop"}


def _for_the_hard_of_hearing(stream: dict[str, Any]) -> bool:
    """Whether a subtitle track names who speaks and the sounds, as SDH tracks do."""
    words = f"{stream.get('Title') or ''} {stream.get('DisplayTitle') or ''}".casefold()
    return bool(stream.get("IsHearingImpaired")) or "sdh" in words.split() or "hearing" in words


def _session(page: dict[str, Any]) -> Session:
    endpoint = page.get("RemoteEndPoint")
    address = endpoint.rsplit(":", 1)[0] if endpoint and endpoint.count(":") == 1 else endpoint
    playing = page.get("NowPlayingItem") or {}
    state = page.get("PlayState") or {}
    return Session(
        id=page["Id"],
        address=address,
        client=page.get("Client", ""),
        controllable=bool(page.get("SupportsRemoteControl", False)),
        now_playing=playing.get("Name"),
        item_id=playing.get("Id") or None,
        position=_seconds(state.get("PositionTicks")) if playing else None,
        runtime=_seconds(playing.get("RunTimeTicks")),
        paused=bool(state.get("IsPaused", False)) if playing else False,
    )


def _seconds(ticks: object) -> float | None:
    return ticks / TICKS if isinstance(ticks, int | float) and ticks > 0 else None


def _item(page: dict[str, Any]) -> MediaItem:
    data = page.get("UserData") or {}
    last = data.get("LastPlayedDate")
    return MediaItem(
        id=page["Id"],
        title=page.get("Name", ""),
        year=page.get("ProductionYear"),
        kind=page.get("Type", ""),
        position=_seconds(data.get("PlaybackPositionTicks")),
        runtime=_seconds(page.get("RunTimeTicks")),
        last_played=str(last)[:10] if last else None,
    )


def _local_address(towards: str) -> str:  # pragma: no cover - asks the operating system
    """The address this computer has on the network that leads to `towards`; nothing is sent."""
    import socket  # noqa: PLC0415

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect((towards, 9))
        return str(probe.getsockname()[0])


async def cast_login(
    url: str,
    token: str,
    client: httpx.AsyncClient,
    cast_address: str,
    *,
    local_address: Callable[[str], str] = _local_address,
) -> CastLogin | None:
    """The login a cast device at `cast_address` needs, as the user who owns `token`.

    The server is named by this computer's address on the cast device's network,
    since "localhost" in the settings would mean the device itself.
    """
    headers = {"Authorization": f'MediaBrowser Token="{token}"'}
    try:
        me = (await client.get(f"{url.rstrip('/')}/Users/Me", headers=headers, timeout=TIMEOUT)).json()
        info = (await client.get(f"{url.rstrip('/')}/System/Info", headers=headers, timeout=TIMEOUT)).json()
        port = httpx.URL(url).port or 8096
        server = f"http://{local_address(cast_address)}:{port}"
        return CastLogin(
            server=server, token=token, user_id=me["Id"], server_id=info["Id"], version=info.get("Version")
        )
    except (httpx.HTTPError, ValueError, KeyError, OSError):
        return None

# SPDX-License-Identifier: GPL-3.0-or-later
"""The Jellyfin server, through its own HTTP API: search, sessions, and play.

Three calls are all that is needed, so this speaks the API directly rather than
through a client library: ``GET /Items``, ``GET /Sessions`` and
``POST /Sessions/{id}/Playing``. The API key is the one the owner made under
Dashboard → API Keys, read from the settings file.
"""

from __future__ import annotations

from typing import Any

import httpx

from tv_mcp.media import MediaItem, Session

TIMEOUT = 5.0
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

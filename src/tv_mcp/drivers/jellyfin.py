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
            page = await self._get("/Items", params)
        except (httpx.HTTPError, ValueError):
            return []
        return [
            MediaItem(
                id=i["Id"], title=i.get("Name", ""), year=i.get("ProductionYear"), kind=i.get("Type", "")
            )
            for i in page.get("Items", [])
        ]

    async def sessions(self) -> list[Session]:
        """The apps connected now, each with the address it connected from."""
        try:
            page = await self._get("/Sessions")
        except (httpx.HTTPError, ValueError):
            return []
        return [_session(s) for s in page]

    async def play(self, session_id: str, item_id: str) -> None:
        """Start `item_id` at once in the session."""
        response = await self._client.post(
            f"{self._url}/Sessions/{session_id}/Playing",
            params={"playCommand": "PlayNow", "itemIds": item_id},
            headers=self._headers,
            timeout=TIMEOUT,
        )
        response.raise_for_status()


def _session(page: dict[str, Any]) -> Session:
    endpoint = page.get("RemoteEndPoint")
    address = endpoint.rsplit(":", 1)[0] if endpoint and endpoint.count(":") == 1 else endpoint
    return Session(
        id=page["Id"],
        address=address,
        client=page.get("Client", ""),
        controllable=bool(page.get("SupportsRemoteControl", False)),
    )

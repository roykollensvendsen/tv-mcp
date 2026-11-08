# SPDX-License-Identifier: GPL-3.0-or-later
"""The Jellyfin library: searching, finding a TV's session, and starting an item on it."""

import asyncio

import httpx

from tv_mcp.drivers.jellyfin import Jellyfin

URL, KEY = "http://192.0.2.5:8096", "example-key"
ITEMS = {
    "Items": [
        {"Id": "a1", "Name": "Star Wars: Episode IV - A New Hope", "ProductionYear": 1977, "Type": "Movie"},
        {"Id": "b2", "Name": "Rogue One: A Star Wars Story", "ProductionYear": 2016, "Type": "Movie"},
    ]
}
SESSIONS = [
    {
        "Id": "s1",
        "Client": "Jellyfin for Tizen",
        "DeviceName": "Samsung The Frame 55",
        "RemoteEndPoint": "192.0.2.10",
        "SupportsRemoteControl": True,
    },
    {"Id": "s2", "Client": "Jellyfin Web", "DeviceName": "Firefox", "RemoteEndPoint": "192.0.2.30:51000"},
]


def _run(handler, work):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await work(Jellyfin(URL, KEY, client))

    return asyncio.run(run())


def test_search_asks_for_films_and_episodes_with_the_key():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=ITEMS)

    found = _run(handler, lambda j: j.search("new hope"))
    assert [i.title for i in found] == ["Star Wars: Episode IV - A New Hope", "Rogue One: A Star Wars Story"]
    assert found[0].year == 1977
    [request] = seen
    assert request.url.path == "/Items"
    assert request.url.params["searchTerm"] == "new hope"
    assert "Movie" in request.url.params["IncludeItemTypes"]
    assert request.headers["Authorization"] == f'MediaBrowser Token="{KEY}"'


def test_sessions_give_each_ones_address_without_its_port():
    sessions = _run(lambda _r: httpx.Response(200, json=SESSIONS), lambda j: j.sessions())
    assert [(s.id, s.address, s.controllable) for s in sessions] == [
        ("s1", "192.0.2.10", True),
        ("s2", "192.0.2.30", False),
    ]


def test_play_tells_the_session_to_play_the_item_now():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(204)

    _run(handler, lambda j: j.play("s1", "a1"))
    [request] = seen
    assert request.method == "POST"
    assert request.url.path == "/Sessions/s1/Playing"
    assert request.url.params["playCommand"] == "PlayNow"
    assert request.url.params["itemIds"] == "a1"


def test_a_server_that_does_not_answer_gives_an_empty_search():
    def handler(request):
        message = "refused"
        raise httpx.ConnectError(message, request=request)

    assert _run(handler, lambda j: j.search("anything")) == []

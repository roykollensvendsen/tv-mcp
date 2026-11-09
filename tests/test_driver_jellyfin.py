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
    [request] = [r for r in seen if r.url.path == "/Items"]
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


def test_control_sends_stop_pause_and_unpause():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(204)

    for command in ("stop", "pause", "resume"):
        _run(handler, lambda j, c=command: j.control("s1", c))
    assert seen == ["/Sessions/s1/Playing/Stop", "/Sessions/s1/Playing/Pause", "/Sessions/s1/Playing/Unpause"]


TICKS = 10_000_000  # Jellyfin counts time in ticks of 100 ns


def _server(seen):
    def handler(request):
        seen.append(request)
        if request.url.path == "/Users":
            return httpx.Response(200, json=[{"Id": "u1", "Name": "family"}])
        if request.url.path == "/Items":
            stopped = {"PlaybackPositionTicks": 72 * 60 * TICKS, "LastPlayedDate": "2026-11-08T20:15:00Z"}
            hope = {**ITEMS["Items"][0], "RunTimeTicks": 121 * 60 * TICKS, "UserData": stopped}
            return httpx.Response(200, json={"Items": [hope, ITEMS["Items"][1]]})
        if request.url.path == "/Sessions":
            playing = {
                **SESSIONS[0],
                "NowPlayingItem": {
                    "Name": "Star Wars: Episode IV - A New Hope",
                    "RunTimeTicks": 121 * 60 * TICKS,
                },
                "PlayState": {"PositionTicks": 72 * 60 * TICKS, "IsPaused": True},
            }
            return httpx.Response(200, json=[playing, SESSIONS[1]])
        return httpx.Response(204)

    return handler


def test_search_gives_where_each_item_was_stopped_and_when_it_was_last_watched():
    seen = []
    hope, rogue = _run(_server(seen), lambda j: j.search("star wars"))
    assert (hope.position, hope.runtime, hope.last_played) == (72 * 60, 121 * 60, "2026-11-08")
    assert rogue.position is None
    assert seen[-1].url.params["userId"] == "u1"


def test_sessions_say_what_is_playing_how_far_in_and_whether_paused():
    playing, idle = _run(_server([]), lambda j: j.sessions())
    assert (playing.now_playing, playing.position, playing.runtime, playing.paused) == (
        "Star Wars: Episode IV - A New Hope",
        72 * 60,
        121 * 60,
        True,
    )
    assert idle.now_playing is None


def test_play_can_start_from_a_position():
    seen = []
    _run(_server(seen), lambda j: j.play("s1", "a1", start=72 * 60))
    assert seen[-1].url.params["startPositionTicks"] == str(72 * 60 * TICKS)


def test_a_cast_login_uses_the_users_own_token_and_an_address_the_chromecast_can_reach():
    from tv_mcp.drivers.jellyfin import cast_login  # noqa: PLC0415

    seen = []

    def handler(request):
        seen.append(request.headers["Authorization"])
        if request.url.path == "/Users/Me":
            return httpx.Response(200, json={"Id": "u1"})
        return httpx.Response(200, json={"Id": "srv", "Version": "12.4.0"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await cast_login(
                "http://192.0.2.9:8096",
                "user-token",
                client,
                "192.0.2.20",
                local_address=lambda _a: "192.0.2.5",
            )

    login = asyncio.run(run())
    assert (login.server, login.user_id, login.server_id) == ("http://192.0.2.5:8096", "u1", "srv")
    assert all('Token="user-token"' in h for h in seen)


def test_seek_tells_the_session_where_to_go_in_ticks():
    seen = []
    _run(_server(seen), lambda j: j.seek("s1", 67 * 60))
    assert seen[-1].url.path == "/Sessions/s1/Playing/Seek"
    assert seen[-1].url.params["seekPositionTicks"] == str(67 * 60 * TICKS)

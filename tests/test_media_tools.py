# SPDX-License-Identifier: GPL-3.0-or-later
"""What the voice gets back from the film tools, with and without YouTube set up."""

import asyncio

from tv_mcp.server import build_server
from tv_mcp.simulator import simulated_service


def _call(service, tool, arguments):
    server = build_server(service, features=["status", "media"], simulated=True)
    return asyncio.run(server.call_tool(tool, arguments)).structured_content


def _takes_a_source(service, tool):
    """Whether `tool` is the one registered with YouTube set up, which takes a source."""
    server = build_server(service, features=["status", "media"], simulated=True)
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    return "source" in tools[tool].input_schema["properties"]


def test_a_seek_with_no_time_asks_where_to_go():
    answer = _call(simulated_service(), "tv_control", {"command": "seek", "tv": "the living room"})
    assert answer["outcome"] == "refused"
    assert answer["say"].endswith("Say where to go, or how far to skip.")
    assert answer["success"] is False


def test_a_seek_with_a_time_goes_to_the_tv():
    service = simulated_service()
    asked = []

    async def seek(name, seconds, *, relative):
        asked.append((name, seconds, relative))
        return {"outcome": "done", "say": "Done."}

    service.seek = seek
    answer = _call(
        service, "tv_control", {"command": "seek", "tv": "the living room", "seconds": 30, "relative": True}
    )
    assert asked == [("the living room", 30, True)]
    assert answer["success"] is True


def test_with_youtube_set_up_a_search_with_no_source_still_finds_films():
    service = simulated_service()
    service.videos = object()  # YouTube set up; a film search must not reach it
    assert _takes_a_source(service, "tv_search")
    answer = _call(service, "tv_search", {"title": "Alien"})
    expected = asyncio.run(simulated_service().search("Alien"))
    assert answer["items"] == expected["items"]
    assert answer["success"] is ("say" not in expected)


def test_with_youtube_set_up_play_with_no_source_still_plays_a_film():
    service = simulated_service()
    service.videos = object()
    assert _takes_a_source(service, "tv_play")
    asked = []

    async def play(title, name, *, from_start=False):
        asked.append((title, name, from_start))
        return {"outcome": "playing", "say": "Playing."}

    service.play = play
    answer = _call(service, "tv_play", {"title": "Alien", "tv": "the living room", "from_start": True})
    assert asked == [("Alien", "the living room", True)]
    assert answer["success"] is True

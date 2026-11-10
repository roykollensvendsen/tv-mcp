# SPDX-License-Identifier: GPL-3.0-or-later
"""Each tool's first sentence is what the voice sees before it loads the tool.

The Claude app lists a tool it has not loaded yet as one line: the connector's
own label, then the description, cut at about eighty characters. That leaves the
voice the first two dozen or so characters of each description to choose by. So
every tool opens with a whole, short sentence on a line of its own, saying what
sets it apart without repeating its name; no two tools open with the same words;
and the details follow on the next lines.

``OPENING_LIMIT`` is what showed on 2026-11-10. The app may change it, so an
opening is kept short rather than written to fill it.
"""

import asyncio
import re

from tv_mcp.server import build_server
from tv_mcp.simulator import simulated_service
from tv_mcp.tools import FEATURES

#: The characters of a description the voice saw before loading a tool, 2026-11-10.
OPENING_LIMIT = 26


def _every_tool():
    """Every tool, from every feature, with YouTube both off and on."""
    plain = simulated_service()
    with_videos = simulated_service()
    with_videos.videos = object()
    tools = []
    for service in (plain, with_videos):
        tools += asyncio.run(build_server(service, features=list(FEATURES)).list_tools())
    return tools


def _opening(tool):
    return (tool.description or "").split("\n", 1)[0]


def test_every_tool_opens_with_a_whole_sentence_the_voice_sees_in_full():
    for tool in _every_tool():
        opening = _opening(tool)
        assert len(opening) <= OPENING_LIMIT, f"{tool.name}: {opening!r} is {len(opening)} characters"
        assert re.fullmatch(r"[A-Z].*[.?]", opening), f"{tool.name}: {opening!r} is not one whole sentence"


def test_an_opening_does_not_repeat_the_tools_name():
    for tool in _every_tool():
        words = set(re.findall(r"[a-z]+", _opening(tool).casefold()))
        named = set(tool.name.removeprefix("tv_").split("_")) - {"app"}
        assert not words & named, f"{tool.name}: {_opening(tool)!r} repeats its name"


def test_no_two_tools_open_with_the_same_words():
    openings = {}
    for tool in _every_tool():
        start = " ".join(_opening(tool).casefold().split()[:2])
        assert openings.setdefault(start, tool.name) == tool.name, f"{tool.name} and {openings[start]}"


def test_the_details_come_on_the_lines_after_the_opening():
    for tool in _every_tool():
        opening = _opening(tool)
        assert not re.search(r"[.?;:] ", opening), f"{tool.name}: {opening!r} runs on past one sentence"

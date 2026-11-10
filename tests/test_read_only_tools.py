# SPDX-License-Identifier: GPL-3.0-or-later
"""The tools that only look are marked read-only, and only those.

A bridge or a voice can then run a read-only tool without asking, and knows
every other tool may change something on a TV (the plugin standard's rule 9).
"""

import asyncio

from tv_mcp.server import build_server
from tv_mcp.simulator import simulated_service
from tv_mcp.tools import FEATURES

#: The tools that change nothing on any TV, nor anything that plays on one.
READ_ONLY = {"tv_status", "tv_search", "tv_scene", "tv_discover"}


def _every_tool():
    plain = simulated_service()
    with_videos = simulated_service()
    with_videos.videos = object()
    tools = {}
    for service in (plain, with_videos):
        for tool in asyncio.run(build_server(service, features=list(FEATURES)).list_tools()):
            tools[tool.name] = tool
    return tools


def test_the_tools_that_only_look_are_marked_read_only_and_no_others():
    marked = {
        name for name, tool in _every_tool().items() if tool.annotations and tool.annotations.read_only_hint
    }
    assert marked == READ_ONLY


def test_every_other_tool_is_marked_as_one_that_changes_something():
    for name, tool in _every_tool().items():
        if name not in READ_ONLY:
            assert tool.annotations is not None, name
            assert tool.annotations.read_only_hint is False, name


def test_the_mark_reaches_the_bridge_under_the_protocols_own_name():
    tool = _every_tool()["tv_status"]
    assert tool.annotations.model_dump(by_alias=True, exclude_none=True) == {"readOnlyHint": True}

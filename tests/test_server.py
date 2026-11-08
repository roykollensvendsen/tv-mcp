# SPDX-License-Identifier: GPL-3.0-or-later
"""The MCP tools, as the voice sees them, against the simulated TV."""

import asyncio

import pytest

from tv_mcp.server import UnknownFeatureError, build_server
from tv_mcp.simulator import simulated_service
from tv_mcp.tools import FEATURES


def _tools(server):
    return {tool.name: tool for tool in asyncio.run(server.list_tools())}


def _call(server, tool, arguments=None):
    return asyncio.run(server.call_tool(tool, arguments or {})).structured_content


def test_only_a_switched_on_feature_adds_tools():
    assert sorted(_tools(build_server(simulated_service(), simulated=True))) == ["tv_status"]
    both = build_server(simulated_service(), features=["status", "setup"], simulated=True)
    assert sorted(_tools(both)) == ["tv_discover", "tv_status"]
    assert _tools(build_server(simulated_service(), features=[], simulated=True)) == {}


def test_every_tool_is_named_after_the_plugin():
    names = _tools(build_server(simulated_service(), features=list(FEATURES), simulated=True))
    assert all(name.startswith(("tv_", "media_")) for name in names)


def test_an_unknown_feature_is_refused_at_start():
    with pytest.raises(UnknownFeatureError, match="status"):
        build_server(simulated_service(), features=["status", "karaoke"])


def test_tv_status_names_the_tv_and_says_it_is_on():
    answer = _call(build_server(simulated_service(), simulated=True), "tv_status", {"tv": "The Frame"})
    assert answer["tvs"][0]["state"] == "on"
    assert answer["simulated"] is True


def test_tv_discover_reports_the_frame_with_its_year_and_platform():
    server = build_server(simulated_service(), features=["setup"], simulated=True)
    answer = _call(server, "tv_discover")
    [frame] = answer["tvs"]
    assert (frame["year"], frame["platform"]) == (2022, "Tizen 6.5")
    assert answer["searched"] is False


def test_the_simulated_server_says_it_is_simulated():
    assert build_server(simulated_service(), simulated=True).instructions.startswith("SIMULATED")

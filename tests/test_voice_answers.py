# SPDX-License-Identifier: GPL-3.0-or-later
"""What the claude-voice bridge needs from every answer: a 'say' line and 'success'."""

import asyncio

from tv_mcp.server import build_server
from tv_mcp.simulator import simulated_service
from tv_mcp.tools import FEATURES

#: The tools the owner approves in claude-voice. Changing this list, or a
#: tool's inputs, means the owner has to approve the plugin again.
APPROVED_DEFAULT = ["tv_control", "tv_play", "tv_search", "tv_status"]


def _server(features=None):
    return build_server(simulated_service(), simulated=True, **({"features": features} if features else {}))


def _call(server, tool, arguments=None):
    return asyncio.run(server.call_tool(tool, arguments or {})).structured_content


def test_every_tool_starts_with_tv():
    names = [t.name for t in asyncio.run(_server(list(FEATURES)).list_tools())]
    assert names
    assert all(name.startswith("tv_") for name in names), names


def test_the_default_tools_are_the_approved_list():
    assert sorted(t.name for t in asyncio.run(_server().list_tools())) == APPROVED_DEFAULT


def test_every_answer_has_a_say_line_and_success():
    server = _server(list(FEATURES))
    calls = [
        ("tv_status", {}),
        ("tv_status", {"tv": "the kitchen"}),
        ("tv_search", {"title": "star wars"}),
        ("tv_search", {"title": "Jaws"}),
        ("tv_play", {"title": "A New Hope", "tv": "The Frame"}),
        ("tv_play", {"title": "star wars", "tv": "The Frame"}),
        ("tv_discover", {}),
        ("tv_control", {"command": "stop", "tv": "The Frame"}),
        ("tv_control", {"command": "stop", "tv": "the kitchen"}),
        ("tv_close_app", {"app": "Jellyfin", "tv": "The Frame"}),
        ("tv_close_app", {"app": "Minesweeper", "tv": "The Frame"}),
        ("tv_power_request", {"state": "off", "tv": "The Frame"}),
        ("tv_power_request", {"state": "on", "tv": "The Frame"}),
        ("tv_power_confirm", {"token": "made-up"}),
    ]
    for tool, arguments in calls:
        answer = _call(server, tool, arguments)
        assert isinstance(answer.get("say"), str), (tool, arguments, answer)
        assert answer["say"], (tool, arguments)
        assert isinstance(answer.get("success"), bool), (tool, arguments, answer)


def test_success_is_false_when_nothing_was_done():
    server = _server()
    assert _call(server, "tv_play", {"title": "star wars", "tv": "The Frame"})["success"] is False
    assert _call(server, "tv_status", {"tv": "the kitchen"})["success"] is False
    assert _call(server, "tv_play", {"title": "A New Hope", "tv": "The Frame"})["success"] is True


def test_the_status_line_names_each_tv_and_its_state():
    say = _call(_server(), "tv_status")["say"]
    assert say == "The living room is on."


def test_the_instructions_say_never_to_switch_a_tv_on_or_off_without_asking():
    assert "never switch a tv on or off without asking" in _server().instructions.lower()


def test_the_power_tools_ask_then_switch_with_the_token():
    server = _server(list(FEATURES))
    question = _call(server, "tv_power_request", {"state": "off", "tv": "The Frame"})
    assert question["success"] is True
    assert question["say"].endswith("?")
    done = _call(server, "tv_power_confirm", {"token": question["token"]})
    assert done["success"] is True, done

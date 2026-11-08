# SPDX-License-Identifier: GPL-3.0-or-later
"""What the default settings cost the voice model: a fixed number of tools and characters.

Every tool, its description and its arguments are read by the model on every
turn, so they cannot be allowed to grow by accident. A change that adds to the
default set raises these numbers on purpose, in the same pull request, and says
why.
"""

import asyncio
import json

from tv_mcp.server import build_server
from tv_mcp.simulator import simulated_service

#: The default set's limits. Raise one only on purpose.
MAX_TOOLS = 4
MAX_CHARACTERS = 1150


def _cost(server):
    tools = asyncio.run(server.list_tools())
    text = server.instructions or ""
    for tool in tools:
        text += tool.name + (tool.description or "") + json.dumps(tool.input_schema, separators=(",", ":"))
    return len(tools), len(text)


def test_the_default_set_stays_within_its_tool_and_character_budget():
    count, characters = _cost(build_server(simulated_service()))
    assert count <= MAX_TOOLS, f"{count} tools by default; the budget is {MAX_TOOLS}"
    assert characters <= MAX_CHARACTERS, f"{characters} characters by default; the budget is {MAX_CHARACTERS}"


def test_a_feature_left_off_costs_nothing():
    _, default = _cost(build_server(simulated_service()))
    _, with_setup = _cost(build_server(simulated_service(), features=["status", "media", "setup"]))
    _, nothing = _cost(build_server(simulated_service(), features=[]))
    assert with_setup > default > nothing

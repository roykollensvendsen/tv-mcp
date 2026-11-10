# SPDX-License-Identifier: GPL-3.0-or-later
"""No two tool names the voice could mix up (the plugin standard's rule 1).

Names that sound alike are listed here on purpose, each with what tells them
apart; any other pair of names must differ by more than a few letters.
"""

import asyncio
import difflib

from tv_mcp.server import build_server
from tv_mcp.simulator import simulated_service
from tv_mcp.tools import FEATURES

#: Pairs that sound alike, kept apart by their first words.
CONFUSABLE = {
    frozenset({"tv_open_app", "tv_close_app"}),
    frozenset({"tv_power_request", "tv_power_confirm"}),
}
#: How alike two names may be, as difflib reckons it, before the pair must be listed.
ALIKE = 0.75


def _tools():
    service = simulated_service()
    service.videos = object()
    return asyncio.run(build_server(service, features=list(FEATURES)).list_tools())


def test_no_two_tool_names_can_be_confused():
    tools = _tools()
    for i, one in enumerate(tools):
        for other in tools[i + 1 :]:
            alike = difflib.SequenceMatcher(None, one.name, other.name).ratio()
            if alike >= ALIKE:
                assert frozenset({one.name, other.name}) in CONFUSABLE, (one.name, other.name, alike)


def test_the_names_that_sound_alike_open_with_different_words():
    openings = {t.name: (t.description or "").split()[0] for t in _tools()}
    for pair in CONFUSABLE:
        one, other = sorted(pair)
        assert openings[one] != openings[other], pair

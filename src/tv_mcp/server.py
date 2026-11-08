# SPDX-License-Identifier: GPL-3.0-or-later
"""The MCP server: the switched-on features' tools, over stdio for a voice session.

Run with ``tv-mcp serve``; ``tv-mcp serve --simulate`` answers the same tools
from a simulated Frame (tv_mcp.simulator). Which tools there are is the
owner's choice of features (tv_mcp.tools).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcp.server.mcpserver import MCPServer

from tv_mcp.tools import DEFAULT_FEATURES, FEATURES

if TYPE_CHECKING:
    from collections.abc import Iterable

    from tv_mcp.service import TvService

INSTRUCTIONS = (
    "The owner's TVs. Name a TV as the owner said it (a room, or a name). Read each 'say' aloud. "
    "Never try to reach a TV reported 'left alone'."
)
SIMULATED = "SIMULATED TVs, not real ones: say so. "


class UnknownFeatureError(ValueError):
    """The settings switch on a feature that does not exist."""


def build_server(
    service: TvService, *, features: Iterable[str] = DEFAULT_FEATURES, simulated: bool = False
) -> MCPServer[Any]:
    """The MCP server with the tools of the features given, and no others."""
    server: MCPServer[Any] = MCPServer(
        name="tv-simulated" if simulated else "tv",
        instructions=(SIMULATED + INSTRUCTIONS) if simulated else INSTRUCTIONS,
    )
    wanted = list(dict.fromkeys(features))
    unknown = [f for f in wanted if f not in FEATURES]
    if unknown:
        msg = f"No feature {unknown[0]!r}; the features are {', '.join(FEATURES)}."
        raise UnknownFeatureError(msg)
    # RULE: only a switched-on feature adds tools
    for feature in wanted:
        FEATURES[feature](server, service, simulated)
    return server

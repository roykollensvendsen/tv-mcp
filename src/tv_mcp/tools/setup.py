# SPDX-License-Identifier: GPL-3.0-or-later
"""Finding and setting up TVs; switched on in the settings when needed."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tv_mcp.tools.hints import LOOKS
from tv_mcp.tools.say import tv_lines

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from tv_mcp.service import TvService


def register(server: MCPServer[Any], service: TvService, simulated: bool) -> None:  # noqa: FBT001
    """Add ``tv_discover``."""

    @server.tool(
        annotations=LOOKS,
        description=(
            "Find TVs on the network.\nTheir model, year, platform, and whether set up here. "
            "full=true asks every TV to answer; only when the owner asks for a full search."
        ),
    )
    async def tv_discover(full: bool = False) -> dict[str, Any]:  # noqa: FBT001, FBT002 - a tool argument
        found = await service.discover(full=full)
        return {"success": True, "say": tv_lines(found["tvs"]), "simulated": simulated, **found}

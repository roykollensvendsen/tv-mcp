# SPDX-License-Identifier: GPL-3.0-or-later
"""Finding a film or episode and starting it on a TV: the everyday media tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from tv_mcp.service import TvService


def register(server: MCPServer[Any], service: TvService, simulated: bool) -> None:  # noqa: FBT001
    """Add ``media_search`` and ``media_play``."""

    @server.tool(description="Find films and episodes by title.")
    async def media_search(title: str) -> dict[str, Any]:
        return {"simulated": simulated, **await service.search(title)}

    @server.tool(description="Play a film or episode on a TV, both named as the owner said them.")
    async def media_play(title: str, tv: str) -> dict[str, Any]:
        return {"simulated": simulated, **await service.play(title, tv)}

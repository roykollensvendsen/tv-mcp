# SPDX-License-Identifier: GPL-3.0-or-later
"""Finding a film or episode and starting it on a TV: the everyday media tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from tv_mcp.tools.say import items_line

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from tv_mcp.service import TvService


def register(server: MCPServer[Any], service: TvService, simulated: bool) -> None:  # noqa: FBT001
    """Add ``tv_search`` and ``tv_play``."""

    @server.tool(description="Find films and episodes by title.")
    async def tv_search(title: str) -> dict[str, Any]:
        found = await service.search(title)
        say = found.get("say") or items_line(title, found["items"])
        return {"success": "say" not in found, "say": say, "simulated": simulated, **found}

    @server.tool(description="Play a film or episode on a TV, both as the owner said them.")
    async def tv_play(title: str, tv: str) -> dict[str, Any]:
        answer = await service.play(title, tv)
        return {"success": answer["outcome"] == "playing", "simulated": simulated, **answer}

    @server.tool(description="Pause, resume or stop what is playing on a TV.")
    async def tv_control(command: Literal["pause", "resume", "stop"], tv: str) -> dict[str, Any]:
        answer = await service.control(command, tv)
        return {"success": answer["outcome"] == "done", "simulated": simulated, **answer}

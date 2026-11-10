# SPDX-License-Identifier: GPL-3.0-or-later
"""What is happening in the film now: off unless the owner switches the feature on."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tv_mcp.tools.hints import LOOKS

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from tv_mcp.service import TvService


def register(server: MCPServer[Any], service: TvService, simulated: bool) -> None:  # noqa: FBT001
    """Add ``tv_scene``."""

    @server.tool(
        annotations=LOOKS,
        description="What happens in the film.\n"
        "The subtitle lines within some minutes of where a TV's film is, and its cast,"
        " to say what is happening or who speaks. Sum them up; never read them out. With chapters,"
        " also the film's chapters or an outline, to find a scene and seek to its time.",
    )
    async def tv_scene(tv: str, minutes: float = 2.0, chapters: bool = False) -> dict[str, Any]:  # noqa: FBT001, FBT002
        answer = await service.scene(tv, minutes=minutes, chapters=chapters)
        return {"success": answer["outcome"] == "done", "simulated": simulated, **answer}

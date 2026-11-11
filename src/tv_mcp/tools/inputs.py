# SPDX-License-Identifier: GPL-3.0-or-later
"""Changing which input a TV shows: off unless the owner switches the feature on."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tv_mcp.tools.hints import CHANGES

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from tv_mcp.service import TvService


def register(server: MCPServer[Any], service: TvService, simulated: bool) -> None:  # noqa: FBT001
    """Add ``tv_input``."""

    @server.tool(
        annotations=CHANGES,
        description=(
            "Change what a TV shows.\nSource: HDMI 1 to HDMI 4, TV for the aerial,"
            " or the name of a device on that TV."
        ),
    )
    async def tv_input(source: str, tv: str) -> dict[str, Any]:
        answer = await service.show_input(source, tv)
        return {"success": answer["outcome"] == "done", "simulated": simulated, **answer}

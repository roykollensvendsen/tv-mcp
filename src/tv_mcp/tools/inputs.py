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
            "Show a device or port.\nSource: a device name for this TV (e.g. Chromecast) or HDMI 1-4 or TV."
        ),
    )
    async def tv_input(source: str, tv: str) -> dict[str, Any]:
        answer = await service.show_input(source, tv)
        return {"success": answer["outcome"] == "done", "simulated": simulated, **answer}

# SPDX-License-Identifier: GPL-3.0-or-later
"""Closing an app on a TV: off unless the owner switches the feature on."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from tv_mcp.service import TvService


def register(server: MCPServer[Any], service: TvService, simulated: bool) -> None:  # noqa: FBT001
    """Add ``tv_close_app``."""

    @server.tool(description="Close an app, such as Jellyfin, on a TV.")
    async def tv_close_app(app: str, tv: str) -> dict[str, Any]:
        answer = await service.close_app(app, tv)
        return {"success": answer["outcome"] == "done", "simulated": simulated, **answer}

# SPDX-License-Identifier: GPL-3.0-or-later
"""The everyday status tool."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from tv_mcp.service import TvService


def register(server: MCPServer[Any], service: TvService, simulated: bool) -> None:  # noqa: FBT001
    """Add ``tv_status``."""

    @server.tool(description="Is a TV on, in standby or off? 'tv': the name the owner used; omit for all.")
    async def tv_status(tv: str | None = None) -> dict[str, Any]:
        return {"simulated": simulated, "tvs": await service.status(tv)}

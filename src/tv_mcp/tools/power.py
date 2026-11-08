# SPDX-License-Identifier: GPL-3.0-or-later
"""Switching a TV on or off after the owner's yes: off unless the owner switches the feature on."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from tv_mcp.power import PowerService

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from tv_mcp.service import TvService


def register(server: MCPServer[Any], service: TvService, simulated: bool) -> None:  # noqa: FBT001
    """Add ``tv_power_request`` and ``tv_power_confirm``."""
    power = PowerService(service)

    @server.tool(
        description="Ask before switching a TV on or off: read 'say' aloud; nothing is switched yet."
    )
    async def tv_power_request(state: Literal["on", "off"], tv: str) -> dict[str, Any]:
        answer = await power.request(state, tv)
        return {"success": answer["outcome"] == "question", "simulated": simulated, **answer}

    @server.tool(
        description="Switch, with the token from tv_power_request, only after the owner's clear yes."
    )
    async def tv_power_confirm(token: str) -> dict[str, Any]:
        answer = await power.confirm(token)
        return {"success": answer["outcome"] == "done", "simulated": simulated, **answer}

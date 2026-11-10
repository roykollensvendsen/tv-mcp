# SPDX-License-Identifier: GPL-3.0-or-later
"""The everyday status tool."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from tv_mcp.tools.hints import LOOKS
from tv_mcp.tools.say import tv_lines

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from tv_mcp.service import TvService


#: What status can wait for a TV to be.
Wanted = Literal["on", "off"]


def register(server: MCPServer[Any], service: TvService, simulated: bool) -> None:  # noqa: FBT001
    """Add ``tv_status``."""

    @server.tool(
        annotations=LOOKS,
        description="Is a TV on?\n'tv' as the owner said it; omit for all."
        " wait_for 'on' or 'off' watches the named TV for about ten seconds.",
    )
    async def tv_status(
        tv: str | None = None, wait_for: Literal["on", "off"] | None = None
    ) -> dict[str, Any]:
        if wait_for is None:
            reports = await service.status(tv)
            success = all(r["state"] != "refused" for r in reports)
            return {"success": success, "say": tv_lines(reports), "simulated": simulated, "tvs": reports}
        waited = await service.wait_for(tv, wait_for)
        reports, reached = waited["tvs"], waited["reached"]
        say = tv_lines(reports) if reports else f"I could not read {tv} in time."
        if not reached and all(r["state"] != "refused" for r in reports):
            say += f" It is not {wait_for} yet. Ask me to wait again."
        return {"success": reached, "say": say, "simulated": simulated, "tvs": reports}

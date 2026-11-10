# SPDX-License-Identifier: GPL-3.0-or-later
"""The everyday status tool."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from tv_mcp.tools.hints import LOOKS
from tv_mcp.tools.say import tv_lines, waited_lines

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
            return _answer(await service.status(tv), simulated=simulated)
        waited = await service.wait_for(tv, wait_for)
        say = waited_lines(waited["tvs"], tv, wait_for, reached=waited["reached"])
        return {"success": waited["reached"], "say": say, "simulated": simulated, "tvs": waited["tvs"]}


def _answer(reports: list[dict[str, Any]], *, simulated: bool) -> dict[str, Any]:
    """Status of each TV, spoken; a failure when a name was not understood."""
    success = all(r["state"] != "refused" for r in reports)
    return {"success": success, "say": tv_lines(reports), "simulated": simulated, "tvs": reports}

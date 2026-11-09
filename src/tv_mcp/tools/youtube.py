# SPDX-License-Identifier: GPL-3.0-or-later
"""YouTube: off unless the owner switches it on.

It adds no tool of its own. With it on, the command line gives the service a
YouTube search and player, and ``tv_search`` and ``tv_play`` take a source
(tv_mcp.tools.media), so the voice still sees the same tools. It needs the
``media`` feature too.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from tv_mcp.service import TvService


def register(server: MCPServer[Any], service: TvService, simulated: bool) -> None:  # noqa: FBT001
    """Nothing to add: the media tools take a source when YouTube is set up."""

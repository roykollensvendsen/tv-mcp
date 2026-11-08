# SPDX-License-Identifier: GPL-3.0-or-later
"""The MCP tools, grouped into features the owner switches on in the settings.

Only the features switched on add tools, so a feature nobody uses costs the
voice model no tools and no description text. ``tests/test_context_budget.py``
holds the default set to a fixed number of tools and characters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tv_mcp.tools import apps, media, power, setup, status

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcp.server.mcpserver import MCPServer

    from tv_mcp.service import TvService

    Register = Callable[[MCPServer[Any], TvService, bool], None]

#: Every feature, by the name the settings file uses.
FEATURES: dict[str, Register] = {
    "status": status.register,
    "media": media.register,
    "apps": apps.register,
    "power": power.register,
    "setup": setup.register,
}
#: What a settings file with no [features] table gets: the everyday tools only.
DEFAULT_FEATURES: tuple[str, ...] = ("status", "media")

# SPDX-License-Identifier: GPL-3.0-or-later
"""The MCP server: the switched-on features' tools, over stdio for a voice session.

Run with ``tv-mcp serve``; ``tv-mcp serve --simulate`` answers the same tools
from a simulated Frame (tv_mcp.simulator). Which tools there are is the
owner's choice of features (tv_mcp.tools).
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any

import httpx
from mcp.server.mcpserver import MCPServer

from tv_mcp.tools import DEFAULT_FEATURES, FEATURES

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable

    from tv_mcp.service import TvService

INSTRUCTIONS = (
    "Controls the owner's TVs and starts films from their Jellyfin library. Name a TV as the owner "
    "said it (a room, or a name), and read each 'say' aloud. Never switch a TV on or off without "
    "asking, and never try to reach a TV reported 'left alone'."
)
SIMULATED = "SIMULATED TVs, not real ones: say so. "
#: What the voice hears when a TV or the library stops answering partway.
DROPPED = "The connection to the TV or the library dropped. Try again."
#: What the voice hears when tv-mcp itself fails, so it never hears only that the tool failed.
BROKE = "That went wrong inside tv-mcp. Try again, and if it fails again, check its log."


class _Guarded:
    """Registers each tool so a failure inside it is still an answer the voice can read."""

    def __init__(self, server: MCPServer[Any], simulated: bool) -> None:  # noqa: FBT001
        self._server, self._simulated = server, simulated
        self.names: list[str] = []

    def tool(self, **options: Any) -> Callable[[Callable[..., Awaitable[Any]]], Any]:  # noqa: ANN401
        register = self._server.tool(**options)

        def guard(tool: Callable[..., Awaitable[Any]]) -> Any:  # noqa: ANN401
            @functools.wraps(tool)
            async def answered(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
                try:
                    return await tool(*args, **kwargs)
                except (httpx.HTTPError, OSError, TimeoutError):
                    say = DROPPED
                except Exception:  # noqa: BLE001 - whatever broke, the voice gets a sentence
                    say = BROKE
                return {"success": False, "outcome": "refused", "say": say, "simulated": self._simulated}

            self.names.append(tool.__name__)
            return register(answered)

        return guard


class UnknownFeatureError(ValueError):
    """The settings switch on a feature that does not exist."""


def build_server(
    service: TvService, *, features: Iterable[str] = DEFAULT_FEATURES, simulated: bool = False
) -> MCPServer[Any]:
    """The MCP server with the tools of the features given, and no others."""
    server: MCPServer[Any] = MCPServer(
        name="tv-simulated" if simulated else "tv",
        instructions=(SIMULATED + INSTRUCTIONS) if simulated else INSTRUCTIONS,
    )
    wanted = list(dict.fromkeys(features))
    unknown = [f for f in wanted if f not in FEATURES]
    if unknown:
        msg = f"No feature {unknown[0]!r}; the features are {', '.join(FEATURES)}."
        raise UnknownFeatureError(msg)
    # RULE: only a switched-on feature adds tools
    guarded = _Guarded(server, simulated)
    for feature in wanted:
        # RULE: every tool answers with a sentence, even when it fails
        FEATURES[feature](guarded, service, simulated)  # type: ignore[arg-type]
    server.guarded = guarded.names  # type: ignore[attr-defined]
    return server

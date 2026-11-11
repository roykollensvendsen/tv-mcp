# SPDX-License-Identifier: GPL-3.0-or-later
"""The MCP server: the switched-on features' tools, over stdio for a voice session.

Run with ``tv-mcp serve``; ``tv-mcp serve --simulate`` answers the same tools
from a simulated Frame (tv_mcp.simulator). Which tools there are is the
owner's choice of features (tv_mcp.tools).
"""

from __future__ import annotations

import asyncio
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
#: The Claude app gives up on a call after about 15 seconds; every tool answers before then.
ANSWER_WITHIN = 12.0
#: What the voice hears when a tool is still working by then; the work carries on.
WORKING = "That is taking a while, and it carries on. Ask again in a moment to hear how it went."
#: What the voice hears when a TV or the library stops answering partway.
DROPPED = "The connection to the TV or the library dropped. Try again."
#: What the voice hears when tv-mcp itself fails, so it never hears only that the tool failed.
BROKE = "That went wrong inside tv-mcp. Try again, and if it fails again, check its log."


class _Guarded:
    """Registers each tool so a failure inside it is still an answer the voice can read."""

    def __init__(self, server: MCPServer[Any], simulated: bool) -> None:  # noqa: FBT001
        self._server, self._simulated = server, simulated
        self.names: list[str] = []
        #: Work still running after its answer was given, kept until it ends.
        self.running: set[asyncio.Future[Any]] = set()

    def tool(self, **options: Any) -> Callable[[Callable[..., Awaitable[Any]]], Any]:  # noqa: ANN401
        register = self._server.tool(**options)

        def guard(tool: Callable[..., Awaitable[Any]]) -> Any:  # noqa: ANN401
            @functools.wraps(tool)
            async def answered(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
                work = asyncio.ensure_future(tool(*args, **kwargs))
                try:
                    # RULE: a tool still working at the deadline says it carries on
                    answer = await asyncio.wait_for(asyncio.shield(work), ANSWER_WITHIN)
                except TimeoutError:
                    if not work.done():
                        self.running.add(work)
                        work.add_done_callback(_ended)
                        work.add_done_callback(self.running.discard)
                        answer = {"success": False, "outcome": "working", "say": WORKING}
                    else:
                        answer = {"success": False, "outcome": "refused", "say": DROPPED}
                except (httpx.HTTPError, OSError):
                    answer = {"success": False, "outcome": "refused", "say": DROPPED}
                except Exception:  # noqa: BLE001 - whatever broke, the voice gets a sentence
                    answer = {"success": False, "outcome": "refused", "say": BROKE}
                answer.setdefault("simulated", self._simulated)
                if self._simulated and isinstance(answer.get("say"), str):
                    answer["say"] = "Simulated: " + answer["say"]
                return answer

            self.names.append(tool.__name__)
            return register(answered)

        return guard


def _ended(work: asyncio.Future[Any]) -> None:
    """Collect what work left running ended with, so a failure there is not left unread."""
    if not work.cancelled():
        work.exception()


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
        named = ", ".join(FEATURES)
        msg = f"No feature {unknown[0]!r}; the features are {named}. Pick from those in the settings."
        raise UnknownFeatureError(msg)
    # RULE: only a switched-on feature adds tools
    guarded = _Guarded(server, simulated)
    for feature in wanted:
        # RULE: every tool answers with a sentence, even when it fails
        FEATURES[feature](guarded, service, simulated)  # type: ignore[arg-type]
    server.guarded = guarded.names  # type: ignore[attr-defined]
    return server

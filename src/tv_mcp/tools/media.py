# SPDX-License-Identifier: GPL-3.0-or-later
"""Finding a film or episode and starting it on a TV: the everyday media tools."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from tv_mcp.tools.say import items_line

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from tv_mcp.service import TvService


def register(server: MCPServer[Any], service: TvService, simulated: bool) -> None:  # noqa: FBT001
    """Add ``tv_search`` and ``tv_play``."""
    if service.videos is not None:
        _register_with_youtube(server, service, simulated)
    else:
        _register_films(server, service, simulated)

    @server.tool(
        description="Pause, resume, stop, seek, mute, unmute or volume on a TV; seek to seconds,"
        " volume to level 0-100, by them if relative."
    )
    async def tv_control(
        command: Literal["pause", "resume", "stop", "seek", "mute", "unmute", "volume"],
        tv: str,
        seconds: int | None = None,
        relative: bool = False,  # noqa: FBT001, FBT002
        level: int | None = None,
    ) -> dict[str, Any]:
        if command == "seek":
            if seconds is None:
                answer = {"outcome": "refused", "say": "Say where to go, or how far to skip."}
            else:
                answer = await service.seek(tv, seconds, relative=relative)
        elif command in {"mute", "unmute", "volume"}:
            answer = await service.sound(command, tv, level=level, relative=relative)
        else:
            answer = await service.control(command, tv)
        return {"success": answer["outcome"] == "done", "simulated": simulated, **answer}


def _register_films(server: MCPServer[Any], service: TvService, simulated: bool) -> None:  # noqa: FBT001
    """Search and play the owner's films."""

    @server.tool(description="Find films and episodes by title.")
    async def tv_search(title: str) -> dict[str, Any]:
        found = await service.search(title)
        say = found.get("say") or items_line(title, found["items"])
        return {"success": "say" not in found, "say": say, "simulated": simulated, **found}

    @server.tool(description="Play a film or episode on a TV, from where it stopped.")
    async def tv_play(title: str, tv: str, from_start: bool = False) -> dict[str, Any]:  # noqa: FBT001, FBT002
        answer = await service.play(title, tv, from_start=from_start)
        return {"success": answer["outcome"] == "playing", "simulated": simulated, **answer}


def _register_with_youtube(server: MCPServer[Any], service: TvService, simulated: bool) -> None:  # noqa: FBT001
    """Search and play with a source: the owner's films, or YouTube."""

    @server.tool(description="Find films and episodes by title, or YouTube videos with source youtube.")
    async def tv_search(title: str, source: Literal["jellyfin", "youtube"] = "jellyfin") -> dict[str, Any]:
        if source == "youtube":
            found = await service.search_youtube(title)
            return {"success": bool(found["items"]), "simulated": simulated, **found}
        found = await service.search(title)
        say = found.get("say") or items_line(title, found["items"])
        return {"success": "say" not in found, "say": say, "simulated": simulated, **found}

    @server.tool(
        description="Play a film or episode on a TV, from where it stopped; with source youtube,"
        " a video by its id or words."
    )
    async def tv_play(
        title: str,
        tv: str,
        from_start: bool = False,  # noqa: FBT001, FBT002
        source: Literal["jellyfin", "youtube"] = "jellyfin",
    ) -> dict[str, Any]:
        if source == "youtube":
            answer = await service.play_youtube(title, tv)
        else:
            answer = await service.play(title, tv, from_start=from_start)
        return {"success": answer["outcome"] == "playing", "simulated": simulated, **answer}

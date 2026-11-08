"""Command line for tv-mcp: serve the tools to a voice session, or look at the TVs."""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import TYPE_CHECKING, Any

import httpx

from tv_mcp import discovery
from tv_mcp.drivers.jellyfin import Jellyfin
from tv_mcp.drivers.samsung_tizen import SamsungTizen
from tv_mcp.service import TvService
from tv_mcp.settings import load_settings, settings_path
from tv_mcp.simulator import simulated_service

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

#: Every verb this command has. The documentation test requires each one to
#: appear in a worked example, so a verb cannot be added without one.
COMMANDS: tuple[str, ...] = ("serve", "status")


def _with_service(*, simulate: bool, work: Callable[[TvService], Awaitable[Any]]) -> Any:  # noqa: ANN401 - whatever the work returns
    async def run() -> Any:  # noqa: ANN401
        if simulate:
            return await work(simulated_service())
        async with httpx.AsyncClient() as client:  # pragma: no cover - needs a real TV
            settings = load_settings(settings_path())
            drivers = {driver.key: driver for driver in (SamsungTizen(client),)}
            library = (
                Jellyfin(settings.jellyfin_url, settings.jellyfin_key, client)
                if settings.jellyfin_url and settings.jellyfin_key
                else None
            )
            service = TvService(settings, drivers=drivers, listen=discovery.listen, library=library)
            return await work(service)

    return asyncio.run(run())


def _line(report: dict[str, Any]) -> str:
    details = [str(report[k]) for k in ("model", "year") if report.get(k)]
    if report.get("platform"):
        details.append(report["platform"])
    extra = f" ({', '.join(details)})" if details else ""
    return f"{report['tv'] or 'not set up'}: {report['state']}{extra}"


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch. Returns a process exit code."""
    parser = argparse.ArgumentParser(prog="tv-mcp", description=__doc__)
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("--simulate", action="store_true", help="use a simulated Frame, not the real TVs")
    args = parser.parse_args(argv)
    if args.command == "status":
        reports = _with_service(simulate=args.simulate, work=lambda s: s.status(None))
        sys.stdout.write("".join(_line(r) + "\n" for r in reports))
        return 0
    from tv_mcp.server import build_server  # noqa: PLC0415 - only serving needs the MCP server

    async def serve(service: TvService) -> None:  # pragma: no cover - runs until stdin closes
        features = service.settings.features
        server = build_server(
            service, simulated=args.simulate, **({"features": features} if features else {})
        )
        await server.run_stdio_async()

    _with_service(simulate=args.simulate, work=serve)  # pragma: no cover
    return 0  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())

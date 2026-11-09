# SPDX-License-Identifier: GPL-3.0-or-later
"""Switching a TV on or off, only after the owner has said yes.

``request`` changes nothing: it returns a question for the voice to read
aloud, with a one-time token. ``confirm`` switches, and is called with that
token only after the owner's clear yes. The rules live here, not in the
voice's instructions, so no wording of a request can skip the question.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, cast

from tv_mcp.settings import AmbiguousTvError, UnknownTvError, find_tv

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from tv_mcp.driver import Switches
    from tv_mcp.service import TvService
    from tv_mcp.settings import Tv

#: How long a question stays open, in seconds.
EXPIRES = 30.0
#: How many seconds to watch a TV for its new state after switching it.
SETTLE = 25
#: The words a request takes.
STATES = ("on", "off")
_OFF = {"standby", "standby or art mode", "off or not reachable"}


@dataclass(frozen=True)
class _Pending:
    token: str
    tv: Tv
    on: bool
    asked_at: float


def _refused(say: str) -> dict[str, Any]:
    return {"outcome": "refused", "say": say}


class PowerService:
    """Asks first, then switches a TV on or off with the token from the question."""

    def __init__(
        self,
        service: TvService,
        *,
        clock: Callable[[], float] = time.monotonic,
        new_token: Callable[[], str] = lambda: secrets.token_urlsafe(16),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Read and reach the TVs through `service`."""
        self._service, self._clock, self._new_token, self._sleep = service, clock, new_token, sleep
        self._pending: _Pending | None = None

    async def _state(self, tv: Tv) -> str | None:
        """'on', 'off', or None when it is not known."""
        if tv.power_driver:
            driver = self._service.drivers.get(tv.power_driver)
            info = await driver.read_info(tv.power_address or "") if driver else None
            if driver is None:
                return None
            return "on" if info is not None and info.power == "on" else "off"
        [report] = await self._service.status(tv.key)
        if report["state"] == "on":
            return "on"
        return "off" if report["state"] in _OFF else None

    def _switcher(self, tv: Tv) -> Switches | None:
        driver = self._service.drivers.get(tv.power_driver or tv.driver)
        return cast("Switches", driver) if callable(getattr(driver, "switch", None)) else None

    async def request(self, state: str, name: str) -> dict[str, Any]:  # noqa: PLR0911 - one refusal per rule
        """A question to read aloud, and its token; nothing is switched."""
        if state not in STATES:
            return _refused(f"I can switch a TV on or off; not {state!r}.")
        try:
            tv = find_tv(self._service.settings, name)
        except (UnknownTvError, AmbiguousTvError) as refusal:
            return _refused(str(refusal))
        # RULE: a hands-off TV is never switched
        if tv.hands_off:
            return _refused(f"{tv.spoken} is left alone; nothing is sent to it.")
        if self._switcher(tv) is None:
            return _refused(f"I cannot switch {tv.spoken} on or off.")
        now = await self._state(tv)
        # RULE: a switch is refused when the TV state is not known
        if now is None:
            return _refused(f"I cannot tell whether {tv.spoken} is on, so I will not switch it.")
        # RULE: a request the TV already satisfies is refused
        if now == state:
            return _refused(f"{tv.spoken.capitalize()} is already {state}.")
        token = self._new_token()
        self._pending = _Pending(token, tv, state == "on", self._clock())
        return {"outcome": "question", "say": f"Switch {tv.spoken} {state}?", "token": token}

    async def confirm(self, token: str) -> dict[str, Any]:
        """Switch, if `token` is from the latest question and nothing has changed since."""
        pending = self._pending
        # RULE: a power token works once
        if pending is None or not secrets.compare_digest(pending.token, token):
            return _refused("There is no such question open; ask again.")
        self._pending = None
        # RULE: a power token expires after thirty seconds
        if self._clock() - pending.asked_at > EXPIRES:
            return _refused("That question expired; ask again.")
        wanted = "on" if pending.on else "off"
        # RULE: a switch is refused when the TV changed since the question
        if await self._state(pending.tv) == wanted:
            return _refused(f"{pending.tv.spoken.capitalize()} is already {wanted}; nothing was sent.")
        switcher = self._switcher(pending.tv)
        target = (
            replace(pending.tv, address=pending.tv.power_address) if pending.tv.power_driver else pending.tv
        )
        if switcher is None or not await switcher.switch(target, on=pending.on):
            return _refused(f"{pending.tv.spoken.capitalize()} did not answer.")
        for _ in range(SETTLE):
            if await self._state(pending.tv) == wanted:
                return {"outcome": "done", "say": f"{pending.tv.spoken.capitalize()} is {wanted} now."}
            await self._sleep(1.0)
        return {
            "outcome": "unverified",
            "say": f"I sent it, but {pending.tv.spoken} still does not seem {wanted}.",
        }

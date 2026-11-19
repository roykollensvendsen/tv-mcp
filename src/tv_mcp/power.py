# SPDX-License-Identifier: GPL-3.0-or-later
"""Switching a TV on or off, only after the owner has said yes.

``request`` changes nothing: it returns a question for the voice to read
aloud, with a one-time token. ``confirm`` switches, and is called with that
token only after the owner's clear yes. The rules live here, not in the
voice's instructions, so no wording of a request can skip the question.
"""

from __future__ import annotations

import asyncio
import logging
import math
import secrets
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, cast

from tv_mcp.driver import WakesScreen
from tv_mcp.settings import AmbiguousTvError, UnknownTvError, find_tv

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from tv_mcp.driver import Switches
    from tv_mcp.service import TvService
    from tv_mcp.settings import Tv

#: How long a question stays open, in seconds.
EXPIRES = 30.0
#: How long a confirmed switch has, from the yes to its one final answer: the switch
#: itself, then watching the TV until it is seen in its new state. It stays inside
#: server.ANSWER_WITHIN, so the voice hears how it went rather than "working".
CONFIRM_WITHIN = 10.0
#: How long a confirm watches a TV woken through its Chromecast: the garage TV came on 25.6 s
#: after the yes (19.11), so the voice can hear "on" in the same answer. The owner's long calls
#: came back (19.11), and the bridge's limit for tv must be above server.ANSWER_WITHIN.
WAKE_CONFIRM_WITHIN = 40.0
#: After a confirm that could not see the switch in time, how long tv-mcp keeps looking, and how
#: often, only to log when the TV came: that is what says how long a confirm should wait.
WATCH_AFTER = 90.0
WATCH_EVERY = 2.0
#: How long a TV woken through its Chromecast takes to come on, as the voice says it, and
#: when to ask again; measured on the garage TV on 19.11 at 25.6 s from the yes.
COMING_ON = "about half a minute"
AGAIN_IN = "half a minute"
#: The words a request takes.
STATES = ("on", "off")
_OFF = {"standby", "standby or art mode", "showing art", "off or not reachable"}
_log = logging.getLogger(__name__)


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
        #: Switches still on their way when a confirm had to answer.
        self._running: set[asyncio.Future[bool]] = set()
        #: Looks at a TV after its confirm answered, kept until they end.
        self.watching: set[asyncio.Future[None]] = set()

    def _waker(self, tv: Tv) -> WakesScreen | None:
        """The device in `tv` that switches it on over HDMI, when it is set up to."""
        driver = self._service.drivers.get(tv.driver) if tv.power_on == "cec" else None
        return driver if isinstance(driver, WakesScreen) else None

    async def _state(self, tv: Tv) -> str | None:
        """'on', 'off', or None when it is not known."""
        waker = self._waker(tv)
        # The device in the TV knows it is on well before the TV answers on the network.
        if waker is not None and tv.address and await waker.screen_on(tv.address):
            return "on"
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

    async def _switch(self, tv: Tv, *, on: bool) -> bool:
        """On through the device in the TV when it is set to wake by HDMI; otherwise by its switcher."""
        waker = self._waker(tv)
        if on and waker is not None and tv.address:
            woken = await waker.wake_screen(tv.address)
            if woken:
                self._service.woken_by_hdmi(tv)
            return woken
        switcher = self._switcher(tv)
        target = replace(tv, address=tv.power_address) if tv.power_driver else tv
        return switcher is not None and await switcher.switch(target, on=on)

    async def request(self, state: str, name: str) -> dict[str, Any]:  # noqa: PLR0911 - one refusal per rule
        """A question to read aloud, and its token; nothing is switched."""
        if state not in STATES:
            return _refused(f"I cannot switch a TV {state!r}. Say on or off.")
        try:
            tv = find_tv(self._service.settings, name)
        except (UnknownTvError, AmbiguousTvError) as refusal:
            return _refused(str(refusal))
        # RULE: a hands-off TV is never switched
        if tv.hands_off:
            return _refused(
                f"{tv.spoken} is left alone; nothing is sent to it."
                " Remove hands_off in the settings to use it."
            )
        if self._switcher(tv) is None:
            return _refused(f"I cannot switch {tv.spoken} on or off. Use its own remote.")
        now = await self._state(tv)
        # RULE: a switch is refused when the TV state is not known
        if now is None:
            return _refused(
                f"I cannot tell whether {tv.spoken} is on, so I will not switch it."
                " Check that it is plugged in, and ask again."
            )
        # RULE: a request the TV already satisfies is refused
        if now == state:
            return _refused(
                f"{tv.spoken.capitalize()} is already {state}. Ask for the other way if you meant that."
            )
        token = self._new_token()
        self._pending = _Pending(token, tv, state == "on", self._clock())
        # The state first, then the question: "Switch it off?" read aloud sounds like a command.
        say = f"{tv.spoken.capitalize()} is {now}. Do you want me to switch it {state}?"
        if state == "on" and self._waker(tv) is not None:
            # RULE: a question to switch on through the Chromecast says how long it takes
            say += f" That takes {COMING_ON}."
        return {"outcome": "question", "say": say, "token": token}

    async def confirm(self, token: str) -> dict[str, Any]:
        """Switch, if `token` is from the latest question and nothing has changed since."""
        started = self._clock()
        pending = self._pending
        # RULE: a power token works once
        if pending is None or not secrets.compare_digest(pending.token, token):
            return _refused("There is no such question open. Ask again.")
        self._pending = None
        # RULE: a power token expires after thirty seconds
        if self._clock() - pending.asked_at > EXPIRES:
            return _refused("That question expired. Ask again.")
        wanted = "on" if pending.on else "off"
        # RULE: a switch is refused when the TV changed since the question
        if await self._state(pending.tv) == wanted:
            return _refused(
                f"{pending.tv.spoken.capitalize()} is already {wanted}; nothing was sent."
                " Ask for the other way if you meant that."
            )
        # Starting an app on the Chromecast asks the TV over HDMI to show the Chromecast.
        through_cast = pending.on and self._waker(pending.tv) is not None
        # RULE: a TV woken through its Chromecast is watched until it has had time to come on
        until = started + (WAKE_CONFIRM_WITHIN if through_cast else CONFIRM_WITHIN)
        switching = asyncio.ensure_future(self._switch(pending.tv, on=pending.on))
        self._running.add(switching)
        switching.add_done_callback(self._running.discard)
        try:
            # Shielded: a switch still on its way when time runs out carries on.
            sent = await asyncio.wait_for(asyncio.shield(switching), max(until - self._clock(), 0.1))
        except TimeoutError:
            sent = True
        # How long a TV takes to come on decides how long a confirm should watch (19.11).
        _log.info("%s: switch %s sent, %.1f s after the yes", pending.tv.key, wanted, self._clock() - started)
        if not sent:
            # Nothing reached the TV, so the yes still stands while the question is fresh.
            if self._pending is None:
                self._pending = pending
            return _refused(
                f"{pending.tv.spoken.capitalize()} did not answer. Check that it is on, and try again."
            )
        seen = await self._seen(pending.tv, wanted, since=started, until=until)
        took = round(self._clock() - started, 1)
        if seen:
            # RULE: a switch seen in time gives the seconds it took
            return {
                "outcome": "done",
                "say": _now(pending.tv, wanted, through_cast=through_cast),
                "seconds": took,
            }
        watch = asyncio.ensure_future(self._watch_after(pending.tv, wanted, since=started))
        self.watching.add(watch)
        watch.add_done_callback(self.watching.discard)
        return _not_yet(pending.tv, wanted, so_far=took, through_cast=through_cast)

    async def _seen(self, tv: Tv, wanted: str, *, since: float, until: float) -> bool:
        """Whether `tv` is seen `wanted`, looking once a second until the clock reaches `until`."""
        # RULE: a confirmed switch answers once, within the voice time
        # At most one look a second, also when the clock is not real time.
        for look in range(1, math.ceil(until - self._clock()) + 1):
            if (left := until - self._clock()) <= 0:
                return False
            asked = self._clock() - since
            try:
                state = await asyncio.wait_for(self._state(tv), left)
            except TimeoutError:
                _log.info("%s: look %d, %.1f s after the yes: no answer in time", tv.key, look, asked)
                return False
            # RULE: a confirmed switch logs each look at the TV with its time
            _log.info(
                "%s: look %d, %.1f s after the yes, answered in %.1f s: %s",
                tv.key,
                look,
                asked,
                self._clock() - since - asked,
                state or "not known",
            )
            if state == wanted:
                return True
            if until - self._clock() <= 1:
                return False
            await self._sleep(1.0)
        return False

    async def _watch_after(self, tv: Tv, wanted: str, *, since: float) -> None:
        """Log when `tv` is first seen `wanted` after its confirm answered; it only reads, says nothing."""
        # A look every WATCH_EVERY seconds, counted, so it ends also when the clock is not real time.
        for _ in range(int(WATCH_AFTER / WATCH_EVERY)):
            await self._sleep(WATCH_EVERY)
            if self._clock() - since > WATCH_AFTER:
                break
            try:
                state = await asyncio.wait_for(self._state(tv), WATCH_EVERY * 2)
            except TimeoutError:
                continue
            if state == wanted:
                # RULE: a TV not seen in time is still watched, only to log when it comes
                _log.info(
                    "%s: seen %s %.1f s after the yes, after the answer",
                    tv.key,
                    wanted,
                    self._clock() - since,
                )
                return
        _log.info("%s: not seen %s within %.0f s of the yes", tv.key, wanted, WATCH_AFTER)


def _not_yet(tv: Tv, wanted: str, *, so_far: float, through_cast: bool) -> dict[str, Any]:
    """The answer when `tv` was not seen `wanted` in time; woken through its Chromecast, it is starting."""
    if through_cast:
        # Woken over HDMI, the garage TV came on 25.6 s after the yes (19.11): longer than
        # one voice call, so the voice says when asking again will find it on.
        # RULE: a TV woken through its Chromecast is said to take half a minute
        say = (
            f"I asked {tv.spoken} to switch on through its Chromecast; it takes {COMING_ON}"
            " to come on, and the Chromecast may take the screen."
            f" Ask me again in {AGAIN_IN} whether it is on."
        )
        # RULE: a TV still starting when the confirm answers is said as starting, with its seconds
        return {"outcome": "starting", "say": say, "seconds": so_far}
    say = f"I sent it, but {tv.spoken} is not {wanted} yet. Ask me to wait for it to be {wanted}."
    return {"outcome": "unverified", "say": say}


def _now(tv: Tv, wanted: str, *, through_cast: bool) -> str:
    """What to say once `tv` is seen `wanted`; woken through its Chromecast, that may hold the screen."""
    if through_cast:
        return (
            f"{tv.spoken.capitalize()} is on now; its Chromecast may have taken the screen."
            " Ask me for another input if you want one."
        )
    return f"{tv.spoken.capitalize()} is {wanted} now."

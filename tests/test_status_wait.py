# SPDX-License-Identifier: GPL-3.0-or-later
"""Status that waits for a TV to come on or go off, and status that stays quick.

After a switch the voice can ask to wait for the TV, and hear the moment it is
seen on, instead of asking again and again. The wait stays inside the time the
voice gives a tool; when it runs out, the voice is told to ask again.
"""

import asyncio

import pytest

from tv_mcp import service as service_module
from tv_mcp.driver import TvInfo
from tv_mcp.server import ANSWER_WITHIN
from tv_mcp.service import WAIT_WITHIN, TvService
from tv_mcp.settings import Settings, Tv

LIVING = Tv(key="living-room", names=("the living room",), address="192.0.2.10")


class Screen:
    key = "samsung-tizen"
    ssdp_target = "x"

    def __init__(self, power):
        self.power = power

    def recognises(self, announcement):
        return False

    async def read_info(self, address):
        return TvInfo(name=None, model=None, year=None, platform=None, power=self.power)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _service(driver, clock, on_tick=None):
    async def tick(seconds):
        clock.now += seconds
        if on_tick:
            on_tick(clock.now)

    async def no_listen(recognises, target):
        return []

    return TvService(
        Settings(tvs=(LIVING,)), drivers={driver.key: driver}, listen=no_listen, sleep=tick, clock=clock
    )


def test_status_can_wait_for_a_tv_to_come_on():
    clock = Clock()
    driver = Screen("standby")
    started = clock.now

    def comes_on(now):
        if now - started >= 4:
            driver.power = "on"

    waited = asyncio.run(_service(driver, clock, comes_on).wait_for("the living room", "on"))
    assert waited["reached"] is True
    assert waited["tvs"][0]["state"] == "on"
    assert clock.now - started <= 5


def test_a_wait_for_a_tv_ends_within_the_voice_time():
    clock = Clock()
    started = clock.now
    waited = asyncio.run(_service(Screen("standby"), clock).wait_for("the living room", "on"))
    assert waited["reached"] is False
    assert clock.now - started <= WAIT_WITHIN
    assert WAIT_WITHIN < ANSWER_WITHIN


def test_a_tv_already_in_the_wanted_state_is_answered_at_once():
    clock = Clock()
    waited = asyncio.run(_service(Screen("standby"), clock).wait_for("the living room", "off"))
    assert waited["reached"] is True
    assert clock.now == 1000.0


def test_status_says_what_it_knows_rather_than_wait_on_a_slow_input_reading(monkeypatch):
    # 2026-11-10: right after the garage TV woke, status took over ten seconds,
    # most of it finding out which input the TV showed.
    monkeypatch.setattr(service_module, "INPUT_READ_WAIT", 0.05)

    class SlowInput(Screen):
        async def input_shown(self, tv):
            await asyncio.sleep(60)

    [report] = asyncio.run(_service(SlowInput("on"), Clock()).status("the living room"))
    assert report["state"] == "on"
    assert "input" not in report


@pytest.mark.parametrize("wanted", ["on", "off"])
def test_a_wait_names_its_tv(wanted):
    waited = asyncio.run(_service(Screen("on"), Clock()).wait_for(None, wanted))
    assert waited["reached"] is False
    assert waited["tvs"][0]["state"] == "refused"


def test_the_status_tool_says_to_ask_again_when_the_tv_is_not_there_yet():
    from tv_mcp.server import build_server  # noqa: PLC0415

    service = _service(Screen("standby"), Clock())
    result = asyncio.run(
        build_server(service).call_tool("tv_status", {"tv": "the living room", "wait_for": "on"})
    )
    answer = result.structured_content or {}
    assert answer["success"] is False
    assert "not on yet" in answer["say"]
    assert answer["say"].rstrip(".").endswith("wait again")

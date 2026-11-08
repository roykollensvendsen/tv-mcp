# SPDX-License-Identifier: GPL-3.0-or-later
"""Switching a TV on or off: a question first, and the switch only after a yes."""

import asyncio

from tv_mcp.driver import TvInfo
from tv_mcp.power import PowerService
from tv_mcp.service import TvService
from tv_mcp.settings import Settings, Tv

LIVING = Tv(
    key="living-room", names=("the living room", "The Frame"), address="192.0.2.10", mac="00:00:5E:00:53:01"
)
UPSTAIRS = Tv(key="upstairs", names=("upstairs",), address="192.0.2.11", hands_off=True)


class PowerDriver:
    key = "samsung-tizen"
    ssdp_target = "x"

    def __init__(self, power="on"):
        self.power, self.switched = power, []

    def recognises(self, announcement):
        return False

    async def read_info(self, address):
        if self.power == "off":
            return None
        return TvInfo(
            name="The Frame", model="QE55LS03BAUXXC", year=2022, platform="Tizen 6.5", power=self.power
        )

    async def switch(self, tv, *, on):
        self.switched.append((tv.key, on))
        return True


async def _no_listen(recognises, target):
    return []


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _power(driver, *tvs, clock=None):
    service = TvService(Settings(tvs=tvs or (LIVING,)), drivers={driver.key: driver}, listen=_no_listen)
    tokens = iter(f"token-{n}" for n in range(100))
    return PowerService(service, clock=clock or Clock(), new_token=lambda: next(tokens))


def _run(coroutine):
    return asyncio.run(coroutine)


def test_a_request_asks_a_question_and_switches_nothing():
    driver = PowerDriver("on")
    question = _run(_power(driver).request("off", "The Frame"))
    assert question["outcome"] == "question"
    assert question["say"] == "Switch the living room off?"
    assert question["token"] == "token-0"  # noqa: S105 - a test token
    assert driver.switched == []


def test_nothing_switches_without_the_token_from_the_question():
    driver = PowerDriver("on")
    power = _power(driver)
    _run(power.request("off", "The Frame"))
    assert _run(power.confirm("made-up"))["outcome"] == "refused"
    assert driver.switched == []
    assert _run(power.confirm("token-0"))["outcome"] == "done"
    assert driver.switched == [("living-room", False)]


def test_a_power_token_works_once():
    driver = PowerDriver("on")
    power = _power(driver)
    _run(power.request("off", "The Frame"))
    _run(power.confirm("token-0"))
    assert _run(power.confirm("token-0"))["outcome"] == "refused"
    assert driver.switched == [("living-room", False)]


def test_a_power_token_expires_after_thirty_seconds():
    driver, clock = PowerDriver("on"), Clock()
    power = _power(driver, clock=clock)
    _run(power.request("off", "The Frame"))
    clock.now += 31
    answer = _run(power.confirm("token-0"))
    assert answer["outcome"] == "refused"
    assert "expired" in answer["say"]
    assert driver.switched == []


def test_only_the_latest_question_can_be_confirmed():
    driver = PowerDriver("on")
    power = _power(driver)
    _run(power.request("off", "The Frame"))
    _run(power.request("off", "The Frame"))
    assert _run(power.confirm("token-0"))["outcome"] == "refused"
    assert driver.switched == []


def test_a_request_the_tv_already_satisfies_is_refused():
    driver = PowerDriver("on")
    answer = _run(_power(driver).request("on", "The Frame"))
    assert answer["outcome"] == "refused"
    assert "already on" in answer["say"]


def test_a_tv_in_standby_or_art_mode_counts_as_off():
    driver = PowerDriver("standby")
    assert _run(_power(driver).request("on", "The Frame"))["outcome"] == "question"


def test_a_switch_is_refused_when_the_tv_changed_since_the_question():
    driver = PowerDriver("on")
    power = _power(driver)
    _run(power.request("off", "The Frame"))
    driver.power = "off"
    answer = _run(power.confirm("token-0"))
    assert answer["outcome"] == "refused"
    assert driver.switched == []


def test_a_hands_off_tv_is_never_switched():
    driver = PowerDriver("off")
    answer = _run(_power(driver, LIVING, UPSTAIRS).request("on", "upstairs"))
    assert answer["outcome"] == "refused"
    # Refused for being hands-off, not merely because its state cannot be read.
    assert "left alone" in answer["say"]
    assert "token" not in answer
    assert driver.switched == []


def test_an_unknown_state_word_is_refused():
    assert _run(_power(PowerDriver()).request("sideways", "The Frame"))["outcome"] == "refused"


def test_a_driver_that_cannot_switch_is_refused():
    class Plain(PowerDriver):
        switch = None

    answer = _run(_power(Plain("on")).request("off", "The Frame"))
    assert answer["outcome"] == "refused"


def test_a_switch_is_refused_when_the_tv_state_is_not_known():
    driver = PowerDriver("unknown")
    answer = _run(_power(driver).request("off", "The Frame"))
    assert answer["outcome"] == "refused"
    assert "token" not in answer

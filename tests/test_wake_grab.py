# SPDX-License-Identifier: GPL-3.0-or-later
"""A TV woken through the Chromecast in it may be taken over by that Chromecast.

On 2026-11-11 the garage TV, switched on by voice, came up on HDMI 3 and then
moved by itself to HDMI 1, its Chromecast. Our wake starts an app on the
Chromecast, and starting an app asks the TV over HDMI to show the Chromecast.
So the voice says so, and an input asked for soon after is looked at again and
sent once more if the Chromecast took the screen.
"""

import asyncio

from test_power import GARAGE, CastWithCec, Clock, PowerDriver, _no_listen, _no_wait

from tv_mcp.driver import INPUTS, InputSent, TvInfo
from tv_mcp.power import PowerService
from tv_mcp.service import TvService
from tv_mcp.settings import Settings, Tv

LOFT = Tv(
    key="loft",
    names=("the loft",),
    address="192.0.2.20",
    driver="chromecast",
    power_driver="samsung-legacy",
    power_address="192.0.2.21",
    power_on="cec",
    inputs={"hdmi3": "Game Box"},
)


class Legacy:
    """An old TV that sets its input by id and says which one it shows; `grabs` are the Chromecast's turns."""

    key = "samsung-legacy"

    def __init__(self, grabs):
        self.showing, self.grabs, self.sent = "HDMI 3", list(grabs), []

    async def read_info(self, address):
        return TvInfo(name=None, model=None, year=None, platform=None, power="on")

    async def show_input(self, tv, source):
        self.sent.append(source)
        self.showing = INPUTS[source]
        if self.grabs and self.grabs.pop(0):
            self.showing = "HDMI 1"
        return InputSent(said=INPUTS[source], shown=self.showing)

    async def input_shown(self, tv):
        if self.grabs and self.grabs.pop(0):
            self.showing = "HDMI 1"
        return self.showing


class Cast:
    key = "chromecast"

    async def read_info(self, address):
        return None


class Ticks:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _service(grabs, *, woken_ago=None):
    clock = Ticks()
    legacy = Legacy(grabs)

    async def wait(seconds):
        clock.now += seconds

    service = TvService(
        Settings(tvs=(LOFT,)),
        drivers={"samsung-legacy": legacy, "chromecast": Cast()},
        listen=_no_listen,
        clock=clock,
        sleep=wait,
    )
    if woken_ago is not None:
        service.woken_by_hdmi(LOFT)
        clock.now += woken_ago
    return service, legacy


def test_an_input_the_chromecast_took_right_after_a_wake_is_sent_again():
    service, legacy = _service([True, False, False], woken_ago=20)
    answer = asyncio.run(service.show_input("Game Box", "the loft"))
    assert legacy.sent == ["hdmi3", "hdmi3"]
    assert answer["outcome"] == "done", answer


def test_an_input_taken_just_after_it_was_shown_is_seen_and_sent_again():
    service, legacy = _service([False, True, False, False], woken_ago=20)
    answer = asyncio.run(service.show_input("Game Box", "the loft"))
    assert legacy.sent == ["hdmi3", "hdmi3"]
    assert answer["outcome"] == "done", answer


def test_an_input_the_chromecast_keeps_taking_is_not_confirmed():
    service, legacy = _service([True, True], woken_ago=20)
    answer = asyncio.run(service.show_input("Game Box", "the loft"))
    assert legacy.sent == ["hdmi3", "hdmi3"]
    assert answer["outcome"] == "unverified"
    assert "HDMI 1" in answer["say"]


def test_an_input_long_after_a_wake_is_sent_once():
    service, legacy = _service([True], woken_ago=600)
    asyncio.run(service.show_input("Game Box", "the loft"))
    assert legacy.sent == ["hdmi3"]


def test_an_input_on_a_tv_not_woken_by_us_is_sent_once():
    service, legacy = _service([True])
    asyncio.run(service.show_input("Game Box", "the loft"))
    assert legacy.sent == ["hdmi3"]


def _power():
    tv_driver = PowerDriver("off")
    cast = CastWithCec(tv_driver)
    service = TvService(
        Settings(tvs=(GARAGE,)), drivers={tv_driver.key: tv_driver, cast.key: cast}, listen=_no_listen
    )
    return service, PowerService(service, clock=Clock(), new_token=lambda: "token-0", sleep=_no_wait)


def test_a_wake_through_the_chromecast_is_remembered_and_said():
    service, power = _power()
    asyncio.run(power.request("on", "the garage"))
    answer = asyncio.run(power.confirm("token-0"))
    assert service.just_woken(GARAGE)
    assert answer["say"] == (
        "The garage is on now; its Chromecast may have taken the screen."
        " Ask me for another input if you want one."
    )

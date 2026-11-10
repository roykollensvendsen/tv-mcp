# SPDX-License-Identifier: GPL-3.0-or-later
"""Changing which input a TV shows, such as HDMI 1, by voice."""

import asyncio
from dataclasses import replace

from tv_mcp.drivers.samsung_legacy import SamsungLegacy
from tv_mcp.service import TvService
from tv_mcp.settings import Settings, Tv

LIVING = Tv(key="living-room", names=("the living room",), address="192.0.2.10")
GARAGE = Tv(
    key="garage",
    names=("the garage",),
    address="192.0.2.20",
    driver="chromecast",
    power_driver="samsung-legacy",
    power_address="192.0.2.21",
)
UPSTAIRS = Tv(key="upstairs", names=("upstairs",), address="192.0.2.11", hands_off=True)


class InputTv:
    key = "samsung-tizen"
    ssdp_target = "x"

    def __init__(self, *, answers=True):
        self.answers, self.shown = answers, []

    def recognises(self, announcement):
        return False

    async def read_info(self, address):
        return None

    async def show_input(self, tv, source):
        self.shown.append((tv.address, source))
        return self.answers


class Cast:
    key = "chromecast"
    ssdp_target = "y"

    def recognises(self, announcement):
        return False

    async def read_info(self, address):
        return None


def _service(*drivers, tvs=(LIVING,)):
    async def no_listen(recognises, target):
        return []

    return TvService(Settings(tvs=tvs), drivers={d.key: d for d in drivers}, listen=no_listen)


def _show(service, source, tv):
    return asyncio.run(service.show_input(source, tv))


def test_an_input_said_aloud_is_shown_on_the_named_tv():
    driver = InputTv()
    answer = _show(_service(driver), "HDMI 2", "the living room")
    assert driver.shown == [("192.0.2.10", "hdmi2")]
    assert answer["outcome"] == "done"
    assert "HDMI 2" in answer["say"]


def test_an_input_there_is_no_key_for_is_refused_naming_the_ones_there_are():
    driver = InputTv()
    answer = _show(_service(driver), "scart", "the living room")
    assert driver.shown == []
    assert answer["outcome"] == "refused"
    assert "HDMI 1" in answer["say"]


def test_a_tv_whose_own_device_cannot_change_input_is_changed_through_its_power_driver():
    legacy = InputTv()
    legacy.key = "samsung-legacy"
    answer = _show(_service(Cast(), legacy, tvs=(GARAGE,)), "hdmi1", "the garage")
    assert legacy.shown == [("192.0.2.21", "hdmi1")]
    assert answer["outcome"] == "done"


def test_a_tv_that_does_not_answer_is_said_plainly():
    answer = _show(_service(InputTv(answers=False)), "hdmi1", "the living room")
    assert answer["outcome"] == "refused"
    assert "on" in answer["say"]


def test_a_tv_with_no_way_to_change_input_is_refused():
    answer = _show(
        _service(Cast(), tvs=(replace(GARAGE, power_driver=None, power_address=None),)), "hdmi1", "the garage"
    )
    assert answer["outcome"] == "refused"


def test_a_hands_off_tv_is_never_changed():
    driver = InputTv()
    answer = _show(_service(driver, tvs=(LIVING, UPSTAIRS)), "hdmi1", "upstairs")
    assert driver.shown == []
    assert answer["outcome"] == "refused"


def test_the_older_samsung_presses_the_inputs_own_key_on_its_remote_port():
    pressed = []

    async def press(address, key, wait):
        pressed.append((address, key))
        return True

    driver = SamsungLegacy(press=press)
    assert asyncio.run(driver.show_input(GARAGE, "hdmi1"))
    assert pressed == [("192.0.2.20", "KEY_HDMI1")]

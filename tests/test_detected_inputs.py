# SPDX-License-Identifier: GPL-3.0-or-later
"""Which inputs have something plugged in, as the TV itself lists them, beside the owner's own names.

Only read, while the screen is on: the list is asked for, never an input changed.
A device the owner named in the settings keeps that name; the TV's list only
adds what it found, and each entry says where it came from.
"""

import asyncio

from tv_mcp.driver import TvInfo
from tv_mcp.drivers.samsung_legacy import parse_devices
from tv_mcp.service import TvService
from tv_mcp.settings import Settings, Tv

DEN = Tv(
    key="den",
    names=("the den",),
    address="192.0.2.30",
    inputs={"hdmi3": "Game Box"},
)


def _source(kind, ident, plugged, name=None):
    named = f"&lt;DeviceName&gt;{name}&lt;/DeviceName&gt;" if name is not None else ""
    return (
        f"&lt;Source&gt;&lt;SourceType&gt;{kind}&lt;/SourceType&gt;&lt;ID&gt;{ident}&lt;/ID&gt;"
        f"&lt;Connected&gt;{plugged}&lt;/Connected&gt;{named}&lt;/Source&gt;"
    )


LISTED = (
    "<Result>OK</Result><SourceList>&lt;SourceList&gt;"
    + _source("TV", "0", "Yes")
    + _source("HDMI1/DVI", "67", "Yes", "Media Stick")
    + _source("HDMI2", "68", "No", "Old Player")
    + _source("HDMI3", "69", "Yes", "")
    + _source("HDMI4", "70", "Yes")
    + "&lt;/SourceList&gt;</SourceList>"
)


class ListingTv:
    key = "samsung-tizen"

    def __init__(self, *, power="on", plugged=None, shows=None):
        self.power, self.plugged, self.shows, self.asked = power, plugged, shows, 0

    async def read_info(self, address):
        return TvInfo(name=None, model=None, year=None, platform=None, power=self.power)

    async def input_shown(self, tv):
        return self.shows

    async def inputs_plugged(self, tv):
        self.asked += 1
        return self.plugged


async def _no_listen(recognises, target):
    return []


def _status(driver, tv=DEN):
    service = TvService(Settings(tvs=(tv,)), drivers={driver.key: driver}, listen=_no_listen)
    [report] = asyncio.run(service.status(tv.names[0]))
    return report


def test_the_older_samsung_lists_what_is_plugged_in_and_any_name_a_device_gave():
    assert parse_devices(LISTED) == {"hdmi1": "Media Stick", "hdmi3": None, "hdmi4": None}


def test_status_lists_each_input_with_where_its_name_came_from():
    report = _status(ListingTv(plugged={"hdmi1": "Media Stick", "hdmi4": None}))
    assert report["inputs"] == [
        {"input": "HDMI 1", "device": "Media Stick", "from": "detected"},
        {"input": "HDMI 3", "device": "Game Box", "from": "set by hand"},
        {"input": "HDMI 4", "device": None, "from": "detected"},
    ]


def test_a_name_set_by_hand_wins_over_a_detected_one():
    report = _status(ListingTv(plugged={"hdmi3": "Console 9000"}, shows="HDMI 3"))
    assert report["inputs"] == [{"input": "HDMI 3", "device": "Game Box", "from": "set by hand"}]
    assert (report["input_device"], report["input_device_from"]) == ("Game Box", "set by hand")


def test_a_device_the_tv_named_is_said_when_it_is_showing():
    report = _status(ListingTv(plugged={"hdmi1": "Media Stick"}, shows="HDMI 1"))
    assert (report["input_device"], report["input_device_from"]) == ("Media Stick", "detected")


def test_the_list_is_not_asked_for_while_the_screen_is_off():
    driver = ListingTv(power="standby", plugged={"hdmi1": "Media Stick"})
    report = _status(driver)
    assert driver.asked == 0
    assert report["inputs"] == [{"input": "HDMI 3", "device": "Game Box", "from": "set by hand"}]


def test_a_tv_that_cannot_list_its_inputs_shows_the_ones_set_by_hand():
    report = _status(ListingTv(plugged=None, shows="HDMI 3"))
    assert report["inputs"] == [{"input": "HDMI 3", "device": "Game Box", "from": "set by hand"}]
    assert report["input_device_from"] == "set by hand"


def test_a_tv_with_nothing_named_or_found_has_no_list():
    report = _status(ListingTv(plugged={}), tv=Tv(key="bare", names=("the bare one",), address="192.0.2.32"))
    assert "inputs" not in report

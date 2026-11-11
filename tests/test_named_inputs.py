# SPDX-License-Identifier: GPL-3.0-or-later
"""Devices on a TV's inputs, named by the owner, so "show the game box" picks its HDMI input.

The names live only in the owner's settings file, as a table per TV:

    [tvs.den.inputs]
    "HDMI 1" = "Streaming Stick"
    "HDMI 3" = "Game Box"
"""

import asyncio

from tv_mcp.driver import INPUTS, InputSent, TvInfo
from tv_mcp.server import build_server
from tv_mcp.service import TvService
from tv_mcp.settings import Settings, input_devices, load_settings
from tv_mcp.simulator import simulated_service
from tv_mcp.tools.say import tv_lines

EXAMPLE = """
[tvs.den]
names = ["the den"]
address = "192.0.2.30"

[tvs.den.inputs]
"HDMI 1" = "Streaming Stick"
"hdmi3" = "Game Box"

[tvs.attic]
names = ["the attic"]
address = "192.0.2.31"

[tvs.attic.inputs]
"HDMI 2" = "Game Box Mini"
"HDMI 4" = "Game Box Classic"
"Scart 9" = "Not An Input"
"""


class InputTv:
    key = "samsung-tizen"

    def __init__(self, reads=None):
        self.shown, self.reads = [], reads

    async def read_info(self, address):
        return TvInfo(name=None, model=None, year=None, platform=None, power="on")

    async def show_input(self, tv, source):
        self.shown.append(source)
        return InputSent(said=INPUTS[source], shown=self.reads or INPUTS[source])

    async def input_shown(self, tv):
        return self.reads


async def _no_listen(recognises, target):
    return []


def _settings(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(EXAMPLE)
    return load_settings(path)


def _service(tmp_path, driver):
    return TvService(_settings(tmp_path), drivers={driver.key: driver}, listen=_no_listen)


def test_the_devices_on_each_input_are_read_from_the_settings(tmp_path):
    den = _settings(tmp_path).tvs[0]
    assert den.inputs == {"hdmi1": "Streaming Stick", "hdmi3": "Game Box"}


def test_an_entry_that_is_not_an_input_is_left_out(tmp_path):
    attic = _settings(tmp_path).tvs[1]
    assert attic.inputs == {"hdmi2": "Game Box Mini", "hdmi4": "Game Box Classic"}


def test_a_device_named_however_it_is_said_picks_its_input(tmp_path):
    driver = InputTv()
    answer = asyncio.run(_service(tmp_path, driver).show_input("the GAME box", "the den"))
    assert driver.shown == ["hdmi3"]
    assert answer["outcome"] == "done", answer
    assert answer["say"] == "The den shows HDMI 3, the Game Box, now."


def test_part_of_a_devices_name_is_enough_when_only_one_device_has_it(tmp_path):
    driver = InputTv()
    asyncio.run(_service(tmp_path, driver).show_input("stick", "the den"))
    assert driver.shown == ["hdmi1"]


def test_a_device_name_that_fits_two_inputs_is_refused(tmp_path):
    driver = InputTv()
    answer = asyncio.run(_service(tmp_path, driver).show_input("game box", "the attic"))
    assert answer["outcome"] == "refused"
    assert "Game Box Mini" in answer["say"]
    assert "Game Box Classic" in answer["say"]
    assert driver.shown == []


def test_a_device_another_tv_has_is_refused_naming_this_tvs_devices(tmp_path):
    driver = InputTv()
    answer = asyncio.run(_service(tmp_path, driver).show_input("Game Box Mini", "the den"))
    assert answer["outcome"] == "refused"
    assert "Streaming Stick" in answer["say"]
    assert driver.shown == []


def test_an_input_said_by_number_is_still_shown_and_named(tmp_path):
    driver = InputTv()
    answer = asyncio.run(_service(tmp_path, driver).show_input("HDMI 1", "the den"))
    assert driver.shown == ["hdmi1"]
    assert answer["say"] == "The den shows HDMI 1, the Streaming Stick, now."


def test_status_says_which_device_is_showing(tmp_path):
    [report] = asyncio.run(_service(tmp_path, InputTv(reads="HDMI 3")).status("the den"))
    assert (report["input"], report["input_device"]) == ("HDMI 3", "Game Box")
    assert tv_lines([report]) == "The den is on, showing HDMI 3, the Game Box."


def test_an_input_with_no_device_named_is_said_by_number(tmp_path):
    [report] = asyncio.run(_service(tmp_path, InputTv(reads="HDMI 2")).status("the den"))
    assert "input_device" not in report
    assert tv_lines([report]) == "The den is on, showing HDMI 2."


def test_another_program_can_read_the_devices_of_every_tv(tmp_path):
    assert input_devices(_settings(tmp_path)) == {
        "den": {"HDMI 1": "Streaming Stick", "HDMI 3": "Game Box"},
        "attic": {"HDMI 2": "Game Box Mini", "HDMI 4": "Game Box Classic"},
    }
    assert input_devices(Settings()) == {}


def test_the_voice_reads_first_that_a_device_name_works():
    tools = asyncio.run(build_server(simulated_service(), features=["status", "input"]).list_tools())
    [tool] = [t for t in tools if t.name == "tv_input"]
    opening, source = tool.description.split("\n")[:2]
    assert opening == "Show a device or port."
    assert source == "Source: a device name for this TV (e.g. Chromecast) or HDMI 1-4 or TV."


def test_an_unknown_name_lists_the_names_this_tv_knows(tmp_path):
    driver = InputTv()
    answer = asyncio.run(_service(tmp_path, driver).show_input("Projector", "the den"))
    assert answer["outcome"] == "refused"
    assert answer["say"] == (
        "The den has no 'Projector'. Say a device: Streaming Stick or Game Box; or HDMI 1 to HDMI 4, or TV."
    )
    assert driver.shown == []

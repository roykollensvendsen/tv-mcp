# SPDX-License-Identifier: GPL-3.0-or-later
"""Whether The Frame shows art, read and never switched.

A Frame showing art answers its information page as in standby, so status
could only say "standby or art mode". The TV's art channel says which, and
status asks it only that: it never switches art mode, or the TV, on or off.
"""

import asyncio
import pathlib

from tv_mcp.driver import TvInfo
from tv_mcp.drivers.samsung_tizen import SamsungTizen
from tv_mcp.service import TvService
from tv_mcp.settings import Settings, Tv

FRAME = Tv(key="the-frame", names=("the living room",), address="192.0.2.10")


class Frame:
    key = "samsung-tizen"
    ssdp_target = "x"

    def __init__(self, power, art):
        self.power, self.art, self.asked = power, art, []

    def recognises(self, announcement):
        return False

    async def read_info(self, address):
        return TvInfo(
            name=None, model=None, year=2022, platform=None, power=self.power, art_mode_capable=True
        )

    async def art_mode(self, tv):
        self.asked.append(tv.key)
        return self.art


def _status(driver):
    async def no_listen(recognises, target):
        return []

    service = TvService(Settings(tvs=(FRAME,)), drivers={driver.key: driver}, listen=no_listen)
    [report] = asyncio.run(service.status("the living room"))
    return report


def test_a_frame_that_shows_art_is_said_to_show_art():
    assert _status(Frame("standby", art=True))["state"] == "showing art"


def test_a_frame_in_standby_without_art_is_said_to_be_in_standby():
    assert _status(Frame("standby", art=False))["state"] == "standby"


def test_a_frame_whose_art_channel_does_not_answer_stays_standby_or_art_mode():
    assert _status(Frame("standby", art=None))["state"] == "standby or art mode"


def test_a_frame_that_is_on_is_not_asked_about_art():
    driver = Frame("on", art=True)
    assert _status(driver)["state"] == "on"
    assert driver.asked == []


class ArtChannel:
    """The art channel of a Frame, as samsungtvws opens it."""

    def __init__(self, mode, opened):
        self.mode, self.opened, self.sent = mode, opened, []

    def get_artmode(self):
        return self.mode

    def set_artmode(self, mode):  # must never be called
        self.sent.append(mode)

    def close(self):
        self.opened.append("closed")


def test_art_mode_is_only_read_never_set():
    opened = []
    channels = []

    def art(address, token_file):
        opened.append((address, token_file.name))
        channels.append(ArtChannel("on", opened))
        return channels[-1]

    driver = SamsungTizen(None, tls_client=object(), token_folder=pathlib.Path("/nowhere"), art=art)
    assert asyncio.run(driver.art_mode(FRAME)) is True
    assert opened == [("192.0.2.10", "the-frame-token"), "closed"]
    assert channels[0].sent == []


def test_an_art_channel_that_fails_says_nothing():
    def art(address, token_file):
        message = "no answer"
        raise OSError(message)

    driver = SamsungTizen(None, tls_client=object(), token_folder=pathlib.Path("/nowhere"), art=art)
    assert asyncio.run(driver.art_mode(FRAME)) is None


def test_a_frame_showing_art_counts_as_off_for_switching_it_on():
    from tv_mcp.power import PowerService  # noqa: PLC0415

    class Switching(Frame):
        async def switch(self, tv, *, on):
            return True

    async def no_listen(recognises, target):
        return []

    service = TvService(
        Settings(tvs=(FRAME,)), drivers={"samsung-tizen": Switching("standby", art=True)}, listen=no_listen
    )
    question = asyncio.run(PowerService(service).request("on", "the living room"))
    assert question["outcome"] == "question"
    assert question["say"].startswith("The living room is off.")

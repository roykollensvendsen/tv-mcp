# SPDX-License-Identifier: GPL-3.0-or-later
"""A 2023 Samsung changes input by its home-screen tile, since it ignores the input keys.

On 2026-11-11 the Q68CA upstairs (Tizen 7.0) took KEY_HDMI2 from YouTube and
kept YouTube on the screen for 20 s. Launching the tile its home screen has for
HDMI 2, over the local "mobilebff" channel, showed the input at once. The same
list of tiles names what is plugged in, as the device announced itself.
"""

import asyncio

import httpx

from tv_mcp.drivers.samsung_tizen import SamsungTizen, input_tiles
from tv_mcp.settings import Tv

UPSTAIRS = Tv(key="upstairs", names=("upstairs",), address="192.0.2.11")
TILES = [
    {"title": "Netflix", "appId": "d/webapp@3201907018807"},
    {"title": "Console 9000", "appId": "s/source.layer.hdmi@HDMI2/0"},
    {"title": "Media Stick", "appId": "s/source.layer.hdmi@HDMI1/1"},
    {"title": "Old Player", "appId": "s/source.layer.hdmi@HDMI3"},
    {"title": "TV Plus", "appId": "s/livetv@TVPLUS"},
]


def test_the_input_tiles_are_read_from_the_home_screen():
    assert input_tiles(TILES) == {
        "hdmi1": ("s/source.layer.hdmi@HDMI1/1", "Media Stick"),
        "hdmi2": ("s/source.layer.hdmi@HDMI2/0", "Console 9000"),
        "hdmi3": ("s/source.layer.hdmi@HDMI3", "Old Player"),
    }


class Home:
    """The TV's home-screen channel: lists `tiles`, and records what it is asked to launch."""

    def __init__(self, tiles, state):
        self.tiles, self.state, self.launched = tiles, state, []

    def ask(self, request_id, params):
        if request_id == "get.apptiles":
            return {"id": request_id, "response": self.tiles}
        if request_id == "launch.app":
            self.launched.append(params["requestId"])
            self.state["front"] = None
            return {"id": request_id, "response": {"status": "ok"}}
        return None

    def close(self):
        pass


def _tv(tmp_path, *, tiles, home_opens=True):
    state = {"front": "youtube"}
    pressed = []
    home = Home(tiles, state)
    ids = {app_id: name for name, app_id in SamsungTizen.apps.items()}

    def handler(request):
        name = ids.get(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, json={"running": name == "youtube", "visible": name == state["front"]})

    class Remote:
        def send_key(self, key):
            pressed.append(key)

        def close(self):
            pass

    def bff(address, token_file):
        if not home_opens:
            raise OSError
        return home

    async def no_wait(seconds):
        return None

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    driver = SamsungTizen(
        client, tls_client=client, token_folder=tmp_path, remote=lambda a, t: Remote(), bff=bff, sleep=no_wait
    )
    return driver, home, pressed


def test_an_input_is_changed_by_its_tile_when_the_tv_lists_one(tmp_path):
    driver, home, pressed = _tv(tmp_path, tiles=TILES)
    sent = asyncio.run(driver.show_input(UPSTAIRS, "hdmi2"))
    assert home.launched == ["s/source.layer.hdmi@HDMI2/0"]
    assert pressed == []
    assert (sent.said, sent.left, sent.accepted) == ("HDMI 2", "YouTube", True)


def test_an_input_with_no_tile_has_nothing_plugged_in_and_is_not_sent(tmp_path):
    driver, home, pressed = _tv(tmp_path, tiles=TILES)
    sent = asyncio.run(driver.show_input(UPSTAIRS, "hdmi4"))
    assert sent.unplugged is True
    assert (home.launched, pressed) == ([], [])


def test_a_tv_without_the_home_screen_channel_gets_the_input_key(tmp_path):
    driver, _, pressed = _tv(tmp_path, tiles=TILES, home_opens=False)
    sent = asyncio.run(driver.show_input(UPSTAIRS, "hdmi2"))
    assert pressed == ["KEY_HDMI2"]
    assert sent.said == "HDMI 2"


def test_a_tv_that_lists_no_input_tiles_gets_the_input_key(tmp_path):
    # The Frame's home screen may not list its inputs; that says nothing about what is plugged in.
    driver, home, pressed = _tv(tmp_path, tiles=[TILES[0]])
    sent = asyncio.run(driver.show_input(UPSTAIRS, "hdmi2"))
    assert (home.launched, pressed) == ([], ["KEY_HDMI2"])
    assert sent.unplugged is False


def test_the_tiles_name_what_is_plugged_in(tmp_path):
    driver, _, _ = _tv(tmp_path, tiles=TILES)
    assert asyncio.run(driver.inputs_plugged(UPSTAIRS)) == {
        "hdmi1": "Media Stick",
        "hdmi2": "Console 9000",
        "hdmi3": "Old Player",
    }


def test_a_tv_without_the_home_screen_channel_cannot_list_its_inputs(tmp_path):
    driver, _, _ = _tv(tmp_path, tiles=TILES, home_opens=False)
    assert asyncio.run(driver.inputs_plugged(UPSTAIRS)) is None

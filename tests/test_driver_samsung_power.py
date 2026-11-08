# SPDX-License-Identifier: GPL-3.0-or-later
"""The Samsung driver switching a TV: the power key when it listens, a wake packet when it does not."""

import asyncio

import httpx

from tv_mcp.drivers.samsung_tizen import SamsungTizen, magic_packet
from tv_mcp.settings import Tv

FRAME = Tv(key="the-frame", names=("The Frame",), address="192.0.2.10", mac="00:00:5E:00:53:01")


class Remote:
    def __init__(self):
        self.keys = []

    def __call__(self, address, token_file):
        self.address, self.token_file = address, token_file
        return self

    def send_key(self, key):
        self.keys.append((key, 0))

    def hold_key(self, key, seconds):
        self.keys.append((key, seconds))

    def close(self):
        pass


def _driver(page, remote, woken, tmp_path):
    def handler(request):
        return httpx.Response(200, json=page) if page else httpx.Response(503)

    async def run(*, on):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            driver = SamsungTizen(
                client, tls_client=client, token_folder=tmp_path, remote=remote, wake=woken.append
            )
            return await driver.switch(FRAME, on=on)

    return run


def _page(power):
    return {"device": {"PowerState": power, "modelName": "QE55LS03BAUXXC", "FrameTVSupport": "true"}}


def test_off_holds_the_power_key_because_a_short_press_only_goes_to_art_mode(tmp_path):
    remote, woken = Remote(), []
    assert asyncio.run(_driver(_page("on"), remote, woken, tmp_path)(on=False)) is True
    assert remote.keys == [("KEY_POWER", 3.0)]
    assert remote.token_file == tmp_path / "the-frame-token"
    assert woken == []


def test_on_from_art_mode_presses_the_power_key(tmp_path):
    remote, woken = Remote(), []
    assert asyncio.run(_driver(_page("standby"), remote, woken, tmp_path)(on=True)) is True
    assert remote.keys == [("KEY_POWER", 0)]
    assert woken == []


def test_on_from_deep_standby_sends_a_wake_packet_to_the_tvs_mac(tmp_path):
    remote, woken = Remote(), []
    assert asyncio.run(_driver(None, remote, woken, tmp_path)(on=True)) is True
    assert woken == ["00:00:5E:00:53:01"]
    assert remote.keys == []


def test_a_wake_packet_is_six_ff_bytes_then_the_mac_sixteen_times():
    packet = magic_packet("00:00:5E:00:53:01")
    assert packet[:6] == b"\xff" * 6
    assert packet[6:] == bytes.fromhex("00005E005301") * 16


def test_a_tv_that_is_already_unreachable_cannot_be_switched_off(tmp_path):
    remote, woken = Remote(), []
    assert asyncio.run(_driver(None, remote, woken, tmp_path)(on=False)) is False
    assert remote.keys == []

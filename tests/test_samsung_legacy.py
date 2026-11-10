# SPDX-License-Identifier: GPL-3.0-or-later
"""Older Samsungs (2011 to 2015, before Tizen): their remote protocol on port 55000, and power."""

import asyncio
import base64

from tv_mcp.drivers.samsung_legacy import SamsungLegacy, answer_of, auth_packet, key_packet
from tv_mcp.power import PowerService
from tv_mcp.service import TvService
from tv_mcp.settings import Settings, Tv, load_settings

GARAGE = Tv(
    key="garage",
    names=("garage",),
    address="192.0.2.20",
    driver="chromecast",
    power_driver="samsung-legacy",
    power_address="192.0.2.21",
    mac="00:00:5E:00:53:02",
)


def _b64(text):
    return base64.b64encode(text.encode())


def test_the_remote_says_who_it_is_in_base64_with_lengths_first():
    packet = auth_packet("tv-mcp")
    payload = b"\x64\x00" + bytes([len(_b64("tv-mcp"))]) + b"\x00" + _b64("tv-mcp")
    payload += bytes([len(_b64("tv-mcp"))]) + b"\x00" + _b64("tv-mcp")
    payload += bytes([len(_b64("tv-mcp"))]) + b"\x00" + _b64("tv-mcp")
    assert packet == b"\x00\x00\x00" + bytes([len(payload)]) + b"\x00" + payload


def test_a_key_is_sent_in_base64():
    inner = b"\x00\x00\x00" + bytes([len(_b64("KEY_POWEROFF"))]) + b"\x00" + _b64("KEY_POWEROFF")
    assert key_packet("KEY_POWEROFF") == b"\x00\x00\x00" + bytes([len(inner)]) + b"\x00" + inner


def test_the_tvs_answers_are_read():
    assert answer_of(b"\x64\x00\x01\x00") == "allowed"
    assert answer_of(b"\x64\x00\x00\x00") == "denied"
    assert answer_of(b"\x0a\x00\x02\x00\x00\x00") == "waiting"
    assert answer_of(b"\x65\x00") == "timed out"


def test_the_power_target_is_read_from_the_settings(tmp_path):
    file = tmp_path / "config.toml"
    file.write_text(
        '[tvs.garage]\nnames = ["garage"]\ndriver = "chromecast"\naddress = "192.0.2.20"\n'
        'power = { driver = "samsung-legacy", address = "192.0.2.21", on = "cec" }\n'
    )
    [tv] = load_settings(file).tvs
    assert (tv.power_driver, tv.power_address, tv.power_on) == ("samsung-legacy", "192.0.2.21", "cec")


class Legacy:
    key = "samsung-legacy"
    ssdp_target = "x"

    def __init__(self, power):
        self.power, self.switched = power, []

    def recognises(self, announcement):
        return False

    async def read_info(self, address):
        from tv_mcp.driver import TvInfo  # noqa: PLC0415

        self.read = address
        return (
            None
            if self.power is None
            else TvInfo(name=None, model=None, year=None, platform=None, power=self.power)
        )

    async def switch(self, tv, *, on):
        self.switched.append((tv.address, on))
        self.power = "on" if on else "standby"
        return True


class Cast:
    key = "chromecast"
    ssdp_target = "x"

    def recognises(self, announcement):
        return False

    async def read_info(self, address):
        return None


def _power(legacy):
    async def no_listen(recognises, target):
        return []

    service = TvService(
        Settings(tvs=(GARAGE,)), drivers={"chromecast": Cast(), legacy.key: legacy}, listen=no_listen
    )

    async def no_wait(seconds):
        return None

    return PowerService(service, new_token=lambda: "t1", sleep=no_wait)


def test_a_tv_with_a_power_target_is_switched_through_it_after_a_yes():
    legacy = Legacy("standby")
    power = _power(legacy)
    question = asyncio.run(power.request("on", "garage"))
    assert question["outcome"] == "question"
    assert legacy.switched == []
    assert asyncio.run(power.confirm("t1"))["outcome"] == "done"
    assert legacy.switched == [("192.0.2.21", True)]


def test_a_power_target_that_does_not_answer_counts_as_off():
    legacy = Legacy(None)
    assert asyncio.run(_power(legacy).request("on", "garage"))["outcome"] == "question"
    assert legacy.read == "192.0.2.21"


def test_an_old_samsung_is_on_when_its_media_renderer_answers_and_in_standby_when_only_the_remote_does():
    async def run(open_ports):
        async def reach(address, port):
            return port in open_ports

        return await SamsungLegacy(reach=reach).read_info("192.0.2.21")

    assert asyncio.run(run({55000, 7676})).power == "on"
    assert asyncio.run(run({55000})).power == "standby"
    assert asyncio.run(run(set())) is None


def test_a_wake_packet_goes_to_the_tvs_own_network_and_not_only_the_default_one():
    # 2026-11-09: this machine is on two networks, and 255.255.255.255 left on the other one.
    from tv_mcp.drivers.samsung_legacy import broadcasts  # noqa: PLC0415

    assert broadcasts("192.0.2.21") == ["192.0.2.255", "255.255.255.255"]


def test_switching_on_counts_as_sent_when_the_wake_packet_went_though_the_remote_port_is_silent():
    from tv_mcp.drivers.samsung_legacy import SamsungLegacy  # noqa: PLC0415
    from tv_mcp.settings import Tv  # noqa: PLC0415

    woken = []

    async def silent(address, key, wait):
        return False

    legacy = SamsungLegacy(wake=lambda mac, address: woken.append((mac, address)), press=silent)
    tv = Tv(key="garage", names=("garage",), address="192.0.2.21", mac="00:00:5e:00:53:01")
    assert asyncio.run(legacy.switch(tv, on=True)) is True
    assert woken == [("00:00:5e:00:53:01", "192.0.2.21")]
    assert asyncio.run(legacy.switch(tv, on=False)) is False


def test_status_says_whether_the_tv_itself_is_on_beside_the_device_that_casts_to_it():
    # 2026-11-09: status for the garage named only the Chromecast, never the Samsung itself.
    from tv_mcp.tools.say import tv_lines  # noqa: PLC0415

    for power, said in (("on", "the TV itself is on"), ("standby", "the TV itself is off"), (None, "off")):
        service = _power(Legacy(power))._service  # noqa: SLF001 - the service under the power checks
        [report] = asyncio.run(service.status("garage"))
        assert report["screen"] == ("on" if power == "on" else "off")
        assert said in tv_lines([report])

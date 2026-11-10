# SPDX-License-Identifier: GPL-3.0-or-later
"""Sound by voice: mute, unmute and volume on every TV, never too loud."""

import asyncio

import httpx

from tv_mcp.driver import TvInfo
from tv_mcp.drivers.samsung_tizen import SamsungTizen
from tv_mcp.service import LOUDEST, TvService
from tv_mcp.settings import Settings, Tv

LIVING = Tv(key="living-room", names=("the living room",), address="192.0.2.10")
UPSTAIRS = Tv(key="upstairs", names=("upstairs",), address="192.0.2.11", hands_off=True)


class Speaker:
    key = "samsung-tizen"
    ssdp_target = "x"

    def __init__(self, level=20, *, works=True):
        self.level, self.is_muted, self.works, self.sent = level, False, works, []

    def recognises(self, announcement):
        return False

    async def read_info(self, address):
        # On, so status asks it what plays and how loud it is.
        return TvInfo(name=None, model=None, year=None, platform=None, power="on")

    async def volume(self, address):
        return self.level if self.works else None

    async def muted(self, address):
        return self.is_muted if self.works else None

    async def set_volume(self, address, level):
        self.sent.append(("volume", level))
        self.level = level
        return self.works

    async def set_mute(self, address, *, on):
        self.sent.append(("mute", on))
        self.is_muted = on
        return self.works


def _service(driver, *tvs):
    async def no_listen(recognises, target):
        return []

    return TvService(Settings(tvs=tvs or (LIVING,)), drivers={driver.key: driver}, listen=no_listen)


def test_mute_and_unmute_go_to_the_tv():
    driver = Speaker()
    service = _service(driver)
    assert asyncio.run(service.sound("mute", "the living room"))["outcome"] == "done"
    assert asyncio.run(service.sound("unmute", "the living room"))["outcome"] == "done"
    assert driver.sent == [("mute", True), ("mute", False)]


def test_volume_is_set_to_a_level_and_said():
    driver = Speaker()
    answer = asyncio.run(_service(driver).sound("volume", "the living room", level=30))
    assert driver.sent == [("volume", 30)]
    assert "30" in answer["say"]


def test_volume_up_and_down_count_from_where_it_is():
    driver = Speaker(level=20)
    service = _service(driver)
    asyncio.run(service.sound("volume", "the living room", level=5, relative=True))
    asyncio.run(service.sound("volume", "the living room", level=-30, relative=True))
    assert driver.sent == [("volume", 25), ("volume", 0)]


def test_the_volume_is_never_set_louder_than_the_cap():
    driver = Speaker(level=40)
    answer = asyncio.run(_service(driver).sound("volume", "the living room", level=100))
    assert driver.sent == [("volume", LOUDEST)]
    assert "at most" in answer["say"]


def test_a_tv_that_does_not_answer_is_said_plainly():
    answer = asyncio.run(_service(Speaker(works=False)).sound("mute", "the living room"))
    assert answer["outcome"] == "refused"


def test_a_hands_off_tv_is_never_sent_sound_commands():
    driver = Speaker()
    answer = asyncio.run(_service(driver, LIVING, UPSTAIRS).sound("mute", "upstairs"))
    assert answer["outcome"] == "refused"
    assert driver.sent == []


def test_a_samsung_takes_volume_and_mute_over_its_standard_rendering_service():
    seen = []

    def handler(request):
        action = request.headers["soapaction"].split("#")[1].strip('"')
        seen.append((request.url.port, request.url.path, action, request.content.decode()))
        if action == "GetVolume":
            return httpx.Response(
                200,
                text="<s:Envelope><s:Body><u:GetVolumeResponse>"
                "<CurrentVolume>22</CurrentVolume></u:GetVolumeResponse></s:Body></s:Envelope>",
            )
        return httpx.Response(200, text="<ok/>")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            tv = SamsungTizen(client)
            return (
                await tv.volume("192.0.2.10"),
                await tv.set_volume("192.0.2.10", 30),
                await tv.set_mute("192.0.2.10", on=True),
            )

    assert asyncio.run(run()) == (22, True, True)
    assert all(port == 9197 and path == "/upnp/control/RenderingControl1" for port, path, _, _ in seen)
    assert "<DesiredVolume>30</DesiredVolume>" in seen[1][3]
    assert "<DesiredMute>1</DesiredMute>" in seen[2][3]


class Reading(Speaker):
    async def muted(self, address):
        return self.muted_now

    async def playing(self, address):
        return None

    async def player(self, tv, command, seconds=None):
        return "unsupported"


def test_status_says_how_loud_each_tv_is_and_whether_it_is_muted():
    driver = Reading(level=15)
    driver.muted_now = False
    [report] = asyncio.run(_service(driver).status("the living room"))
    assert (report["volume"], report["muted"]) == (15, False)
    driver.muted_now = True
    [report] = asyncio.run(_service(driver).status("the living room"))
    assert report["muted"] is True


def test_the_status_line_says_the_volume_or_that_it_is_muted():
    from tv_mcp.tools.say import tv_lines  # noqa: PLC0415

    assert "volume 15" in tv_lines([{"tv": "the living room", "state": "on", "volume": 15, "muted": False}])
    assert "muted" in tv_lines([{"tv": "the living room", "state": "on", "volume": 15, "muted": True}])


def test_a_hands_off_tv_is_never_asked_how_loud_it_is():
    driver = Reading()
    driver.muted_now = False
    [report] = asyncio.run(_service(driver, LIVING, UPSTAIRS).status("upstairs"))
    assert "volume" not in report


def test_a_samsung_says_whether_it_is_muted():
    def handler(request):
        return httpx.Response(
            200,
            text="<s:Envelope><s:Body><u:GetMuteResponse><CurrentMute>1</CurrentMute>"
            "</u:GetMuteResponse></s:Body></s:Envelope>",
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await SamsungTizen(client).muted("192.0.2.10")

    assert asyncio.run(run()) is True

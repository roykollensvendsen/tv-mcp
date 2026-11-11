# SPDX-License-Identifier: GPL-3.0-or-later
"""A TV that plays through a Chromecast is muted and turned up on the TV itself.

On 2026-11-11 the garage TV showed a games machine on HDMI 3 and was told by
voice to mute. The mute went to the Chromecast on HDMI 1, so the games machine
went on sounding. The older Samsung there takes volume and mute over the
standard UPnP service on its own port 7676, whatever input it shows; the
Chromecast's volume reaches only what the Chromecast plays.
"""

import asyncio

import httpx

from tv_mcp.driver import TvInfo
from tv_mcp.drivers import samsung_legacy
from tv_mcp.drivers.samsung_legacy import SamsungLegacy
from tv_mcp.service import TvService
from tv_mcp.settings import Settings, Tv

LOFT = Tv(
    key="loft",
    names=("the loft",),
    address="192.0.2.20",
    driver="chromecast",
    power_driver="samsung-legacy",
    power_address="192.0.2.21",
)


class Speaker:
    """A driver with sound: `works` False when it does not answer."""

    def __init__(self, key, level, *, works=True, in_front=None):
        self.key, self.level, self.works, self.in_front = key, level, works, in_front
        self.is_muted, self.sent = False, []

    async def read_info(self, address):
        return TvInfo(name=None, model=None, year=None, platform=None, power="on")

    async def volume(self, address):
        return self.level if self.works else None

    async def muted(self, address):
        return self.is_muted if self.works else None

    async def set_volume(self, address, level):
        self.sent.append((address, "volume", level))
        return self.works

    async def set_mute(self, address, *, on):
        self.sent.append((address, "mute", on))
        return self.works


class Cast(Speaker):
    async def on_screen(self, address):
        return self.in_front


async def _no_listen(recognises, target):
    return []


def _loft(*, tv_answers=True, in_front=None):
    tv = Speaker("samsung-legacy", 12, works=tv_answers)
    cast = Cast("chromecast", 80, in_front=in_front)
    service = TvService(Settings(tvs=(LOFT,)), drivers={tv.key: tv, cast.key: cast}, listen=_no_listen)
    return service, tv, cast


def test_the_sound_goes_to_the_tv_itself_before_the_device_that_plays_through_it():
    service, tv, cast = _loft()
    answer = asyncio.run(service.sound("mute", "the loft"))
    assert tv.sent == [("192.0.2.21", "mute", True)]
    assert cast.sent == []
    assert answer == {"outcome": "done", "say": "Muted the loft."}


def test_volume_up_counts_from_the_tvs_own_volume():
    service, tv, cast = _loft()
    answer = asyncio.run(service.sound("volume", "the loft", level=5, relative=True))
    assert tv.sent == [("192.0.2.21", "volume", 17)]
    assert cast.sent == []
    assert answer["say"] == "Volume 17 on the loft."


def test_status_says_how_loud_the_tv_itself_is():
    service, _, _ = _loft()
    [report] = asyncio.run(service.status("the loft"))
    assert (report["volume"], report["muted"]) == (12, False)


def test_a_sound_change_only_the_chromecast_took_says_so():
    service, _, cast = _loft(tv_answers=False, in_front=False)
    answer = asyncio.run(service.sound("mute", "the loft"))
    assert cast.sent == [("192.0.2.20", "mute", True)]
    assert answer["outcome"] == "unverified"
    assert answer["say"] == (
        "The loft did not answer, so I muted its Chromecast only. The loft shows another input,"
        " so that sound is unchanged. Use the TV's own remote for it."
    )


def test_a_sound_change_on_the_chromecast_it_shows_is_done():
    service, _, cast = _loft(tv_answers=False, in_front=True)
    answer = asyncio.run(service.sound("volume", "the loft", level=30))
    assert cast.sent == [("192.0.2.20", "volume", 30)]
    assert answer == {"outcome": "done", "say": "Volume 30 on the loft.", "volume": 30}


def test_a_sound_change_on_a_chromecast_that_cannot_tell_what_shows_says_so():
    service, _, _ = _loft(tv_answers=False, in_front=None)
    answer = asyncio.run(service.sound("volume", "the loft", level=30))
    assert answer["outcome"] == "unverified"
    assert answer["say"] == (
        "The loft did not answer, so I set its Chromecast only, to volume 30."
        " Use the TV's own remote for its sound if the loft shows another input."
    )


def test_neither_the_tv_nor_its_chromecast_answering_is_said_with_what_to_do():
    service, _, cast = _loft(tv_answers=False)
    cast.works = False
    answer = asyncio.run(service.sound("mute", "the loft"))
    assert answer["outcome"] == "refused"
    assert answer["say"] == "The loft did not answer. Check that it is on, and try again."


RENDERING = "urn:schemas-upnp-org:service:RenderingControl:1"


def _older_samsung(answers):
    """An older Samsung whose standard volume service answers `answers`, by action."""
    calls = []

    async def rendering(address, action, arguments):
        calls.append((address, action, arguments))
        return answers.get(action)

    return SamsungLegacy(rendering=rendering), calls


def test_an_older_samsung_says_its_volume_and_whether_it_is_muted():
    driver, _ = _older_samsung(
        {
            "GetVolume": "<u:GetVolumeResponse><CurrentVolume>14</CurrentVolume></u:GetVolumeResponse>",
            "GetMute": "<u:GetMuteResponse><CurrentMute>1</CurrentMute></u:GetMuteResponse>",
        }
    )
    assert asyncio.run(driver.volume("192.0.2.21")) == 14
    assert asyncio.run(driver.muted("192.0.2.21")) is True


def test_an_older_samsung_takes_volume_and_mute():
    driver, calls = _older_samsung({"SetVolume": "<ok/>", "SetMute": "<ok/>"})
    assert asyncio.run(driver.set_volume("192.0.2.21", 25)) is True
    assert asyncio.run(driver.set_mute("192.0.2.21", on=True)) is True
    assert calls == [
        ("192.0.2.21", "SetVolume", "<DesiredVolume>25</DesiredVolume>"),
        ("192.0.2.21", "SetMute", "<DesiredMute>1</DesiredMute>"),
    ]


def test_an_older_samsung_that_does_not_answer_says_nothing_of_its_sound():
    driver, _ = _older_samsung({})
    assert asyncio.run(driver.volume("192.0.2.21")) is None
    assert asyncio.run(driver.muted("192.0.2.21")) is None
    assert asyncio.run(driver.set_mute("192.0.2.21", on=False)) is False


def test_the_volume_service_is_found_on_the_tvs_numbered_pages():
    def handler(request):
        if request.url.path == "/smp_7_":
            return httpx.Response(
                200,
                text=f"<service><serviceType>{RENDERING}</serviceType>"
                "<controlURL>/smp_8_</controlURL></service>",
            )
        return httpx.Response(200, text=f"<serviceType>{samsung_legacy.AGENT}</serviceType>")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await samsung_legacy.find_service(client, "192.0.2.21", RENDERING)

    assert asyncio.run(run()) == "/smp_8_"

# SPDX-License-Identifier: GPL-3.0-or-later
"""Films on a Chromecast, through Jellyfin's own receiver app."""

import asyncio

import httpx

from tv_mcp.driver import TvInfo
from tv_mcp.drivers.chromecast import JELLYFIN_RECEIVER, Chromecast, control_message, play_message
from tv_mcp.media import CastLogin, MediaItem, Session
from tv_mcp.service import TvService
from tv_mcp.settings import Settings, Tv

EXAMPLE_TOKEN = "user-token"  # noqa: S105 - an example
LOGIN = CastLogin(
    server="http://192.0.2.5:8096",
    token=EXAMPLE_TOKEN,
    user_id="u1",
    server_id="srv",
    version="12.4.0",
)
GARAGE = Tv(key="garage", names=(), location="garage", address="192.0.2.20", driver="chromecast")
HOPE = MediaItem(id="a1", title="A New Hope", year=1977, kind="Movie", position=72 * 60)


def test_the_play_message_carries_the_item_where_to_start_and_the_users_login():
    message = play_message(LOGIN, HOPE, 72 * 60)
    assert message["command"] == "PlayNow"
    # Without its type and media type the receiver loads the item but never plays it (2026-11-09).
    assert message["options"]["items"][0] == {
        "Id": "a1",
        "ServerId": "srv",
        "Name": "A New Hope",
        "Type": "Movie",
        "MediaType": "Video",
        "IsFolder": False,
    }
    assert message["options"]["startPositionTicks"] == 72 * 60 * 10_000_000
    assert (message["accessToken"], message["userId"], message["serverAddress"]) == (
        "user-token",
        "u1",
        "http://192.0.2.5:8096",
    )


def test_pause_resume_and_stop_are_the_receivers_own_commands():
    assert [control_message(LOGIN, c)["command"] for c in ("pause", "resume", "stop")] == [
        "Pause",
        "Unpause",
        "Stop",
    ]


async def _login(address):
    return LOGIN


def _driver(sent, login=_login, handler=None):
    async def send(address, message):
        sent.append((address, message["command"]))
        return True

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler or (lambda r: httpx.Response(404))))
    return Chromecast(client, login=login, send=send)


def test_a_film_is_cast_to_the_chromecast_at_the_tvs_address():
    sent = []
    assert asyncio.run(_driver(sent).cast("192.0.2.20", HOPE, 0)) is True
    assert sent == [("192.0.2.20", "PlayNow")]
    assert JELLYFIN_RECEIVER == "F007D354"


def test_without_a_user_login_nothing_is_cast():
    async def none(address):
        return None

    sent = []
    assert asyncio.run(_driver(sent, login=none).cast("192.0.2.20", HOPE, 0)) is False
    assert sent == []


def test_the_chromecast_says_what_it_is_from_its_own_page():
    page = {"name": "Garage", "device_info": {"model_name": "Chromecast", "manufacturer": "Google Inc."}}

    def handler(request):
        assert request.url.port == 8008
        return httpx.Response(200, json=page)

    info = asyncio.run(_driver([], handler=handler).read_info("192.0.2.20"))
    assert (info.name, info.brand, info.product_line, info.power) == (
        "Garage",
        "Google",
        "Chromecast",
        "unknown",
    )


class CastDriver:
    key = "chromecast"
    ssdp_target = "x"

    def __init__(self):
        self.casts, self.controls = [], []

    def recognises(self, announcement):
        return False

    async def read_info(self, address):
        return None

    async def cast(self, address, item, start):
        self.casts.append((address, item.id, start))
        return True

    async def cast_control(self, address, command):
        self.controls.append((address, command))
        return True


class Library:
    async def search(self, term):
        return [HOPE]

    async def sessions(self):
        return [Session(id="c1", address="192.0.2.20", client="Chromecast", controllable=False)]


async def _no_listen(recognises, target):
    return []


def _service(driver, *tvs):
    return TvService(
        Settings(tvs=tvs or (GARAGE,)), drivers={driver.key: driver}, listen=_no_listen, library=Library()
    )


def test_a_film_on_a_chromecast_tv_is_cast_from_where_it_stopped():
    driver = CastDriver()
    answer = asyncio.run(_service(driver).play("A New Hope", "garage"))
    assert answer["outcome"] == "playing", answer
    assert driver.casts == [("192.0.2.20", "a1", 72 * 60)]
    assert "garage from 1 h 12 min" in answer["say"]


def test_pause_on_a_chromecast_tv_goes_to_the_chromecast():
    driver = CastDriver()
    answer = asyncio.run(_service(driver).control("pause", "garage"))
    assert answer["outcome"] == "done", answer
    assert driver.controls == [("192.0.2.20", "pause")]


def test_a_hands_off_chromecast_tv_is_never_cast_to():
    driver = CastDriver()
    left = Tv(
        key="garage", names=(), location="garage", address="192.0.2.20", driver="chromecast", hands_off=True
    )
    answer = asyncio.run(_service(driver, left).play("A New Hope", "garage"))
    assert answer["outcome"] == "refused"
    assert driver.casts == []


def test_a_chromecast_that_answers_is_reported_reachable_since_its_tv_cannot_be_read():
    class Answering(CastDriver):
        async def read_info(self, address):
            return TvInfo(
                name="Garage", model="Chromecast", year=None, platform="Google Cast", power="unknown"
            )

    [report] = asyncio.run(_service(Answering()).status("garage"))
    assert report["state"] == "reachable"


def test_the_receivers_report_says_which_item_it_is_playing():
    from tv_mcp.drivers.chromecast import playing_item  # noqa: PLC0415

    started = {"data": {"ItemId": "a1", "PlayState": {"CanSeek": True, "PositionTicks": 0}}}
    assert playing_item(started) == "a1"
    # Loaded but not started: it names the item but cannot seek in it yet.
    assert playing_item({"data": {"ItemId": "a1", "PlayState": {"CanSeek": False}}}) is None
    assert playing_item({"data": {"ItemId": "", "PlayState": {}}}) is None
    assert playing_item({"type": "something else"}) is None


def test_a_cast_that_does_not_start_is_reported_as_not_playing():
    async def send(address, message):
        return False  # the receiver never said it was playing

    driver = Chromecast(httpx.AsyncClient(), login=_login, send=send)
    assert asyncio.run(driver.cast("192.0.2.20", HOPE, 0)) is False

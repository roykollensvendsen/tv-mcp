# SPDX-License-Identifier: GPL-3.0-or-later
"""Closing an app on a TV, such as Jellyfin once the film is over."""

import asyncio
import types

import httpx

from tv_mcp.drivers.samsung_tizen import SamsungTizen
from tv_mcp.server import build_server
from tv_mcp.service import TvService
from tv_mcp.settings import Settings, Tv
from tv_mcp.simulator import simulated_service

LIVING = Tv(key="living-room", names=("the living room", "The Frame"), address="192.0.2.10")
UPSTAIRS = Tv(key="upstairs", names=("upstairs",), address="192.0.2.11", hands_off=True)


class FakeDriver:
    key = "samsung-tizen"
    ssdp_target = "x"
    apps = types.MappingProxyType({"jellyfin": "AprZAARz4r.Jellyfin", "youtube": "111299001912"})

    def __init__(self):
        self.closed = []

    def recognises(self, announcement):
        return False

    async def read_info(self, address):
        return None

    async def close_app(self, address, app_id):
        self.closed.append((address, app_id))
        return True


async def _no_listen(recognises, target):
    return []


def _service(driver, *tvs):
    return TvService(Settings(tvs=tvs or (LIVING,)), drivers={driver.key: driver}, listen=_no_listen)


def test_closing_jellyfin_on_the_named_tv():
    driver = FakeDriver()
    answer = asyncio.run(_service(driver).close_app("Jellyfin", "The Frame"))
    assert answer["outcome"] == "done", answer
    assert driver.closed == [("192.0.2.10", "AprZAARz4r.Jellyfin")]


def test_an_app_the_driver_does_not_know_is_refused_naming_the_ones_it_does():
    driver = FakeDriver()
    answer = asyncio.run(_service(driver).close_app("Minesweeper", "The Frame"))
    assert answer["outcome"] == "refused"
    assert "Jellyfin" in answer["say"]
    assert driver.closed == []


def test_closing_never_reaches_a_hands_off_tv():
    driver = FakeDriver()
    answer = asyncio.run(_service(driver, LIVING, UPSTAIRS).close_app("Jellyfin", "upstairs"))
    assert answer["outcome"] == "refused"
    assert driver.closed == []


def test_the_samsung_driver_closes_an_app_through_the_tvs_own_api():
    seen = []

    def handler(request):
        seen.append((request.method, str(request.url)))
        return httpx.Response(200, json={"running": True} if request.method == "GET" else True)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await SamsungTizen(client, tls_client=client).close_app(
                "192.0.2.10", "AprZAARz4r.Jellyfin"
            )

    assert asyncio.run(run()) is True
    url = "https://192.0.2.10:8002/api/v2/applications/AprZAARz4r.Jellyfin"
    assert seen == [("GET", url), ("DELETE", url)]


def test_an_app_that_is_not_running_counts_as_closed_without_asking_the_tv_to_close_it():
    # 2026-11-08: The Frame drops the connection when told to close an app that is not running.
    seen = []

    def handler(request):
        seen.append(request.method)
        return httpx.Response(200, json={"running": False})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await SamsungTizen(client, tls_client=client).close_app(
                "192.0.2.10", "AprZAARz4r.Jellyfin"
            )

    assert asyncio.run(run()) is True
    assert seen == ["GET"]


def test_the_apps_feature_is_off_by_default_and_adds_tv_close_app():
    names = lambda server: {t.name for t in asyncio.run(server.list_tools())}  # noqa: E731
    assert "tv_close_app" not in names(build_server(simulated_service()))
    assert "tv_close_app" in names(build_server(simulated_service(), features=["status", "media", "apps"]))


class OpeningDriver(FakeDriver):
    def __init__(self):
        super().__init__()
        self.opened = []

    async def open_app(self, address, app_id):
        self.opened.append((address, app_id))
        return True


def test_opening_an_app_on_the_named_tv():
    driver = OpeningDriver()
    answer = asyncio.run(_service(driver).open_app("YouTube", "The Frame"))
    assert answer["outcome"] == "done", answer
    assert driver.opened == [("192.0.2.10", "111299001912")]


def test_a_hands_off_tv_never_has_an_app_opened_or_closed():
    driver = OpeningDriver()
    answer = asyncio.run(_service(driver, LIVING, UPSTAIRS).open_app("Jellyfin", "upstairs"))
    assert answer["outcome"] == "refused"
    assert driver.opened == []
    closed = asyncio.run(_service(driver, LIVING, UPSTAIRS).close_app("Jellyfin", "upstairs"))
    assert "left alone" in closed["say"]
    assert driver.closed == []


def test_an_app_that_cannot_be_opened_is_refused_naming_the_ones_that_can():
    driver = OpeningDriver()
    answer = asyncio.run(_service(driver).open_app("Minesweeper", "The Frame"))
    assert answer["outcome"] == "refused"
    assert "Youtube" in answer["say"] or "YouTube" in answer["say"]
    assert driver.opened == []


def test_the_samsung_driver_opens_an_app_through_the_tvs_own_api():
    seen = []

    def handler(request):
        seen.append((request.method, str(request.url)))
        return httpx.Response(200, json=True)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await SamsungTizen(client, tls_client=client).open_app("192.0.2.10", "111299001912")

    assert asyncio.run(run()) is True
    assert seen == [("POST", "https://192.0.2.10:8002/api/v2/applications/111299001912")]


def test_the_apps_feature_adds_tv_open_app():
    names = {t.name for t in asyncio.run(build_server(simulated_service(), features=["apps"]).list_tools())}
    assert names == {"tv_open_app", "tv_close_app"}

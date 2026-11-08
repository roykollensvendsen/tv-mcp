# SPDX-License-Identifier: GPL-3.0-or-later
"""Reading a Samsung TV's own information page."""

import asyncio

import httpx

from tv_mcp.drivers.samsung_tizen import SamsungTizen, fetch_info, parse_info

FRAME_2022 = {
    "device": {
        "name": "Samsung The Frame 55",
        "modelName": "QE55LS03BAUXXC",
        "model": "22_PONTUSM_FTV",
        "OS": "Tizen",
        "PowerState": "on",
        "FrameTVSupport": "true",
        "developerMode": "1",
        "TokenAuthSupport": "true",
        "networkType": "wireless",
    },
    "version": "2.0.25",
}


def test_model_year_and_tizen_version_come_from_the_model_code():
    info = parse_info(FRAME_2022)
    assert info.model == "QE55LS03BAUXXC"
    assert info.year == 2022
    assert info.platform == "Tizen 6.5"
    assert info.art_mode_capable
    assert info.developer_mode
    assert info.power == "on"


def test_an_unknown_model_code_gives_no_year_rather_than_a_guess():
    payload = {"device": {"model": "PONTUS", "modelName": "X"}}
    info = parse_info(payload)
    assert info.year is None
    assert info.platform is None
    assert info.power == "unknown"


def test_a_year_with_no_known_tizen_version_still_gives_the_year():
    info = parse_info({"device": {"model": "31_FUTURE", "modelName": "X"}})
    assert info.year == 2031
    assert info.platform is None


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_the_information_page_is_read_from_port_8001():
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, json=FRAME_2022)

    async def run():
        async with _client(handler) as client:
            return await fetch_info("192.0.2.10", client)

    assert asyncio.run(run()) == FRAME_2022
    assert seen == ["http://192.0.2.10:8001/api/v2/"]


def test_a_tv_that_does_not_answer_gives_none():
    def handler(request):
        message = "refused"
        raise httpx.ConnectError(message, request=request)

    async def run():
        async with _client(handler) as client:
            return await fetch_info("192.0.2.10", client)

    assert asyncio.run(run()) is None


def test_a_page_that_is_not_json_gives_none():
    async def run():
        async with _client(lambda _r: httpx.Response(200, text="<html>")) as client:
            return await fetch_info("192.0.2.10", client)

    assert asyncio.run(run()) is None


def test_the_driver_recognises_only_samsung_tvs():
    driver = SamsungTizen(httpx.AsyncClient())
    tv = (
        b"HTTP/1.1 200 OK\r\nSERVER: Samsung-Linux/4.1, UPnP/1.0\r\n"
        b"ST: urn:samsung.com:device:RemoteControlReceiver:1\r\n"
    )
    assert driver.recognises(tv)
    assert not driver.recognises(b"HTTP/1.1 200 OK\r\nSERVER: Linux UPnP/1.0 SomePrinter\r\n")


def test_the_driver_reads_info_in_the_cores_words():
    async def run():
        async with _client(lambda _r: httpx.Response(200, json=FRAME_2022)) as client:
            return await SamsungTizen(client).read_info("192.0.2.10")

    assert asyncio.run(run()).model == "QE55LS03BAUXXC"

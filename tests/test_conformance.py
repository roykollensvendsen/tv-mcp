# SPDX-License-Identifier: GPL-3.0-or-later
"""The conformance kit, run on the drivers here and shown to catch a driver that breaks the rules."""

import asyncio

import httpx

from tv_mcp.conformance import check
from tv_mcp.driver import TvInfo
from tv_mcp.drivers.samsung_tizen import SamsungTizen
from tv_mcp.simulator import FRAME_ADDRESS, SimulatedTv

ANSWERS, SILENT = "192.0.2.10", "192.0.2.99"
PAGE = {"device": {"PowerState": "on", "modelName": "QE55LS03BAUXXC", "model": "22_PONTUSM_FTV"}}


def _samsung_check():
    def handler(request):
        if request.url.host == SILENT:
            message = "nothing there"
            raise httpx.ConnectError(message, request=request)
        return httpx.Response(200, json=PAGE)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await check(SamsungTizen(client, tls_client=client), answers=ANSWERS, silent=SILENT)

    return asyncio.run(run())


def test_the_samsung_driver_conforms():
    assert _samsung_check() == []


def test_the_simulated_tv_conforms():
    assert asyncio.run(check(SimulatedTv(), answers=FRAME_ADDRESS)) == []


class Broken:
    key = "Broken Driver"
    ssdp_target = ""

    def recognises(self, announcement):
        return "yes"

    async def read_info(self, address):
        if address == SILENT:
            raise OSError
        return TvInfo(name=None, model=None, year=None, platform=None, power="sleepy")

    async def switch(self, tv, *, on):
        return True


def test_the_kit_names_each_broken_rule():
    problems = asyncio.run(check(Broken(), answers=ANSWERS, silent=SILENT))
    text = "\n".join(problems)
    for expected in ("key", "ssdp_target", "recognises", "sleepy", "raised OSError", "no address"):
        assert expected in text, (expected, problems)

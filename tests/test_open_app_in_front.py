# SPDX-License-Identifier: GPL-3.0-or-later
"""Opening an app says it is open only once the TV shows it in front.

On 2026-11-11 The Frame answered "done" to opening NRK TV while Netflix was
still in front; NRK came to the front a couple of seconds later. So the TV is
watched, for a few seconds, until the app is in front, and the voice is told
plainly when it is not there yet.
"""

import asyncio
import types

import httpx

from tv_mcp.drivers.samsung_tizen import SamsungTizen
from tv_mcp.service import OPEN_IN_FRONT_WITHIN, TvService
from tv_mcp.settings import Settings, Tv

LIVING = Tv(key="living-room", names=("The Frame",), address="192.0.2.10")
NRK = "3202012022410"


class Clock:
    """Time that moves only when the service sleeps."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds


class SlowTv:
    """A TV that brings an opened app to the front `after` seconds, or never."""

    key = "samsung-tizen"
    apps = types.MappingProxyType({"nrk": NRK})

    def __init__(self, clock, after):
        self.clock, self.after, self.opened, self.asked = clock, after, None, 0

    async def read_info(self, address):
        return None

    async def open_app(self, address, app_id):
        self.opened = self.clock()
        return True

    async def in_front(self, address, app_id):
        self.asked += 1
        return self.after is not None and self.clock() - self.opened >= self.after


async def _no_listen(recognises, target):
    return []


def _open(tv):
    service = TvService(
        Settings(tvs=(LIVING,)),
        drivers={tv.key: tv},
        listen=_no_listen,
        sleep=tv.clock.sleep,
        clock=tv.clock,
    )
    return asyncio.run(service.open_app("NRK TV", "The Frame"))


def test_an_app_is_said_open_only_once_it_is_in_front():
    clock = Clock()
    tv = SlowTv(clock, after=3)
    answer = _open(tv)
    assert answer["outcome"] == "done", answer
    assert answer["say"] == "Opened NRK TV on The Frame."
    assert clock.now == 3


def test_an_app_not_in_front_in_time_is_said_plainly():
    clock = Clock()
    tv = SlowTv(clock, after=None)
    answer = _open(tv)
    assert answer["outcome"] == "unverified", answer
    assert answer["say"].startswith("I asked The Frame to open NRK TV, but it is not in front yet.")
    assert clock.now <= OPEN_IN_FRONT_WITHIN


def test_an_app_already_in_front_is_answered_at_once():
    clock = Clock()
    answer = _open(SlowTv(clock, after=0))
    assert answer["outcome"] == "done"
    assert clock.now == 0


def test_a_tv_that_cannot_say_what_is_in_front_is_answered_as_before():
    clock = Clock()
    tv = SlowTv(clock, after=None)

    async def unknown(address, app_id):
        return None

    tv.in_front = unknown
    answer = _open(tv)
    assert answer["outcome"] == "done"
    assert clock.now == 0


def test_the_samsung_driver_reads_whether_an_app_is_in_front():
    def handler(request):
        visible = {NRK: True, "3201907018807": False}.get(request.url.path.rsplit("/", 1)[-1])
        if visible is None:
            return httpx.Response(404)
        return httpx.Response(200, json={"running": True, "visible": visible})

    async def run(app_id):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await SamsungTizen(client, tls_client=client).in_front("192.0.2.10", app_id)

    assert asyncio.run(run(NRK)) is True
    assert asyncio.run(run("3201907018807")) is False
    assert asyncio.run(run("unknown")) is None

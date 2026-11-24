# SPDX-License-Identifier: GPL-3.0-or-later
"""Status for every TV answers in time, even when one TV is slow or never answers."""

import asyncio
from dataclasses import replace

from bounded import WITHIN

from tv_mcp import server
from tv_mcp import service as service_module
from tv_mcp.drivers.samsung_tizen import parse_info
from tv_mcp.service import TvService
from tv_mcp.settings import Settings, Tv
from tv_mcp.tools import say

ON = {"device": {"name": "Samsung", "modelName": "QE55LS03BAUXXC", "PowerState": "on"}}
DOWN = Tv(key="down", names=("downstairs",), address="192.0.2.10")
UP = Tv(key="up", names=("upstairs",), address="192.0.2.11")
GARAGE = Tv(key="garage", names=("the garage",), address="192.0.2.12")
#: The test's own bound on a status that should answer at once: far above the TVs' bound, far
#: below a hang. A status that waits for a TV that never answers fails here, not in five minutes.
SOON = 5.0


class Network:
    """A driver whose TVs answer on cue: `meet` answer only once both have been asked, `silent` never."""

    key = "samsung-tizen"
    ssdp_target = "urn:example:tv"

    def __init__(self, *, meet=(), silent=()):
        self.meet, self.silent = set(meet), set(silent)
        self.asked = {address: asyncio.Event() for address in self.meet}

    def recognises(self, announcement):
        return True

    async def read_info(self, address):
        if address in self.silent:
            await asyncio.Event().wait()  # never set: this TV never answers
        if address in self.meet:
            self.asked[address].set()
            for other in self.meet - {address}:
                await self.asked[other].wait()  # asked one after the other, this waits for ever
        return parse_info(ON)

    async def listen(self, recognises, target):
        return []


def _status(network, *tvs, name=None):
    service = TvService(Settings(tvs=tvs), drivers={network.key: network}, listen=network.listen)
    return asyncio.run(asyncio.wait_for(service.status(name), SOON))


def test_each_tv_is_asked_side_by_side_so_a_slow_one_holds_up_none(monkeypatch):
    monkeypatch.setattr(service_module, "TV_ANSWER_WITHIN", 1.0)
    # Each of the two answers only once the other has been asked: one at a time, neither would.
    reports = _status(Network(meet={"192.0.2.10", "192.0.2.11"}), DOWN, UP)
    assert [(r["tv"], r["state"]) for r in reports] == [("downstairs", "on"), ("upstairs", "on")]


def test_a_tv_that_does_not_answer_in_time_is_said_as_that(monkeypatch):
    monkeypatch.setattr(service_module, "TV_ANSWER_WITHIN", 0.05)
    reports = _status(Network(silent={"192.0.2.12"}), DOWN, GARAGE, UP)
    assert [(r["tv"], r["state"]) for r in reports] == [
        ("downstairs", "on"),
        ("the garage", "did not answer in time"),
        ("upstairs", "on"),
    ]
    assert reports[1]["say"] == (
        "The garage did not answer in time. Ask about the garage on its own in a moment."
    )


def test_a_status_for_every_tv_is_spoken_with_the_slow_one_named(monkeypatch):
    monkeypatch.setattr(service_module, "TV_ANSWER_WITHIN", 0.05)
    network = Network(silent={"192.0.2.12"})
    service = TvService(Settings(tvs=(DOWN, GARAGE)), drivers={network.key: network}, listen=network.listen)
    built = server.build_server(service)

    async def ask():
        return await asyncio.wait_for(built.call_tool("tv_status", {}), WITHIN)

    answer = asyncio.run(ask()).structured_content
    assert answer["say"] == (
        "Downstairs is on. The garage did not answer in time. Ask about the garage on its own in a moment."
    )


def test_every_tv_is_asked_inside_the_voice_time():
    # The TVs are asked side by side, each within this, so the whole status answers before the
    # tool's own deadline says it is still working, with room to put the sentences together.
    assert service_module.TV_ANSWER_WITHIN <= server.ANSWER_WITHIN - 2


class SilentCast:
    """A device in front of the TV that never answers, so the TV's own read is done but not the rest."""

    key = "silent-cast"
    ssdp_target = "urn:example:cast"

    def recognises(self, announcement):
        return True

    async def read_info(self, address):
        await asyncio.Event().wait()  # never set: the rest of the report never comes

    async def listen(self, recognises, target):
        return []


def test_a_tv_slow_to_finish_is_said_with_what_was_read_so_far(monkeypatch):
    monkeypatch.setattr(service_module, "TV_ANSWER_WITHIN", 0.05)
    network = Network()
    slow = replace(GARAGE, power_driver=SilentCast.key, power_address="192.0.2.13")
    drivers = {network.key: network, SilentCast.key: SilentCast()}
    service = TvService(Settings(tvs=(slow,)), drivers=drivers, listen=network.listen)
    reports = asyncio.run(asyncio.wait_for(service.status(None), SOON))
    assert (reports[0]["state"], reports[0]["partial"]) == ("on", True)
    assert "screen" not in reports[0]
    assert say.tv_lines(reports) == (
        "The garage is on. I could not read the rest in time. Ask about the garage on its own in a moment."
    )

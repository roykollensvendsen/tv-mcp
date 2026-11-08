# SPDX-License-Identifier: GPL-3.0-or-later
"""Status and discovery, against TVs that are only data."""

import asyncio

from tv_mcp.drivers.samsung_tizen import parse_info
from tv_mcp.service import TvService
from tv_mcp.settings import Settings, Tv

FRAME = {
    "device": {
        "name": "Samsung The Frame 55",
        "modelName": "QE55LS03BAUXXC",
        "model": "22_PONTUSM_FTV",
        "PowerState": "on",
        "FrameTVSupport": "true",
    }
}
OTHER = {
    "device": {
        "name": "Samsung Q68CA 55",
        "modelName": "TQ55Q68CAUXXC",
        "model": "23_NIKEL_UHD_OS80",
        "PowerState": "on",
        "FrameTVSupport": "false",
    }
}

LIVING = Tv(key="living-room", names=("the living room", "The Frame"), address="192.0.2.10")
UPSTAIRS = Tv(key="upstairs", names=("upstairs",), address="192.0.2.11", hands_off=True)


class FakeNetwork:
    """A driver that answers for the addresses it is given, and records every one asked."""

    key = "samsung-tizen"
    ssdp_target = "urn:example:tv"

    def __init__(self, pages, announced=()):
        self.pages, self.announced, self.asked, self.searched = pages, list(announced), [], []

    def recognises(self, announcement):
        return True

    async def read_info(self, address):
        self.asked.append(address)
        page = self.pages.get(address)
        return parse_info(page) if page else None

    async def listen(self, recognises, target):
        self.searched.append(target is not None)
        return list(self.announced)


def _service(network, *tvs):
    return TvService(Settings(tvs=tvs), drivers={network.key: network}, listen=network.listen)


def test_status_says_whether_a_named_tv_is_on():
    network = FakeNetwork({"192.0.2.10": FRAME})
    [report] = asyncio.run(_service(network, LIVING).status("The Frame"))
    assert report["tv"] == "the living room"
    assert report["state"] == "on"
    assert report["model"] == "QE55LS03BAUXXC"


def test_a_tv_that_does_not_answer_is_reported_off_or_unreachable():
    [report] = asyncio.run(_service(FakeNetwork({}), LIVING).status(None))
    assert report["state"] == "off or not reachable"


def test_a_frame_in_standby_may_be_showing_art():
    page = {"device": {**FRAME["device"], "PowerState": "standby"}}
    [report] = asyncio.run(_service(FakeNetwork({"192.0.2.10": page}), LIVING).status(None))
    assert report["state"] == "standby or art mode"


def test_a_hands_off_tv_is_never_contacted():
    network = FakeNetwork({"192.0.2.10": FRAME, "192.0.2.11": OTHER}, announced=["192.0.2.11"])
    service = _service(network, LIVING, UPSTAIRS)
    reports = asyncio.run(service.status(None))
    found = asyncio.run(service.discover(full=False))
    assert "192.0.2.11" not in network.asked
    assert {r["tv"]: r["state"] for r in reports}["upstairs"] == "left alone"
    assert [t["state"] for t in found["tvs"] if t.get("tv") == "upstairs"] == ["left alone"]


def test_status_of_an_unknown_name_is_a_refusal_naming_the_tvs():
    [report] = asyncio.run(_service(FakeNetwork({}), LIVING).status("the kitchen"))
    assert report["state"] == "refused"
    assert "the living room" in report["say"]


def test_discovery_reports_model_year_and_tizen_for_each_tv_it_finds():
    network = FakeNetwork({"192.0.2.10": FRAME, "192.0.2.20": OTHER}, announced=["192.0.2.20"])
    found = asyncio.run(_service(network, LIVING).discover(full=False))
    by_model = {t["model"]: t for t in found["tvs"]}
    assert by_model["QE55LS03BAUXXC"]["tv"] == "the living room"
    assert by_model["QE55LS03BAUXXC"]["platform"] == "Tizen 6.5"
    assert by_model["TQ55Q68CAUXXC"]["tv"] is None  # found, but not in the settings yet
    assert by_model["TQ55Q68CAUXXC"]["year"] == 2023


def test_discovery_only_listens_unless_a_full_search_is_asked_for():
    network = FakeNetwork({})
    asyncio.run(_service(network).discover(full=False))
    asyncio.run(_service(network).discover(full=True))
    assert network.searched == [False, True]


def test_an_address_announced_twice_is_read_once():
    network = FakeNetwork({"192.0.2.10": FRAME}, announced=["192.0.2.10", "192.0.2.10"])
    asyncio.run(_service(network, LIVING).discover(full=False))
    assert network.asked == ["192.0.2.10"]

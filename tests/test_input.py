# SPDX-License-Identifier: GPL-3.0-or-later
"""Changing which input a TV shows, such as HDMI 1, by voice."""

import asyncio
from dataclasses import replace

from tv_mcp.driver import INPUTS, InputSent, TvInfo
from tv_mcp.drivers.samsung_legacy import SamsungLegacy, parse_current, parse_sources
from tv_mcp.service import TvService
from tv_mcp.settings import Settings, Tv

LIVING = Tv(key="living-room", names=("the living room",), address="192.0.2.10")
GARAGE = Tv(
    key="garage",
    names=("the garage",),
    address="192.0.2.20",
    driver="chromecast",
    power_driver="samsung-legacy",
    power_address="192.0.2.21",
)
UPSTAIRS = Tv(key="upstairs", names=("upstairs",), address="192.0.2.11", hands_off=True)


class InputTv:
    key = "samsung-tizen"
    ssdp_target = "x"

    def __init__(self, *, answers=True, power="on"):
        self.answers, self.power, self.shown = answers, power, []

    def recognises(self, announcement):
        return False

    async def read_info(self, address):
        if self.power is None:
            return None
        return TvInfo(name=None, model=None, year=None, platform=None, power=self.power)

    async def show_input(self, tv, source):
        self.shown.append((tv.address, source))
        return InputSent(said=INPUTS[source], shown=self.reads) if self.answers else None

    reads = None


class Cast:
    key = "chromecast"
    ssdp_target = "y"

    def recognises(self, announcement):
        return False

    async def read_info(self, address):
        return None


def _service(*drivers, tvs=(LIVING,)):
    async def no_listen(recognises, target):
        return []

    return TvService(Settings(tvs=tvs), drivers={d.key: d for d in drivers}, listen=no_listen)


def _show(service, source, tv):
    return asyncio.run(service.show_input(source, tv))


def test_an_input_said_aloud_is_shown_on_the_named_tv():
    driver = InputTv()
    answer = _show(_service(driver), "HDMI 2", "the living room")
    assert driver.shown == [("192.0.2.10", "hdmi2")]
    assert answer["outcome"] == "done"
    assert "HDMI 2" in answer["say"]


def test_the_answer_says_the_key_was_sent_not_that_the_tv_shows_it():
    # 2026-11-10: the garage TV took KEY_HDMI1 without a word and did not change.
    answer = _show(_service(InputTv()), "HDMI 1", "the living room")
    assert "shows" not in answer["say"]
    assert "sent" in answer["say"].casefold()


def test_an_input_there_is_no_key_for_is_refused_naming_the_ones_there_are():
    driver = InputTv()
    answer = _show(_service(driver), "scart", "the living room")
    assert driver.shown == []
    assert answer["outcome"] == "refused"
    assert "HDMI 1" in answer["say"]


def test_a_tv_whose_own_device_cannot_change_input_is_changed_through_its_power_driver():
    legacy = InputTv()
    legacy.key = "samsung-legacy"
    answer = _show(_service(Cast(), legacy, tvs=(GARAGE,)), "hdmi1", "the garage")
    assert legacy.shown == [("192.0.2.21", "hdmi1")]
    assert answer["outcome"] == "done"


def test_a_tv_that_does_not_answer_is_said_plainly():
    answer = _show(_service(InputTv(answers=False)), "hdmi1", "the living room")
    assert answer["outcome"] == "refused"
    assert "on" in answer["say"]


def test_a_tv_with_no_way_to_change_input_is_refused():
    answer = _show(
        _service(Cast(), tvs=(replace(GARAGE, power_driver=None, power_address=None),)), "hdmi1", "the garage"
    )
    assert answer["outcome"] == "refused"


def test_an_input_is_changed_only_while_the_screen_is_on():
    # A remote key sent to a TV in standby may wake it, and a TV must never come
    # on by itself at night. So a TV that is off, or cannot say, is not sent a key.
    for power in ("standby", "unknown", None):
        driver = InputTv(power=power)
        answer = _show(_service(driver), "hdmi1", "the living room")
        assert driver.shown == [], power
        assert answer["outcome"] == "refused", power
        assert "on" in answer["say"], power


def test_a_tv_shown_through_another_device_is_asked_by_its_power_driver_whether_it_is_on():
    legacy = InputTv(power="standby")
    legacy.key = "samsung-legacy"
    answer = _show(_service(Cast(), legacy, tvs=(GARAGE,)), "hdmi1", "the garage")
    assert legacy.shown == []
    assert answer["outcome"] == "refused"


def test_a_hands_off_tv_is_never_changed():
    driver = InputTv()
    answer = _show(_service(driver, tvs=(LIVING, UPSTAIRS)), "hdmi1", "upstairs")
    assert driver.shown == []
    assert answer["outcome"] == "refused"


def test_the_older_samsung_presses_the_inputs_own_key_on_its_remote_port():
    pressed = []

    async def press(address, key, wait):
        pressed.append((address, key))
        return True

    driver = SamsungLegacy(press=press, agent=no_agent)
    assert asyncio.run(driver.show_input(GARAGE, "tv")) == InputSent(said="the aerial")
    assert pressed == [("192.0.2.20", "KEY_TV")]


def test_the_older_samsung_steps_to_the_next_hdmi_input_since_it_cannot_pick_one_by_number():
    # 2026-11-10, the garage ES6715: KEY_HDMI1 did nothing; KEY_HDMI went from the
    # aerial to HDMI 1, and then stepped between the HDMI inputs with something plugged in.
    pressed = []

    async def press(address, key, wait):
        pressed.append(key)
        return True

    sent = asyncio.run(SamsungLegacy(press=press, agent=no_agent).show_input(GARAGE, "hdmi2"))
    assert pressed == ["KEY_HDMI"]
    assert sent == InputSent(said="the next HDMI input")


async def no_agent(address, action, arguments):
    return None


# What the garage ES6715's MainTVAgent2 answered on 2026-11-10, cut to the parts read.
SOURCES = (
    "<Result>OK</Result><SourceList>&lt;?xml version=&quot;1.0&quot;?&gt;&lt;SourceList&gt;"
    "&lt;CurrentSourceType&gt;HDMI1/DVI&lt;/CurrentSourceType&gt;&lt;ID&gt;67&lt;/ID&gt;"
    "&lt;Source&gt;&lt;SourceType&gt;TV&lt;/SourceType&gt;&lt;ID&gt;0&lt;/ID&gt;&lt;Connected&gt;Yes&lt;/Connected&gt;&lt;/Source&gt;"
    "&lt;Source&gt;&lt;SourceType&gt;HDMI1/DVI&lt;/SourceType&gt;&lt;ID&gt;67&lt;/ID&gt;&lt;Connected&gt;Yes&lt;/Connected&gt;&lt;/Source&gt;"
    "&lt;Source&gt;&lt;SourceType&gt;HDMI3&lt;/SourceType&gt;&lt;ID&gt;69&lt;/ID&gt;&lt;Connected&gt;Yes&lt;/Connected&gt;&lt;/Source&gt;"
    "&lt;Source&gt;&lt;SourceType&gt;HDMI2&lt;/SourceType&gt;&lt;ID&gt;68&lt;/ID&gt;&lt;Connected&gt;No&lt;/Connected&gt;&lt;/Source&gt;"
    "&lt;/SourceList&gt;</SourceList>"
)


def _current(source):
    return f"<Result>OK</Result><CurrentExternalSource>{source}</CurrentExternalSource><ID>69</ID>"


def test_the_older_samsungs_inputs_are_read_with_their_ids_and_whether_anything_is_plugged_in():
    assert parse_sources(SOURCES) == {
        "tv": ("TV", "0"),
        "hdmi1": ("HDMI1/DVI", "67"),
        "hdmi3": ("HDMI3", "69"),
    }
    assert parse_current(_current("HDMI1/DVI")) == "hdmi1"
    assert parse_current(_current("TV")) == "tv"
    assert parse_current("<Result>NOTOK</Result>") is None


class Agent:
    def __init__(self, *, takes=True):
        self.takes, self.calls, self.now = takes, [], "HDMI1/DVI"

    async def __call__(self, address, action, arguments):
        self.calls.append((action, arguments))
        if action == "GetSourceList":
            return SOURCES
        if action == "SetMainTVSource":
            if self.takes:
                self.now = "HDMI3"
            return "<Result>OK</Result>"
        return _current(self.now)


async def _no_wait(seconds):
    return None


def test_the_older_samsung_picks_the_input_by_its_id_and_reads_back_what_it_shows():
    agent, pressed = Agent(), []

    async def press(address, key, wait):
        pressed.append(key)
        return True

    driver = SamsungLegacy(press=press, agent=agent, sleep=_no_wait)
    assert asyncio.run(driver.show_input(GARAGE, "hdmi3")) == InputSent(said="HDMI 3", shown="HDMI 3")
    assert ("SetMainTVSource", "<Source>HDMI3</Source><ID>69</ID><UiID>-1</UiID>") in agent.calls
    assert pressed == []


def test_the_older_samsung_says_what_it_still_shows_when_the_input_did_not_take():
    driver = SamsungLegacy(agent=Agent(takes=False), sleep=_no_wait)
    assert asyncio.run(driver.show_input(GARAGE, "hdmi3")) == InputSent(said="HDMI 3", shown="HDMI 1")


def test_an_input_with_nothing_plugged_in_is_not_sent_to():
    agent = Agent()
    sent = asyncio.run(SamsungLegacy(agent=agent, sleep=_no_wait).show_input(GARAGE, "hdmi2"))
    assert sent == InputSent(said="HDMI 2", shown="HDMI 1", unplugged=True)
    assert all(action != "SetMainTVSource" for action, _ in agent.calls)


def test_the_answer_says_the_tv_shows_the_input_only_once_it_was_read_back():
    driver = InputTv()
    driver.reads = "HDMI 3"
    assert "shows HDMI 3 now" in _show(_service(driver), "HDMI 3", "the living room")["say"]
    driver.reads = "HDMI 1"
    answer = _show(_service(driver), "HDMI 3", "the living room")
    assert answer["outcome"] == "unverified"
    assert "still shows HDMI 1" in answer["say"]


def test_status_says_which_input_the_tv_shows():
    class Reads(InputTv):
        async def input_shown(self, tv):
            return "HDMI 1"

        async def read_info(self, address):
            return TvInfo(name=None, model=None, year=None, platform=None, power="on")

    [report] = asyncio.run(_service(Reads()).status("the living room"))
    assert report["input"] == "HDMI 1"

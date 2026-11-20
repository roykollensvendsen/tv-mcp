# SPDX-License-Identifier: GPL-3.0-or-later
"""An older Samsung (before Tizen) that has no address, will not list, or lets the remote in."""

import asyncio

from bounded import WITHIN

from tv_mcp.drivers import samsung_legacy
from tv_mcp.drivers.samsung_legacy import SamsungLegacy, answer_of, find_service, key_packet
from tv_mcp.settings import Tv

GARAGE = Tv(key="garage", names=("garage",), address="192.0.2.21")
NO_ADDRESS = Tv(key="garage", names=("garage",))


class Calls:
    """Stand-ins for the TV's remote port and its MainTVAgent2 that record what they are asked."""

    def __init__(self, *, pressed=True, agent=None):
        self.pressed, self.answers, self.asked = pressed, agent or {}, []

    async def press(self, address, key, wait):
        self.asked.append(("press", key))
        return self.pressed

    async def agent(self, address, action, arguments):
        self.asked.append(("agent", action))
        return self.answers.get(action)


def _driver(calls):
    async def no_wait(seconds):
        return None

    return SamsungLegacy(press=calls.press, agent=calls.agent, sleep=no_wait)


def test_an_answer_the_remote_does_not_know_is_unknown():
    assert answer_of(b"\x99\x00") == "unknown"


def test_the_driver_takes_older_samsungs_and_leaves_tizen_ones_to_the_newer_driver():
    driver = SamsungLegacy()
    assert driver.recognises(b"SERVER: SHP, UPnP/1.0, Samsung UPnP SDK/1.0")
    assert not driver.recognises(b"SERVER: Samsung-Linux/4.1, UPnP/1.0")
    assert not driver.recognises(b"SERVER: Linux, UPnP/1.0, LG")


def test_a_tv_with_no_address_is_never_switched_asked_or_changed():
    calls = Calls()
    driver = _driver(calls)

    async def run():
        return (
            await driver.switch(NO_ADDRESS, on=False),
            await driver.input_shown(NO_ADDRESS),
            await driver.inputs_plugged(NO_ADDRESS),
            await driver.show_input(NO_ADDRESS, "hdmi1"),
        )

    assert asyncio.run(run()) == (False, None, None, None)
    assert calls.asked == []


def test_a_tv_that_will_not_list_its_inputs_says_nothing_of_what_is_plugged_in():
    calls = Calls()
    assert asyncio.run(_driver(calls).inputs_plugged(GARAGE)) is None
    assert calls.asked == [("agent", "GetSourceList")]


def test_an_input_key_the_tv_does_not_take_is_no_answer():
    calls = Calls(pressed=False)
    assert asyncio.run(_driver(calls).show_input(GARAGE, "hdmi2")) is None
    assert calls.asked == [("agent", "GetSourceList"), ("press", "KEY_HDMI")]


def test_an_input_the_tv_will_not_switch_to_is_no_answer_and_is_not_read_back():
    listing = (
        "<SourceList><Source><SourceType>HDMI2</SourceType><ID>58</ID>"
        "<Connected>Yes</Connected></Source></SourceList>"
    )
    calls = Calls(agent={"GetSourceList": listing})
    assert asyncio.run(_driver(calls).show_input(GARAGE, "hdmi2")) is None
    assert calls.asked == [("agent", "GetSourceList"), ("agent", "SetMainTVSource")]


def test_a_service_no_page_lists_is_not_found_and_a_page_that_fails_is_skipped():
    pages = []

    class Client:
        async def get(self, url, **_):
            pages.append(url)
            if url.endswith("_1_"):
                message = "the page did not answer"
                raise OSError(message)

            class Page:
                text = "<service>something else</service>"

            return Page()

    assert asyncio.run(find_service(Client(), "192.0.2.21", "RenderingControl")) is None
    assert len(pages) == samsung_legacy.PAGES


async def _tv_that_answers(answer, received):
    """A remote port that answers "may I?" with `answer` once, then keeps what it is sent."""

    async def serve(reader, writer):
        await reader.read(256)
        name = b"iapp.samsung"
        frame = b"\x00" + len(name).to_bytes(2, "little") + name
        writer.write(frame + len(answer).to_bytes(2, "little") + answer)
        await writer.drain()
        received.append(await reader.read(256))
        writer.close()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


def _press(answer):
    received = []

    async def run():
        server, port = await _tv_that_answers(answer, received)
        async with server:
            pressed = await samsung_legacy._press("127.0.0.1", "KEY_MUTE", 0.5, port=port)  # noqa: SLF001 - no TV
            for _ in range(20):
                if received:
                    break
                await asyncio.sleep(0.01)
            return pressed

    return asyncio.run(asyncio.wait_for(run(), WITHIN)), received


def test_a_key_is_sent_once_the_tv_lets_the_remote_in():
    pressed, received = _press(b"\x64\x00\x01\x00")
    assert pressed is True
    assert received == [key_packet("KEY_MUTE")]


def test_a_remote_the_tv_neither_lets_in_nor_refuses_sends_no_key():
    pressed, received = _press(b"\x65\x00")
    assert pressed is False
    assert received in ([], [b""])

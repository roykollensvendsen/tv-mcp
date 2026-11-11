# SPDX-License-Identifier: GPL-3.0-or-later
"""After changing input, the voice says only what the TV confirmed, and never "done" without it.

On 2026-11-11 the Q68CA upstairs took KEY_HDMI1 and KEY_HDMI2 without a word
while YouTube stayed on the screen, and the voice said both were sent. That TV
cannot say which input it shows; it can only say whether the app in front left.
"""

import asyncio

from tv_mcp.driver import INPUTS, InputSent, TvInfo
from tv_mcp.service import TvService
from tv_mcp.settings import Settings, Tv

UPSTAIRS = Tv(key="upstairs", names=("upstairs",), address="192.0.2.11")


class Tizen:
    key = "samsung-tizen"

    def __init__(self, sent):
        self.sent = sent

    async def read_info(self, address):
        return TvInfo(name=None, model=None, year=None, platform=None, power="on")

    async def show_input(self, tv, source):
        return self.sent


async def _no_listen(recognises, target):
    return []


def _show(sent):
    service = TvService(Settings(tvs=(UPSTAIRS,)), drivers={"samsung-tizen": Tizen(sent)}, listen=_no_listen)
    return asyncio.run(service.show_input("HDMI 2", "upstairs"))


def test_an_app_that_left_the_screen_is_said_but_not_the_input():
    answer = _show(InputSent(said=INPUTS["hdmi2"], left="YouTube"))
    assert answer["outcome"] == "unverified"
    assert answer["say"] == (
        "I sent HDMI 2 to upstairs. YouTube left the screen, but this TV cannot say which input is on screen."
    )


def test_an_app_still_in_front_means_the_input_did_not_change():
    answer = _show(InputSent(said=INPUTS["hdmi2"], stayed="YouTube"))
    assert answer["outcome"] == "unverified"
    assert answer["say"] == (
        "I sent HDMI 2 to upstairs, but YouTube is still on the screen."
        " Nothing may be connected there, or it is off. Check it, or use the TV's own remote."
    )


def test_an_input_change_the_tv_cannot_confirm_is_never_done():
    answer = _show(InputSent(said=INPUTS["hdmi2"]))
    assert answer["outcome"] == "unverified"
    assert answer["say"].endswith("cannot say which input is on screen, so it is not confirmed.")


def _tizen_tv(tmp_path, *, front, leaves):
    """A Tizen TV with `front` on the screen; the input key takes it off only if `leaves`."""
    import httpx  # noqa: PLC0415

    from tv_mcp.drivers.samsung_tizen import SamsungTizen  # noqa: PLC0415

    ids = {app_id: name for name, app_id in SamsungTizen.apps.items()}
    state = {"front": front}
    pressed = []

    def handler(request):
        name = ids.get(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(200, json={"running": name == front, "visible": name == state["front"]})

    class Remote:
        def send_key(self, key):
            pressed.append(key)
            if leaves:
                state["front"] = None

        def close(self):
            pass

    async def no_wait(seconds):
        return None

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            tv = SamsungTizen(
                client, tls_client=client, token_folder=tmp_path, remote=lambda a, t: Remote(), sleep=no_wait
            )
            return await tv.show_input(UPSTAIRS, "hdmi2")

    return asyncio.run(run()), pressed


def test_the_tizen_tv_says_when_the_app_in_front_left_after_the_key(tmp_path):
    sent, pressed = _tizen_tv(tmp_path, front="youtube", leaves=True)
    assert pressed == ["KEY_HDMI2"]
    assert (sent.said, sent.left, sent.stayed, sent.shown) == ("HDMI 2", "YouTube", None, None)


def test_the_tizen_tv_says_when_the_app_in_front_stayed(tmp_path):
    sent, _ = _tizen_tv(tmp_path, front="youtube", leaves=False)
    assert (sent.left, sent.stayed) == (None, "YouTube")


def test_the_tizen_tv_with_no_app_in_front_cannot_confirm_anything(tmp_path):
    sent, pressed = _tizen_tv(tmp_path, front=None, leaves=False)
    assert pressed == ["KEY_HDMI2"]
    assert (sent.left, sent.stayed, sent.shown) == (None, None, None)


def test_a_switch_the_tv_accepted_is_said_as_accepted_but_not_seen():
    named = Tv(key="upstairs", names=("upstairs",), address="192.0.2.11", inputs={"hdmi2": "Game Box"})
    service = TvService(
        Settings(tvs=(named,)),
        drivers={"samsung-tizen": Tizen(InputSent(said="HDMI 2", accepted=True))},
        listen=_no_listen,
    )
    answer = asyncio.run(service.show_input("Game Box", "upstairs"))
    assert answer["outcome"] == "unverified"
    assert (
        answer["say"] == "Upstairs accepted the switch to HDMI 2 (Game Box), but can't confirm the picture."
    )

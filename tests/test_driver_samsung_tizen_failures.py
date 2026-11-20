# SPDX-License-Identifier: GPL-3.0-or-later
"""A 2022-2023 Samsung that fails, drops or refuses: the driver answers plainly, never with a raw error."""

import asyncio

import httpx
import pytest
from samsungtvws.exceptions import UnauthorizedError

from tv_mcp.driver import NO_ANSWER, RefusedError
from tv_mcp.drivers.samsung_tizen import YOUTUBE_TRIES, SamsungTizen
from tv_mcp.settings import Tv

ADDRESS = "192.0.2.10"
FRAME = Tv(key="the-frame", names=("The Frame",), address=ADDRESS, mac="00:00:5E:00:53:01")
NO_ADDRESS = Tv(key="the-frame", names=("The Frame",))
INFO = {"device": {"model": "22_PONTUSM_FTV", "modelName": "QE55LS03BAUXXC"}}


class Remote:
    """A paired remote that fails every key with `failure`."""

    def __init__(self, failure):
        self.failure, self.keys = failure, []

    def __call__(self, address, token_file):
        return self

    def send_key(self, key):
        self.keys.append(key)
        raise self.failure

    def hold_key(self, key, seconds):
        self.keys.append(key)
        raise self.failure

    def close(self):
        pass


def _run(handler, act, tmp_path, *, remote=None):
    """Run `act` on a driver whose TV answers every request with `handler`; it never waits."""

    async def no_wait(seconds):
        return None

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            extra = {"remote": remote} if remote else {}
            driver = SamsungTizen(client, tls_client=client, token_folder=tmp_path, sleep=no_wait, **extra)
            return await act(driver)

    return asyncio.run(run())


def _down(request):
    message = "the TV is not there"
    raise httpx.ConnectError(message, request=request)


def test_youtube_that_will_not_open_gives_no_screen_and_asks_nothing_more(tmp_path):
    seen = []

    def handler(request):
        seen.append(request.url.port)
        return httpx.Response(404)

    assert _run(handler, lambda d: d.youtube_screen(ADDRESS), tmp_path) is None
    assert seen == [8002]


def test_youtube_whose_screen_never_answers_gives_no_screen_after_its_tries(tmp_path):
    dial = []

    def handler(request):
        if request.url.port == 8002:
            return httpx.Response(200, json={"ok": True})
        dial.append(request.url.path)
        return _down(request)

    assert _run(handler, lambda d: d.youtube_screen(ADDRESS), tmp_path) is None
    assert len(dial) == YOUTUBE_TRIES


def test_a_tv_whose_volume_service_does_not_answer_gives_no_volume(tmp_path):
    assert _run(_down, lambda d: d.volume(ADDRESS), tmp_path) is None


def test_a_tv_that_drops_the_connection_twice_says_nothing_of_the_app(tmp_path):
    def handler(request):
        message = "the TV hung up"
        raise httpx.RemoteProtocolError(message, request=request)

    assert _run(handler, lambda d: d.in_front(ADDRESS, "111299001912"), tmp_path) is None


def test_an_app_state_that_is_not_json_says_nothing_of_the_app(tmp_path):
    def handler(request):
        return httpx.Response(200, text="<html>not json</html>")

    assert _run(handler, lambda d: d.in_front(ADDRESS, "111299001912"), tmp_path) is None


def test_a_media_key_for_a_tv_with_no_address_is_no_answer(tmp_path):
    assert _run(_down, lambda d: d.player(NO_ADDRESS, "pause"), tmp_path) == NO_ANSWER


def test_a_media_key_the_remote_fails_to_send_is_no_answer(tmp_path):
    remote = Remote(OSError("the connection closed"))
    assert _run(_down, lambda d: d.player(FRAME, "pause"), tmp_path, remote=remote) == NO_ANSWER
    assert remote.keys == ["KEY_PAUSE"]


def test_a_media_key_the_tv_refuses_is_said_as_refused(tmp_path):
    remote = Remote(UnauthorizedError("denied"))
    with pytest.raises(RefusedError):
        _run(_down, lambda d: d.player(FRAME, "pause"), tmp_path, remote=remote)


def test_an_app_the_tv_will_not_close_and_no_remote_to_press_home_stays_open(tmp_path):
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"running": True, "visible": True})
        return httpx.Response(500)

    assert _run(handler, lambda d: d.close_app(ADDRESS, "111299001912"), tmp_path) is False


def test_an_app_that_stays_in_front_after_home_counts_as_not_closed(tmp_path):
    gets = []

    def handler(request):
        if request.method == "DELETE":
            return httpx.Response(501)
        gets.append(request.url.path)
        if len(gets) % 2 == 0:
            return _down(request)  # every other look fails; none sees the app leave
        return httpx.Response(200, json={"running": True, "visible": True})

    class Presses(Remote):
        def send_key(self, key):
            self.keys.append(key)

    remote = Presses(None)
    closed = _run(
        handler, lambda d: d.close_app(ADDRESS, "111299001912", tv_key=FRAME.key), tmp_path, remote=remote
    )
    assert closed is False
    assert remote.keys == ["KEY_HOME"]


def test_a_power_key_the_remote_fails_to_send_counts_as_not_switched(tmp_path):
    def handler(request):
        return httpx.Response(200, json=INFO)

    remote = Remote(OSError("the connection closed"))
    assert _run(handler, lambda d: d.switch(FRAME, on=False), tmp_path, remote=remote) is False
    assert remote.keys == ["KEY_POWER"]

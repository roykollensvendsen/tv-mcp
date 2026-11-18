# SPDX-License-Identifier: GPL-3.0-or-later
"""Pause, resume, stop and seek on a Chromecast go to the app that is playing.

Jellyfin's receiver takes its own commands; any other app, such as YouTube, takes the
Chromecast's standard media commands. The calls that need a real device are stood in for.
"""

import asyncio

import httpx
import pytest

from tv_mcp.driver import DONE, NO_ANSWER
from tv_mcp.drivers import chromecast as chromecast_module
from tv_mcp.drivers.chromecast import JELLYFIN_RECEIVER, Chromecast, control_message
from tv_mcp.media import CastLogin
from tv_mcp.settings import Tv

EXAMPLE_TOKEN = "user-token"  # noqa: S105 - an example
LOGIN = CastLogin(
    server="http://192.0.2.5:8096", token=EXAMPLE_TOKEN, user_id="u1", server_id="srv", version="12.4.0"
)
GARAGE = Tv(key="garage", names=(), location="garage", address="192.0.2.20", driver="chromecast")


async def _login(_address):
    return LOGIN


def _driver(sent, *, delivered=True, handler=None):
    async def send(address, message):
        sent.append((address, message["command"]))
        return delivered

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler or (lambda _r: httpx.Response(404))))
    return Chromecast(client, login=_login, send=send)


def _app(monkeypatch, app):
    monkeypatch.setattr(chromecast_module, "_app_blocking", lambda _address: app)


def test_with_no_app_answering_a_command_reaches_nothing(monkeypatch):
    _app(monkeypatch, None)
    sent = []
    assert asyncio.run(_driver(sent).player(GARAGE, "pause")) == NO_ANSWER
    assert sent == []


def test_pause_in_jellyfin_s_receiver_is_the_receiver_s_own_command(monkeypatch):
    _app(monkeypatch, JELLYFIN_RECEIVER)
    sent = []
    assert asyncio.run(_driver(sent).player(GARAGE, "pause")) == DONE
    assert sent == [("192.0.2.20", control_message(LOGIN, "pause")["command"])]


def test_seek_in_jellyfin_s_receiver_is_the_receiver_s_own_seek(monkeypatch):
    _app(monkeypatch, JELLYFIN_RECEIVER)
    sent = []
    assert asyncio.run(_driver(sent).player(GARAGE, "seek", 90)) == DONE
    assert sent == [("192.0.2.20", "Seek")]


def test_a_receiver_command_that_is_not_delivered_is_said_as_no_answer(monkeypatch):
    _app(monkeypatch, JELLYFIN_RECEIVER)
    assert asyncio.run(_driver([], delivered=False).player(GARAGE, "stop")) == NO_ANSWER


def test_another_app_gets_the_chromecast_s_standard_media_command(monkeypatch):
    _app(monkeypatch, "YouTube")
    asked = []

    def media(address, command, seconds):
        asked.append((address, command, seconds))
        return DONE

    monkeypatch.setattr(chromecast_module, "_media_blocking", media)
    sent = []
    assert asyncio.run(_driver(sent).player(GARAGE, "seek", 30)) == DONE
    assert asked == [("192.0.2.20", "seek", 30)]
    assert sent == [], "Jellyfin's receiver commands went to another app"


@pytest.mark.parametrize(
    "handler",
    [
        lambda _r: httpx.Response(500),
        lambda _r: httpx.Response(200, text="not a page"),
    ],
    ids=["refused", "not-json"],
)
def test_a_chromecast_page_that_cannot_be_read_says_nothing_about_it(handler):
    assert asyncio.run(_driver([], handler=handler).read_info("192.0.2.20")) is None


@pytest.mark.parametrize(
    ("call", "blocking", "answer", "expected"),
    [
        (lambda d: d.volume("192.0.2.20"), "_sound_blocking", 40, 40),
        (lambda d: d.set_volume("192.0.2.20", 15), "_sound_blocking", 15, True),
        (lambda d: d.set_volume("192.0.2.20", 15), "_sound_blocking", None, False),
        (lambda d: d.set_mute("192.0.2.20", on=True), "_sound_blocking", 0, True),
        (lambda d: d.set_mute("192.0.2.20", on=True), "_sound_blocking", None, False),
        (lambda d: d.muted("192.0.2.20"), "_muted_blocking", True, True),
        (lambda d: d.screen_on("192.0.2.20"), "_screen_blocking", False, False),
        (lambda d: d.on_screen("192.0.2.20"), "_in_front_blocking", True, True),
        (lambda d: d.wake_screen("192.0.2.20"), "_wake_blocking", True, True),
        (lambda d: d.youtube_screen("192.0.2.20"), "_youtube_screen_blocking", "screen-1", "screen-1"),
    ],
    ids=[
        "volume",
        "set-volume",
        "set-volume-unanswered",
        "mute",
        "mute-unanswered",
        "muted",
        "screen-on",
        "on-screen",
        "wake",
        "youtube-screen",
    ],
)
def test_what_the_chromecast_answers_is_passed_on_as_it_is(monkeypatch, call, blocking, answer, expected):
    asked = []
    monkeypatch.setattr(chromecast_module, blocking, lambda *args: asked.append(args) or answer)
    assert asyncio.run(call(_driver([]))) == expected
    assert [args[0] for args in asked] == ["192.0.2.20"]

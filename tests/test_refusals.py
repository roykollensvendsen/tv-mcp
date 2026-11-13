# SPDX-License-Identifier: GPL-3.0-or-later
"""When a TV, Jellyfin or YouTube says no, the voice says why and what to do.

A sweep of the plugin's fakes on 2026-11-13 found three refusals no test made:
a TV that will not let tv-mcp's remote in, a Jellyfin key that no longer
works, and YouTube's daily search limit. Each came out as the wrong reason:
"did not answer", "Jellyfin is not open", or "found nothing".
"""

import asyncio

import httpx
import pytest
from samsungtvws.exceptions import UnauthorizedError

from tv_mcp.driver import RefusedError
from tv_mcp.drivers import samsung_legacy
from tv_mcp.drivers.jellyfin import Jellyfin, cast_login
from tv_mcp.drivers.samsung_tizen import SamsungTizen
from tv_mcp.drivers.youtube import DataApiSearch, FirstThatAnswers
from tv_mcp.server import build_server
from tv_mcp.settings import Tv
from tv_mcp.simulator import simulated_service

URL = "http://192.0.2.5:8096"
DEN = Tv(key="den", names=("the den",), address="192.0.2.30", mac="00:00:5E:00:53:01")


def _refused_by_jellyfin(request):
    return httpx.Response(401, text="Unauthorized")


def _with(handler, work):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await work(client)

    return asyncio.run(run())


def test_a_jellyfin_key_that_is_refused_is_said_as_refused():
    for ask in (lambda j: j.search("Alien"), lambda j: j.sessions()):
        with pytest.raises(RefusedError) as refusal:
            _with(_refused_by_jellyfin, lambda client, ask=ask: ask(Jellyfin(URL, "old-key", client)))
        assert str(refusal.value) == (
            "Jellyfin refused tv-mcp's API key. Add a new key from Jellyfin's dashboard, under API Keys,"
            " to ~/.config/tv-mcp/jellyfin-key, then restart the TV plugin."
        )


def test_a_refused_jellyfin_login_for_the_chromecast_is_said_as_refused():
    with pytest.raises(RefusedError) as refusal:
        _with(
            _refused_by_jellyfin,
            lambda client: cast_login(
                URL, "old-token", client, "192.0.2.20", local_address=lambda a: "192.0.2.2"
            ),
        )
    assert "~/.config/tv-mcp/jellyfin-user-token" in str(refusal.value)
    assert str(refusal.value).endswith("then restart the TV plugin.")


def test_a_refusal_reaches_the_voice_as_its_own_sentence():
    service = simulated_service()

    async def refused(title):
        message = "Jellyfin refused tv-mcp's API key. Add a new key, then restart the TV plugin."
        raise RefusedError(message)

    service.search = refused
    answer = asyncio.run(build_server(service).call_tool("tv_search", {"title": "Alien"})).structured_content
    assert answer["success"] is False
    assert answer["outcome"] == "refused"
    assert answer["say"] == "Jellyfin refused tv-mcp's API key. Add a new key, then restart the TV plugin."


QUOTA = {
    "error": {
        "code": 403,
        "message": "The request cannot be completed because you have exceeded your quota.",
        "errors": [{"reason": "quotaExceeded", "domain": "youtube.quota"}],
    }
}


class FindsNothing:
    async def search(self, words):
        return []

    async def video(self, video_id):
        return None


def test_a_used_up_youtube_quota_is_said_as_used_up():
    def handler(request):
        return httpx.Response(403, json=QUOTA)

    async def run(client):
        return await FirstThatAnswers(FindsNothing(), DataApiSearch("a-key", client)).search("cats")

    with pytest.raises(RefusedError) as refusal:
        _with(handler, run)
    assert str(refusal.value) == (
        "YouTube's official search has used its searches for today, and the other search found nothing."
        " Try other words, or try again tomorrow."
    )


def test_a_youtube_search_that_finds_nothing_is_still_nothing():
    def handler(request):
        return httpx.Response(200, json={"items": []})

    async def run(client):
        return await FirstThatAnswers(FindsNothing(), DataApiSearch("a-key", client)).search("cats")

    assert _with(handler, run) == []


class RefusingRemote:
    """The TV's remote channel when the TV has said no to tv-mcp: ms.channel.unauthorized."""

    def __init__(self, address, token_file):
        raise UnauthorizedError({"event": "ms.channel.unauthorized"})


def _tizen(client, tmp_path):
    async def no_wait(seconds):
        return None

    return SamsungTizen(
        client, tls_client=client, token_folder=tmp_path, remote=RefusingRemote, sleep=no_wait
    )


TIZEN_REFUSED = (
    "The TV refused tv-mcp's remote. Allow tv-mcp on the TV under Settings, General,"
    " External Device Manager, Device Connection Manager, Device List; then try again."
)


def test_a_samsung_that_refuses_the_remote_is_said_as_refused(tmp_path):
    def handler(request):
        return httpx.Response(200, json={"device": {"PowerState": "on"}, "running": True, "visible": True})

    with pytest.raises(RefusedError) as refusal:
        _with(handler, lambda client: _tizen(client, tmp_path).switch(DEN, on=False))
    assert str(refusal.value) == TIZEN_REFUSED


async def _legacy_tv(answer, *, repeat=1):
    """An older Samsung's remote port that answers each "may I?" with `answer`, `repeat` times."""

    async def serve(reader, writer):
        await reader.read(256)
        for _ in range(repeat):
            payload = answer
            name = b"iapp.samsung"
            frame = b"\x00" + len(name).to_bytes(2, "little") + name
            writer.write(frame + len(payload).to_bytes(2, "little") + payload)
            await writer.drain()
            await asyncio.sleep(0.05)
        await asyncio.sleep(1)
        writer.close()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


def _legacy_press(answer, *, repeat=1, wait=0.5):
    async def run():
        server, port = await _legacy_tv(answer, repeat=repeat)
        async with server:
            loop = asyncio.get_running_loop()
            started = loop.time()
            try:
                return await samsung_legacy._press(  # noqa: SLF001 - the remote protocol, with no TV
                    "127.0.0.1", "KEY_MUTE", wait, port=port
                ), loop.time() - started
            finally:
                server.close()

    return asyncio.run(run())


def test_an_older_samsung_that_refuses_the_remote_is_said_as_refused():
    with pytest.raises(RefusedError) as refusal:
        _legacy_press(b"\x64\x00\x00\x00")
    assert str(refusal.value) == (
        "The TV refused tv-mcp's remote. Allow tv-mcp in the TV's own menu, in its list of devices"
        " that may control it; then try again."
    )


def test_an_older_samsung_that_keeps_asking_is_given_up_in_time():
    pressed, took = _legacy_press(b"\x0a\x00\x01\x00", repeat=40, wait=0.5)
    assert pressed is False
    assert took < 1.0


def test_an_older_samsungs_press_ends_within_the_voices_answer_time():
    from tv_mcp import server  # noqa: PLC0415

    # Reaching its remote port, then its "may I?", all before the voice hears "still working".
    assert samsung_legacy.REACH_WAIT + samsung_legacy.ANSWER_WAIT < server.ANSWER_WITHIN


def test_an_older_samsung_that_does_not_open_its_remote_port_is_given_up_quickly():
    async def run():
        loop = asyncio.get_running_loop()
        started = loop.time()
        # A documentation address: nothing answers, so only the wait to reach it ends this.
        pressed = await samsung_legacy._press("192.0.2.1", "KEY_MUTE", 0.1)  # noqa: SLF001 - no TV
        return pressed, loop.time() - started

    pressed, took = asyncio.run(run())
    assert pressed is False
    assert took <= samsung_legacy.REACH_WAIT + 0.5


def test_a_scene_from_subtitles_says_a_refused_jellyfin_key_aloud():
    from test_scene import WATCHING, SceneLibrary  # noqa: PLC0415

    from tv_mcp.drivers.jellyfin import KEY_REFUSED  # noqa: PLC0415
    from tv_mcp.service import TvService  # noqa: PLC0415
    from tv_mcp.settings import Settings  # noqa: PLC0415

    class Refusing(SceneLibrary):
        async def subtitles(self, item_id):
            raise RefusedError(KEY_REFUSED)

    async def no_listen(recognises, target):
        return []

    living = Tv(key="living-room", names=("the living room",), address="192.0.2.10")
    service = TvService(
        Settings(tvs=(living,)), drivers={}, listen=no_listen, library=Refusing([WATCHING], [])
    )
    answer = asyncio.run(
        build_server(service, features=["status", "scene"]).call_tool("tv_scene", {"tv": "the living room"})
    ).structured_content
    assert (answer["success"], answer["say"]) == (False, KEY_REFUSED)


class RefusingHome:
    """The home-screen channel of a TV that has said no to tv-mcp."""

    def ask(self, request_id, params):
        raise RefusedError(TIZEN_REFUSED)

    def close(self):
        pass


def test_a_samsung_whose_home_screen_refuses_tv_mcp_is_said_as_refused(tmp_path):
    pressed = []

    class Remote:
        def send_key(self, key):
            pressed.append(key)

        def close(self):
            pass

    def handler(request):
        return httpx.Response(200, json={"running": False, "visible": False})

    async def no_wait(seconds):
        return None

    async def run(client):
        tv = SamsungTizen(
            client,
            tls_client=client,
            token_folder=tmp_path,
            remote=lambda a, t: Remote(),
            bff=lambda a, t: RefusingHome(),
            sleep=no_wait,
        )
        return await tv.show_input(DEN, "hdmi2")

    with pytest.raises(RefusedError) as refusal:
        _with(handler, run)
    assert str(refusal.value) == TIZEN_REFUSED
    assert pressed == []

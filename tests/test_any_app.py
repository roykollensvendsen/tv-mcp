# SPDX-License-Identifier: GPL-3.0-or-later
"""The same controls for whatever plays on a TV: Jellyfin, YouTube or another app."""

import asyncio

from tv_mcp.driver import Playing, TvInfo
from tv_mcp.service import TvService
from tv_mcp.settings import Settings, Tv

LIVING = Tv(key="living-room", names=("the living room",), address="192.0.2.10")
UPSTAIRS = Tv(key="upstairs", names=("upstairs",), address="192.0.2.11", hands_off=True)
CLIP = Playing(app="YouTube", title="Death Star battle", position=120.0, runtime=600.0, paused=False)


class Player:
    key = "samsung-tizen"
    ssdp_target = "x"

    def __init__(self, playing=CLIP, *, answer="done"):
        self.now, self.answer, self.sent = playing, answer, []

    def recognises(self, announcement):
        return False

    async def read_info(self, address):
        # On, so status asks it what plays and how loud it is.
        return TvInfo(name=None, model=None, year=None, platform=None, power="on")

    async def playing(self, address):
        return self.now

    async def player(self, tv, command, seconds=None):
        self.sent.append((command, seconds))
        return self.answer


class NoFilms:
    async def sessions(self):
        return []


def _service(driver, *tvs):
    async def no_listen(recognises, target):
        return []

    async def no_wait(seconds):
        return None

    return TvService(
        Settings(tvs=tvs or (LIVING,)),
        drivers={driver.key: driver},
        listen=no_listen,
        library=NoFilms(),
        sleep=no_wait,
    )


def test_pause_resume_and_stop_reach_an_app_that_is_not_jellyfin():
    driver = Player()
    service = _service(driver)
    for command in ("pause", "resume", "stop"):
        assert asyncio.run(service.control(command, "the living room"))["outcome"] == "done"
    assert driver.sent == [("pause", None), ("resume", None), ("stop", None)]


def test_seek_reaches_an_app_that_is_not_jellyfin_counting_from_its_position():
    driver = Player()
    answer = asyncio.run(_service(driver).seek("the living room", 60, relative=True))
    assert answer["outcome"] == "done"
    assert driver.sent == [("seek", 180.0)]


def test_an_app_that_cannot_do_a_command_is_said_plainly():
    driver = Player(answer="unsupported")
    answer = asyncio.run(_service(driver).seek("the living room", 60, relative=False))
    assert answer["outcome"] == "refused"
    assert "YouTube" in answer["say"]
    assert "cannot" in answer["say"]


def test_status_says_what_plays_in_any_app():
    [report] = asyncio.run(_service(Player()).status("the living room"))
    assert report["playing"] == {
        "app": "YouTube",
        "title": "Death Star battle",
        "at": "2 min",
        "left": "8 min",
        "paused": False,
    }


def test_nothing_playing_in_any_app_is_said_plainly():
    answer = asyncio.run(_service(Player(playing=None)).control("pause", "the living room"))
    assert answer["outcome"] == "refused"


def test_a_hands_off_tv_is_never_asked_what_plays():
    driver = Player()
    [report] = asyncio.run(_service(driver, LIVING, UPSTAIRS).status("upstairs"))
    assert "playing" not in report
    answer = asyncio.run(_service(driver, LIVING, UPSTAIRS).control("pause", "upstairs"))
    assert answer["outcome"] == "refused"
    assert driver.sent == []


def test_a_samsung_pauses_another_app_with_its_media_key(tmp_path):
    import httpx  # noqa: PLC0415

    from tv_mcp.drivers.samsung_tizen import SamsungTizen  # noqa: PLC0415

    pressed = []

    class Remote:
        def send_key(self, key):
            pressed.append(key)

        def close(self):
            pressed.append("closed")

    def opened(address, token_file):
        assert token_file == tmp_path / "living-room-token"
        return Remote()

    async def run():
        async with httpx.AsyncClient() as client:
            tv = SamsungTizen(client, token_folder=tmp_path, remote=opened)
            return await tv.player(LIVING, "pause"), await tv.player(LIVING, "seek", 60.0)

    assert asyncio.run(run()) == ("done", "unsupported")
    assert pressed == ["KEY_PAUSE", "closed"]


def test_a_samsung_says_which_app_is_in_front():
    import httpx  # noqa: PLC0415

    from tv_mcp.drivers.samsung_tizen import SamsungTizen  # noqa: PLC0415

    def handler(request):
        visible = request.url.path.endswith("/111299001912")
        return httpx.Response(200, json={"running": visible, "visible": visible})

    async def run():
        transport = httpx.MockTransport(handler)
        async with (
            httpx.AsyncClient(transport=transport) as client,
            httpx.AsyncClient(transport=transport) as tls,
        ):
            return await SamsungTizen(client, tls_client=tls).playing("192.0.2.10")

    assert asyncio.run(run()) == Playing(app="YouTube")


def test_one_app_that_does_not_answer_does_not_hide_the_app_in_front():
    import httpx  # noqa: PLC0415

    from tv_mcp.drivers.samsung_tizen import SamsungTizen  # noqa: PLC0415

    def handler(request):
        if request.url.path.endswith("/AprZAARz4r.Jellyfin"):
            slow = "the TV took too long"
            raise httpx.ReadTimeout(slow, request=request)
        visible = request.url.path.endswith("/3201907018807")
        return httpx.Response(200, json={"running": visible, "visible": visible})

    async def run():
        transport = httpx.MockTransport(handler)
        async with (
            httpx.AsyncClient(transport=transport) as client,
            httpx.AsyncClient(transport=transport) as tls,
        ):
            return await SamsungTizen(client, tls_client=tls).playing("192.0.2.10")

    assert asyncio.run(run()) == Playing(app="Netflix")


def test_status_names_the_app_in_front_and_never_says_none_when_the_tv_gives_no_title():
    # 2026-11-09: "Stua oppe is on, playing None, volume 6." with NRK TV open.
    from tv_mcp.tools.say import tv_lines  # noqa: PLC0415

    report = {"tv": "stua oppe", "state": "on", "playing": {"app": "NRK TV", "title": None, "paused": False}}
    line = tv_lines([{**report, "volume": 6}])
    assert line == "Stua oppe is on, NRK TV is open, volume 6."
    assert "None" not in line


def test_a_jump_to_a_time_in_jellyfin_waits_for_its_report_instead_of_asking_the_app():
    # 2026-11-09: "Jellyfin on stua nede cannot seek" for 1 h 7 min, while skips worked just after.
    from tv_mcp.media import Session  # noqa: PLC0415

    quiet = Session(id="s1", address="192.0.2.10", client="Jellyfin for Tizen", controllable=True)
    playing = Session(**{**quiet.__dict__, "now_playing": "A New Hope", "position": 600.0, "runtime": 7500.0})

    class Library:
        def __init__(self):
            self.reports, self.seeks = [[quiet], [playing]], []

        async def sessions(self):
            return self.reports.pop(0) if len(self.reports) > 1 else self.reports[0]

        async def seek(self, session_id, seconds):
            self.seeks.append((session_id, seconds))

    driver, library = Player(Playing(app="Jellyfin")), Library()
    service = _service(driver)
    service.library = library
    answer = asyncio.run(service.seek("the living room", 4020, relative=False))
    assert answer["outcome"] == "done", answer
    assert library.seeks == [("s1", 4020)]
    assert driver.sent == []

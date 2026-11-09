# SPDX-License-Identifier: GPL-3.0-or-later
"""Finding a film and starting it on a TV named the way the owner names it."""

import asyncio
import types

from tv_mcp.media import MediaItem, Session
from tv_mcp.service import TvService
from tv_mcp.settings import Settings, Tv

LIVING = Tv(key="living-room", names=("the living room", "The Frame"), address="192.0.2.10")
UPSTAIRS = Tv(key="upstairs", names=("upstairs",), address="192.0.2.11", hands_off=True)
HOPE = MediaItem(id="a1", title="Star Wars: Episode IV - A New Hope", year=1977, kind="Movie")
ROGUE = MediaItem(id="b2", title="Rogue One: A Star Wars Story", year=2016, kind="Movie")
EMPIRE = MediaItem(id="c3", title="Star Wars: Episode V - The Empire Strikes Back", year=1980, kind="Movie")


class FakeLibrary:
    def __init__(self, items, sessions):
        self.items, self._sessions, self.played = items, sessions, []

    async def search(self, term):
        words = term.casefold().split()
        return [i for i in self.items if all(w in i.title.casefold() for w in words)]

    async def sessions(self):
        return list(self._sessions)

    async def play(self, session_id, item_id):
        self.played.append((session_id, item_id))


FRAME_SESSION = Session(id="s1", address="192.0.2.10", client="Jellyfin for Tizen", controllable=True)


async def _no_listen(recognises, target):
    return []


async def _no_wait(seconds):
    return None


def _service(library, *tvs):
    return TvService(
        Settings(tvs=tvs or (LIVING,)), drivers={}, listen=_no_listen, library=library, sleep=_no_wait
    )


def _play(library, title, tv="The Frame", *tvs):
    return asyncio.run(_service(library, *tvs).play(title, tv))


def test_search_gives_title_and_year_of_each_match():
    library = FakeLibrary([HOPE, ROGUE], [])
    found = asyncio.run(_service(library).search("star wars"))
    assert [(i["title"], i["year"]) for i in found["items"]] == [(HOPE.title, 1977), (ROGUE.title, 2016)]


def test_one_sentence_starts_the_film_on_the_named_tv():
    library = FakeLibrary([HOPE, ROGUE], [FRAME_SESSION])
    answer = _play(library, "A New Hope")
    assert library.played == [("s1", "a1")]
    assert answer["outcome"] == "playing"
    assert "A New Hope" in answer["say"]
    assert "the living room" in answer["say"]


def test_a_title_that_matches_several_items_is_refused_naming_them():
    library = FakeLibrary([HOPE, EMPIRE], [FRAME_SESSION])
    answer = _play(library, "star wars episode")
    assert library.played == []
    assert answer["outcome"] == "refused"
    assert "A New Hope" in answer["say"]
    assert "Empire" in answer["say"]


def test_an_exact_title_wins_over_longer_ones():
    sequel = MediaItem(id="d4", title="Rogue One: A Star Wars Story (Extended)", year=2016, kind="Movie")
    library = FakeLibrary([ROGUE, sequel], [FRAME_SESSION])
    _play(library, "Rogue One: A Star Wars Story")
    assert library.played == [("s1", "b2")]


def test_nothing_found_is_said_plainly():
    answer = _play(FakeLibrary([HOPE], [FRAME_SESSION]), "Jaws")
    assert answer["outcome"] == "refused"
    assert "Jaws" in answer["say"]


def test_play_needs_jellyfin_open_on_that_tv():
    elsewhere = Session(id="s9", address="192.0.2.99", client="Jellyfin Web", controllable=True)
    library = FakeLibrary([HOPE], [elsewhere])
    answer = _play(library, "A New Hope")
    assert library.played == []
    assert answer["outcome"] == "refused"
    assert "Jellyfin" in answer["say"]


def test_a_hands_off_tv_is_never_played_on():
    upstairs_session = Session(id="s2", address="192.0.2.11", client="Jellyfin for Tizen", controllable=True)
    library = FakeLibrary([HOPE], [upstairs_session])
    answer = _play(library, "A New Hope", "upstairs", LIVING, UPSTAIRS)
    assert library.played == []
    assert answer["outcome"] == "refused"


def test_an_unknown_tv_is_refused_before_anything_is_searched():
    library = FakeLibrary([HOPE], [FRAME_SESSION])
    answer = _play(library, "A New Hope", "the kitchen")
    assert answer["outcome"] == "refused"
    assert library.played == []


def test_without_a_library_play_says_jellyfin_is_not_set_up():
    answer = asyncio.run(_service(None).play("A New Hope", "The Frame"))
    assert answer["outcome"] == "refused"
    assert "Jellyfin" in answer["say"]


class ControlLibrary(FakeLibrary):
    def __init__(self, sessions):
        super().__init__([HOPE], sessions)
        self.commands = []

    async def control(self, session_id, command):
        self.commands.append((session_id, command))


def test_stop_pause_and_resume_go_to_the_named_tvs_session():
    library = ControlLibrary([FRAME_SESSION])
    service = _service(library)
    for command in ("pause", "resume", "stop"):
        answer = asyncio.run(service.control(command, "The Frame"))
        assert answer["outcome"] == "done", answer
    assert library.commands == [("s1", "pause"), ("s1", "resume"), ("s1", "stop")]


def test_an_unknown_command_is_refused():
    library = ControlLibrary([FRAME_SESSION])
    answer = asyncio.run(_service(library).control("explode", "The Frame"))
    assert answer["outcome"] == "refused"
    assert library.commands == []


def test_a_hands_off_tv_is_never_played_on_or_controlled():
    upstairs_session = Session(id="s2", address="192.0.2.11", client="Jellyfin for Tizen", controllable=True)
    library = ControlLibrary([upstairs_session])
    answer = asyncio.run(_service(library, LIVING, UPSTAIRS).control("stop", "upstairs"))
    assert answer["outcome"] == "refused"
    assert library.commands == []


class AppDriver:
    key = "samsung-tizen"
    ssdp_target = "x"
    apps = types.MappingProxyType({"jellyfin": "AprZAARz4r.Jellyfin"})

    def __init__(self, library, *, works=True):
        self.library, self.works, self.opened = library, works, []

    def recognises(self, announcement):
        return False

    async def read_info(self, address):
        return None

    async def open_app(self, address, app_id):
        self.opened.append(app_id)
        if self.works:
            self.library._sessions.append(FRAME_SESSION)  # noqa: SLF001 - the fake library's own list
        return self.works


def _opening_service(library, driver):
    async def no_wait(seconds):
        return None

    return TvService(
        Settings(tvs=(LIVING,)),
        drivers={driver.key: driver},
        listen=_no_listen,
        library=library,
        sleep=no_wait,
    )


def test_play_opens_jellyfin_on_the_tv_when_it_is_closed_and_then_plays():
    library = FakeLibrary([HOPE], [])
    driver = AppDriver(library)
    answer = asyncio.run(_opening_service(library, driver).play("A New Hope", "The Frame"))
    assert driver.opened == ["AprZAARz4r.Jellyfin"]
    assert library.played == [("s1", "a1")]
    assert answer["outcome"] == "playing"


def test_play_gives_up_when_jellyfin_does_not_connect_in_time():
    library = FakeLibrary([HOPE], [])
    driver = AppDriver(library, works=False)
    answer = asyncio.run(_opening_service(library, driver).play("A New Hope", "The Frame"))
    assert answer["outcome"] == "refused"
    assert library.played == []


def test_play_does_not_open_anything_for_a_title_it_cannot_find():
    library = FakeLibrary([HOPE], [])
    driver = AppDriver(library)
    asyncio.run(_opening_service(library, driver).play("Jaws", "The Frame"))
    assert driver.opened == []


STOPPED = MediaItem(
    id="a1",
    title=HOPE.title,
    year=1977,
    kind="Movie",
    position=72 * 60,
    runtime=121 * 60,
    last_played="2026-11-08",
)


class ResumingLibrary(FakeLibrary):
    async def play(self, session_id, item_id, start=0.0):
        self.played.append((session_id, item_id, start))


def test_search_says_where_a_film_was_stopped_and_when():
    found = asyncio.run(_service(FakeLibrary([STOPPED], [])).search("new hope"))
    [item] = found["items"]
    assert (item["stopped_at"], item["last_watched"]) == ("1 h 12 min", "2026-11-08")


def test_a_film_that_was_stopped_carries_on_where_it_stopped():
    library = ResumingLibrary([STOPPED], [FRAME_SESSION])
    answer = _play(library, "A New Hope")
    assert library.played == [("s1", "a1", 72 * 60)]
    assert "from 1 h 12 min" in answer["say"]


def test_status_says_what_is_playing_how_far_in_and_how_much_is_left():
    watching = Session(
        id="s1",
        address="192.0.2.10",
        client="Jellyfin for Tizen",
        controllable=True,
        now_playing=HOPE.title,
        position=72 * 60,
        runtime=121 * 60,
        paused=False,
    )
    service = _service(FakeLibrary([HOPE], [watching]))
    [report] = asyncio.run(service.status("The Frame"))
    assert report["playing"] == {"title": HOPE.title, "at": "1 h 12 min", "left": "49 min", "paused": False}


class SeekingLibrary(ResumingLibrary):
    def __init__(self, items, sessions):
        super().__init__(items, sessions)
        self.seeks = []

    async def seek(self, session_id, seconds):
        self.seeks.append((session_id, seconds))


WATCHING = Session(
    id="s1",
    address="192.0.2.10",
    client="Jellyfin for Tizen",
    controllable=True,
    now_playing=HOPE.title,
    position=30 * 60,
    runtime=121 * 60,
    paused=False,
)


def test_play_from_the_start_ignores_where_the_film_was_stopped():
    library = ResumingLibrary([STOPPED], [FRAME_SESSION])
    answer = asyncio.run(_service(library).play("A New Hope", "The Frame", from_start=True))
    assert library.played == [("s1", "a1", 0.0)]
    assert "from" not in answer["say"]


def test_seek_jumps_to_a_time_in_the_film():
    library = SeekingLibrary([HOPE], [WATCHING])
    answer = asyncio.run(_service(library).seek("The Frame", 67 * 60, relative=False))
    assert library.seeks == [("s1", 67 * 60)]
    assert answer["outcome"] == "done"
    assert "1 h 7 min" in answer["say"]


def test_seek_skips_forward_and_back_from_where_the_film_is():
    library = SeekingLibrary([HOPE], [WATCHING])
    asyncio.run(_service(library).seek("The Frame", 10 * 60, relative=True))
    asyncio.run(_service(library).seek("The Frame", -45 * 60, relative=True))
    assert library.seeks == [("s1", 40 * 60), ("s1", 0)]


def test_seek_needs_something_playing():
    library = SeekingLibrary([HOPE], [FRAME_SESSION])
    answer = asyncio.run(_service(library).seek("The Frame", 60, relative=True))
    assert answer["outcome"] == "refused"
    assert library.seeks == []

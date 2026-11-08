# SPDX-License-Identifier: GPL-3.0-or-later
"""Finding a film and starting it on a TV named the way the owner names it."""

import asyncio

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


def _service(library, *tvs):
    return TvService(Settings(tvs=tvs or (LIVING,)), drivers={}, listen=_no_listen, library=library)


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

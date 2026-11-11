# SPDX-License-Identifier: GPL-3.0-or-later
"""Every way a jump in a film can be refused, and that a refused jump moves nothing."""

import asyncio
import dataclasses

from tv_mcp.drivers.samsung_tizen import parse_info
from tv_mcp.media import Session
from tv_mcp.service import TvService
from tv_mcp.settings import Settings, Tv

LIVING = Tv(key="living-room", names=("The Frame",), address="192.0.2.10")
GARAGE = Tv(key="garage", names=("garage",), address="192.0.2.20", driver="chromecast")
WATCHING = Session(
    id="s1",
    address="192.0.2.10",
    client="Jellyfin for Tizen",
    controllable=True,
    now_playing="A New Hope",
    position=30 * 60,
    runtime=121 * 60,
)


class Library:
    def __init__(self, *sessions):
        self._sessions, self.seeks = sessions, []

    async def sessions(self):
        return list(self._sessions)

    async def seek(self, session_id, seconds):
        self.seeks.append((session_id, seconds))


class Twin:
    """A TV at the expected address that says it is another device."""

    key = "samsung-tizen"

    async def read_info(self, address):
        page = {"device": {"name": "Samsung The Frame 55", "PowerState": "on", "id": "uuid:frame-2"}}
        return parse_info(page)


class DeafCast:
    """A Chromecast that does not answer a jump."""

    key = "chromecast"

    def __init__(self):
        self.seeks = []

    async def read_info(self, address):
        return None

    async def cast(self, address, item, start):
        return True

    async def cast_seek(self, address, seconds):
        self.seeks.append((address, seconds))
        return False


async def _no_listen(recognises, target):
    return []


def _seek(library, tv, *drivers, name="The Frame", seconds=60.0):
    service = TvService(
        Settings(tvs=(tv,)),
        drivers={d.key: d for d in drivers},
        listen=_no_listen,
        library=library,
    )
    return asyncio.run(service.seek(name, seconds, relative=True))


def test_a_jump_on_an_unknown_tv_is_refused_before_anything_moves():
    library = Library(WATCHING)
    answer = _seek(library, LIVING, name="the attic")
    assert answer["outcome"] == "refused"
    assert library.seeks == []


def test_a_jump_is_not_made_on_another_tv_answering_at_the_address():
    library = Library(WATCHING)
    frame = Tv(key="living-room", names=("The Frame",), address="192.0.2.10", device_id="uuid:frame-1")
    answer = _seek(library, frame, Twin())
    assert answer["outcome"] == "refused"
    assert library.seeks == []


def test_a_chromecast_that_does_not_answer_the_jump_is_reported():
    watching = Session(
        id="c1",
        address="192.0.2.20",
        client="Chromecast",
        controllable=False,
        now_playing="A New Hope",
        position=600,
        runtime=7200,
    )
    cast = DeafCast()
    answer = _seek(Library(watching), GARAGE, cast, name="garage")
    assert answer["outcome"] == "refused"
    assert "did not answer" in answer["say"]
    assert cast.seeks == [("192.0.2.20", 660)]


def test_a_film_playing_where_jellyfin_cannot_be_steered_is_refused():
    library = Library(dataclasses.replace(WATCHING, controllable=False))
    answer = _seek(library, LIVING)
    assert answer["outcome"] == "refused"
    assert "Jellyfin is not open" in answer["say"]
    assert library.seeks == []


def test_a_jump_past_the_end_stops_at_the_end():
    library = Library(WATCHING)
    answer = _seek(library, LIVING, seconds=5 * 3600)
    assert answer["outcome"] == "done"
    assert library.seeks == [("s1", 121 * 60)]

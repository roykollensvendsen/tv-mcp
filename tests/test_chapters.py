# SPDX-License-Identifier: GPL-3.0-or-later
"""Finding a scene: the film's chapters, or an outline from its subtitles, and fresh positions."""

import asyncio

from tv_mcp.media import Chapter, Cue, Session, outline
from tv_mcp.service import TvService
from tv_mcp.settings import Settings, Tv

LIVING = Tv(key="living-room", names=("the living room",), address="192.0.2.10")


def _watching(position, item_id="a1"):
    return Session(
        id="s1",
        address="192.0.2.10",
        client="Jellyfin for Tizen",
        controllable=True,
        now_playing="A New Hope",
        item_id=item_id,
        position=position,
        runtime=7200,
    )


class Library:
    def __init__(self, answers, *, chapters=(), cues=()):
        self._answers, self.seeks = list(answers), []
        self._chapters, self._cues = list(chapters), list(cues)

    async def sessions(self):
        return self._answers.pop(0) if len(self._answers) > 1 else self._answers[0]

    async def subtitles(self, item_id):
        return self._cues

    async def cast(self, item_id):
        return []

    async def chapters(self, item_id):
        return self._chapters

    async def seek(self, session_id, seconds):
        self.seeks.append(seconds)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _service(library, clock=None):
    async def no_listen(recognises, target):
        return []

    async def no_wait(seconds):
        if clock:
            clock.now += seconds

    return TvService(
        Settings(tvs=(LIVING,)),
        drivers={},
        listen=no_listen,
        library=library,
        sleep=no_wait,
        **({"clock": clock} if clock else {}),
    )


def test_right_after_a_seek_the_position_is_where_it_was_sent_not_the_old_one():
    clock = Clock()
    library = Library([[_watching(600)]], cues=[Cue(3000, 3002, "Set your course for Alderaan.")])
    service = _service(library, clock)
    asyncio.run(service.seek("the living room", 3000, relative=False))
    clock.now += 4
    answer = asyncio.run(service.scene("the living room", minutes=1))
    assert answer["at"] == "50 min"
    asyncio.run(service.seek("the living room", 60, relative=True))
    assert library.seeks[-1] == 3000 + 4 + 60


def test_after_a_while_the_tvs_own_position_counts_again():
    clock = Clock()
    library = Library([[_watching(600)]], cues=[Cue(600, 602, "Hello.")])
    service = _service(library, clock)
    asyncio.run(service.seek("the living room", 3000, relative=False))
    clock.now += 60
    assert asyncio.run(service.scene("the living room", minutes=1))["at"] == "10 min"


def test_a_film_that_drops_out_for_a_moment_is_asked_for_again():
    library = Library([[], [], [_watching(600)]], cues=[Cue(600, 602, "Hello.")])
    answer = asyncio.run(_service(library).scene("the living room", minutes=1))
    assert answer["outcome"] == "done"


def test_named_chapters_are_given_with_their_start_times():
    chapters = [Chapter(0, "Opening"), Chapter(2700, "The Death Star"), Chapter(3300, "Rescuing Leia")]
    library = Library([[_watching(600)]], chapters=chapters, cues=[Cue(600, 602, "Hello.")])
    answer = asyncio.run(_service(library).scene("the living room", minutes=1, chapters=True))
    assert answer["chapters"] == ["0:00 Opening", "45:00 The Death Star", "55:00 Rescuing Leia"]


def test_without_named_chapters_an_outline_from_the_subtitles_is_given():
    cues = [Cue(s, s + 2, f"line at {s}") for s in range(0, 1200, 30)]
    library = Library(
        [[_watching(600)]], chapters=[Chapter(0, "Chapter 1"), Chapter(300, "Chapter 2")], cues=cues
    )
    answer = asyncio.run(_service(library).scene("the living room", minutes=1, chapters=True))
    assert "chapters" not in answer
    assert answer["outline"][0].startswith("0:00 ")
    assert answer["outline"][1].startswith("5:00 ")


def test_an_outline_takes_a_few_lines_from_each_stretch_and_stays_short():
    cues = [Cue(float(s), s + 2.0, "word " * 10) for s in range(0, 7200, 10)]
    lines = outline(cues, every=300, limit=3000)
    assert len(lines) == 24
    assert sum(len(line) for line in lines) <= 3000

# SPDX-License-Identifier: GPL-3.0-or-later
"""What is happening in the film now: the subtitle lines around where it is."""

import asyncio

from tv_mcp.media import Cue, Session, parse_srt, scene_lines
from tv_mcp.service import TvService
from tv_mcp.settings import Settings, Tv

SRT = """1
00:00:01,000 --> 00:00:03,000
<i>A long time ago...</i>

2
00:10:00,500 --> 00:10:02,000
Help me, Obi-Wan Kenobi.
You're my only hope.

3
00:11:30,000 --> 00:11:32,000
These aren't the droids
you're looking for.

4
00:20:00,000 --> 00:20:01,000
That's no moon.
"""

LIVING = Tv(key="living-room", names=("the living room",), address="192.0.2.10")
UPSTAIRS = Tv(key="upstairs", names=("upstairs",), address="192.0.2.11", hands_off=True)


def test_subtitles_are_read_from_srt_without_their_markup():
    cues = parse_srt(SRT)
    assert cues[0] == Cue(start=1.0, end=3.0, text="A long time ago...")
    assert cues[1] == Cue(start=600.5, end=602.0, text="Help me, Obi-Wan Kenobi. You're my only hope.")
    assert len(cues) == 4


def test_the_scene_is_the_lines_within_the_window_around_the_position():
    lines = scene_lines(parse_srt(SRT), position=11 * 60, window=2 * 60)
    assert lines == [
        "10:00 Help me, Obi-Wan Kenobi. You're my only hope.",
        "11:30 These aren't the droids you're looking for.",
    ]


def test_a_long_scene_is_cut_to_the_lines_nearest_the_position():
    cues = [Cue(start=float(s), end=s + 1.0, text="word " * 20) for s in range(0, 240, 2)]
    lines = scene_lines(cues, position=120, window=120, limit=400)
    assert sum(len(line) for line in lines) <= 400
    assert any(line.startswith("2:00 ") for line in lines)
    assert lines == sorted(
        lines, key=lambda line: int(line.split(":")[0]) * 60 + int(line.split()[0].split(":")[1])
    )


class SceneLibrary:
    def __init__(self, sessions, subtitles):
        self._sessions, self._subtitles, self.asked = sessions, subtitles, []

    async def sessions(self):
        return list(self._sessions)

    async def subtitles(self, item_id):
        self.asked.append(item_id)
        return self._subtitles

    async def cast(self, item_id):
        return [("Luke Skywalker", "Mark Hamill")]


WATCHING = Session(
    id="s1",
    address="192.0.2.10",
    client="Jellyfin for Tizen",
    controllable=True,
    now_playing="A New Hope",
    item_id="a1",
    position=11 * 60,
    runtime=7200,
)


def _service(library, *tvs):
    async def no_listen(recognises, target):
        return []

    return TvService(Settings(tvs=tvs or (LIVING,)), drivers={}, listen=no_listen, library=library)


def test_scene_gives_title_time_and_the_lines_around_it():
    library = SceneLibrary([WATCHING], parse_srt(SRT))
    answer = asyncio.run(_service(library).scene("the living room", minutes=2))
    assert answer["outcome"] == "done"
    assert (answer["title"], answer["at"]) == ("A New Hope", "11 min")
    assert len(answer["lines"]) == 2
    assert answer["cast"] == ["Luke Skywalker: Mark Hamill"]
    assert library.asked == ["a1"]


def test_scene_needs_something_playing():
    idle = Session(id="s1", address="192.0.2.10", client="Jellyfin for Tizen", controllable=True)
    answer = asyncio.run(_service(SceneLibrary([idle], [])).scene("the living room", minutes=2))
    assert answer["outcome"] == "refused"


def test_a_film_without_subtitles_is_said_plainly():
    answer = asyncio.run(_service(SceneLibrary([WATCHING], None)).scene("the living room", minutes=2))
    assert answer["outcome"] == "refused"
    assert "subtitles" in answer["say"]


def test_a_hands_off_tv_is_never_read_for_its_scene():
    upstairs = Session(
        id="s2",
        address="192.0.2.11",
        client="Jellyfin for Tizen",
        controllable=True,
        now_playing="A New Hope",
        item_id="a1",
        position=60,
    )
    library = SceneLibrary([upstairs], parse_srt(SRT))
    answer = asyncio.run(_service(library, LIVING, UPSTAIRS).scene("upstairs", minutes=2))
    assert answer["outcome"] == "refused"
    assert library.asked == []

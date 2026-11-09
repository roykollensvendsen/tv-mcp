# SPDX-License-Identifier: GPL-3.0-or-later
"""The sentences read aloud say how far a film has got."""

from tv_mcp.tools.say import items_line, tv_lines


def test_a_search_says_where_a_film_was_stopped_and_when():
    items = [{"title": "A New Hope", "year": 1977, "stopped_at": "1 h 12 min", "last_watched": "2026-11-08"}]
    assert items_line("hope", items) == "Found: A New Hope (1977), stopped at 1 h 12 min on 2026-11-08."


def test_status_says_what_is_playing_how_far_in_and_what_is_left():
    playing = {"title": "A New Hope", "at": "1 h 12 min", "left": "49 min", "paused": False}
    line = tv_lines([{"tv": "stua nede", "state": "on", "playing": playing}])
    assert line == "Stua nede is on, playing A New Hope: 1 h 12 min in, 49 min left."


def test_status_says_when_a_film_is_paused():
    playing = {"title": "A New Hope", "at": "1 h 12 min", "left": "49 min", "paused": True}
    line = tv_lines([{"tv": "stua nede", "state": "on", "playing": playing}])
    assert line == "Stua nede is on, A New Hope is paused: 1 h 12 min in, 49 min left."

# SPDX-License-Identifier: GPL-3.0-or-later
"""A TV's YouTube pairing is kept, made again when it has run out, and a refused one is said.

The Lounge pairs once with the screen id the TV's YouTube app gives, and the
pairing is kept beside the settings. YouTube lets a kept pairing run out; then
its refresh fails, and the screen id makes a new one. A screen that will not
pair at all is said as that, not as a video that "did not start".
"""

import asyncio
import json
import types

from test_youtube import TRAILER, Videos, YouTubeTv, _service

from tv_mcp.drivers.youtube import lounge_pairing


class Api:
    """pyytlounge's YtLoungeApi, as far as pairing goes: `kept` is the pairing in the file."""

    def __init__(self, *, refreshes=True, pairs=True):
        self.auth = types.SimpleNamespace(screen_id=None)
        self.refreshes, self.pairs, self.asked = refreshes, pairs, []

    def load_auth_state(self, state):
        self.auth.screen_id = state["screen_id"]

    def store_auth_state(self):
        return {"screen_id": self.auth.screen_id}

    async def refresh_auth(self):
        self.asked.append("refresh")
        if isinstance(self.refreshes, Exception):
            raise self.refreshes
        return self.refreshes

    async def pair_with_screen_id(self, screen_id):
        self.asked.append("pair")
        if self.pairs:
            self.auth.screen_id = screen_id
        return self.pairs


def _pair(tmp_path, api, *, kept="screen-1"):
    file = tmp_path / "den-youtube"
    if kept:
        file.write_text(json.dumps({"screen_id": kept}))
    return asyncio.run(lounge_pairing(api, file, "screen-1")), file


def test_a_kept_youtube_pairing_that_still_works_is_used_as_it_is(tmp_path):
    api = Api()
    paired, _ = _pair(tmp_path, api)
    assert paired is True
    assert api.asked == ["refresh"]


def test_an_expired_youtube_pairing_is_made_again_from_the_screen(tmp_path):
    api = Api(refreshes=False)
    paired, file = _pair(tmp_path, api)
    assert paired is True
    assert api.asked == ["refresh", "pair"]
    assert json.loads(file.read_text()) == {"screen_id": "screen-1"}
    assert file.stat().st_mode & 0o077 == 0


def test_a_youtube_pairing_whose_refresh_breaks_is_made_again(tmp_path):
    api = Api(refreshes=ConnectionError("the refresh was cut off"))
    paired, _ = _pair(tmp_path, api)
    assert paired is True
    assert api.asked == ["refresh", "pair"]


def test_a_pairing_for_another_screen_is_not_refreshed_but_made_anew(tmp_path):
    api = Api()
    paired, _ = _pair(tmp_path, api, kept="screen-9")
    assert paired is True
    assert api.asked == ["pair"]


def test_a_screen_that_will_not_pair_keeps_nothing(tmp_path):
    api = Api(pairs=False)
    paired, file = _pair(tmp_path, api, kept=None)
    assert paired is False
    assert not file.exists()


class Unpaired:
    advert = False

    async def play(self, tv_key, screen_id, video_id):
        self.refusal = "unpaired"
        return False


def test_a_youtube_screen_that_will_not_pair_is_said_as_that():
    answer = asyncio.run(
        _service(Videos([TRAILER]), Unpaired(), YouTubeTv()).play_youtube(TRAILER.id, "the living room")
    )
    assert answer["outcome"] == "refused"
    assert answer["say"] == (
        "YouTube on the living room would not pair with tv-mcp. Open YouTube on the TV, then ask again."
    )

# SPDX-License-Identifier: GPL-3.0-or-later
"""YouTube by voice: finding a video and starting it on a TV, honestly."""

import asyncio

import httpx

from tv_mcp.drivers.samsung_tizen import SamsungTizen
from tv_mcp.drivers.youtube import (
    FirstThatAnswers,
    StartWatch,
    video_from_page,
    videos_from_api,
    videos_from_search,
)
from tv_mcp.service import TvService
from tv_mcp.settings import Settings, Tv
from tv_mcp.video import Video, is_video_id

LIVING = Tv(key="living-room", names=("the living room",), address="192.0.2.10")
UPSTAIRS = Tv(key="upstairs", names=("upstairs",), address="192.0.2.11", hands_off=True)
TRAILER = Video(
    id="XHk5kCIiGoM", title="STAR WARS Original Trailer", channel="The ReDiscovered Future", duration=122
)


def test_search_results_keep_title_channel_and_length_and_leave_out_live_and_shorts():
    entries = [
        {
            "id": "XHk5kCIiGoM",
            "title": "STAR WARS Original Trailer",
            "channel": "The ReDiscovered Future",
            "duration": 122,
        },
        {
            "id": "aaaaaaaaaaa",
            "title": "Live now",
            "channel": "C",
            "duration": None,
            "live_status": "is_live",
        },
        {"id": "bbbbbbbbbbb", "title": "A short", "channel": "C", "duration": 30},
    ]
    assert videos_from_search(entries) == [TRAILER]


def test_the_data_api_gives_the_same_videos_with_their_length():
    search = {
        "items": [
            {
                "id": {"videoId": "XHk5kCIiGoM"},
                "snippet": {
                    "title": "STAR WARS Original Trailer",
                    "channelTitle": "The ReDiscovered Future",
                    "liveBroadcastContent": "none",
                },
            }
        ]
    }
    details = {"items": [{"id": "XHk5kCIiGoM", "contentDetails": {"duration": "PT2M2S"}}]}
    assert videos_from_api(search, details) == [TRAILER]


def test_the_fallback_search_is_used_when_the_first_finds_nothing_or_fails():
    class Fails:
        async def search(self, words):
            raise RuntimeError(words)

    class Finds:
        async def search(self, words):
            return [TRAILER]

        async def video(self, video_id):
            return TRAILER

    assert asyncio.run(FirstThatAnswers(Fails(), Finds()).search("star wars")) == [TRAILER]
    assert asyncio.run(FirstThatAnswers(Finds(), Fails()).search("star wars")) == [TRAILER]
    assert asyncio.run(FirstThatAnswers(Fails(), Finds()).video("XHk5kCIiGoM")) == TRAILER


def test_a_video_id_is_told_from_words():
    assert is_video_id("XHk5kCIiGoM")
    assert not is_video_id("star wars")
    assert not is_video_id("Darth Vader")


class Videos:
    def __init__(self, found):
        self.found, self.asked = found, []

    async def search(self, words):
        self.asked.append(words)
        return list(self.found)

    async def video(self, video_id):
        return next((v for v in self.found if v.id == video_id), None)


class Lounge:
    def __init__(self, *, starts=True):
        self.starts, self.played = starts, []

    async def play(self, tv_key, screen_id, video_id):
        self.played.append((tv_key, screen_id, video_id))
        return self.starts


class YouTubeTv:
    key = "samsung-tizen"
    ssdp_target = "x"

    def __init__(self, screen="screen-1"):
        self.screen, self.asked = screen, []

    def recognises(self, announcement):
        return False

    async def read_info(self, address):
        return None

    async def youtube_screen(self, address):
        self.asked.append(address)
        return self.screen


def _service(videos, lounge, driver, *tvs):
    async def no_listen(recognises, target):
        return []

    return TvService(
        Settings(tvs=tvs or (LIVING,)),
        drivers={driver.key: driver},
        listen=no_listen,
        videos=videos,
        lounge=lounge,
    )


def test_youtube_search_says_title_channel_and_length():
    service = _service(Videos([TRAILER]), Lounge(), YouTubeTv())
    found = asyncio.run(service.search_youtube("star wars trailer"))
    assert found["items"] == [
        {
            "id": "XHk5kCIiGoM",
            "title": "STAR WARS Original Trailer",
            "channel": "The ReDiscovered Future",
            "length": "2 min",
        }
    ]
    assert "The ReDiscovered Future" in found["say"]


def test_playing_words_starts_the_best_match_and_says_so_once_it_plays():
    lounge, driver = Lounge(), YouTubeTv()
    answer = asyncio.run(
        _service(Videos([TRAILER]), lounge, driver).play_youtube("star wars trailer", "the living room")
    )
    assert lounge.played == [("living-room", "screen-1", "XHk5kCIiGoM")]
    assert answer["outcome"] == "playing"
    assert "STAR WARS Original Trailer" in answer["say"]


def test_playing_a_video_id_does_not_search_but_names_the_video():
    videos, lounge = Videos([TRAILER]), Lounge()
    answer = asyncio.run(_service(videos, lounge, YouTubeTv()).play_youtube("XHk5kCIiGoM", "the living room"))
    assert videos.asked == []
    assert lounge.played[0][2] == "XHk5kCIiGoM"
    assert answer["video"]["channel"] == "The ReDiscovered Future"
    assert "STAR WARS Original Trailer" in answer["say"]


def test_one_videos_page_gives_its_title_channel_and_length():
    page = {
        "id": "XHk5kCIiGoM",
        "title": "STAR WARS Original Trailer",
        "channel": "The ReDiscovered Future",
        "duration": 122,
    }
    assert video_from_page(page) == TRAILER
    assert video_from_page({"id": "x"}) is None


def test_a_video_counts_as_started_only_once_the_screen_says_it_plays_it():
    watch = StartWatch("XHk5kCIiGoM")
    watch.now_playing(None, "Stopped")
    watch.now_playing("XHk5kCIiGoM", "Starting")
    watch.playback("Starting")
    assert not watch.started.is_set()
    watch.playback("Playing")
    assert watch.started.is_set()


def test_another_video_playing_does_not_count():
    watch = StartWatch("XHk5kCIiGoM")
    watch.now_playing("HHbt6rPuC3M", "Playing")
    watch.playback("Playing")
    assert not watch.started.is_set()


def test_a_video_that_does_not_start_is_said_plainly():
    answer = asyncio.run(
        _service(Videos([TRAILER]), Lounge(starts=False), YouTubeTv()).play_youtube(
            "star wars trailer", "the living room"
        )
    )
    assert answer["outcome"] == "refused"
    assert "did not start" in answer["say"]


def test_youtube_that_does_not_open_is_said_plainly():
    lounge = Lounge()
    answer = asyncio.run(
        _service(Videos([TRAILER]), lounge, YouTubeTv(screen=None)).play_youtube(
            "star wars trailer", "the living room"
        )
    )
    assert answer["outcome"] == "refused"
    assert lounge.played == []


def test_a_hands_off_tv_never_gets_youtube():
    driver, lounge = YouTubeTv(), Lounge()
    answer = asyncio.run(
        _service(Videos([TRAILER]), lounge, driver, LIVING, UPSTAIRS).play_youtube(
            "star wars trailer", "upstairs"
        )
    )
    assert answer["outcome"] == "refused"
    assert (driver.asked, lounge.played) == ([], [])


def test_without_the_youtube_feature_set_up_it_is_said_plainly():
    answer = asyncio.run(_service(None, None, YouTubeTv()).play_youtube("star wars", "the living room"))
    assert answer["outcome"] == "refused"
    assert "YouTube" in answer["say"]


DIAL = """<?xml version="1.0" encoding="UTF-8"?>
<service xmlns="urn:dial-multiscreen-org:schemas:dial" dialVer="1.7">
  <name>YouTube</name><state>running</state>
  <additionalData><screenId>screen-7</screenId></additionalData>
</service>"""


def test_a_samsung_opens_youtube_and_gives_its_screen_id_over_dial():
    seen = []

    def handler(request):
        seen.append((request.method, request.url.port, request.url.path, request.headers.get("origin")))
        if request.url.port == 8002:
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(200, text=DIAL)

    async def run():
        transport = httpx.MockTransport(handler)
        async with (
            httpx.AsyncClient(transport=transport) as client,
            httpx.AsyncClient(transport=transport) as tls,
        ):

            async def no_wait(seconds):
                return None

            tv = SamsungTizen(client, tls_client=tls, sleep=no_wait)
            return await tv.youtube_screen("192.0.2.10")

    assert asyncio.run(run()) == "screen-7"
    assert ("POST", 8002, "/api/v2/applications/111299001912", None) in seen
    assert ("GET", 8080, "/ws/apps/YouTube", "https://www.youtube.com") in seen


def test_with_youtube_set_up_search_and_play_take_a_source_and_no_tool_is_added():
    from tv_mcp.server import build_server  # noqa: PLC0415

    service = _service(Videos([TRAILER]), Lounge(), YouTubeTv())
    server = build_server(service, features=["status", "media", "youtube"], simulated=True)
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    assert sorted(tools) == ["tv_control", "tv_play", "tv_search", "tv_status"]
    assert "source" in tools["tv_search"].input_schema["properties"]
    answer = asyncio.run(
        server.call_tool(
            "tv_play", {"title": "star wars trailer", "tv": "the living room", "source": "youtube"}
        )
    ).structured_content
    assert answer["outcome"] == "playing"


def test_a_youtube_key_beside_the_settings_is_read(tmp_path):
    from tv_mcp.settings import load_settings  # noqa: PLC0415

    settings = tmp_path / "config.toml"
    settings.write_text("")
    (tmp_path / "youtube-key").write_text("example-youtube-key\n")
    assert load_settings(settings).youtube_key == "example-youtube-key"


def test_an_advert_before_the_video_counts_as_started_and_is_said():
    watch = StartWatch("XHk5kCIiGoM")
    watch.now_playing("XHk5kCIiGoM", "Advertisement")
    assert watch.started.is_set()
    assert watch.advert
    lounge = Lounge()
    lounge.advert = True
    answer = asyncio.run(
        _service(Videos([TRAILER]), lounge, YouTubeTv()).play_youtube("XHk5kCIiGoM", "the living room")
    )
    assert answer["say"].endswith("after an advert.")


def test_a_youtube_screen_waiting_for_a_profile_gets_a_refusal_that_says_so_and_never_a_raw_error():
    # 2026-11-09: The Frame's YouTube showed its profile picker, which answers as YouTube Kids.
    class Kids(Lounge):
        async def play(self, tv_key, screen_id, video_id):
            self.refusal = "kids"
            return False

    answer = asyncio.run(
        _service(Videos([TRAILER]), Kids(), YouTubeTv()).play_youtube(TRAILER.id, "the living room")
    )
    assert answer["outcome"] == "refused"
    assert "pick a profile" in answer["say"].casefold()


def test_a_lounge_that_fails_unexpectedly_gives_a_refusal_not_an_error():
    class Broken(Lounge):
        async def play(self, tv_key, screen_id, video_id):
            message = "the screen hung up"
            raise RuntimeError(message)

    answer = asyncio.run(
        _service(Videos([TRAILER]), Broken(), YouTubeTv()).play_youtube(TRAILER.id, "the living room")
    )
    assert answer["outcome"] == "refused"
    assert "did not start" in answer["say"]

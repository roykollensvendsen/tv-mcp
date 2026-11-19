# SPDX-License-Identifier: GPL-3.0-or-later
"""A TV woken through its Chromecast takes about half a minute to come on.

Measured on the garage TV on 19.11: the yes at 10.53.46, and the screen seen on 25.6 s
later, while a confirm had 10 s then. So the confirm now watches a wake for 40 s, and
if the TV is still not on, the voice says when to ask again; asking in the meantime says it is
on its way rather than off. Nothing here switches anything: power is sent once, after the yes.
"""

import asyncio

from test_power import GARAGE, CastWithCec, Clock, PowerDriver, _no_listen

from tv_mcp.power import PowerService
from tv_mcp.service import TvService
from tv_mcp.settings import Settings
from tv_mcp.tools.say import tv_lines


def _garage(clock):
    tv_driver = PowerDriver("off")
    cast = CastWithCec(tv_driver)

    async def wakes(address):
        cast.woken.append(address)
        return True

    async def not_yet(address):
        return False

    async def ticking(seconds):
        clock.now += seconds

    cast.wake_screen, cast.screen_on = wakes, not_yet
    service = TvService(
        Settings(tvs=(GARAGE,)),
        drivers={tv_driver.key: tv_driver, cast.key: cast},
        listen=_no_listen,
        clock=clock,
        sleep=ticking,
    )
    return service, tv_driver, cast, ticking


def test_a_tv_woken_through_its_chromecast_is_said_to_take_half_a_minute():
    clock = Clock()
    service, tv_driver, cast, ticking = _garage(clock)
    power = PowerService(service, clock=clock, new_token=lambda: "token-0", sleep=ticking)

    async def answered():
        await power.request("on", "the garage")
        return await power.confirm("token-0")

    answer = asyncio.run(answered())
    assert answer["outcome"] == "starting"
    assert answer["say"] == (
        "I asked the garage to switch on through its Chromecast; it takes about half a minute to come on,"
        " and the Chromecast may take the screen. Ask me again in half a minute whether it is on."
    )
    assert cast.woken == ["192.0.2.20"]
    assert tv_driver.switched == []


def test_a_tv_still_coming_on_is_said_to_be_on_its_way_not_off():
    clock = Clock()
    service, *_ = _garage(clock)
    service.woken_by_hdmi(GARAGE)
    clock.now += 12
    [report] = asyncio.run(service.status("the garage"))
    assert report["screen"] == "off"
    assert report["coming_on"] == 12
    assert tv_lines([report]) == (
        "The garage is off or not reachable, the TV itself is not on yet: it was asked to switch on"
        " 12 s ago, which takes about half a minute."
    )


def test_a_tv_asked_to_come_on_long_ago_and_still_off_is_said_to_be_off():
    clock = Clock()
    service, *_ = _garage(clock)
    service.woken_by_hdmi(GARAGE)
    clock.now += 181  # past the time a wake is still looked after
    [report] = asyncio.run(service.status("the garage"))
    assert "coming_on" not in report
    assert "the TV itself is off" in tv_lines([report])


def test_a_question_to_switch_on_through_the_chromecast_says_how_long_it_takes():
    clock = Clock()
    service, *_ = _garage(clock)
    power = PowerService(service, clock=clock, new_token=lambda: "token-0")
    question = asyncio.run(power.request("on", "the garage"))
    assert question["say"] == (
        "The garage is off. Do you want me to switch it on? That takes about half a minute."
    )


def test_a_tv_still_starting_when_the_confirm_answers_is_said_as_starting_with_its_seconds():
    clock = Clock()
    service, *_, ticking = _garage(clock)
    power = PowerService(service, clock=clock, new_token=lambda: "token-0", sleep=ticking)

    async def answered():
        await power.request("on", "the garage")
        return await power.confirm("token-0")

    answer = asyncio.run(answered())
    assert answer["outcome"] == "starting"
    assert answer["seconds"] == 39.0


def test_a_switch_seen_in_time_gives_the_seconds_it_took():
    clock = Clock()
    service, _, cast, ticking = _garage(clock)
    lit_after = clock.now + 3

    async def lit(address):
        return clock.now >= lit_after

    cast.screen_on = lit
    power = PowerService(service, clock=clock, new_token=lambda: "token-0", sleep=ticking)

    async def answered():
        await power.request("on", "the garage")
        return await power.confirm("token-0")

    answer = asyncio.run(answered())
    assert answer["outcome"] == "done"
    assert answer["seconds"] == 3.0


def test_a_tv_asked_to_come_on_that_did_not_is_said_to_have_probably_failed():
    clock = Clock()
    service, *_ = _garage(clock)
    service.woken_by_hdmi(GARAGE)
    clock.now += 95
    [report] = asyncio.run(service.status("the garage"))
    assert report["not_on_after"] == 95
    assert tv_lines([report]) == (
        "The garage is off or not reachable, the TV itself has not come on: it was asked to switch on"
        " 95 s ago, and it usually takes about half a minute. Ask me to switch it on again."
    )


def test_the_screen_behind_a_chromecast_is_read_through_hdmi_before_the_tv_answers():
    # The garage TV's own port answered about 75 s after it came on (10.11); HDMI knows at once.
    clock = Clock()
    service, _, cast, _ = _garage(clock)

    async def lit(address):
        return True

    cast.screen_on = lit
    [report] = asyncio.run(service.status("the garage"))
    assert report["screen"] == "on"


def test_a_screen_neither_hdmi_nor_the_tv_can_tell_is_said_as_not_known():
    clock = Clock()
    service, _, cast, _ = _garage(clock)

    async def cannot_tell(address):
        return None

    cast.screen_on = cannot_tell
    [report] = asyncio.run(service.status("the garage"))
    assert report["screen"] == "not known"


def test_a_screen_hdmi_calls_off_but_the_tv_says_is_on_is_said_as_on():
    # The garage set left is_stand_by True while it was on (10.11): HDMI's "off" is not the last word.
    clock = Clock()
    service, tv_driver, *_ = _garage(clock)
    tv_driver.power = "on"
    [report] = asyncio.run(service.status("the garage"))
    assert report["screen"] == "on"


def test_a_tv_woken_through_its_chromecast_is_watched_until_it_has_had_time_to_come_on():
    # The garage TV came on 25.6 s after the yes (19.11): the confirm sees it, in the same answer.
    clock = Clock()
    service, tv_driver, cast, ticking = _garage(clock)
    power = PowerService(service, clock=clock, new_token=lambda: "token-0", sleep=ticking)

    async def answered():
        await power.request("on", "the garage")
        yes = clock.now

        async def on_after_a_while(address):
            return clock.now - yes >= 26

        cast.screen_on = on_after_a_while
        return await power.confirm("token-0")

    answer = asyncio.run(answered())
    assert answer["outcome"] == "done"
    assert 26 <= answer["seconds"] <= 27
    assert cast.woken == ["192.0.2.20"]
    assert tv_driver.switched == []


def test_a_wait_for_a_tv_lasts_as_long_as_the_garage_tv_takes_to_come_on():
    clock = Clock()
    service, _tv, cast, _ = _garage(clock)
    started = clock.now

    async def on_after_a_while(address):
        return clock.now - started >= 26

    cast.screen_on = on_after_a_while
    waited = asyncio.run(service.wait_for("the garage", "on"))
    assert waited["reached"] is True


def test_the_time_for_one_answer_covers_the_longest_wait_for_a_tv_to_come_on():
    from tv_mcp import power, server, service  # noqa: PLC0415
    from tv_mcp.drivers import chromecast  # noqa: PLC0415

    # The switch through the Chromecast, then the watch, both inside one answer.
    assert chromecast.CONNECT_TIMEOUT < power.WAKE_CONFIRM_WITHIN < server.ANSWER_WITHIN
    assert service.WAIT_WITHIN < server.ANSWER_WITHIN

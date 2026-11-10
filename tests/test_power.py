# SPDX-License-Identifier: GPL-3.0-or-later
"""Switching a TV on or off: a question first, and the switch only after a yes."""

import asyncio

from tv_mcp.driver import TvInfo
from tv_mcp.power import PowerService
from tv_mcp.service import TvService
from tv_mcp.settings import Settings, Tv

LIVING = Tv(
    key="living-room", names=("the living room", "The Frame"), address="192.0.2.10", mac="00:00:5E:00:53:01"
)
UPSTAIRS = Tv(key="upstairs", names=("upstairs",), address="192.0.2.11", hands_off=True)


class PowerDriver:
    key = "samsung-tizen"
    ssdp_target = "x"

    def __init__(self, power="on", *, obeys=True):
        self.power, self.switched, self.obeys = power, [], obeys

    def recognises(self, announcement):
        return False

    async def read_info(self, address):
        if self.power == "off":
            return None
        return TvInfo(
            name="The Frame", model="QE55LS03BAUXXC", year=2022, platform="Tizen 6.5", power=self.power
        )

    async def switch(self, tv, *, on):
        self.switched.append((tv.key, on))
        if self.obeys:
            self.power = "on" if on else "off"
        return True


async def _no_listen(recognises, target):
    return []


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _power(driver, *tvs, clock=None):
    service = TvService(Settings(tvs=tvs or (LIVING,)), drivers={driver.key: driver}, listen=_no_listen)
    tokens = iter(f"token-{n}" for n in range(100))
    return PowerService(service, clock=clock or Clock(), new_token=lambda: next(tokens), sleep=_no_wait)


async def _no_wait(seconds):
    return None


def _run(coroutine):
    return asyncio.run(coroutine)


def test_a_request_asks_a_question_and_switches_nothing():
    driver = PowerDriver("on")
    question = _run(_power(driver).request("off", "The Frame"))
    assert question["outcome"] == "question"
    assert question["say"] == "Switch the living room off?"
    assert question["token"] == "token-0"  # noqa: S105 - a test token
    assert driver.switched == []


def test_nothing_switches_without_the_token_from_the_question():
    driver = PowerDriver("on")
    power = _power(driver)
    _run(power.request("off", "The Frame"))
    assert _run(power.confirm("made-up"))["outcome"] == "refused"
    assert driver.switched == []
    assert _run(power.confirm("token-0"))["outcome"] == "done"
    assert driver.switched == [("living-room", False)]


def test_a_power_token_works_once():
    # A TV that stays on, so only the token can refuse the second confirm.
    driver = PowerDriver("on", obeys=False)
    power = _power(driver)
    _run(power.request("off", "The Frame"))
    _run(power.confirm("token-0"))
    assert _run(power.confirm("token-0"))["outcome"] == "refused"
    assert driver.switched == [("living-room", False)]


def test_a_power_token_expires_after_thirty_seconds():
    driver, clock = PowerDriver("on"), Clock()
    power = _power(driver, clock=clock)
    _run(power.request("off", "The Frame"))
    clock.now += 31
    answer = _run(power.confirm("token-0"))
    assert answer["outcome"] == "refused"
    assert "expired" in answer["say"]
    assert driver.switched == []


def test_only_the_latest_question_can_be_confirmed():
    driver = PowerDriver("on")
    power = _power(driver)
    _run(power.request("off", "The Frame"))
    _run(power.request("off", "The Frame"))
    assert _run(power.confirm("token-0"))["outcome"] == "refused"
    assert driver.switched == []


def test_a_request_the_tv_already_satisfies_is_refused():
    driver = PowerDriver("on")
    answer = _run(_power(driver).request("on", "The Frame"))
    assert answer["outcome"] == "refused"
    assert "already on" in answer["say"]


def test_a_tv_in_standby_or_art_mode_counts_as_off():
    driver = PowerDriver("standby")
    assert _run(_power(driver).request("on", "The Frame"))["outcome"] == "question"


def test_a_switch_is_refused_when_the_tv_changed_since_the_question():
    driver = PowerDriver("on")
    power = _power(driver)
    _run(power.request("off", "The Frame"))
    driver.power = "off"
    answer = _run(power.confirm("token-0"))
    assert answer["outcome"] == "refused"
    assert driver.switched == []


def test_a_hands_off_tv_is_never_switched():
    driver = PowerDriver("off")
    answer = _run(_power(driver, LIVING, UPSTAIRS).request("on", "upstairs"))
    assert answer["outcome"] == "refused"
    # Refused for being hands-off, not merely because its state cannot be read.
    assert "left alone" in answer["say"]
    assert "token" not in answer
    assert driver.switched == []


def test_an_unknown_state_word_is_refused():
    assert _run(_power(PowerDriver()).request("sideways", "The Frame"))["outcome"] == "refused"


def test_a_driver_that_cannot_switch_is_refused():
    class Plain(PowerDriver):
        switch = None

    answer = _run(_power(Plain("on")).request("off", "The Frame"))
    assert answer["outcome"] == "refused"


def test_a_switch_is_refused_when_the_tv_state_is_not_known():
    driver = PowerDriver("unknown")
    answer = _run(_power(driver).request("off", "The Frame"))
    assert answer["outcome"] == "refused"
    assert "token" not in answer


def test_a_switch_is_done_only_once_the_tv_is_seen_in_its_new_state():
    driver = PowerDriver("on")
    power = _power(driver)
    _run(power.request("off", "The Frame"))
    answer = _run(power.confirm("token-0"))
    assert answer["outcome"] == "done"
    assert "off now" in answer["say"]


def test_a_tv_that_does_not_change_after_the_key_is_not_called_switched():
    # 2026-11-09: the garage TV let tv-mcp in and stayed on, and the voice said it was switching off.
    driver = PowerDriver("on", obeys=False)
    power = _power(driver)
    _run(power.request("off", "The Frame"))
    answer = _run(power.confirm("token-0"))
    assert answer["outcome"] == "unverified"
    assert "not off yet" in answer["say"]
    assert driver.switched == [("living-room", False)]


def test_a_switch_that_does_not_take_is_answered_within_the_voices_time_limit():
    # 2026-11-09: switching the garage TV on hung past the voice's 30 seconds and came back as a raw error.
    from tv_mcp.power import SETTLE  # noqa: PLC0415

    clock = Clock()
    service = TvService(
        Settings(tvs=(LIVING,)), drivers={"samsung-tizen": PowerDriver("on", obeys=False)}, listen=_no_listen
    )

    async def ticking(seconds):
        clock.now += seconds

    tokens = iter(f"token-{n}" for n in range(9))
    power = PowerService(service, clock=clock, new_token=lambda: next(tokens), sleep=ticking)
    _run(power.request("off", "The Frame"))
    started = clock.now
    answer = _run(power.confirm("token-0"))
    assert answer["outcome"] == "unverified"
    assert clock.now - started <= SETTLE
    assert SETTLE <= 15


class CastWithCec:
    """A Chromecast in a TV, which wakes the TV over HDMI and can tell when its screen is on."""

    key = "chromecast"
    ssdp_target = "y"

    def __init__(self, tv_driver):
        self.tv_driver, self.woken = tv_driver, []

    def recognises(self, announcement):
        return False

    async def read_info(self, address):
        return None

    async def wake_screen(self, address):
        self.woken.append(address)
        self.tv_driver.power = "on"
        return True

    async def screen_on(self, address):
        return self.tv_driver.power == "on"


GARAGE = Tv(
    key="garage",
    names=("the garage",),
    address="192.0.2.20",
    driver="chromecast",
    power_driver="samsung-tizen",
    power_address="192.0.2.21",
    power_on="cec",
)


def _power_with_cast(tv_driver, cast):
    service = TvService(
        Settings(tvs=(GARAGE,)), drivers={tv_driver.key: tv_driver, cast.key: cast}, listen=_no_listen
    )
    return PowerService(service, clock=Clock(), new_token=lambda: "token-0", sleep=_no_wait)


def test_a_tv_set_to_wake_by_cec_is_switched_on_through_the_device_in_it():
    # 2026-11-10: the 2012 garage TV ignores wake packets, but wakes when its Chromecast starts an app.
    tv_driver = PowerDriver("off")
    cast = CastWithCec(tv_driver)
    power = _power_with_cast(tv_driver, cast)
    _run(power.request("on", "the garage"))
    answer = _run(power.confirm("token-0"))
    assert cast.woken == ["192.0.2.20"]
    assert tv_driver.switched == []
    assert answer["outcome"] == "done", answer


def test_a_tv_set_to_wake_by_cec_is_still_switched_off_through_its_power_driver():
    tv_driver = PowerDriver("on")
    cast = CastWithCec(tv_driver)
    power = _power_with_cast(tv_driver, cast)
    _run(power.request("off", "the garage"))
    _run(power.confirm("token-0"))
    assert tv_driver.switched == [("garage", False)]
    assert cast.woken == []


def test_the_screen_counts_as_on_when_the_device_in_it_says_so_before_the_tv_answers():
    # The garage TV takes most of a minute to answer on the network; its Chromecast knows sooner.
    tv_driver = PowerDriver("off")
    cast = CastWithCec(tv_driver)

    async def lit(address):
        return True

    cast.screen_on = lit
    power = _power_with_cast(tv_driver, cast)
    assert _run(power.request("on", "the garage"))["outcome"] == "refused"


def test_a_tv_woken_by_cec_that_is_not_seen_on_in_time_is_said_to_be_on_its_way():
    # 2026-11-10: the garage TV woke, but answered on the network only after about 75 s,
    # and its Chromecast kept saying standby; "not on yet" sounded like a failure.
    tv_driver = PowerDriver("off")
    cast = CastWithCec(tv_driver)

    async def wakes_slowly(address):
        cast.woken.append(address)
        return True

    async def cannot_tell(address):
        return None

    cast.wake_screen, cast.screen_on = wakes_slowly, cannot_tell
    power = _power_with_cast(tv_driver, cast)
    _run(power.request("on", "the garage"))
    answer = _run(power.confirm("token-0"))
    assert answer["outcome"] == "unverified"
    assert answer["say"] == "I asked the garage to switch on; it can take a minute before it is on."

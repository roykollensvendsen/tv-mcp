# SPDX-License-Identifier: GPL-3.0-or-later
"""Whether the TV behind a Chromecast is on is read as the Chromecast answers now.

The Chromecast tells a kept connection its state when something on it changes, such as an
app starting. A TV woken over HDMI comes on a while after the waker app has started and
closed, and the Chromecast need not say so again; read from what it last said, the TV
stayed "off" for minutes after it came on (seen on the garage TV, 18.11).
"""

import threading
import time
from types import SimpleNamespace

from tv_mcp.drivers.chromecast import fresh_status

STANDBY = SimpleNamespace(is_stand_by=True)
ON = SimpleNamespace(is_stand_by=False)


class _Cast:
    """A kept connection whose last word was standby, and whose answer to a fresh ask is `now`."""

    def __init__(self, now, *, answers=True):
        self.status = STANDBY
        receiver = SimpleNamespace(update_status=self._update_status)
        self.socket_client = SimpleNamespace(receiver_controller=receiver)
        self._now, self._answers = now, answers
        self.asked = 0

    def _update_status(self, *, callback_function=None):
        self.asked += 1
        if not self._answers:
            return

        def answer():
            self.status = self._now  # as pychromecast does: the status first, then the callback
            if callback_function:
                callback_function(True, {})  # noqa: FBT003 - PyChromecast's own call

        threading.Timer(0.05, answer).start()


def test_the_tv_s_power_is_read_as_it_is_now_not_as_the_chromecast_last_said():
    cast = _Cast(ON)
    assert fresh_status(cast, 5) is ON
    assert cast.asked == 1


def test_a_chromecast_that_does_not_answer_in_time_gives_what_it_last_said():
    cast = _Cast(ON, answers=False)
    started = time.monotonic()
    assert fresh_status(cast, 0.2) is STANDBY
    assert time.monotonic() - started < 5

# SPDX-License-Identifier: GPL-3.0-or-later
"""Each tool answers within the time the voice gives it.

claude-voice gives a plugin tool 30 seconds. A tool still waiting after that is
cut off, and the voice hears only "MCP tool call failed", with nothing to say
to the owner. On 2026-11-09 switching the garage TV on did exactly that.

So each tool's longest path, added up from the waits it makes, has to leave
room inside the limit. A new wait, or a longer one, goes into the sum here.
The paths marked as known to run over are defects, not exceptions: the test
for one turns green, and must then lose its mark, once its waits are cut.
"""

import pytest

from tv_mcp import power, service
from tv_mcp.drivers import jellyfin, samsung_legacy, samsung_tizen, youtube

#: How long claude-voice waits for a plugin tool, in seconds.
VOICE_LIMIT = 30.0
#: Room kept for everything not counted: the bridge, quick calls, the network.
MARGIN = 2.0

OVER = pytest.mark.xfail(strict=True, reason="known to run past the voice's limit")

LONGEST = {
    "power on, a TV before Tizen": samsung_legacy.STANDBY_WAIT + power.SETTLE,
    "power off, a TV before Tizen": samsung_legacy.ANSWER_WAIT + power.SETTLE,
    "play, opening Jellyfin first": samsung_tizen.TIMEOUT + service.OPEN_WAIT + jellyfin.TIMEOUT,
    "close an app, by the home key when refused": (
        samsung_tizen.TIMEOUT + samsung_tizen.KEY_WAIT + samsung_tizen.HOME_TRIES
    ),
    "play a YouTube video": pytest.param(youtube.START_WAIT * youtube.START_TRIES, marks=OVER),
    "play a YouTube video, opening YouTube first": pytest.param(
        samsung_tizen.YOUTUBE_TRIES + youtube.START_WAIT * youtube.START_TRIES, marks=OVER
    ),
    "the scene, from subtitles inside the film": pytest.param(
        jellyfin.SUBTITLE_TIMEOUT + jellyfin.TIMEOUT, marks=OVER
    ),
}


@pytest.mark.parametrize("seconds", LONGEST.values(), ids=LONGEST.keys())
def test_a_tools_longest_wait_fits_in_the_voices_time(seconds):
    assert seconds + MARGIN <= VOICE_LIMIT

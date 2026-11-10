# SPDX-License-Identifier: GPL-3.0-or-later
"""Each tool answers within the time the voice gives it.

claude-voice gives a plugin tool 30 seconds. A tool still waiting after that is
cut off, and the voice hears only "MCP tool call failed", with nothing to say
to the owner. On 2026-11-09 switching the garage TV on did exactly that.

So each tool's longest path, added up from the waits it makes, has to leave
room inside the limit. A new wait, or a longer one, goes into the sum here.
Work that can take longer, such as pulling subtitles out of a film or a screen
starting a video, is left running past a wait of its own, and the voice is told
it is on its way rather than cut off.
"""

import pytest

from tv_mcp import power, service
from tv_mcp.drivers import chromecast, jellyfin, samsung_legacy, samsung_tizen

#: How long claude-voice waits for a plugin tool, in seconds.
VOICE_LIMIT = 30.0
#: Room kept for everything not counted: the bridge, quick calls, the network.
MARGIN = 2.0

LONGEST = {
    "power on, a TV before Tizen": samsung_legacy.STANDBY_WAIT + power.SETTLE,
    "power on, by HDMI from a Chromecast": chromecast.CONNECT_TIMEOUT
    + chromecast.START_TIMEOUT
    + power.SETTLE,
    "power off, a TV before Tizen": samsung_legacy.ANSWER_WAIT + power.SETTLE,
    "play, opening Jellyfin first": samsung_tizen.TIMEOUT + service.OPEN_WAIT + jellyfin.TIMEOUT,
    "close an app, by the home key when refused": (
        samsung_tizen.TIMEOUT + samsung_tizen.KEY_WAIT + samsung_tizen.HOME_TRIES
    ),
    "change input, a TV before Tizen, by its keys when it lists no inputs": (
        samsung_tizen.TIMEOUT
        + samsung_legacy.FIND_WAIT
        + samsung_legacy.AGENT_WAIT
        + samsung_legacy.ANSWER_WAIT
    ),
    "change input, a TV before Tizen, picked and read back": (
        samsung_tizen.TIMEOUT
        + samsung_legacy.FIND_WAIT
        + 3 * samsung_legacy.AGENT_WAIT
        + samsung_legacy.INPUT_SETTLE
    ),
    "change input, by the paired remote": samsung_tizen.TIMEOUT + samsung_tizen.KEY_WAIT,
    "play a YouTube video, opening YouTube first": samsung_tizen.TIMEOUT + service.YOUTUBE_WAIT,
    "the scene, from subtitles inside the film": (
        jellyfin.TIMEOUT + service.SUBTITLE_WAIT + 2 * jellyfin.TIMEOUT
    ),
}


@pytest.mark.parametrize("seconds", LONGEST.values(), ids=LONGEST.keys())
def test_a_tools_longest_wait_fits_in_the_voices_time(seconds):
    assert seconds + MARGIN <= VOICE_LIMIT

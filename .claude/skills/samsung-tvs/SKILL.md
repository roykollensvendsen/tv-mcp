---
name: samsung-tvs
description: What is special about each Samsung TV that tv-mcp controls, and how to get one ready - reading its model and year, developer mode, the full restart, sideloading the Jellyfin app, pairing the remote API, waking it over the network, and the Frame's Art Mode - with one sub-skill per model family. Use it whenever a task touches a real Samsung TV (The Frame, a Q-series QLED, any Tizen set), when developer mode will not open, when port 26101 or 8001/8002 does not answer, when Jellyfin is missing from the TV's app store, or when adding a new Samsung model to tv_setup, even if the user only says "the TV".
---

# Samsung TVs

Samsung TVs since 2016 run Tizen. They differ by model year more than by
size or range, so the knowledge is kept per family, and each family's sub-skill
holds what was tested on a real set, with the date:

| Family | Sub-skill | State |
|---|---|---|
| 2022, Tizen 6.5 (The Frame QE55LS03BAUXXC) | [`samsung-tvs-2022-frame`](../samsung-tvs-2022-frame/SKILL.md) | set up and used, 2026-11-08 |
| 2023, Tizen 7.0 (Q68CA TQ55Q68CAUXXC) | [`samsung-tvs-2023-tizen7`](../samsung-tvs-2023-tizen7/SKILL.md) | **on hold, hands-off** |

## Rules for every Samsung TV

1. **Look before you touch.** The information page,
   `http://<tv>:8001/api/v2/`, needs no pairing, shows nothing and makes no
   sound. It gives the model code (`22_PONTUSM_FTV`: the first two digits are
   the year), `PowerState`, `FrameTVSupport`, `developerMode` and
   `developerIP`. It does not give the Tizen or firmware version; take Tizen
   from the year.
2. **A TV marked `hands_off` in the owner's settings gets nothing**, not even
   that page. Read `~/.config/tv-mcp/config.toml` first.
3. **No answer at all** (no ping, no address resolution) means the TV is off
   in deep standby, not that a setting is wrong. Do not report a setting as
   off from that.
4. **Anything that switches the TV on, makes a sound or shows an Allow prompt
   waits for the owner** to say it suits them.
5. **The owner runs installers themselves.** The Jellyfin installer is code
   from elsewhere, and Claude Code's checks refuse to run it; give the owner
   the exact `!` command and read its output.

6. **An app's id comes from the TV itself**, never from a guess or a list
   online: ids differ by country and firmware. With developer mode on, run
   `sdb connect <tv>:26101` and `sdb shell 0 vd_applist` (the owner runs it;
   `sdb` is in the Jellyfin installer image) and take `app_id`. Check it
   silently with `GET https://<tv>:8002/api/v2/applications/<id>`. The paired
   remote's installed-apps request got no answer from a 2022 Frame, and DIAL
   on port 8080 can see and close an app by name but would not start one
   (2026-11-09).

## The setup steps, in order

Each family's sub-skill says how a step differs on that family.

1. **Jellyfin from the store first.** The official app exists since February
   2026 for 2021-and-newer TVs, but reaches countries one at a time. Search
   from the magnifier *on the Apps page*; the home screen's search shows only
   films.
2. **Developer mode**, when the store has no Jellyfin: the code 12345 is
   typed inside **Apps → App Settings** (at the bottom of the Apps page), not
   on the Apps page itself. Switch it on, enter the computer's address on the
   home network, OK. Check `developerMode: 1` and `developerIP` on the
   information page.
3. **A full restart**, or port 26101 stays closed even though the page says
   developer mode is on. Hold the power button until the Samsung logo; if
   that only switches it off, pull the plug for a minute. Check: port 26101
   answers.
4. **Install Jellyfin** with
   `docker run --ulimit nofile=1024:65536 --rm ghcr.io/georift/install-jellyfin-tizen <tv>`,
   run by the owner. Success ends with `Tizen application is successfully installed.`
   No Samsung certificate was needed on 2022 firmware.
5. **Pair the remote API** (port 8002): the TV shows a box asking to allow
   the app, once. Only when the owner is at the TV with the remote and says it
   suits; tell them first what will appear and to choose Allow within about 30
   seconds. The token goes in a private file in the owner's settings folder,
   never the repository. Missed or denied: see the family's sub-skill.
6. **Wake over the network**: Settings → General → Network → Expert Settings →
   *Power On with Mobile* and *IP Remote*. Over wireless it is unreliable from
   deep standby; plan to fall back to the power key when the TV is in Art Mode.

## Adding a family

Copy the 2022 sub-skill's shape into `samsung-tvs-<year>-<family>/`, write
only what differs and what was tested (with dates), add the row above, and add
the matching `src/tv_mcp/models/<year>-<family>.toml`. Check the family with
skill-creator's `check_family`.

## Keeping it true

When a step here or in a sub-skill turns out wrong on a real TV, correct that
step, in the same change, with the date it was seen.

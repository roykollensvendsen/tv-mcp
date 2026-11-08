---
name: samsung-tvs-2022-frame
description: The 2022 Samsung The Frame on Tizen 6.5 (QE55LS03BAUXXC, model code 22_PONTUSM_FTV) as it behaved on a real set - developer mode via App Settings, the two-try full restart, port 26101, sideloading Jellyfin, Art Mode and the power key. Use it for any work on The Frame or another 2022 Samsung TV. Part of samsung-tvs.
---

# The Frame, 2022, Tizen 6.5

The shared rules and the order of the setup steps are in the parent,
[`samsung-tvs`](../samsung-tvs/SKILL.md). This file holds only what is special
about this family, each with the date it was seen.

## What it reports

- Information page: `model 22_PONTUSM_FTV`, `FrameTVSupport true`, API
  version 2.0.25, `firmwareVersion Unknown`, `networkType wireless`, country
  `NO`. Ports 8001 and 8002 open while on (2026-11-08).
- The Jellyfin app, once installed, has the id `AprZAARz4r.Jellyfin`.

## Setup, as it went on 2026-11-08

1. **Store:** Jellyfin was not in the Norwegian store. Search showed films
   only, because it was the home screen's search.
2. **Developer mode:** 12345 on the Apps page did nothing, with the remote's
   on-screen numbers or SmartThings, fast or slow. Typed inside **App
   Settings** at the bottom of Apps, the window opened at once.
3. **Restart:** the first restart left `developerMode 0`: the setting had not
   been saved. After the second try the page showed `developerMode 1` and
   the right address, but port 26101 stayed closed. It opened about two and a
   half minutes after a full restart.
4. **Install:** the owner ran the georift installer; it connected on 26101,
   found the TV as `QE55LS03BAUXXC`, and installed with the default
   development certificate. No Samsung account was needed.
5. **Pairing:** with the owner sitting at the TV, remote in hand, the first
   connection to the remote API (port 8002) showed a box asking to allow
   *tv-mcp*. Allow was chosen within the 30 seconds and a token came back. It
   is saved in a private file in the owner's settings folder, outside the
   repository, so the box does not come again. Tell the owner what will appear
   and what to press *before* connecting, and never connect while nobody is at
   the TV. If the box was missed, timed out or got Deny: connect again with the
   owner there; after a Deny, allow or delete *tv-mcp* under Settings → General
   → External Device Manager → Device Connection Manager → Device List first.
6. **Playing:** `tv_play` started A New Hope on the open Jellyfin app through
   Jellyfin's session API. The app's session is found by the TV's address.
7. **Power:** `tv_power_confirm` is built and tested with fakes only
   (2026-11-08); it has not yet switched the real Frame. Off holds the power
   key three seconds over the paired connection; on presses it from Art Mode
   or standby, and sends Wake-on-LAN from deep standby. Try it with the owner
   there, both ways, and record what happened here.

## Behaviour to design around

- **Power key:** a short press goes to Art Mode, not off. Off is the power key
  held for about three seconds (what Home Assistant does). In Art Mode the
  network stays awake, so waking from Art Mode is a key, not a Wake-on-LAN
  packet.
- **Standby or art:** `PowerState standby` on a Frame can mean Art Mode is on;
  tv-mcp reports it as "standby or art mode".
- **In the browser** Jellyfin works but is clumsy; the app is the way.
- **Sound:** the film's Dolby Digital 5.1 needs no transcoding in the app; the
  TV's browser would need audio transcoding.

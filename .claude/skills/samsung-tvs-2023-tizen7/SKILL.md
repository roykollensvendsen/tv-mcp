---
name: samsung-tvs-2023-tizen7
description: 2023 Samsung TVs on Tizen 7.0, starting with the Q68CA (TQ55Q68CAUXXC, model code 23_NIKEL_UHD_OS80) - Jellyfin comes from the Norwegian app store, so no developer mode is needed. Use it before any work on the Q68CA or another 2023 Samsung TV. Part of samsung-tvs.
---

# 2023 Samsung TVs, Tizen 7.0

**Ask before sound, prompts or power.** The owner's Q68CA is where the
children sleep. It was on hold from 2026-11-08; the owner lifted the hold
themselves on 2026-11-09 to set it up. Reading it silently is fine; anything that
makes a sound, shows a prompt or switches it waits for the owner, and if the
owner puts the hold back (`hands_off = true`), it gets nothing again.

The shared rules and the setup steps are in the parent,
[`samsung-tvs`](../samsung-tvs/SKILL.md).

## Known so far

- Information page, read once on 2026-11-08 before the hold: `model
  23_NIKEL_UHD_OS80`, `FrameTVSupport false`, wireless, developer mode off.
- Later the same evening it did not answer at all: off in deep standby.

- **Jellyfin is in the Norwegian app store** for the Q68CA (2026-11-09), so
  setup step 1 is the whole install: no developer mode, no full restart, no
  installer. Sign the app in to the server ("remember me") before pairing.
- At power-on it opened YouTube by itself (2026-11-09), and Jellyfin later
  the same day: most likely the TV's own setting to start the last app.
  tv-mcp sends it only silent reads, so look there first.
- **It refuses to close apps** over the app interface (`DELETE
  /api/v2/applications/<id>` fails for Netflix, 2026-11-09), though opening
  works. tv-mcp then presses the remote's Home key over the paired
  connection and counts the app closed once its status says it is no longer
  visible. Home leaves the app running in the background.
- **The store's Jellyfin has another app id** than the sideloaded one on the
  Frame: `AprZAARz4r.Jellyfin` answers 404 here (2026-11-09). Netflix
  (`3201907018807`), YouTube (`111299001912`) and NRK TV (`3202012022410`)
  have the same ids on both. The store id is not known yet; reading it needs
  the installed-apps list over the paired connection.
- The store's Jellyfin says it takes no remote control (2026-11-09), so a
  film cannot be started on it by voice yet.
- Switched on, it answered neither its old address nor an SSDP search
  (2026-11-09): check *Settings → General → Network → Network Status* on the
  TV for the network and address before blaming tv-mcp.

## Not yet known

- Whether developer mode opens from App Settings as on the 2022 Frame (not
  needed for Jellyfin; needed only for `sdb`, for example to read app ids).
- The Norwegian names of *Power On with Mobile* and *IP Remote* on Tizen 7.

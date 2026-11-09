---
name: chromecast
description: How tv-mcp plays Jellyfin films on a Chromecast plugged into a TV that cannot run Jellyfin itself (an older Samsung, or any brand) - finding it with mDNS, the user login the receiver needs, Quick Connect, the receiver's message, pause/stop, and what HDMI-CEC can and cannot do. Use it whenever a task touches a Chromecast or casting, when a cast shows "Ready to cast" but nothing plays, when Jellyfin logs "Guid can't be empty", or when a TV is "not on the network" but has a Chromecast in it.
---

# Chromecast

Tested on a Chromecast ("Garasje") in a 2012 Samsung UE40ES6715, 2026-11-09.

## Rules

1. **Find it silently.** mDNS `_googlecast._tcp` gives its name, model and
   address; `http://<cast>:8008/setup/eureka_info?params=name,device_info,ssdp_udn`
   gives the rest. Neither shows anything on the screen. It may sit on another
   home network than the TVs: check which address it has before concluding it
   is missing, and that the Jellyfin server answers from that network.
2. **Cast through Jellyfin's own receiver app** (`F007D354`, namespace
   `urn:x-cast:com.connectsdk`, message `PlayNow` with the item and
   `startPositionTicks`), not a stream URL to the default receiver. The
   receiver lets the server transcode, keeps subtitles, and reports progress,
   so resuming keeps working.
3. **The receiver needs a user's own login, never the server's API key.** The
   API key belongs to no user: the receiver opens and shows "Ready to cast",
   then nothing plays, and the server logs `Guid can't be empty` for
   `GET /Items/<id>` (2026-11-09). The login lives in `jellyfin-user-token`
   beside the settings, mode 600, never in the repository.
4. **Get the login with Quick Connect**, so no password is seen: start
   `/QuickConnect/Initiate`, give the owner the code, and keep polling
   `/QuickConnect/Connect` for at least ten minutes before trading the secret
   at `/Users/AuthenticateWithQuickConnect`. A five-minute wait ran out while
   the owner was still installing the Jellyfin app on the phone (2026-11-09).
5. **`serverAddress` must be reachable from the Chromecast.** "localhost" in
   the settings means the Chromecast itself; tv-mcp names the server by this
   computer's address on the Chromecast's network.
6. **Each item in `PlayNow` needs its `Name`, `Type` and `MediaType`**
   ("Movie", "Video"). With the id alone the receiver asks the server about
   the item and then never starts the stream: the session sits at 0 min and
   no transcode starts (2026-11-09).
7. **Never leave the receiver.** It closes when its last sender disconnects
   on purpose, so a sender that sends and then disconnects ends the film in
   seconds, while Jellyfin's session keeps guessing a growing position.
   tv-mcp keeps one connection per Chromecast open for as long as it runs.
   Check the Chromecast's own app (`cast.app_display_name`, "Backdrop" means
   idle), not only Jellyfin's session, before believing a film is playing.
8. **A command never launches the receiver.** Launching a running receiver
   restarts it and ends the film. Pause, resume and stop are sent to the
   receiver already running (its own `Pause`, `Unpause`, `Stop`), and refused
   when it is not; the Chromecast's Jellyfin session takes no remote control.
9. **Count a cast as playing only when the receiver says so**: its playback
   report names the item and `CanSeek` is true. Before that it may name the
   item while nothing plays.
10. **Power.** Starting the receiver may switch the TV on and to the
   Chromecast's input over HDMI-CEC (Samsung: Anynet+), not yet tested. A
   Chromecast can never switch its TV off; that needs the TV's own driver.
   tv-mcp reports a Chromecast as "reachable", never "on", because it cannot
   tell whether the screen is on.

## Setting one up

Settings entry: `location`, `address` (the Chromecast's), `driver =
"chromecast"`. Install the `chromecast` extra (PyChromecast, MIT; it brings
zeroconf, LGPL-2.1-or-later). Then the Quick Connect step above, once.

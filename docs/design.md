# Design: voice control for the TV and films

Status: **proposal, waiting for the owner's yes.** Nothing below is built.

The goal is one sentence said to the voice assistant, such as "play A New Hope
on The Frame". The TV switches on, the Jellyfin app opens, and the film starts.
It is an ordinary MCP server, and claude-voice can take it in as an optional
plugin, the same way it takes the garage door and the vacuum.

## The TVs it was measured against

These were read on 2026-11-08 from each TV's own information page, read-only.
Addresses, hardware addresses and names of the home network are kept in the
owner's settings file, never here (see `scripts/private_data_scan.py`).

| | The Frame 55 | Q68CA 55 |
|---|---|---|
| Model | QE55LS03BAUXXC | TQ55Q68CAUXXC |
| Year (from the model code) | 2022 (`22_PONTUSM_FTV`) | 2023 (`23_NIKEL_UHD_OS80`) |
| Tizen | 6.5, from the model year; the TV does not report it | 7.0, from the model year; not reported |
| Software version | not reported (`firmwareVersion: Unknown`) | not reported |
| Local remote API, ports 8001 and 8002 | open, API 2.0.25, token pairing supported | answered earlier in the evening; at later readings the TV did not answer on the network at all (no ping, no address resolution), which is a TV that is off rather than a setting |
| Network | wireless | wireless |
| Developer mode | on (Jellyfin is sideloaded) | off |
| Jellyfin app | installed by developer mode, app id `AprZAARz4r.Jellyfin` | wanted; the store first (2023 is inside the official app's 2021-and-newer range), developer mode if Norway does not have it yet |

Wake-on-LAN was not tested, because sending the packet switches the TV on.
Both TVs are on wireless, and switching a Samsung TV on over wireless is
reported to be unreliable from deep standby. The TV's setting for it is
"Power On with Mobile". The design falls back to the power key when the TV is
only in Art Mode, which keeps the network awake.

## Reuse, and what is built here

| Piece | Choice | Why |
|---|---|---|
| Talking to the TV | **samsungtvws** (LGPL-3.0, released 2026-11-02, the library Home Assistant uses) | keys, holding a key, launching an app by id, Art Mode, token pairing, async |
| Switching on | **wakeonlan** (MIT) | one small function |
| Jellyfin | **httpx** against Jellyfin's own API | three calls are needed (search, list sessions, play); the existing clients are synchronous or out of date |
| MCP | the official `mcp` Python SDK | the same as the garage door and the vacuum |
| Read, not used | Home Assistant's `samsungtv` (`bridge.py`), `renfield-mcp-samsung`, `smartest-tv`, `jaredtrent/jellyfin-mcp` | how others handle the Frame's power key, pairing and Jellyfin sessions |

Built here: the tools, their safety rules, the simulated TV and server for
tests, and the settings file.

Existing Jellyfin MCP servers were judged and left out. One has 368 tools,
which is far too many for a voice. The other is written in Go and has no TV
control.

## Tools

Every tool is named after the plugin. A tool marked *asks* returns a question
and a confirmation token. It acts only when `tv_confirm` comes back with that
token after the owner's own spoken yes, the same pattern as `garage_request`
and `garage_confirm`.

| Tool | Does | Safety |
|---|---|---|
| `tv_status` | whether each TV is on, in Art Mode or off, and what is playing | read-only |
| `tv_power_request` | `tv_power_request(state, tv)`: a question to read aloud ("Switch the living room off?") and a one-time token; switches nothing | *asks* |
| `tv_power_confirm` | `tv_power_confirm(token)`: switches, after the owner's yes. On: the power key when the TV still listens (standby or Art Mode), otherwise Wake-on-LAN. Off: on the Frame, the power key held for three seconds, since a short press only goes to Art Mode | the token works once, expires after 30 s, and only the latest question's counts; refused when the TV changed since the question |
| `tv_confirm` | carries out the one action the token names | the token is used once and expires after a minute |
| `tv_open_app` | `tv_open_app(app, tv)`: opens an app the driver knows by name (on Samsung: Jellyfin, Netflix, YouTube; NRK TV once its id is read from a real set). Part of the opt-in `apps` feature, with `tv_close_app` | only apps the driver knows; never on a hands-off TV; never switches a TV on |
| sound | `tv_control` with `mute`, `unmute` or `volume` (a level 0-100, or up and down with `relative`). Samsung: the standard UPnP volume service on port 9197, which needs no pairing. Chromecast: its own volume, which the TV's volume then scales | never louder than 50 out of 100, said when capped; never on a hands-off TV |
| `tv_scene` | `tv_scene(tv, minutes=2)`: the title, how far in, the subtitle lines within that many minutes either side (at most 1200 characters, those nearest kept) and up to 15 of the cast as character: actor, so the voice can say what is happening or who is likely speaking. A track for the hard of hearing is preferred, since it names who speaks. The opt-in `scene` feature | only reads; never on a hands-off TV; the voice sums the lines up rather than reading them out |
| `tv_key` | one remote key: play, pause, back, home, arrows, OK | no power key; that goes through `tv_power_*` |
| `tv_volume` | up, down or mute | at most five steps per call |
| `tv_search` | finds a film or episode in Jellyfin by name | read-only |
| `tv_play` | `tv_play(title, tv)`: finds the title, opens Jellyfin when it is not open, waits up to 15 s for its session, and starts the item (switching the TV on first is still to come) | no extra question: naming a film and a TV is the request (see Safety 1); it refuses when the title matches more than one item and says which ones |
| `tv_control` | pause, resume, stop, or jump back or forward on the TV's session | |

Two more tools find the TVs and get each one ready:

| Tool | Does | Safety |
|---|---|---|
| `tv_discover` | finds Samsung TVs on the home network (SSDP/UPnP search, then each TV's own information page on port 8001) and gives model, year, Tizen version, which network it is on, and whether developer mode and the remote API are on | read-only; it never pairs or switches anything |
| `tv_setup` | guides one TV through setup, one step at a time by voice. It checks over the network whether the last step took, and says the next one. | read-only, except the Jellyfin install step, which *asks* |

`tv_setup` goes through these steps in order, and checks each one before it
moves on:

1. **Developer mode.** On Apps, scroll to the bottom and open *App Settings*.
   Type 12345 there, not on the Apps page itself, with the remote's number pad
   or the phone's SmartThings remote. Switch it on, enter this computer's
   address on the home network, and press OK. *Check:* the information page
   reports `developerMode: 1` and the right address.
2. **A full restart.** Hold the power button until the Samsung logo shows.
   If holding it only switches the TV off, pull the plug for a minute.
   *Check:* port 26101 answers. On 2026-11-08 it took two tries.
3. **Pairing the remote control.** The TV shows an *Allow* prompt the first
   time; choose Allow. *Check:* a token comes back and is stored in the
   settings file.
4. **Switching on over the network.** Turn on *Power On with Mobile* in the
   TV's settings. *Check:* the TV is in standby and wakes from the packet. Only
   with the owner's yes, since it switches the TV on.
5. **The Jellyfin app.** From the store where it is offered in the TV's
   country; otherwise installed through developer mode. *Asks*: it installs
   software on the TV. *Check:* the TV lists the app id.

The instructions that depend on the model are kept in data files, one per
model family, so that a new TV is added with a file rather than with code:
`src/tv_mcp/models/<year>-<family>.toml`. The first two are `2022-frame.toml`
(The Frame, Tizen 6.5, tested on 2026-11-08) and `2023-tizen7.toml` (the
Q68CA, not yet tested and **on hold**: the owner has asked that nothing is sent to it for now, so it is marked hands-off and set up later). Both TVs go through the same five steps. The Q68CA
has one step before them: **the TV has to be reachable on the network while it
is off.** In Settings → General → Network → Expert Settings, *Power On with
Mobile* and *IP Remote* are switched on. Under External Device Manager →
Device Connection Manager, *Access Notification* must not block new devices.
These are menu names reported for Tizen TVs of these years; the model file
records the exact Norwegian names once they are seen on the TV. Each
file holds how the year is recognised from the model code, the Tizen version,
the menu names in English and Norwegian, the steps that differ from the
defaults, and what has been tested on a real TV, with the date. A step with no
model file falls back to the general instructions and says so.

A TV is called by where it stands ("the living room", "upstairs"), and may
carry a free-text description the voice can read to pick the right one. It is
also found by what the TV reports about itself: its maker, its model code or a
part of it ("LS03B"), and the name it gives itself. Each TV has one entry in
the local settings file, `~/.config/tv-mcp/config.toml`, which also holds its
address, hardware address and the TV's own lasting id. The repository holds
only an example with documentation addresses:

```toml
[tvs.living-room]
location = "the living room"
description = "The Frame by the window"
names = ["The Frame"]
address = "192.0.2.10"
mac = "00:00:5E:00:53:01"
model = "QE55LS03BAUXXC"
device_id = "uuid:..."
```

Two TVs of one model are told apart by where they stand, and by their ids: a
TV that answers at an address with another id than the one set up is reported
and never acted on, because the router may have handed the addresses round.

`tv_setup` writes the entry when a TV is set up and asks the owner what to
call it. A name that matches two TVs is refused rather than guessed. Every
tool that takes a TV takes one of these names, never an address.

## Apps on the TVs

Only one app has to be on each TV: **Jellyfin**. It has to stay signed in to
the server ("remember me"), because a TV turns up in Jellyfin's list of
sessions, which `tv_play` needs, only once the app is open and signed in.

No helper app is needed for the rest:

| Need | What does it | App needed |
|---|---|---|
| Keys, opening apps, Art Mode | the TV's own remote API on ports 8001 and 8002, which samsungtvws speaks | none; the TV asks once to allow the computer |
| Switching on over the network | the TV's own *Power On with Mobile* setting | none |
| Volume | the remote API, or the TV's own UPnP volume control | none |

Should a model need a helper app after all, it goes in that model's data file
with why it is needed, and `tv_setup` asks the owner before installing it.

## TVs that cannot run Jellyfin: a Chromecast

A TV too old for the Jellyfin app (the garage's 2012 Samsung) gets its films
through a Chromecast plugged into it, with the `chromecast` driver. `tv_play`
casts through Jellyfin's own receiver app, from where the film was stopped;
`tv_control` sends pause, resume and stop to the receiver. The receiver
fetches films as a user, so it needs that user's own login (from Quick
Connect, kept beside the settings), not the server's key. No tool is added.
How it was found to work is in the `chromecast` skill.

## Music, planned

Music comes from Jellyfin too (podcasts and audiobooks stay in Audiobookshelf).
Planned, not built:

- `tv_search` also finds artists, albums, songs and playlists (`MusicArtist`,
  `MusicAlbum`, `Audio`, `Playlist`), each with its kind, so the voice can say
  "the album Rumours by Fleetwood Mac".
- `tv_play` plays any of them: an album or playlist in order, an artist as a
  shuffled mix of their songs (`/Items` with `artistIds`, or Jellyfin's
  instant mix). On a TV that goes through `PlayNow` with the item ids, on a
  Chromecast through the receiver's `PlayNow` with the same ids.
- `tv_control` gains next and previous track; `tv_status` says the song and
  artist playing.
- A title that matches a film and an album is refused with both named, as two
  films are today.

## YouTube, planned

The owner asks for a YouTube video by voice and it plays on any of the TVs.
Researched 2026-11-09 from sources only; nothing below is tried yet.

- **An opt-in `youtube` feature**, folded into the tools that exist:
  `tv_search` and `tv_play` take a source, "jellyfin" by default, so the
  default set stays at four tools.
- **Search with yt-dlp** (Unlicense), `ytsearch8:` with flat extraction in a
  worker thread: title, channel and length come from the search page itself,
  with no call per video. Live videos and Shorts are left out. The answer is
  a short list read aloud, as for films.
- **The YouTube Data API is the fallback**, used when the owner puts a key in
  a secret file beside the config or yt-dlp fails. It is the only route
  YouTube's terms clearly allow, but gives 100 searches a day and needs a
  second call for each list's lengths.
- **Play on all three TVs through YouTube's own "Lounge" remote protocol**,
  the one the phone app uses to cast to a TV's YouTube app, with pyytlounge
  (MIT, async). Each TV is paired once, from the screen id its YouTube app
  gives over DIAL, or from the TV code in YouTube's settings, and the pairing
  is kept in a secret file. On the Chromecast the YouTube app is opened
  first. This is what works today in Home Assistant, developed on a Samsung.
- **Not used:** PyChromecast's YouTube controller (its pairing fails and the
  fix was not merged), and DIAL `v=<id>` on Tizen (the app opens and ignores
  the id). When Lounge fails, tv-mcp opens YouTube and says the video could
  not be started, rather than guessing.
- **Risks, said to the owner:** the Lounge protocol and yt-dlp are not
  official, so YouTube can break them and its terms do not allow them; the
  risk for one home is small but not none. Shorts and YouTube Kids profiles
  cannot be controlled.
- **Built after seek, tried first on The Frame and the garage.** Pairing a
  TV shows a prompt on it, so it waits for the owner's yes, and the Q68CA is
  not touched unless the owner asks.

## Safety

1. Switching a TV on or off on its own waits for a spoken yes:
   `tv_power_request` asks, and only `tv_power_confirm` with that token
   switches, as the garage door does. The rule lives in the server, not in the
   voice's instructions. The one exception is the owner's own main use:
   one sentence naming a film and a TV ("play A New Hope on The Frame") is
   itself the request, so `tv_play` switches that TV on without asking
   again. The owner chose this on 2026-11-08. It never switches a TV off,
   and it never acts on a TV the sentence did not name.
2. **A TV can be marked hands-off** in the settings file (`hands_off = true`),
   for example one in a room where children are asleep. No tool sends it
   anything while the mark is there: no power, no Wake-on-LAN, no pairing
   prompt, and no probe, not even discovery. A hands-off TV is reported as
   "left alone", and only the owner removes the mark by editing the file.
   `tv_discover` reads only what TVs announce of their own accord, unless the
   owner asks for a full search.
3. Nothing is retried, and nothing happens on a schedule.
4. Nothing leaves the home network. No cloud services are used, and the
   SmartThings route is ruled out because its personal tokens now expire
   after a day.
5. Secrets live in a file the server is pointed at
   (`~/.config/tv-mcp/config.toml`): the TV pairing tokens, the Jellyfin API
   key, the addresses. They are never in an environment variable the bridge
   would hold, and never in this repository.
6. A simulated mode (`tv-mcp serve --simulate`) answers the same tools from a
   fake TV and a fake Jellyfin, for the tests and for the first try by voice.

## The same controls in every app

Pause, resume, stop, seek, mute, volume and what `tv_status` says is playing
act on whatever plays on a TV, whichever app it is in, not only on what
tv-mcp started. When Jellyfin plays, its session is used, as it says the
title and the position. Otherwise each driver's player answers
(`driver.HasPlayer`):

- **Chromecast:** the open app's media session. Jellyfin's receiver takes its
  own commands; YouTube and other apps take the Chromecast's standard media
  commands. Its media status gives the app, the title and the position.
- **Samsung:** the app in front, from the TV's app status, and the remote's
  media keys (play, pause, stop), which most apps take. The TV does not say
  what an app plays, and seek is not a key, so a seek outside Jellyfin is
  refused. The keys need the paired remote connection, which hangs on both
  Samsungs today (2026-11-09), so they answer "did not answer" until that is
  fixed.

An app that cannot do a command is named in a plain refusal. When tv-mcp
starts one YouTube video it turns YouTube's autoplay off, so it does not
run on into the next.

## Layers, drivers and features

The project is meant to take support for other people's TVs, so it is built
in layers, and `tests/test_layers.py` refuses an import that crosses them:

| Layer | Holds | May use |
|---|---|---|
| core | settings, the driver interface (`driver.py`), what the tools do (`service.py`), discovery, the simulated TV | nothing above it; never MCP, never a driver |
| drivers | one module per brand or platform: `samsung_tizen` first; LG webOS, Google TV and Roku later | the core |
| tools | MCP tools, grouped into features | the core and MCP; never a driver |
| top | the server and the command line, which put them together | everything |

**A driver** implements `tv_mcp.driver.Driver`: a key for the settings file,
the SSDP service its TVs answer to, whether an announcement is one of its TVs,
and reading a TV's description of itself. Each later slice adds a method with
its own safety rule. A contributor's driver comes with:

- a model data file per model family for `tv_setup`;
- a run of the conformance kit (`tv_mcp.conformance.check`): the same checks
  every driver must pass, against the contributor's driver and against the
  simulated TV in `simulator.py`, so most of it needs no hardware;
- the "Add a new TV" steps in `CONTRIBUTING.md`, which the
  development skill follows for a contributor's own agent.

**Features** decide which tools the voice model sees. Only switched-on
features add tools, so an unused feature or brand costs no tools and no
description text. The settings file lists them under `[features] enabled`.
Without that list, the owner gets the small default set: `status` today, then
`media` (search and play) once it exists. `setup`, `power` and anything extra
are opt-in. Tool descriptions are kept short, and each opens with one short
sentence on its own line, which is all the voice sees of a tool it has not
loaded yet (`tests/test_tool_openings.py`).
`tests/test_context_budget.py` holds the default set to a fixed number of
tools and characters (4 tools and 1511 characters today: status, search, play (from where it stopped, or from the start) and pause/resume/stop/seek/mute/unmute/volume, with the instructions claude-voice passes on; closing an app is the opt-in `apps` feature). A change that raises
either does it on purpose, in its own pull request.

The repository stays private until the owner decides otherwise. It is written
to be ready for that: GPL-3.0-or-later, and nothing about the owner's home in
it.

## How it plugs into claude-voice

As the `write-plugin` skill in claude-voice describes:

1. `[plugins.tv]` in `~/.config/claude-voice/config.toml`, starting
   `tv-mcp serve` over stdio.
2. The owner runs `claude-voice plugins approve tv`. The voice is offered only
   the tools this project's own session calls safe for voice.
3. Simulated mode first, then the real TVs.

The plugin's instructions tell the voice when to ask, which tool takes which
token, and to read back each refusal.

## First slice, after a yes

The walking skeleton is `tv_discover` and `tv_status` against the simulated
TV, then against The Frame, through claude-voice. The next slice is `tv_setup`
with the Frame's model file. The next slices are `tv_search` and
`tv_play` on a TV that is already on, and the power tools come last.

## Open questions for the owner

- Which apps besides Jellyfin go on the list?
- Should the Q68CA get Jellyfin as well? It needs developer mode in the same
  way.

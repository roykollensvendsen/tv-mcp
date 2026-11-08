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
| `tv_open_app` | opens an app from a short list in the settings (Jellyfin, YouTube, NRK TV) | only apps on the list |
| `tv_key` | one remote key: play, pause, back, home, arrows, OK | no power key; that goes through `tv_power_*` |
| `tv_volume` | up, down or mute | at most five steps per call |
| `tv_search` | finds a film or episode in Jellyfin by name | read-only |
| `tv_play` | `tv_play(title, tv)`: finds the title, switches the TV on if it is off, opens Jellyfin, waits for its session, and starts the item | no extra question: naming a film and a TV is the request (see Safety 1); it refuses when the title matches more than one item and says which ones |
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

A TV is named the way the owner says it, usually by room ("the living room",
"the bedroom") or by its name ("The Frame"). Each TV has one entry in the
local settings file, `~/.config/tv-mcp/config.toml`, holding its friendly name,
any other names it answers to, and its address, hardware address and pairing
token. The repository holds only an example with documentation addresses:

```toml
[tvs.living-room]
names = ["the living room", "The Frame"]
address = "192.0.2.10"
mac = "00:00:5E:00:53:01"
```

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
- a run of the conformance kit (`tests/conformance/`, to come): the same tests
  every driver must pass, against the contributor's driver and against the
  simulated TV in `simulator.py`, so most of it needs no hardware;
- the "add a new TV" template in `CONTRIBUTING.md` (to come), which the
  development skill follows for a contributor's own agent.

**Features** decide which tools the voice model sees. Only switched-on
features add tools, so an unused feature or brand costs no tools and no
description text. The settings file lists them under `[features] enabled`.
Without that list, the owner gets the small default set: `status` today, then
`media` (search and play) once it exists. `setup`, `power` and anything extra
are opt-in. Tool descriptions are kept to one line.
`tests/test_context_budget.py` holds the default set to a fixed number of
tools and characters (4 tools and 1150 characters today: status, search, play and pause/resume/stop, with the instructions claude-voice passes on; closing an app is the opt-in `apps` feature). A change that raises
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

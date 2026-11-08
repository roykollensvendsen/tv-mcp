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
| Local remote API, ports 8001 and 8002 | open, API 2.0.25, token pairing supported | open when it was on; switched off at the second reading |
| Network | wireless | wireless |
| Developer mode | on (Jellyfin is sideloaded) | off |
| Jellyfin app | installed by developer mode, app id `AprZAARz4r.Jellyfin` | none |

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
| `tv_power_on` | switches a TV on: Wake-on-LAN, or the power key when it is in Art Mode | *asks* |
| `tv_power_off` | switches a TV off: on the Frame, the power key held for three seconds, since a short press only goes to Art Mode | *asks* |
| `tv_confirm` | carries out the one action the token names | the token is used once and expires after a minute |
| `tv_open_app` | opens an app from a short list in the settings (Jellyfin, YouTube, NRK TV) | only apps on the list |
| `tv_key` | one remote key: play, pause, back, home, arrows, OK | no power key; that goes through `tv_power_*` |
| `tv_volume` | up, down or mute | at most five steps per call |
| `media_search` | finds a film or episode in Jellyfin by name | read-only |
| `media_play` | plays an item on a named TV: opens Jellyfin, waits for its session, and starts the item | asks first if the TV is off, through `tv_power_on` |
| `media_control` | pause, resume, stop, or jump back or forward on the TV's session | |

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
`src/tv_mcp/models/<year>-<family>.toml`, for example `2022-frame.toml`. Each
file holds how the year is recognised from the model code, the Tizen version,
the menu names in English and Norwegian, the steps that differ from the
defaults, and what has been tested on a real TV, with the date. A step with no
model file falls back to the general instructions and says so.

A TV is named as the owner names it ("The Frame", "the bedroom") by aliases in
the settings file, never by address.

## Safety

1. Switching a TV on or off waits for a spoken yes. A film never starts on a
   TV that is off without that yes.
2. Nothing is retried, and nothing happens on a schedule.
3. Nothing leaves the home network. No cloud services are used, and the
   SmartThings route is ruled out because its personal tokens now expire
   after a day.
4. Secrets live in a file the server is pointed at
   (`~/.config/tv-mcp/config.toml`): the TV pairing tokens, the Jellyfin API
   key, the addresses. They are never in an environment variable the bridge
   would hold, and never in this repository.
5. A simulated mode (`tv-mcp serve --simulate`) answers the same tools from a
   fake TV and a fake Jellyfin, for the tests and for the first try by voice.

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
with the Frame's model file. The next slices are `media_search` and
`media_play` on a TV that is already on, and the power tools come last.

## Open questions for the owner

- Should `media_play` on a TV that is already on just start, or ask too?
- Which apps besides Jellyfin go on the list?
- Should the Q68CA get Jellyfin as well? It needs developer mode in the same
  way.

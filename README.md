# tv-mcp

Voice control for Samsung TVs, Chromecasts and a Jellyfin server, as an MCP
server and an optional [claude-voice](https://github.com/roykollensvendsen/claude-voice) plugin.

You say "play A New Hope in the living room", and the film starts there, from
where you stopped it last time. Every answer carries a short sentence for the
voice to read aloud, and every refusal says why.

## What it can do

| Feature | What the voice can do |
|---|---|
| `status` | say which TVs are on, what each is playing, how far in, and how much is left |
| `media` | find a film in Jellyfin and start it on a named TV, from where it stopped or from the start; pause, resume, stop, jump to a time, skip forward or back; mute, unmute and set the volume |
| `apps` | open or close an app such as Jellyfin, NRK TV, Netflix or YouTube; playing a film opens Jellyfin by itself when it is closed |
| `scene` | say what is happening in the film right now and who is likely speaking, from its subtitles and cast, and find a scene by its chapters |
| `youtube` | search YouTube and hear title, channel and length; start a chosen video, and say it plays only once the screen reports it |
| `power` | switch a TV on or off, only after a spoken yes to the question it asks first |
| `setup` | find the TVs on the network |

A settings file with no `[features]` table gets `status` and `media` only, so a
feature nobody uses costs the voice model nothing.

It knows three kinds of screen:

- **Samsung TVs on Tizen** (2016 and later), over the TV's own remote-control
  and UPnP interfaces. Jellyfin plays in the TV's Jellyfin app.
- **Chromecasts**, which play films themselves: tv-mcp casts the film from
  Jellyfin. A Chromecast on a TV with HDMI-CEC can also switch that TV on.
- **Samsung TVs from before Tizen** (2011 to 2015), which take only a few
  remote keys. Such a TV may ignore Wake-on-LAN altogether. With a Chromecast
  on one of its HDMI inputs it is switched off through its own remote port and
  on by the Chromecast over HDMI-CEC.

Any TV can be marked `hands_off`, and then no tool sends it anything.

YouTube search uses YouTube's official Data API when a key is given, and yt-dlp
otherwise. Videos are started through YouTube's "Lounge", the service the
YouTube phone app casts with. Neither yt-dlp nor the Lounge is an official
YouTube interface: YouTube can change them, and its terms do not allow them. Both come
with the optional `youtube` extra, and the feature is off unless switched on.

## Set it up

<!-- steps:begin -->
<!-- Made by `voice-checks docs --write` from docs/setup.md. Change the guide, then run it. -->

The steps, in full, are in [docs/setup.md](docs/setup.md):

1. Install the project
2. Ask a simulated TV whether it is on
3. Ask the real TVs whether they are on

### Steps only the owner can do

#### A. Write the settings file

Why: it holds the house's addresses, the TVs' pairings and the Jellyfin key, which are the
owner's, and the owner's settings are changed only on the owner's own yes.

Write `~/.config/tv-mcp/config.toml` in the format at the top of `src/tv_mcp/settings.py`: one
`[tvs.<key>]` table per TV, with what it is called, its address and model, and a `[jellyfin]`
table with the server's address. Put the Jellyfin API key in `jellyfin-key` beside it. Then make
both the owner's alone:

<!-- not run: it changes the owner's own files -->
```bash
chmod 600 ~/.config/tv-mcp/config.toml ~/.config/tv-mcp/jellyfin-key
```

Check: `stat -c %a ~/.config/tv-mcp/config.toml ~/.config/tv-mcp/jellyfin-key` prints `600`
twice.

#### B. Let each TV take orders from this computer

Why: it is done at the TV, with its remote, and the TV asks the owner to allow a new device on
its own screen.

On each Samsung TV, as its model file in `src/tv_mcp/models/` says: switch on *IP Remote* and
*Power On with Mobile*, and choose *Allow* when the TV asks whether this computer may control
it. A TV the owner wants left alone gets `hands_off = true` in step A instead, and then no tool
sends it anything.

Check: in step 3, `uv run tv-mcp status` names the TV with a state other than `refused`.

#### C. Add the plugin to claude-voice and approve it

Why: claude-voice runs a new plugin only once its owner has typed its name, and its settings
are the owner's.

Add `[plugins.tv]` to `~/.config/claude-voice/config.toml`, starting `tv-mcp serve` over stdio,
as claude-voice's `write-plugin` skill describes. Then approve it:

<!-- not run: it changes the owner's own voice setup -->
```bash
claude-voice plugins approve tv
```

Check: `claude-voice plugins list` shows `tv` as approved, and asking the voice which TVs are
on gets an answer naming them.

<!-- steps:end -->

## Try it

Against a simulated Frame, which needs no TV and no settings:

```console
$ uv run tv-mcp status --simulate
the living room: on (QE55LS03BAUXXC, 2022, Tizen 6.5)
```

The same tools are served to a voice session over stdio, and the server stops
when its input closes:

```console
$ uv run tv-mcp serve --simulate < /dev/null
```

Without `--simulate` it reads the TVs named in `~/.config/tv-mcp/config.toml`
(or the file `TV_MCP_SETTINGS` names); the format is at the top of
`src/tv_mcp/settings.py`. That file, and the keys and pairings beside it, stay
outside the repository and readable only by their owner. The Chromecast and
YouTube parts need the `chromecast` and `youtube` extras:
`uv sync --extra chromecast --extra youtube`.

How it plugs into claude-voice, and why each tool is shaped the way it is, is
in [`docs/design.md`](docs/design.md). Adding a TV brand of your own is
described in [`CONTRIBUTING.md`](CONTRIBUTING.md), with the conformance kit
every driver has to pass.

## The gates

Every one of these runs in continuous integration, and all of them run here:

```console
$ uv run ruff check .
All checks passed!
```

<!-- not run: the workflow runs each of these; nesting them here would run the suite inside itself -->
```bash
uv run ruff format --check .   # layout
uv run mypy src                # types
uv run pytest -q               # behaviour
python scripts/mutate.py       # that each rule's own test can fail
```

CI also scans every commit in the history for secrets.
[`CONTRIBUTING.md`](CONTRIBUTING.md) says what each gate is for, and
[`decisions/`](decisions/README.md) records the choices that shaped them,
including how a change is made here.

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE).

# Setting up tv-mcp

This guide is for an agent setting up tv-mcp on the owner's computer. Follow it top to bottom.
Each step has its commands and a `Check:` line, the command whose output proves the step
worked. Do not go on past a step whose check fails.

tv-mcp lets the voice look at and control the TVs in the house: Samsung TVs, a Chromecast in a
TV, and the films on a Jellyfin server. The voice reaches it through claude-voice, as the `tv`
plugin. What each tool does, and why it is shaped as it is, is in [design.md](design.md).

Some steps wait for one only the owner can do. Those are at the end, under their own heading,
and each agent step names the one it waits for. Ask the owner, then go on when its check passes.

Nothing in this guide switches a TV on or off, makes a sound, or shows anything on a screen.
Never do any of those while setting up, unless the owner says yes to that one action first.

## What you need first

- Linux, and the computer on the same home network as the TVs.
- [uv](https://docs.astral.sh/uv/) and Python 3.12 or newer.
- claude-voice, set up and running, for the last step.

## Steps

### 1. Install the project

The `chromecast` and `youtube` extras are only needed for a TV with a Chromecast in it, and for
YouTube.

<!-- not run: it installs packages from the network -->
```bash
uv sync --all-extras
git config core.hooksPath .githooks
```

Check: `uv run tv-mcp --help` lists the `serve` and `status` commands.

### 2. Ask a simulated TV whether it is on

`--simulate` asks a made-up Frame, never a real TV, and needs no settings.

<!-- safe-to-run -->
```console
$ uv run tv-mcp status --simulate
the living room: on (QE55LS03BAUXXC, 2022, Tizen 6.5)
```

Check: it prints that line and exits with 0.

### 3. Ask the real TVs whether they are on

Wait for owner steps A and B.

This only reads: it asks each TV in the settings file how it is, and sends nothing a TV acts on.

<!-- not run: it asks the TVs in the owner's house -->
```bash
uv run tv-mcp status
```

Check: every TV in the settings file is named, each with a state such as `on` or
`off or not reachable`, and none says `refused`. A TV that is off says so; that is a pass.

## Steps only the owner can do

### A. Write the settings file

<!-- owner -->
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

### B. Let each TV take orders from this computer

<!-- owner -->
Why: it is done at the TV, with its remote, and the TV asks the owner to allow a new device on
its own screen.

On each Samsung TV, as its model file in `src/tv_mcp/models/` says: switch on *IP Remote* and
*Power On with Mobile*, and choose *Allow* when the TV asks whether this computer may control
it. A TV the owner wants left alone gets `hands_off = true` in step A instead, and then no tool
sends it anything.

Check: in step 3, `uv run tv-mcp status` names the TV with a state other than `refused`.

### C. Add the plugin to claude-voice and approve it

<!-- owner -->
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

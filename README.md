# tv-mcp

Voice control for a Samsung TV and a Jellyfin server, as an MCP server and an optional claude-voice plugin.

It is a design being built in slices ([`docs/design.md`](docs/design.md)).
What works today is reading the TVs, never changing anything on them.

Try it against a simulated Frame, which needs no TV and no settings:

```console
$ uv run tv-mcp status --simulate
the living room: on (QE55LS03BAUXXC, 2022, Tizen 6.5)
```

The same tools are served to a voice session over stdio, and the server stops
when its input closes:

```console
$ uv run tv-mcp serve --simulate < /dev/null
```

Without `--simulate` it reads the TVs named in `~/.config/tv-mcp/config.toml`;
the format is at the top of `src/tv_mcp/settings.py`.

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

`CONTRIBUTING.md` says what each one is for, and
[`decisions/`](decisions/README.md) records the choices that shaped them,
including how a change is made here.

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE).

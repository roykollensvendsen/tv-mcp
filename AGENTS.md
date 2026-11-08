<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# AGENTS.md

Instructions for coding agents working in this repository. People should
start with [README.md](README.md) and [CONTRIBUTING.md](CONTRIBUTING.md);
this file is the same rules, for an agent.

## What this is

Voice control for Samsung TVs and a Jellyfin server: an MCP server that
claude-voice can take in as an optional plugin. What it will do, and what it
reuses, is [`docs/design.md`](docs/design.md). It is a proposal: **build
nothing in `src/` until the owner has said yes to it.**

## Hard rules

1. **Switching a TV on or off waits for the owner's spoken yes**, through a
   confirmation token, never on a guess. Nothing is retried or scheduled.
2. **Nothing about the owner's home is committed**: no home-network address,
   hardware address, host name, pairing token or API key. Examples use
   192.0.2.x and 00:00:5E:00:53:xx. `scripts/private_data_scan.py` refuses the
   rest, in the pre-commit hook and in CI; never weaken it to make a commit
   pass.
3. **No link to a Claude session in a commit message.** No `Claude-Session:`
   line, whatever an assistant's own attribution says;
   `scripts/no_session_links.py` refuses it.
4. **Never touch a real TV** (pairing, switching on, installing) unless the
   owner asks for it in this session. Reading a TV's information page is
   fine.
5. Every line marked `# RULE:` has a row in `scripts/mutations.toml` and a
   test named after it, and `uv run python scripts/mutate.py` must show each
   rule's own test going red.

## Commands

The gates are in [CONTRIBUTING.md](CONTRIBUTING.md#the-gates); run them all
after the last edit.

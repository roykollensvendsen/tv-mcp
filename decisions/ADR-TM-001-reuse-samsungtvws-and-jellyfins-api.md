# ADR-TM-001: Reuse samsungtvws and Jellyfin's own API

## Status

Proposed, 2026-11-08, waiting for the owner's yes. Nothing rests on it yet.

## Context

The server has to switch a Samsung TV on and off, open an app, send keys, and
start a film on a Jellyfin server. The existing projects were judged on
2026-11-08: licence, last release, and fit. The full comparison and the TVs it
was measured against are in [`docs/design.md`](../docs/design.md).

## Options considered

- **Write the Samsung protocol from scratch.** Not taken: samsungtvws already
  does pairing, keys, apps and Art Mode, is released often, and is what
  Home Assistant runs on.
- **Use an existing Jellyfin MCP server.** Not taken: one offers 368 tools,
  far too many for a voice, and the other is in Go and has no TV control.
- **Use a Jellyfin client library.** Not taken: the maintained one is
  synchronous, and the generated one is behind the server's API. Three plain
  HTTP calls are less to keep up.
- **Do nothing and use Home Assistant.** Not taken: it would add a home server
  to run, and claude-voice already takes plugins.

## Decision

Build a small MCP server of our own on samsungtvws (LGPL-3.0), wakeonlan (MIT)
and httpx against Jellyfin's own API, with the tools, safety rules and
simulated mode in [`docs/design.md`](../docs/design.md).

## Consequences

- An LGPL dependency is used as a library, which is compatible with this
  project's GPL-3.0.
- A change to Jellyfin's session API breaks `media_play`, and no library
  absorbs it for us. The tests against a simulated server cannot see that; only
  a run against the real server can.
- Samsung changes the local API from one year to the next, and samsungtvws is
  one maintainer's work.

## Related

[`docs/design.md`](../docs/design.md)

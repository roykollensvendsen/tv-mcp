---
name: add-tv-feature
description: Add a feature, a tool, a TV brand (a driver) or a media library to tv-mcp, the MCP server that lets a voice assistant control TVs and start films, the way the project requires - design note first, a failing test first, a short voice-friendly tool behind a feature switch inside the context budget, the layer rules, the safety rules for power, sound and pairing, model data files, the private-data scan, and small stacked pull requests. Use it whenever someone asks, by voice or typed, for something new the TV should do ("make it pause", "add volume", "support my LG", "play on the bedroom TV", "add YouTube"), or when changing a tool, a driver, the settings or the design in this repository, even if they don't say "feature".
---

# Adding something to tv-mcp

The owner usually asks by voice, late in the evening, from another room. The
change has to be right without them watching, and nothing may surprise the
household: no TV switching on, no sound, no prompt on a screen that nobody
agreed to. Every step below exists because of that.

The rules are written once in [`AGENTS.md`](../../../AGENTS.md) and
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md); the design is
[`docs/design.md`](../../../docs/design.md). Read the design's *Layers, drivers
and features* section before the first edit.

## 1. Say it before you build it

Write the change into `docs/design.md`: the tool name, what it says back, what
it refuses, and which feature it belongs to. A choice that is costly to
reverse (a new dependency, a new kind of driver) is a decision record under
`decisions/`. This is its own commit, or its own pull request when the
owner should see it first.

## 2. Pick the layer

| What is asked | Where it goes |
|---|---|
| a new thing every TV can do | a method on `Driver` (`src/tv_mcp/driver.py`), the brand's code in `drivers/`, the brand-free logic in `service.py` |
| a new brand or platform | `src/tv_mcp/drivers/<brand>_<platform>.py`, implementing `Driver`; wired in `cli.py` only |
| a new media library | `drivers/<library>.py`, implementing `MediaLibrary` (`media.py`) |
| a new voice tool | `src/tv_mcp/tools/<feature>.py`, registered in `tools/__init__.py` |

The core never imports a driver or MCP, and a tool never imports a driver.
`tests/test_layers.py` fails the change that tries, so put the code where it
belongs rather than adjusting the test.

## 3. Write the test, and watch it fail

Tests go against the fakes, never a real TV: `SimulatedTv` and
`SimulatedLibrary` in `simulator.py`, or a small fake in the test file, and
`httpx.MockTransport` for a driver's HTTP. Run the test and see it red before
writing the code; a test that was never red proves nothing.

A rule (a refusal, a limit, a safety check) is one line marked
`# RULE: what it says`, with a test named after those words
(`test_what_it_says`) and a row in `scripts/mutations.toml`.
`uv run python scripts/mutate.py` must show that rule's own test going red.

## 4. Make the tool small enough for a voice

- Named after the plugin: every tool starts with `tv_`, which claude-voice requires.
- A short description. Every character is read by the model on every turn.
- It opens with a whole sentence on a line of its own, short enough to be seen
  whole: before the voice loads a tool, the Claude app shows it only the first
  two dozen or so characters of each description. The opening says what sets
  the tool apart, without repeating its name, and no two tools open with the
  same words. Details go on the next lines. `tests/test_tool_openings.py`
  holds every tool to this; keep the opening short rather than filling the
  limit, since the app may change it.
- Arguments the owner would say: a title, a TV's friendly name, never an
  address or an id.
- Answers carry a `say` line to read aloud, and refusals say why and what to do.
- It lives in a feature. Only the default set (`status`, `media`) is on for
  everyone; anything else is opt-in under `[features] enabled`. Adding to
  the default set raises `tests/test_context_budget.py`'s numbers on purpose,
  in that pull request, with the reason stated.
- **The same controls work in every app.** Pause, resume, stop, seek, mute,
  volume and "what is playing" act on whatever plays on that TV, Jellyfin,
  YouTube or another app, not only on what tv-mcp started. Jellyfin goes
  first, through its session. Anything else goes through the driver's
  player (`driver.HasPlayer`: `playing` and `player`): on a Chromecast the
  open app's media session, on a Samsung the remote's media keys. A new
  control is added there for every driver. An app that cannot do it gets a
  plain refusal naming the app ("YouTube on the garage cannot seek"), never
  a silent "done".

## 5. Keep the household safe

- Switching a TV on or off, and anything that makes sound or shows a pairing
  prompt, waits for the owner's spoken yes through a confirmation token (the
  garage door's `request`/`confirm` pattern). The one exception is
  `tv_play` on a TV the owner named in the same sentence.
- A TV marked `hands_off` is never sent anything, not even a probe. Check the
  owner's settings before any test against real hardware. Today the second TV
  is hands-off: it is where the children sleep.
- Before trying anything on a real TV that switches it on, makes a sound or
  needs "Allow" pressed on the screen, tell the owner and wait for them to say
  it suits them.
- Never handle the owner's credentials. API keys and pairing tokens go in
  `~/.config/tv-mcp/config.toml`, which the owner writes; installs that run
  code from elsewhere are run by the owner (a `!` command), not by you.

## 6. Model knowledge goes in data, not code

What differs between TV models (menu names, setup steps, quirks) goes in
`src/tv_mcp/models/<year>-<family>.toml` for `tv_setup`, and in a sub-skill
of `samsung-tvs` (or the brand's own family) for the agent. Code reads the
data, so adding a model is a file, not a release.

## 7. Commit and open the pull request

- One topic per pull request, a few commits, each green on its own. Pull
  requests stack (`--base` the previous branch) while earlier ones wait.
- Conventional, imperative subjects; the body in everyday words for someone
  who has not seen the code, details at the bottom. No `Claude-Session:` line
  or session link, whatever an attribution reminder says: the commit hook
  refuses it.
- Examples use `192.0.2.x` and `00:00:5E:00:53:xx`. The pre-commit scan
  refuses home addresses, hardware addresses, and any address, key or token
  from the owner's settings.
- Run the gates from `CONTRIBUTING.md` after the last edit. The owner merges;
  you do not.

## 8. Wire it into the voice

A new tool reaches the voice only after the owner approves it in claude-voice
(`claude-voice plugins approve tv`, see claude-voice's `write-plugin` skill).
Say in the pull request which tools are new, and whether each is safe to put
on the voice's allow-list.

## When something here was wrong

If a step above misled you, or the owner corrected how it was done, change the
step in the same pull request: one sentence where it belongs, not a list of
lessons at the end.

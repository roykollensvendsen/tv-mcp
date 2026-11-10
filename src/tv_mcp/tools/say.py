# SPDX-License-Identifier: GPL-3.0-or-later
"""The sentences the voice reads aloud, made from what the service found."""

from __future__ import annotations

from typing import Any


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:]


def tv_lines(reports: list[dict[str, Any]]) -> str:
    """One sentence per TV, or the refusal when a name was not understood."""
    if not reports:
        return "No TVs are set up yet."
    lines = []
    for report in reports:
        if report.get("say"):
            lines.append(report["say"])
        else:
            name = report["tv"] or (f"a {report['model']}" if report.get("model") else "an unknown TV")
            lines.append(
                f"{_capital(name)} is {report['state']}{_screen(report)}{_playing(report.get('playing'))}"
                f"{_sound(report)}."
            )
    return " ".join(lines)


def waited_lines(reports: list[dict[str, Any]], tv: str | None, wanted: str, *, reached: bool) -> str:
    """What a wait for a TV found, and to ask again when it is not there yet."""
    if not reports:
        return f"I could not read {tv} in time. Ask me to wait again."
    say = tv_lines(reports)
    if reached or any(r["state"] == "refused" for r in reports):
        return say
    return f"{say} It is not {wanted} yet. Ask me to wait again."


def _screen(report: dict[str, Any]) -> str:
    """Whether the TV itself is on, when status reads a device that plays to it."""
    return f", the TV itself is {report['screen']}" if report.get("screen") else ""


def _sound(report: dict[str, Any]) -> str:
    """How loud the TV is, as the end of a sentence."""
    if report.get("muted"):
        return ", muted"
    return f", volume {report['volume']}" if report.get("volume") is not None else ""


def _playing(playing: dict[str, Any] | None) -> str:
    """What is playing, how far in and what is left, as the end of a sentence."""
    if not playing:
        return ""
    if not playing.get("title"):
        # The TV names the app in front but not what it plays, if anything.
        return _apps(playing.get("app"), playing.get("behind") or [])
    what = f", {playing['title']} is paused" if playing.get("paused") else f", playing {playing['title']}"
    far = [f"{playing['at']} in"] if playing.get("at") else []
    far += [f"{playing['left']} left"] if playing.get("left") else []
    return what + (": " + ", ".join(far) if far else "")


def _apps(front: str | None, behind: list[str]) -> str:
    """Which app is on the screen and which run behind it, as the end of a sentence."""
    named = " and ".join(behind)
    if front and behind:
        return f", {front} is open, {named} {'runs' if len(behind) == 1 else 'run'} behind it"
    if behind:
        return f", nothing is open, {named} {'runs' if len(behind) == 1 else 'run'} in the background"
    return f", {front} is open" if front else ""


def _item(item: dict[str, Any]) -> str:
    said = f"{item['title']} ({item['year']})" if item.get("year") else item["title"]
    if item.get("stopped_at"):
        said += f", stopped at {item['stopped_at']}"
        if item.get("last_watched"):
            said += f" on {item['last_watched']}"
    return said


def items_line(term: str, items: list[dict[str, Any]]) -> str:
    """What a search found, titles and years."""
    if not items:
        return f"Found nothing called {term!r}."
    found = "; ".join(_item(i) for i in items)
    return f"Found: {found}."

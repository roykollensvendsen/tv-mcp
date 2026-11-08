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
            lines.append(f"{_capital(name)} is {report['state']}.")
    return " ".join(lines)


def items_line(term: str, items: list[dict[str, Any]]) -> str:
    """What a search found, titles and years."""
    if not items:
        return f"Found nothing called {term!r}."
    found = "; ".join(f"{i['title']} ({i['year']})" if i.get("year") else i["title"] for i in items)
    return f"Found: {found}."

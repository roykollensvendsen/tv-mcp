#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Refuse a commit that would publish something about the owner's home.

This repository may be made public, so nothing in it may say where the TV is
or how to reach it. Two checks on every file given (by default: the files
staged for commit):

- no home-network address: a private IPv4 address or a hardware (MAC)
  address, except the ranges set aside for documentation (RFC 5737 and
  RFC 7042), which are what examples use;
- no value from the owner's local settings file (an address, a token, a
  key), however it is written.

    python3 scripts/private_data_scan.py            # the staged files (pre-commit)
    python3 scripts/private_data_scan.py --tracked  # every tracked file (the tests, CI)
"""

from __future__ import annotations

import argparse
import os
import pathlib
import re
import subprocess
import sys
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SETTINGS = pathlib.Path(os.environ.get("TV_MCP_SETTINGS", "~/.config/tv-mcp/config.toml")).expanduser()
PRIVATE_IPV4 = re.compile(
    r"(?<![\d.])(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}(?![\d.])"
)
MAC = re.compile(r"(?<![0-9A-Fa-f:])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f:])")
DOCUMENTATION_MAC = re.compile(r"^00[:-]00[:-]5E[:-]00[:-]53[:-]", re.IGNORECASE)
MIN_SECRET = 6  # shorter values ("true", a port) would match ordinary text


#: The settings that say where the home is or unlock something. A TV's friendly
#: names ("the living room") are not among them: they are meant to be said.
PRIVATE_KEYS = {"address", "mac", "url", "api_key", "token"}


def private_values(settings: pathlib.Path) -> set[str]:
    """The private values in the owner's settings file, at any depth."""
    out: set[str] = set()
    stack: list[dict[str, object]] = [tomllib.loads(settings.read_text())] if settings.is_file() else []
    while stack:
        for key, value in stack.pop().items():
            if isinstance(value, dict):
                stack.append(value)
            elif key in PRIVATE_KEYS and isinstance(value, str) and len(value) >= MIN_SECRET:
                out.add(value)
    # The Jellyfin key may sit in a file of its own beside the settings.
    key_file = settings.with_name("jellyfin-key")
    key = key_file.read_text().strip() if key_file.is_file() else ""
    if len(key) >= MIN_SECRET:
        out.add(key)
    return out


def offences(text: str, secrets: set[str]) -> list[str]:
    """What in `text` would say something about the owner's home."""
    found = []
    # RULE: a home-network address is never committed
    found += [f"home-network address {m}" for m in PRIVATE_IPV4.findall(text)]
    found += [f"hardware address {m}" for m in MAC.findall(text) if not DOCUMENTATION_MAC.match(m)]
    # RULE: a value from the settings file is never committed
    found += [f"a value from {SETTINGS.name}" for s in secrets if s in text]
    return found


def _files(*, tracked: bool) -> list[pathlib.Path]:
    command = ["git", "ls-files"] if tracked else ["git", "diff", "--cached", "--name-only"]
    names = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=True)  # noqa: S603
    return [ROOT / n for n in names.stdout.splitlines() if (ROOT / n).is_file()]


def main(argv: list[str] | None = None) -> int:
    """Scan the staged (or every tracked) file; 1 when anything is found."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tracked", action="store_true", help="scan every tracked file")
    args = parser.parse_args(argv)
    secrets = private_values(SETTINGS)
    bad = 0
    for path in _files(tracked=args.tracked):
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        for offence in offences(text, secrets):
            sys.stderr.write(f"{path.relative_to(ROOT)}: {offence}\n")
            bad += 1
    if bad:
        sys.stderr.write("Use 192.0.2.x and 00:00:5E:00:53:xx in examples.\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

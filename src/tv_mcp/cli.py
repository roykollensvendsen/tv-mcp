"""Command line for tv-mcp."""

from __future__ import annotations

import argparse
import sys

#: Every verb this command has. The documentation test requires each one to
#: appear in a worked example, so a verb cannot be added without one.
COMMANDS: tuple[str, ...] = ()


def main(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch. Returns a process exit code."""
    parser = argparse.ArgumentParser(prog="tv-mcp", description=__doc__)
    if COMMANDS:
        parser.add_argument("command", nargs="?", choices=COMMANDS)
    parser.parse_args(argv)
    sys.stdout.write("tv-mcp: nothing to do yet\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

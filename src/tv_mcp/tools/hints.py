# SPDX-License-Identifier: GPL-3.0-or-later
"""Whether a tool only looks, or may change something on a TV."""

from mcp.types import ToolAnnotations

#: Changes nothing on any TV, nor anything that plays on one.
LOOKS = ToolAnnotations(read_only_hint=True)
#: May change what a TV shows, plays or does.
CHANGES = ToolAnnotations(read_only_hint=False)

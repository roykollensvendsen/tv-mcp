# SPDX-License-Identifier: GPL-3.0-or-later
"""Finding TVs on the home network over SSDP, the UPnP announcement protocol.

Which announcements count as a TV, and which service a search asks for, are
the driver's to say; this module knows no brand.

Listening only hears TVs that announce themselves, and sends nothing. A
search also asks every TV of that kind on the network to answer. Neither wakes a TV
or makes a sound, but a search does reach every TV, including one marked
hands-off, so it runs only when the owner asks for a full search.
"""

from __future__ import annotations

import socket
import struct
import time
from typing import TYPE_CHECKING

import anyio

if TYPE_CHECKING:
    from collections.abc import Callable

GROUP, PORT = "239.255.255.250", 1900


def _search(target: str) -> bytes:
    return (
        "M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {GROUP}:{PORT}\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 2\r\n"
        f"ST: {target}\r\n\r\n"
    ).encode()


def _gather(
    recognises: Callable[[bytes], bool], target: str | None, seconds: float
) -> list[str]:  # pragma: no cover - needs a real network
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", PORT if target is None else 0))
    if target is None:
        membership = struct.pack("4sl", socket.inet_aton(GROUP), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
    else:
        sock.sendto(_search(target), (GROUP, PORT))
    found: list[str] = []
    end = time.monotonic() + seconds
    with sock:
        while (left := end - time.monotonic()) > 0:
            sock.settimeout(left)
            try:
                datagram, (address, _port) = sock.recvfrom(4096)
            except TimeoutError:
                break
            if recognises(datagram) and address not in found:
                found.append(address)
    return found


async def listen(
    recognises: Callable[[bytes], bool], target: str | None, seconds: float = 3.0
) -> list[str]:  # pragma: no cover - needs a real network
    """Addresses of the TVs heard within `seconds`; `target` set also searches for that service."""
    try:
        return await anyio.to_thread.run_sync(lambda: _gather(recognises, target, seconds))
    except OSError:
        return []

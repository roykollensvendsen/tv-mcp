# SPDX-License-Identifier: GPL-3.0-or-later
"""The driver for older Samsung TVs (2011 to 2015, before Tizen), for power only.

These TVs take remote keys over a plain TCP connection on port 55000. The
first time a remote connects, the TV shows an "allow" question that the owner
answers with its own remote; after that it is let in. Nothing needs pairing
files. Whether the TV is on is read from which of its ports answer: its media
renderer (port 7676) only while it is on, its remote port in standby too. The
protocol is the one samsungctl documents.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import socket
from typing import TYPE_CHECKING

from tv_mcp.driver import TvInfo

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from tv_mcp.settings import Tv

REMOTE_PORT, MEDIA_PORT = 55000, 7676
#: The name the TV shows in its "allow" question, and remembers.
NAME = "tv-mcp"
#: How long the owner gets to answer the TV's "allow" question.
ANSWER_WAIT = 30.0


def _string(text: bytes | str, *, raw: bool = False) -> bytes:
    data = text.encode() if isinstance(text, str) else text
    if not raw:
        data = base64.b64encode(data)
    return bytes([len(data)]) + b"\x00" + data


def auth_packet(name: str) -> bytes:
    """What a remote sends first: its description, id and name."""
    payload = b"\x64\x00" + _string(name) + _string(name) + _string(name)
    return b"\x00\x00\x00" + _string(payload, raw=True)


def key_packet(key: str) -> bytes:
    """One key press, such as KEY_POWEROFF."""
    return b"\x00\x00\x00" + _string(b"\x00\x00\x00" + _string(key), raw=True)


def answer_of(payload: bytes) -> str:
    """What the TV said to the remote: allowed, denied, waiting or timed out."""
    if payload == b"\x64\x00\x01\x00":
        return "allowed"
    if payload == b"\x64\x00\x00\x00":
        return "denied"
    if payload[:1] == b"\x0a":
        return "waiting"
    if payload[:1] == b"\x65":
        return "timed out"
    return "unknown"


def broadcasts(address: str) -> list[str]:
    """Where a wake packet for the TV at `address` goes: its own network first, then the default one.

    A machine on two networks sends 255.255.255.255 out of only one of them.
    The TV's network is taken to be a /24, as home networks are.
    """
    return [address.rsplit(".", 1)[0] + ".255", "255.255.255.255"]


def _send_wake(mac: str, address: str) -> None:  # pragma: no cover - sends to the network
    """A Wake-on-LAN packet: six 0xFF bytes, then the MAC sixteen times."""
    packet = b"\xff" * 6 + bytes.fromhex(mac.replace(":", "").replace("-", "")) * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for target in broadcasts(address):
            with contextlib.suppress(OSError):
                sock.sendto(packet, (target, 9))


async def _reach(address: str, port: int) -> bool:  # pragma: no cover - the network
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(address, port), 2.0)
    except (OSError, TimeoutError):
        return False
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return True


class SamsungLegacy:
    """An older Samsung TV, reached on its remote port."""

    key = "samsung-legacy"
    ssdp_target = "urn:samsung.com:device:RemoteControlReceiver:1"

    def __init__(
        self,
        *,
        reach: Callable[[str, int], Awaitable[bool]] = _reach,
        wake: Callable[[str, str], None] | None = None,
        press: Callable[[str, str], Awaitable[bool]] | None = None,
    ) -> None:
        """Check ports with `reach`, send wake packets with `wake`, and press keys with `press`."""
        self._reach, self._wake = reach, wake or _send_wake
        self._press = press or _press

    def recognises(self, announcement: bytes) -> bool:
        """Whether an announcement comes from an older Samsung."""
        text = announcement.decode(errors="ignore").lower()
        return "samsung" in text and "samsung-linux" not in text

    async def read_info(self, address: str) -> TvInfo | None:
        """On, standby, or None when it does not answer at all."""
        if not await self._reach(address, REMOTE_PORT):
            return None
        power = "on" if await self._reach(address, MEDIA_PORT) else "standby"
        return TvInfo(
            name=None, model=None, year=None, platform="Samsung, before Tizen", power=power, brand="Samsung"
        )

    async def switch(self, tv: Tv, *, on: bool) -> bool:
        """Off with the power key; on with a wake packet and the power key, which some take in standby."""
        if tv.address is None:
            return False
        woken = False
        if on and tv.mac:
            self._wake(tv.mac, tv.address)
            woken = True
        pressed = await self._press(tv.address, "KEY_POWERON" if on else "KEY_POWEROFF")
        # In deep standby the remote port may not answer; the wake packet may still switch it on.
        return pressed or woken


async def _press(address: str, key: str) -> bool:  # pragma: no cover - a real TV
    """Press `key` on the TV's remote port, after it lets tv-mcp in."""
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(address, REMOTE_PORT), 5.0)
    except (OSError, TimeoutError):
        return False
    try:
        writer.write(auth_packet(NAME))
        await writer.drain()
        answer = "waiting"
        while answer == "waiting":
            header = await asyncio.wait_for(reader.readexactly(3), ANSWER_WAIT)
            await reader.readexactly(int.from_bytes(header[1:3], "little"))
            size = int.from_bytes(await reader.readexactly(2), "little")
            answer = answer_of(await reader.readexactly(size))
        if answer != "allowed":
            return False
        writer.write(key_packet(key))
        await writer.drain()
    except (OSError, TimeoutError, asyncio.IncompleteReadError):
        return False
    finally:
        writer.close()
    return True

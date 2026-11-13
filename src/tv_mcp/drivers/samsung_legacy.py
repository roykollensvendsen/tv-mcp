# SPDX-License-Identifier: GPL-3.0-or-later
"""The driver for older Samsung TVs (2011 to 2015, before Tizen): power, inputs and sound.

These TVs take remote keys over a plain TCP connection on port 55000. The
first time a remote connects, the TV shows an "allow" question that the owner
answers with its own remote; after that it is let in. Nothing needs pairing
files. Whether the TV is on is read from which of its ports answer: its media
renderer (port 7676) only while it is on, its remote port in standby too. The
protocol is the one samsungctl documents.

While on, the TV also answers SOAP on port 7676 through Samsung's own
MainTVAgent2 service, which lists its inputs, says which one it shows, and
switches to one by its id. That needs no "allow" question. The same port has
the standard UPnP RenderingControl service, which sets the TV's own volume and
mute, whatever input it shows.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import html
import re
import socket
from typing import TYPE_CHECKING, Any

from tv_mcp.driver import INPUTS, InputSent, RefusedError, TvInfo
from tv_mcp.drivers import RENDERING, mute_in, soap, volume_in

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from tv_mcp.settings import Tv

REMOTE_PORT, MEDIA_PORT = 55000, 7676
#: The name the TV shows in its "allow" question, and remembers.
NAME = "tv-mcp"
#: Said when the TV has said no to tv-mcp's remote.
REMOTE_REFUSED = (
    "The TV refused tv-mcp's remote. Allow tv-mcp in the TV's own menu, in its list of devices"
    " that may control it; then try again."
)
#: How long the owner gets to answer the TV's "allow" question, within the voice's 30 seconds.
ANSWER_WAIT = 10.0
#: How long a TV in standby gets to answer; one that is let in answers at once.
STANDBY_WAIT = 3.0
#: How long one of the TV's ports gets to answer, when asking whether it is on.
REACH_WAIT = 2.0
#: Samsung's own service for inputs, and how long each call to it gets.
AGENT = "urn:samsung.com:service:MainTVAgent2:1"
AGENT_WAIT = 3.0
#: How long finding that service among the TV's pages gets, and how many pages are looked at.
FIND_WAIT = 4.0
PAGES = 30
#: How long one of those pages gets; a page that answers does so at once.
PAGE_WAIT = 0.3
#: How long the TV gets to change input before it is read back.
INPUT_SETTLE = 2.0
#: Where each TV's MainTVAgent2 answers, by address, once found.
_CONTROL: dict[tuple[str, str], str] = {}


def _input_key(source_type: str) -> str:
    """tv-mcp's name for one of the TV's own input names: "HDMI1/DVI" is "hdmi1"."""
    return re.sub(r"[^a-z0-9]", "", source_type.split("/", maxsplit=1)[0].casefold())


def parse_sources(answer: str) -> dict[str, tuple[str, str]]:
    """The inputs with something plugged in, by tv-mcp's name: the TV's own name and its id."""
    found = {}
    for block in re.findall(r"<Source>(.*?)</Source>", html.unescape(answer), re.DOTALL):
        kind, ident, plugged = (
            re.search(rf"<{tag}>([^<]*)", block) for tag in ("SourceType", "ID", "Connected")
        )
        if kind and ident and plugged and plugged.group(1) == "Yes" and _input_key(kind.group(1)) in INPUTS:
            found[_input_key(kind.group(1))] = (kind.group(1), ident.group(1))
    return found


def _tag(block: str, tag: str) -> str:
    """The text of one tag in a block of the TV's XML; empty when the tag is missing."""
    found = re.search(rf"<{tag}>([^<]*)", block)
    return found.group(1).strip() if found else ""


def parse_devices(answer: str) -> dict[str, str | None]:
    """The inputs with something plugged in, leaving out the aerial, with the name each device gave."""
    found: dict[str, str | None] = {}
    for block in re.findall(r"<Source>(.*?)</Source>", html.unescape(answer), re.DOTALL):
        key = _input_key(_tag(block, "SourceType"))
        if _tag(block, "Connected") == "Yes" and key in INPUTS and key != "tv":
            found[key] = _tag(block, "DeviceName") or None
    return found


def parse_current(answer: str) -> str | None:
    """tv-mcp's name for the input the TV says it shows; None when it would not say."""
    shown = re.search(r"<CurrentExternalSource>([^<]*)", answer)
    return _input_key(shown.group(1)) if "<Result>OK<" in answer and shown else None


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
        _, writer = await asyncio.wait_for(asyncio.open_connection(address, port), REACH_WAIT)
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

    def __init__(  # noqa: PLR0913 - one stand-in per way of reaching the TV
        self,
        *,
        reach: Callable[[str, int], Awaitable[bool]] = _reach,
        wake: Callable[[str, str], None] | None = None,
        press: Callable[[str, str, float], Awaitable[bool]] | None = None,
        agent: Callable[[str, str, str], Awaitable[str | None]] | None = None,
        rendering: Callable[[str, str, str], Awaitable[str | None]] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Check ports with `reach`, send wake packets with `wake`, press keys with `press`.

        `agent` calls the TV's MainTVAgent2, and `rendering` its volume service:
        address, action, arguments.
        """
        self._reach, self._wake = reach, wake or _send_wake
        self._press, self._agent, self._sleep = press or _press, agent or _agent, sleep
        self._rendering = rendering or _rendering

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
        if on:
            pressed = await self._press(tv.address, "KEY_POWERON", STANDBY_WAIT)
        else:
            pressed = await self._press(tv.address, "KEY_POWEROFF", ANSWER_WAIT)
        # In deep standby the remote port may not answer; the wake packet may still switch it on.
        return pressed or woken

    async def input_shown(self, tv: Tv) -> str | None:
        """The input the TV says it shows, said aloud; None when it would not say."""
        if tv.address is None:
            return None
        answer = await self._agent(tv.address, "GetCurrentExternalSource", "")
        shown = parse_current(answer) if answer else None
        return INPUTS.get(shown, shown) if shown else None

    async def inputs_plugged(self, tv: Tv) -> dict[str, str | None] | None:
        """The inputs with something plugged in, from the TV's own list; only read."""
        if tv.address is None:
            return None
        listing = await self._agent(tv.address, "GetSourceList", "")
        return parse_devices(listing) if listing else None

    async def show_input(self, tv: Tv, source: str) -> InputSent | None:
        """Pick the input by its id, and read back what the TV shows.

        A TV that will not list its inputs gets remote keys instead: KEY_TV, or
        KEY_HDMI for any HDMI input, since these sets ignore KEY_HDMI1 and the
        like. KEY_HDMI goes to the first HDMI input with something plugged in,
        then steps on to the next one.
        """
        if tv.address is None:
            return None
        listing = await self._agent(tv.address, "GetSourceList", "")
        inputs = parse_sources(listing) if listing else {}
        if not inputs:
            hdmi = source.startswith("hdmi")
            if not await self._press(
                tv.address, "KEY_HDMI" if hdmi else f"KEY_{source.upper()}", ANSWER_WAIT
            ):
                return None
            return InputSent(said="the next HDMI input" if hdmi else INPUTS[source])
        if source not in inputs:
            return InputSent(said=INPUTS[source], shown=await self.input_shown(tv), unplugged=True)
        kind, ident = inputs[source]
        chosen = f"<Source>{kind}</Source><ID>{ident}</ID><UiID>-1</UiID>"
        if await self._agent(tv.address, "SetMainTVSource", chosen) is None:
            return None
        await self._sleep(INPUT_SETTLE)
        return InputSent(said=INPUTS[source], shown=await self.input_shown(tv))

    async def volume(self, address: str) -> int | None:
        """The TV's own volume, 0 to 100, whatever input it shows."""
        return volume_in(await self._rendering(address, "GetVolume", ""))

    async def muted(self, address: str) -> bool | None:
        """Whether the TV's own sound is off."""
        return mute_in(await self._rendering(address, "GetMute", ""))

    async def set_volume(self, address: str, level: int) -> bool:
        """Set the TV's own volume, 0 to 100."""
        return (
            await self._rendering(address, "SetVolume", f"<DesiredVolume>{level}</DesiredVolume>") is not None
        )

    async def set_mute(self, address: str, *, on: bool) -> bool:
        """Mute or unmute the TV itself."""
        return await self._rendering(address, "SetMute", f"<DesiredMute>{int(on)}</DesiredMute>") is not None


async def _agent(address: str, action: str, arguments: str) -> str | None:  # pragma: no cover - a real TV
    """Call `action` on the TV's MainTVAgent2; its answer, or None when it gave none."""
    return await _call(address, AGENT, action, arguments)


async def _rendering(address: str, action: str, arguments: str) -> str | None:  # pragma: no cover - a real TV
    """Call `action` on the TV's standard volume service, on its master channel."""
    if not await _reach(address, MEDIA_PORT):
        return None
    return await _call(
        address, RENDERING, action, f"<InstanceID>0</InstanceID><Channel>Master</Channel>{arguments}"
    )


async def _call(
    address: str, service: str, action: str, arguments: str
) -> str | None:  # pragma: no cover - a real TV
    """Call `action` on `service` at the TV; its answer, or None when it gave none."""
    import httpx  # noqa: PLC0415 - only a real TV needs it here

    body, headers = soap(service, action, arguments)
    async with httpx.AsyncClient(timeout=AGENT_WAIT) as client:
        try:
            control = _CONTROL.get((address, service)) or await asyncio.wait_for(
                find_service(client, address, service), FIND_WAIT
            )
            if control is None:
                return None
            _CONTROL[address, service] = control
            response = await client.post(
                f"http://{address}:{MEDIA_PORT}{control}", content=body, headers=headers
            )
        except (httpx.HTTPError, TimeoutError):
            return None
    return response.text if response.is_success else None


async def find_service(client: Any, address: str, service: str) -> str | None:  # noqa: ANN401
    """Where `service` answers: the TV lists its services on numbered pages.

    A description page answers in a few hundredths of a second; a control page
    holds a plain request open, so each page gets only ``PAGE_WAIT``.
    """
    for number in range(1, PAGES + 1):
        try:
            response = await client.get(f"http://{address}:{MEDIA_PORT}/smp_{number}_", timeout=PAGE_WAIT)
        except Exception:  # noqa: BLE001, S112 - a page that does not answer is skipped
            continue
        if service in response.text and (found := re.search(r"<controlURL>([^<]+)", response.text)):
            return found.group(1)
    return None


async def _press(address: str, key: str, wait: float, *, port: int = REMOTE_PORT) -> bool:
    """Press `key` on the TV's remote port, after it lets tv-mcp in, all within `wait` seconds."""
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(address, port), 5.0)
    except (OSError, TimeoutError):
        return False
    try:
        answer = await asyncio.wait_for(_let_in(reader, writer), wait)
        # RULE: an older Samsung that refuses the remote is said as refused
        if answer == "denied":
            raise RefusedError(REMOTE_REFUSED)
        if answer != "allowed":
            return False
        writer.write(key_packet(key))
        await writer.drain()
    except (OSError, TimeoutError, asyncio.IncompleteReadError):
        return False
    finally:
        writer.close()
    return True


async def _let_in(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> str:
    """Ask the TV to let tv-mcp's remote in; what it said once it stopped "waiting"."""
    writer.write(auth_packet(NAME))
    await writer.drain()
    answer = "waiting"
    while answer == "waiting":
        header = await reader.readexactly(3)
        await reader.readexactly(int.from_bytes(header[1:3], "little"))
        size = int.from_bytes(await reader.readexactly(2), "little")
        answer = answer_of(await reader.readexactly(size))
    return answer

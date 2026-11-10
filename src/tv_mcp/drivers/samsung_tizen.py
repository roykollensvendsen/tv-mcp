# SPDX-License-Identifier: GPL-3.0-or-later
"""The driver for Samsung TVs running Tizen (2016 and later).

It reads the TV's own information page on port 8001, which needs no pairing,
shows nothing on the screen and makes no sound. The TV does not report its
Tizen or software version, so the Tizen version is taken from the model year,
which is the first two digits of the model code (``22_PONTUSM_FTV``).
"""

from __future__ import annotations

import asyncio
import pathlib
import re
import socket
from typing import TYPE_CHECKING, Any, ClassVar, Protocol

import httpx

from tv_mcp.driver import DONE, INPUTS, NO_ANSWER, UNSUPPORTED, InputSent, Playing, TvInfo

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from tv_mcp.settings import Tv

#: How long the power key is held to switch off; a short press only goes to Art Mode.
HOLD_TO_SWITCH_OFF = 3.0


class Remote(Protocol):
    """The TV's paired remote-control connection (port 8002)."""

    def send_key(self, key: str) -> None: ...  # noqa: D102
    def hold_key(self, key: str, seconds: float) -> None: ...  # noqa: D102
    def close(self) -> None: ...  # noqa: D102


def _samsung_remote(address: str, token_file: pathlib.Path) -> Remote:  # pragma: no cover - needs a real TV
    from samsungtvws import SamsungTVWS  # noqa: PLC0415 - only loaded when a TV is switched

    remote: Remote = SamsungTVWS(
        host=address, port=8002, name="tv-mcp", timeout=10, token_file=str(token_file)
    )
    return remote


class ArtChannel(Protocol):
    """The Frame's art channel; only reading its mode is used."""

    def get_artmode(self) -> str: ...  # noqa: D102
    def close(self) -> None: ...  # noqa: D102


def _samsung_art(address: str, token_file: pathlib.Path) -> ArtChannel:  # pragma: no cover - needs a real TV
    from samsungtvws.art import SamsungTVArt  # noqa: PLC0415 - only loaded when art mode is read

    channel: ArtChannel = SamsungTVArt(  # type: ignore[no-untyped-call]
        host=address, port=8002, name="tv-mcp", timeout=TIMEOUT, token_file=str(token_file)
    )
    return channel


def magic_packet(mac: str) -> bytes:
    """A Wake-on-LAN packet: six 0xFF bytes, then the MAC sixteen times."""
    return b"\xff" * 6 + bytes.fromhex(mac.replace(":", "").replace("-", "")) * 16


def _send_wake(mac: str) -> None:  # pragma: no cover - sends to the network
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(magic_packet(mac), ("255.255.255.255", 9))


#: Tizen version by model year, from Samsung's release history.
TIZEN_BY_YEAR = {2020: "5.5", 2021: "6.0", 2022: "6.5", 2023: "7.0", 2024: "8.0", 2025: "9.0"}
TIMEOUT = 3.0
#: The remote's media keys, by command.
MEDIA_KEYS = {"pause": "KEY_PAUSE", "resume": "KEY_PLAY", "stop": "KEY_STOP"}
#: How many seconds to wait for an app to leave the screen after Home.
HOME_TRIES = 5
#: How long the remote connection gets to send one key.
KEY_WAIT = 10.0
#: How each app is named aloud.
APP_NAMES = {"jellyfin": "Jellyfin", "netflix": "Netflix", "nrk": "NRK TV", "youtube": "YouTube"}
#: The standard UPnP service the TV takes volume and mute through, on port 9197.
RENDERING = "urn:schemas-upnp-org:service:RenderingControl:1"
#: Where a YouTube remote says it comes from; the TV's DIAL answers no one else.
YOUTUBE_ORIGIN = "https://www.youtube.com"
#: How many seconds to give YouTube to start and announce its screen.
YOUTUBE_TRIES = 15


def parse_info(payload: dict[str, Any]) -> TvInfo:
    """The parts of the information page that matter here."""
    device: dict[str, Any] = payload.get("device", {})
    code = re.match(r"(\d{2})_", str(device.get("model", "")))
    year = 2000 + int(code.group(1)) if code else None
    tizen = TIZEN_BY_YEAR.get(year) if year else None
    return TvInfo(
        name=device.get("name"),
        model=device.get("modelName"),
        year=year,
        platform=f"Tizen {tizen}" if tizen else None,
        power=str(device.get("PowerState", "unknown")),
        art_mode_capable=device.get("FrameTVSupport") == "true",
        developer_mode=device.get("developerMode") == "1",
        device_id=device.get("id") or None,
        brand="Samsung",
        product_line="The Frame" if device.get("FrameTVSupport") == "true" else None,
    )


async def fetch_info(address: str, client: httpx.AsyncClient) -> dict[str, Any] | None:
    """The TV's information page, or None when it does not answer."""
    try:
        response = await client.get(f"http://{address}:8001/api/v2/", timeout=TIMEOUT)
        response.raise_for_status()
        page = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    return page if isinstance(page, dict) else None


class SamsungTizen:
    """A Samsung Tizen TV, reached over the home network."""

    key = "samsung-tizen"
    ssdp_target = "urn:samsung.com:device:RemoteControlReceiver:1"

    #: Apps it can close, by spoken name. Jellyfin's id is the one the
    #: sideloaded app has; the others are Samsung's store ids.
    apps: ClassVar[dict[str, str]] = {
        "jellyfin": "AprZAARz4r.Jellyfin",
        "netflix": "3201907018807",
        "nrk": "3202012022410",
        "youtube": "111299001912",
    }

    def __init__(  # noqa: PLR0913 - each is a seam a test replaces
        self,
        client: httpx.AsyncClient,
        *,
        tls_client: httpx.AsyncClient | None = None,
        token_folder: pathlib.Path | None = None,
        remote: Callable[[str, pathlib.Path], Remote] = _samsung_remote,
        wake: Callable[[str], None] = _send_wake,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        art: Callable[[str, pathlib.Path], ArtChannel] = _samsung_art,
    ) -> None:
        """Use `client` for every request; pairing tokens are kept in `token_folder`."""
        self._client = client
        self._token_folder = token_folder or pathlib.Path("~/.config/tv-mcp").expanduser()
        self._remote, self._wake, self._sleep, self._art = remote, wake, sleep, art
        # The TV's port 8002 answers with a certificate it signed itself.
        self._tls = tls_client or httpx.AsyncClient(verify=False)  # noqa: S501 - the TV's own certificate

    def recognises(self, announcement: bytes) -> bool:
        """Whether an SSDP announcement or answer comes from a Samsung TV."""
        text = announcement.decode(errors="ignore").lower()
        return "samsung" in text and ("remotecontrolreceiver" in text or "samsung-linux" in text)

    async def read_info(self, address: str) -> TvInfo | None:
        """The TV's information page, in the core's words."""
        page = await fetch_info(address, self._client)
        return parse_info(page) if page is not None else None

    async def open_app(self, address: str, app_id: str) -> bool:
        """Open `app_id` on the TV; no pairing is needed for this."""
        try:
            response = await self._tls.post(f"https://{address}:8002/api/v2/applications/{app_id}", timeout=5)
        except httpx.HTTPError:
            return False
        return response.is_success

    async def youtube_screen(self, address: str) -> str | None:
        """Open YouTube on the TV and give the screen id its YouTube app announces over DIAL.

        The app only says its screen id while it runs, and only to a caller
        that names YouTube as where it comes from.
        """
        if not await self.open_app(address, self.apps["youtube"]):
            return None
        for _ in range(YOUTUBE_TRIES):
            await self._sleep(1.0)
            try:
                response = await self._client.get(
                    f"http://{address}:8080/ws/apps/YouTube",
                    headers={"Origin": YOUTUBE_ORIGIN},
                    timeout=TIMEOUT,
                )
            except httpx.HTTPError:
                continue
            if found := re.search(r"<screenId>([^<]+)</screenId>", response.text):
                return found.group(1)
        return None

    async def _rendering(self, address: str, action: str, arguments: str = "") -> str | None:
        """Call `action` on the TV's standard UPnP volume service; None when it does not answer."""
        body = (
            '<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"'
            ' s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
            f'<u:{action} xmlns:u="{RENDERING}"><InstanceID>0</InstanceID><Channel>Master</Channel>'
            f"{arguments}</u:{action}></s:Body></s:Envelope>"
        )
        headers = {"Content-Type": 'text/xml; charset="utf-8"', "SOAPACTION": f'"{RENDERING}#{action}"'}
        try:
            response = await self._client.post(
                f"http://{address}:9197/upnp/control/RenderingControl1",
                content=body,
                headers=headers,
                timeout=TIMEOUT,
            )
        except httpx.HTTPError:
            return None
        return response.text if response.is_success else None

    async def volume(self, address: str) -> int | None:
        """The TV's volume now, 0 to 100."""
        answer = await self._rendering(address, "GetVolume")
        found = re.search(r"<CurrentVolume>(\d+)</CurrentVolume>", answer or "")
        return int(found.group(1)) if found else None

    async def muted(self, address: str) -> bool | None:
        """Whether the TV's sound is off."""
        answer = await self._rendering(address, "GetMute")
        found = re.search(r"<CurrentMute>([01])</CurrentMute>", answer or "")
        return found.group(1) == "1" if found else None

    async def set_volume(self, address: str, level: int) -> bool:
        """Set the TV's volume, 0 to 100; no pairing is needed for this."""
        return (
            await self._rendering(address, "SetVolume", f"<DesiredVolume>{level}</DesiredVolume>") is not None
        )

    async def set_mute(self, address: str, *, on: bool) -> bool:
        """Mute or unmute the TV."""
        return await self._rendering(address, "SetMute", f"<DesiredMute>{int(on)}</DesiredMute>") is not None

    async def _app_state(self, address: str, app_id: str) -> dict[str, Any]:
        """What the TV says of one app; asked once more when it drops the connection."""
        url = f"https://{address}:8002/api/v2/applications/{app_id}"
        for last in (False, True):
            try:
                state = await self._tls.get(url, timeout=TIMEOUT)
            except httpx.RemoteProtocolError:
                # 2026-11-10: The Frame drops a reused connection now and then; a new one answers.
                if last:
                    return {}
                continue
            except (httpx.HTTPError, ValueError):
                return {}  # one app not answering says nothing about the others
            try:
                return state.json() if state.is_success else {}
            except ValueError:
                return {}
        return {}

    async def playing(self, address: str) -> Playing | None:
        """The app in front, by name, and the known apps running behind it.

        The TV does not say what an app plays or how far in.
        """
        front, behind = None, []
        for name, app_id in self.apps.items():
            state = await self._app_state(address, app_id)
            if state.get("visible") is True:
                front = APP_NAMES.get(name, name)
            elif state.get("running") is True:
                behind.append(APP_NAMES.get(name, name))
        return Playing(app=front, behind=tuple(behind)) if front or behind else None

    async def player(self, tv: Tv, command: str, seconds: float | None = None) -> str:  # noqa: ARG002 - seek is refused
        """Pause, resume or stop with the remote's media keys, which most apps take; seek is not a key."""
        key = MEDIA_KEYS.get(command)
        if key is None:
            return UNSUPPORTED
        if tv.address is None:
            return NO_ANSWER
        return DONE if await self._press(tv.address, tv.key, key) else NO_ANSWER

    async def close_app(self, address: str, app_id: str, *, tv_key: str | None = None) -> bool:
        """Close `app_id` on the TV; no pairing is needed for this.

        An app that is not running counts as closed. The TV is not asked to
        close it, because a 2022 Frame drops the connection when it is. A TV
        that refuses to close it (the 2023 Q68CA on Tizen 7.0) gets the
        remote's Home key instead, when it is paired, and the app counts as
        closed once it is off the screen.
        """
        url = f"https://{address}:8002/api/v2/applications/{app_id}"
        try:
            state = await self._tls.get(url, timeout=5)
            if state.is_success and state.json().get("running") is False:
                return True
            response = await self._tls.delete(url, timeout=5)
        except (httpx.HTTPError, ValueError):
            return False
        if response.is_success:
            return True
        if tv_key is None or not await self._press(address, tv_key, "KEY_HOME"):
            return False
        for _ in range(HOME_TRIES):
            await self._sleep(1.0)
            try:
                state = await self._tls.get(url, timeout=5)
                if state.is_success and state.json().get("visible") is False:
                    return True
            except (httpx.HTTPError, ValueError):
                continue
        return False

    async def art_mode(self, tv: Tv) -> bool | None:
        """Whether The Frame shows art, read over its paired art channel; None when it cannot tell."""
        token_file = self._token_folder / f"{tv.key}-token"

        def read() -> bool | None:
            # RULE: art mode is only read, never set
            channel = self._art(tv.address or "", token_file)
            try:
                mode = channel.get_artmode()
            finally:
                channel.close()
            return {"on": True, "off": False}.get(str(mode))

        try:
            return await asyncio.wait_for(asyncio.to_thread(read), TIMEOUT + 1)
        except Exception:  # noqa: BLE001 - whatever the channel does, status says what it knows
            return None

    async def _press(self, address: str, tv_key: str, key: str) -> bool:
        """Press one remote key on the TV over its paired connection."""
        token_file = self._token_folder / f"{tv_key}-token"

        def press() -> None:
            remote = self._remote(address, token_file)
            try:
                remote.send_key(key)
            finally:
                remote.close()

        try:
            await asyncio.wait_for(asyncio.to_thread(press), KEY_WAIT)
        except Exception:  # noqa: BLE001 - any failure of the remote connection means no answer
            return False
        return True

    async def show_input(self, tv: Tv, source: str) -> InputSent | None:
        """Press the input's own key, such as KEY_HDMI1, over the paired connection."""
        if tv.address is None or not await self._press(tv.address, tv.key, f"KEY_{source.upper()}"):
            return None
        return InputSent(said=INPUTS[source])

    async def switch(self, tv: Tv, *, on: bool) -> bool:
        """Switch `tv` on or off.

        Off holds the power key, since a short press only goes to Art Mode.
        On presses it when the TV still listens (standby or Art Mode), and
        otherwise sends a wake packet to its MAC address.
        """
        if tv.address is None:
            return False
        listening = await fetch_info(tv.address, self._client) is not None
        if not listening:
            if not on or tv.mac is None:
                return False
            self._wake(tv.mac)
            return True
        token_file = self._token_folder / f"{tv.key}-token"

        def press() -> None:
            remote = self._remote(tv.address or "", token_file)
            try:
                if on:
                    remote.send_key("KEY_POWER")
                else:
                    remote.hold_key("KEY_POWER", HOLD_TO_SWITCH_OFF)
            finally:
                remote.close()

        try:
            await asyncio.to_thread(press)
        except Exception:  # noqa: BLE001 - any failure of the TV's connection means it did not switch
            return False
        return True

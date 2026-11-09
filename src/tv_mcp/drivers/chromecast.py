# SPDX-License-Identifier: GPL-3.0-or-later
"""The driver for a Chromecast plugged into a TV that cannot run Jellyfin itself.

Films are cast through Jellyfin's own receiver app, which fetches the stream,
lets the server transcode what the Chromecast cannot play, and reports how far
it got, so resuming keeps working. The receiver needs a login that belongs to
a user: the server's API key belongs to none, and the receiver fails with it.

A Chromecast cannot switch its TV off. Starting the receiver may switch the
TV on and to the Chromecast's input, over HDMI-CEC (Samsung's Anynet+).

Talking to the Chromecast needs PyChromecast (MIT), the ``chromecast`` extra.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
import urllib.request
import uuid
from typing import TYPE_CHECKING, Any

import httpx

from tv_mcp.driver import TvInfo

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from tv_mcp.media import CastLogin, MediaItem

#: Jellyfin's stable receiver app, which the server sets up by default.
JELLYFIN_RECEIVER = "F007D354"
NAMESPACE = "urn:x-cast:com.connectsdk"
TICKS = 10_000_000
TIMEOUT = 3.0

#: The receiver's name for each command in tv_mcp.media.COMMANDS.
RECEIVER_COMMANDS = {"pause": "Pause", "resume": "Unpause", "stop": "Stop"}


def _message(login: CastLogin, command: str, options: dict[str, Any]) -> dict[str, Any]:
    return {
        "command": command,
        "options": options,
        "userId": login.user_id,
        "deviceId": "tv-mcp",
        "accessToken": login.token,
        "serverAddress": login.server,
        "serverId": login.server_id,
        "serverVersion": login.version,
        "receiverName": "tv-mcp",
    }


#: Jellyfin's media type for each kind of item.
MEDIA_TYPES = {"Movie": "Video", "Episode": "Video", "Audio": "Audio"}


def play_message(login: CastLogin, item: MediaItem, start: float) -> dict[str, Any]:
    """The message that starts `item`, `start` seconds in.

    The receiver needs the item's type and media type: with the id alone it
    loads the item and then never plays it.
    """
    said = {
        "Id": item.id,
        "ServerId": login.server_id,
        "Name": item.title,
        "Type": item.kind,
        "MediaType": MEDIA_TYPES.get(item.kind, "Video"),
        "IsFolder": False,
    }
    return _message(login, "PlayNow", {"items": [said], "startPositionTicks": int(start * TICKS)})


def control_message(login: CastLogin, command: str) -> dict[str, Any]:
    """The message for `command`, one of tv_mcp.media.COMMANDS."""
    return _message(login, RECEIVER_COMMANDS[command], {})


class Chromecast:
    """A Chromecast on the home network, reached by its address."""

    key = "chromecast"
    ssdp_target = "urn:dial-multiscreen-org:service:dial:1"

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        login: Callable[[str], Awaitable[CastLogin | None]],
        send: Callable[[str, dict[str, Any]], Awaitable[bool]] | None = None,
    ) -> None:
        """Read its page over `client`, log in to the library with `login`, and `send` messages."""
        self._client, self._login = client, login
        self._send = send or _send_with_pychromecast

    def recognises(self, announcement: bytes) -> bool:
        """Whether an SSDP announcement comes from a Chromecast."""
        text = announcement.decode(errors="ignore").lower()
        return "chromecast" in text or "eureka" in text

    async def read_info(self, address: str) -> TvInfo | None:
        """The Chromecast's own page; it cannot tell whether its TV is on."""
        try:
            response = await self._client.get(
                f"http://{address}:8008/setup/eureka_info",
                params={"params": "name,device_info"},
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            page = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        device = page.get("device_info") or {}
        return TvInfo(
            name=page.get("name"),
            model=device.get("model_name") or "Chromecast",
            year=None,
            platform="Google Cast",
            power="unknown",
            brand="Google",
            product_line="Chromecast",
        )

    async def cast(self, address: str, item: MediaItem, start: float) -> bool:
        """Start `item` on the Chromecast; False without a user login, or when it does not start."""
        login = await self._login(address)
        return login is not None and await self._send(address, play_message(login, item, start))

    async def cast_control(self, address: str, command: str) -> bool:
        """Pause, resume or stop what the receiver is playing."""
        login = await self._login(address)
        return login is not None and await self._send(address, control_message(login, command))


def _uuid(address: str) -> uuid.UUID:  # pragma: no cover - a real device
    """The Chromecast's own id, from its page; PyChromecast wants it to connect by address."""
    url = f"http://{address}:8008/setup/eureka_info?params=ssdp_udn"
    with urllib.request.urlopen(url, timeout=TIMEOUT) as page:
        return uuid.UUID(json.load(page)["ssdp_udn"])


def playing_item(report: dict[str, Any]) -> str | None:
    """The item a receiver's playback report says has started, or None.

    A loaded item that has not started is named too, but cannot be seeked in yet.
    """
    data = report.get("data")
    if not isinstance(data, dict):
        return None
    item, state = data.get("ItemId"), data.get("PlayState") or {}
    return str(item) if item and state.get("CanSeek") else None


#: Seconds the receiver needs after starting before it listens to messages.
RECEIVER_READY = 4.0
#: Seconds to wait for the receiver to say it is playing what was sent.
CONFIRM_WAIT = 12.0


async def _send_with_pychromecast(
    address: str, message: dict[str, Any]
) -> bool:  # pragma: no cover - a real device
    return await asyncio.to_thread(_send_blocking, address, message)


#: One open connection per Chromecast, kept while tv-mcp runs. The receiver
#: closes when its last sender leaves, so tv-mcp never leaves: a disconnect
#: right after casting ended the film within seconds (2026-11-09).
_connections: dict[str, tuple[Any, Any, threading.Event]] = {}
_lock = threading.Lock()


def _connection(address: str) -> tuple[Any, Any, threading.Event]:  # pragma: no cover - a real device
    """The Chromecast at `address` with a Jellyfin receiver handler, connected once and kept."""
    import pychromecast  # type: ignore[import-not-found,unused-ignore]  # noqa: PLC0415 - the optional chromecast extra
    from pychromecast.controllers import BaseController  # type: ignore[import-not-found,unused-ignore]  # noqa: PLC0415

    with _lock:
        known = _connections.get(address)
        if known is not None and known[0].socket_client.is_connected:
            return known
        playing = threading.Event()

        class Receiver(BaseController):  # type: ignore[misc,unused-ignore]
            wanted: str | None = None

            def __init__(self) -> None:
                super().__init__(NAMESPACE, JELLYFIN_RECEIVER)

            def receive_message(self, _message: object, data: object) -> bool:
                if isinstance(data, dict) and self.wanted and playing_item(data) == self.wanted:
                    playing.set()
                return True

        cast = pychromecast.get_chromecast_from_host((address, 8009, _uuid(address), None, None))
        cast.wait(timeout=10)
        receiver = Receiver()
        cast.register_handler(receiver)
        _connections[address] = (cast, receiver, playing)
        return _connections[address]


def _send_blocking(address: str, message: dict[str, Any]) -> bool:  # pragma: no cover - a real device
    """Send `message` to the receiver; for PlayNow, True only once it says it is playing the item."""
    try:
        import pychromecast  # type: ignore[import-not-found,unused-ignore]  # noqa: PLC0415 - the optional chromecast extra
    except ImportError:
        return False
    try:
        cast, receiver, playing = _connection(address)
        wanted = message["options"]["items"][0]["Id"] if message["command"] == "PlayNow" else None
        if wanted:
            launched = threading.Event()
            playing.clear()
            receiver.wanted = wanted
            receiver.launch(callback_function=lambda *_: launched.set())
            if not launched.wait(timeout=15):
                return False
            if cast.app_id != JELLYFIN_RECEIVER or not getattr(receiver, "ready", False):
                time.sleep(RECEIVER_READY)
            receiver.send_message(message)
            receiver.ready = True
            return playing.wait(timeout=CONFIRM_WAIT)
        if cast.app_id != JELLYFIN_RECEIVER:
            # A command goes only to a receiver already running: launching it
            # again would restart it and end what it was playing.
            return False
        receiver.send_message(message)
    except (pychromecast.error.PyChromecastError, OSError, TimeoutError, ValueError, KeyError):
        _connections.pop(address, None)
        return False
    return True

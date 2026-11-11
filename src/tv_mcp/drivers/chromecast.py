# SPDX-License-Identifier: GPL-3.0-or-later
"""The driver for a Chromecast plugged into a TV that cannot run Jellyfin itself.

Films are cast through Jellyfin's own receiver app, which fetches the stream,
lets the server transcode what the Chromecast cannot play, and reports how far
it got, so resuming keeps working. The receiver needs a login that belongs to
a user: the server's API key belongs to none, and the receiver fails with it.

A Chromecast cannot switch its TV off. Starting an app on it asks the TV to
switch on and to the Chromecast's input, over HDMI-CEC (Samsung's Anynet+), and
HDMI tells it whether the TV is in standby: ``wake_screen`` and ``screen_on``.

Talking to the Chromecast needs PyChromecast (MIT), the ``chromecast`` extra.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import time
import urllib.request
import uuid
from typing import TYPE_CHECKING, Any

import httpx

from tv_mcp.driver import DONE, NO_ANSWER, UNSUPPORTED, Playing, TvInfo

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from tv_mcp.media import CastLogin, MediaItem
    from tv_mcp.settings import Tv

#: Jellyfin's stable receiver app, which the server sets up by default.
JELLYFIN_RECEIVER = "F007D354"
NAMESPACE = "urn:x-cast:com.connectsdk"
TICKS = 10_000_000
TIMEOUT = 3.0

#: Google's own receiver, started only to wake the TV, and how long it is left open for that.
WAKER = "CC1AD845"
WAKE_HOLD = 5.0
#: How long the Chromecast gets to connect, and to start an app.
CONNECT_TIMEOUT = 10.0
START_TIMEOUT = 5.0

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


def seek_message(login: CastLogin, seconds: float) -> dict[str, Any]:
    """The message that moves the film to `seconds` from its start."""
    return _message(login, "Seek", {"position": seconds})


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

    async def wake_screen(self, address: str) -> bool:
        """Start an app for a moment, which asks the TV over HDMI to switch on."""
        return await asyncio.to_thread(_wake_blocking, address)

    async def screen_on(self, address: str) -> bool | None:
        """Whether the TV is on, from what HDMI tells the Chromecast."""
        return await asyncio.to_thread(_screen_blocking, address)

    async def on_screen(self, address: str) -> bool | None:
        """Whether the TV shows the Chromecast's input, from what HDMI tells the Chromecast."""
        return await asyncio.to_thread(_in_front_blocking, address)

    async def playing(self, address: str) -> Playing | None:
        """What plays on the Chromecast, in whatever app: Jellyfin, YouTube or another."""
        return await asyncio.to_thread(_playing_blocking, address)

    async def player(self, tv: Tv, command: str, seconds: float | None = None) -> str:
        """Pause, resume, stop or seek in the app playing.

        Jellyfin's receiver takes its own commands; any other app takes the
        Chromecast's standard media commands.
        """
        address = tv.address or ""
        app = await asyncio.to_thread(_app_blocking, address)
        if app is None:
            return NO_ANSWER
        if app == JELLYFIN_RECEIVER:
            if command == "seek":
                sent = await self.cast_seek(address, seconds or 0.0)
            else:
                sent = await self.cast_control(address, command)
            return DONE if sent else NO_ANSWER
        return await asyncio.to_thread(_media_blocking, address, command, seconds)

    async def volume(self, address: str) -> int | None:
        """The Chromecast's own volume, 0 to 100."""
        return await asyncio.to_thread(_sound_blocking, address, None, None)

    async def muted(self, address: str) -> bool | None:
        """Whether the Chromecast's sound is off."""
        return await asyncio.to_thread(_muted_blocking, address)

    async def set_volume(self, address: str, level: int) -> bool:
        """Set the Chromecast's own volume; the TV's volume stays as it is."""
        return await asyncio.to_thread(_sound_blocking, address, level, None) is not None

    async def set_mute(self, address: str, *, on: bool) -> bool:
        """Mute or unmute the Chromecast."""
        return await asyncio.to_thread(_sound_blocking, address, None, on) is not None

    async def youtube_screen(self, address: str) -> str | None:
        """Open YouTube on the Chromecast and give its screen id."""
        return await asyncio.to_thread(_youtube_screen_blocking, address)

    async def cast_seek(self, address: str, seconds: float) -> bool:
        """Move what the receiver is playing to `seconds` from its start."""
        login = await self._login(address)
        return login is not None and await self._send(address, seek_message(login, seconds))

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
        cast.wait(timeout=CONNECT_TIMEOUT)
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


#: The YouTube app on a Chromecast, and the channel that gives its screen id.
YOUTUBE_APP = "233637DE"
YOUTUBE_NAMESPACE = "urn:x-cast:com.google.youtube.mdx"


def _youtube_screen_blocking(address: str) -> str | None:  # pragma: no cover - a real device
    """Launch YouTube on the Chromecast and ask it for its screen id."""
    try:
        import pychromecast  # type: ignore[import-not-found,unused-ignore]  # noqa: PLC0415 - the optional chromecast extra
        from pychromecast.controllers import BaseController  # type: ignore[import-not-found,unused-ignore]  # noqa: PLC0415
    except ImportError:
        return None
    answered = threading.Event()
    screen: list[str] = []

    class YouTube(BaseController):  # type: ignore[misc,unused-ignore]
        def __init__(self) -> None:
            super().__init__(YOUTUBE_NAMESPACE, YOUTUBE_APP)

        def receive_message(self, _message: object, data: object) -> bool:
            if isinstance(data, dict) and (data.get("data") or {}).get("screenId"):
                screen.append(str(data["data"]["screenId"]))
                answered.set()
            return True

    try:
        cast, _, _ = _connection(address)
        youtube = YouTube()
        cast.register_handler(youtube)
        launched = threading.Event()
        youtube.launch(callback_function=lambda *_: launched.set())
        if not launched.wait(timeout=20):
            return None
        for _ in range(5):
            youtube.send_message({"type": "getMdxSessionStatus"})
            if answered.wait(timeout=3):
                return screen[0]
    except (pychromecast.error.PyChromecastError, OSError, TimeoutError, ValueError, KeyError):
        _connections.pop(address, None)
    return None


def _sound_blocking(address: str, level: int | None, mute: bool | None) -> int | None:  # noqa: FBT001  # pragma: no cover - a real device
    """Set the level or the mute when given, and give the volume, 0 to 100; None when it did not answer."""
    try:
        import pychromecast  # type: ignore[import-not-found,unused-ignore]  # noqa: PLC0415 - the optional chromecast extra
    except ImportError:
        return None
    try:
        cast, _, _ = _connection(address)
        if level is not None:
            cast.set_volume(level / 100, timeout=5)
        if mute is not None:
            cast.set_volume_muted(mute, timeout=5)
        status = cast.status
        return round(status.volume_level * 100) if status is not None else None
    except (pychromecast.error.PyChromecastError, OSError, TimeoutError, ValueError, KeyError):
        _connections.pop(address, None)
        return None


def _wake_blocking(address: str) -> bool:  # pragma: no cover - a real device
    """Start the waker app, and close it again a moment later, without waiting for that."""
    try:
        import pychromecast  # type: ignore[import-not-found,unused-ignore]  # noqa: PLC0415 - the optional chromecast extra
    except ImportError:
        return False
    try:
        cast, _, _ = _connection(address)
        cast.start_app(WAKER, timeout=START_TIMEOUT)
    except (pychromecast.error.PyChromecastError, OSError, TimeoutError, ValueError, KeyError):
        _connections.pop(address, None)
        return False

    def close() -> None:
        if cast.app_id == WAKER:
            with contextlib.suppress(pychromecast.error.PyChromecastError, OSError, TimeoutError):
                cast.quit_app(timeout=START_TIMEOUT)

    threading.Timer(WAKE_HOLD, close).start()
    return True


def _status_blocking(address: str) -> Any:  # noqa: ANN401  # pragma: no cover - a real device
    """The Chromecast's own status, with what HDMI tells it; None when it does not answer."""
    try:
        import pychromecast  # type: ignore[import-not-found,unused-ignore]  # noqa: PLC0415 - the optional chromecast extra
    except ImportError:
        return None
    try:
        cast, _, _ = _connection(address)
    except (pychromecast.error.PyChromecastError, OSError, TimeoutError, ValueError, KeyError):
        return None
    return cast.status


def _screen_blocking(address: str) -> bool | None:  # pragma: no cover - a real device
    """True when HDMI says the TV is on, False in standby, None when the Chromecast does not know."""
    status = _status_blocking(address)
    if status is None or status.is_stand_by is None:
        return None
    return not status.is_stand_by


def _in_front_blocking(address: str) -> bool | None:  # pragma: no cover - a real device
    """True when HDMI says the TV shows the Chromecast, None when the Chromecast does not know."""
    status = _status_blocking(address)
    return None if status is None or status.is_active_input is None else bool(status.is_active_input)


#: What the Chromecast shows when no app is open.
IDLE_APPS = {"Backdrop", None}


def _app_blocking(address: str) -> str | None:  # pragma: no cover - a real device
    """The id of the app open on the Chromecast, or None when it does not answer."""
    try:
        import pychromecast  # type: ignore[import-not-found,unused-ignore]  # noqa: PLC0415, F401 - the optional chromecast extra
    except ImportError:
        return None
    try:
        cast, _, _ = _connection(address)
    except (OSError, TimeoutError, ValueError, KeyError):
        return None
    return str(cast.app_id) if cast.app_id else None


def _playing_blocking(address: str) -> Playing | None:  # pragma: no cover - a real device
    """What the app open on the Chromecast is playing, from its media status."""
    try:
        cast, _, _ = _connection(address)
        if cast.app_display_name in IDLE_APPS:
            return None
        media = cast.media_controller
        media.update_status()
        time.sleep(1.0)
        status = media.status
    except Exception:  # noqa: BLE001 - any failure of the device means it cannot tell
        return None
    if status is None or status.player_state in {"IDLE", "UNKNOWN", None}:
        return None
    return Playing(
        app=cast.app_display_name,
        title=status.title,
        position=status.adjusted_current_time,
        runtime=status.duration,
        paused=status.player_state == "PAUSED",
    )


def _media_blocking(
    address: str, command: str, seconds: float | None
) -> str:  # pragma: no cover - a real device
    """Send the Chromecast's standard media `command` to the app open on it."""
    try:
        cast, _, _ = _connection(address)
        media = cast.media_controller
        media.update_status()
        time.sleep(1.0)
        status = media.status
        able = {
            "pause": status.supports_pause,
            "resume": status.supports_pause,
            "seek": status.supports_seek,
            "stop": True,
        }[command]
        if not able:
            return UNSUPPORTED
        if command == "pause":
            media.pause()
        elif command == "resume":
            media.play()
        elif command == "seek":
            media.seek(seconds or 0.0)
        else:
            try:
                media.stop()
            except Exception:  # noqa: BLE001 - an app that will not stop is closed instead
                cast.quit_app()
    except Exception:  # noqa: BLE001 - any failure of the device means no answer
        return NO_ANSWER
    return DONE


def _muted_blocking(address: str) -> bool | None:  # pragma: no cover - a real device
    """Whether the Chromecast is muted, from its status."""
    try:
        cast, _, _ = _connection(address)
        status = cast.status
    except Exception:  # noqa: BLE001 - any failure of the device means it cannot tell
        return None
    return bool(status.volume_muted) if status is not None else None

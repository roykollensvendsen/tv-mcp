# SPDX-License-Identifier: GPL-3.0-or-later
"""The driver for Samsung TVs running Tizen (2016 and later).

It reads the TV's own information page on port 8001, which needs no pairing,
shows nothing on the screen and makes no sound. The TV does not report its
Tizen or software version, so the Tizen version is taken from the model year,
which is the first two digits of the model code (``22_PONTUSM_FTV``).
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from tv_mcp.driver import TvInfo

#: Tizen version by model year, from Samsung's release history.
TIZEN_BY_YEAR = {2020: "5.5", 2021: "6.0", 2022: "6.5", 2023: "7.0", 2024: "8.0", 2025: "9.0"}
TIMEOUT = 3.0


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

    def __init__(self, client: httpx.AsyncClient) -> None:
        """Use `client` for every request, so its connections are shared."""
        self._client = client

    def recognises(self, announcement: bytes) -> bool:
        """Whether an SSDP announcement or answer comes from a Samsung TV."""
        text = announcement.decode(errors="ignore").lower()
        return "samsung" in text and ("remotecontrolreceiver" in text or "samsung-linux" in text)

    async def read_info(self, address: str) -> TvInfo | None:
        """The TV's information page, in the core's words."""
        page = await fetch_info(address, self._client)
        return parse_info(page) if page is not None else None

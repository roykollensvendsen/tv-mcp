# SPDX-License-Identifier: GPL-3.0-or-later
"""One module per brand or platform of TV, each implementing tv_mcp.driver.Driver."""

import re

#: The standard UPnP service many TVs take their volume and mute through.
RENDERING = "urn:schemas-upnp-org:service:RenderingControl:1"


def soap(service: str, action: str, arguments: str) -> tuple[str, dict[str, str]]:
    """The body and headers that call `action` on a UPnP `service`."""
    body = (
        '<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/"'
        ' s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
        f'<u:{action} xmlns:u="{service}">{arguments}</u:{action}></s:Body></s:Envelope>'
    )
    return body, {"Content-Type": 'text/xml; charset="utf-8"', "SOAPACTION": f'"{service}#{action}"'}


def volume_in(answer: str | None) -> int | None:
    """The volume in a RenderingControl GetVolume answer."""
    found = re.search(r"<CurrentVolume>(\d+)</CurrentVolume>", answer or "")
    return int(found.group(1)) if found else None


def mute_in(answer: str | None) -> bool | None:
    """Whether a RenderingControl GetMute answer says the sound is off."""
    found = re.search(r"<CurrentMute>([01])</CurrentMute>", answer or "")
    return found.group(1) == "1" if found else None

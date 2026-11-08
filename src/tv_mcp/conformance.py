# SPDX-License-Identifier: GPL-3.0-or-later
"""The conformance kit: what every TV driver must do, checked without a real TV.

A contributor runs it against their driver, given one address where the
driver's TV answers and, when they can, one where nothing does. Both can be
fakes: a driver takes its network client in its constructor, so a test hands
it one that answers from a recorded page. ``check`` returns the problems
found, in plain words; an empty list means the driver conforms.

    problems = await check(MyDriver(client), answers="192.0.2.10", silent="192.0.2.99")
    assert problems == []
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from tv_mcp.driver import TvInfo
from tv_mcp.settings import Tv

if TYPE_CHECKING:
    from tv_mcp.driver import Driver

#: The power states a driver may report.
POWER_STATES = {"on", "standby", "unknown"}
_KEY = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


async def _never_raises(problems: list[str], what: str, call: Any) -> Any:  # noqa: ANN401 - whatever the call gives
    try:
        return await call
    except Exception as error:  # noqa: BLE001 - reporting any error is the point
        problems.append(f"{what} raised {type(error).__name__}; a driver answers instead of raising")
        return None


async def check(driver: Driver, *, answers: str, silent: str | None = None) -> list[str]:
    """Problems with `driver`; `answers` is an address its TV answers at, `silent` one where nothing does."""
    problems: list[str] = []
    if not isinstance(driver.key, str) or not _KEY.match(driver.key):
        problems.append(f"key {driver.key!r} is not lower-case words joined by hyphens")
    if not isinstance(driver.ssdp_target, str) or not driver.ssdp_target:
        problems.append("ssdp_target is empty")
    for announcement in (b"", b"\xff\xfe garbage", b"HTTP/1.1 200 OK\r\nST: upnp:rootdevice\r\n\r\n"):
        try:
            if not isinstance(driver.recognises(announcement), bool):
                problems.append("recognises() does not return True or False")
                break
        except Exception as error:  # noqa: BLE001
            problems.append(f"recognises() raised {type(error).__name__} on a strange announcement")
            break
    info = await _never_raises(problems, "read_info() on a TV that answers", driver.read_info(answers))
    if not isinstance(info, TvInfo):
        problems.append("read_info() on a TV that answers gave no TvInfo")
    elif info.power not in POWER_STATES:
        problems.append(
            f"read_info() reported power {info.power!r}; it must be one of {sorted(POWER_STATES)}"
        )
    if silent is not None:
        quiet = await _never_raises(problems, "read_info() on a silent address", driver.read_info(silent))
        if quiet is not None:
            problems.append("read_info() on a silent address must give None")
    await _check_optional(driver, problems, silent)
    return problems


async def _check_optional(driver: Driver, problems: list[str], silent: str | None) -> None:
    """The methods a driver may add, each with its rule."""
    extra: Any = driver
    if callable(getattr(extra, "switch", None)):
        nowhere = Tv(key="nowhere", names=("nowhere",))
        switched = await _never_raises(
            problems, "switch() on a TV with no address", extra.switch(nowhere, on=True)
        )
        if switched is not False:
            problems.append("switch() on a TV with no address must give False and send nothing")
    if callable(getattr(extra, "close_app", None)):
        apps = getattr(extra, "apps", None)
        if not isinstance(apps, Mapping):
            problems.append("a driver that closes apps names them in 'apps'")
            return
        if any(name != name.casefold() for name in apps):
            problems.append(
                "the names in 'apps' are lower case, as the owner's words are matched in lower case"
            )
        if silent is not None and apps:
            app_id = next(iter(apps.values()))
            closed = await _never_raises(
                problems, "close_app() on a silent address", extra.close_app(silent, app_id)
            )
            if closed is not False:
                problems.append("close_app() on a silent address must give False")
    await _check_open_app(extra, problems, silent)


async def _check_open_app(extra: Any, problems: list[str], silent: str | None) -> None:  # noqa: ANN401
    """open_app(), when the driver has it."""
    if callable(getattr(extra, "open_app", None)) and silent is not None:
        apps = getattr(extra, "apps", None) or {}
        if apps:
            app_id = next(iter(apps.values()))
            opened = await _never_raises(
                problems, "open_app() on a silent address", extra.open_app(silent, app_id)
            )
            if opened is not False:
                problems.append("open_app() on a silent address must give False")

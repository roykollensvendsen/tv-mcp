# SPDX-License-Identifier: GPL-3.0-or-later
"""The owner's settings file: which TVs there are, what each is called, and the Jellyfin server.

The file lives outside the repository (``~/.config/tv-mcp/config.toml``, or the
path in ``TV_MCP_SETTINGS``), because it holds addresses, tokens and keys:

    [jellyfin]
    url = "http://192.0.2.5:8096"
    # the API key: in a file of its own, ``jellyfin-key`` beside this one, or here as api_key

    [tvs.living-room]
    location = "the living room"   # what the TV is called and answers to
    description = "The Frame by the window"   # free text the voice can read
    names = ["The Frame"]          # other names it answers to, if any
    address = "192.0.2.10"
    model = "QE55LS03BAUXXC"       # as the TV reports it; also found by "LS03B"
    device_id = "uuid:..."         # the TV's own id, so a TV that answers as another is not used
    mac = "00:00:5E:00:53:01"
    hands_off = false        # true: no tool sends this TV anything
    driver = "samsung-tizen"  # the brand or platform; this is the default

    [features]
    enabled = ["status", "setup"]   # leave out for the default: status only
"""

from __future__ import annotations

import os
import pathlib
import re
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

DEFAULT_PATH = "~/.config/tv-mcp/config.toml"
#: The Jellyfin API key's own file, beside the settings file, so it can be
#: pasted into an editor without touching the settings.
KEY_FILE = "jellyfin-key"
#: A user's own login, for a Chromecast to fetch films as that user (Quick Connect gives one).
USER_TOKEN_FILE = "jellyfin-user-token"  # noqa: S105 - a file name, not a token


@dataclass(frozen=True)
class Tv:
    """One TV as the owner set it up."""

    key: str
    names: tuple[str, ...]
    address: str | None = None
    mac: str | None = None
    hands_off: bool = False
    driver: str = "samsung-tizen"
    location: str | None = None
    description: str | None = None
    model: str | None = None
    device_id: str | None = None
    device_name: str | None = None  # the name the TV gives itself

    @property
    def spoken(self) -> str:
        """The name to say back: where it stands, else the first name the owner gave, else the key."""
        return self.location or (self.names[0] if self.names else self.key)

    @property
    def brand(self) -> str | None:
        """The maker, from the driver the TV uses."""
        return BRANDS.get(self.driver)

    def answers_to(self) -> set[str]:
        """Every name this TV is found by, as names compare."""
        said = [self.key, *self.names, self.model or "", self.device_name or "", self.brand or ""]
        if self.location:
            said += [self.location, f"tv {self.location}", f"tv-en {self.location}"]
        return {_plain(n) for n in said if n}

    def has_model(self, wanted: str) -> bool:
        """Whether `wanted` is the model code or a part of it, such as "Q68CA" in "TQ55Q68CAUXXC"."""
        part = wanted.replace(" ", "")
        return bool(self.model) and len(part) >= MODEL_PART and part in _plain(self.model or "")


#: The makers behind each driver.
BRANDS = {"samsung-tizen": "Samsung"}
#: The shortest part of a model code a TV is found by.
MODEL_PART = 4


@dataclass(frozen=True)
class Settings:
    """Everything read from the settings file."""

    tvs: tuple[Tv, ...] = ()
    jellyfin_url: str | None = None
    jellyfin_key: str | None = None
    jellyfin_user_token: str | None = None
    #: The features switched on; None means the default set (tv_mcp.tools).
    features: tuple[str, ...] | None = None


class UnknownTvError(LookupError):
    """No TV answers to the name given."""


class AmbiguousTvError(LookupError):
    """More than one TV answers to the name given."""


def settings_path(env: Mapping[str, str] | None = None) -> pathlib.Path:
    """Where the settings file is read from."""
    env = os.environ if env is None else env
    return pathlib.Path(env.get("TV_MCP_SETTINGS", DEFAULT_PATH)).expanduser()


def load_settings(path: pathlib.Path) -> Settings:
    """Read the settings file; a missing file means no TVs and no server."""
    if not path.is_file():
        return Settings()
    data = tomllib.loads(path.read_text())
    jellyfin: dict[str, Any] = data.get("jellyfin", {})
    tvs = tuple(_tv(key, table) for key, table in data.get("tvs", {}).items())
    enabled = data.get("features", {}).get("enabled")
    return Settings(
        tvs=tvs,
        jellyfin_url=jellyfin.get("url"),
        jellyfin_key=jellyfin.get("api_key") or _key_file(path),
        jellyfin_user_token=_key_file(path, USER_TOKEN_FILE),
        features=tuple(enabled) if enabled is not None else None,
    )


def _key_file(settings: pathlib.Path, name: str = KEY_FILE) -> str | None:
    file = settings.with_name(name)
    key = file.read_text().strip() if file.is_file() else ""
    return key or None


def _tv(key: str, table: dict[str, Any]) -> Tv:
    return Tv(
        key=key,
        names=tuple(table.get("names", ())),
        address=table.get("address"),
        mac=table.get("mac"),
        hands_off=bool(table.get("hands_off", False)),
        driver=str(table.get("driver", "samsung-tizen")),
        location=table.get("location"),
        description=table.get("description"),
        model=table.get("model"),
        device_id=table.get("device_id"),
        device_name=table.get("device_name"),
    )


def _plain(name: str) -> str:
    """A name as it compares: case, hyphens, spacing and a leading "the" do not matter."""
    words = re.sub(r"[-_\s]+", " ", name).strip().casefold().split()
    if words[:1] == ["the"]:
        words = words[1:]
    return " ".join(words)


def find_tv(settings: Settings, name: str) -> Tv:
    """The one TV that answers to `name`; refuses rather than guesses."""
    wanted = _plain(name)
    matches = [tv for tv in settings.tvs if wanted in tv.answers_to() or tv.has_model(wanted)]
    if not matches:
        known = ", ".join(tv.spoken for tv in settings.tvs) or "none set up yet"
        msg = f"No TV is called {name!r}. The TVs are: {known}."
        raise UnknownTvError(msg)
    # RULE: a name that matches two TVs is refused
    if len(matches) > 1:
        both = " and ".join(tv.spoken for tv in matches)
        msg = f"{name!r} could mean {both}. Say which one."
        raise AmbiguousTvError(msg)
    return matches[0]

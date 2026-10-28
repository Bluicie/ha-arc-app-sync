"""The TVs of the arc_launcher integration, as this integration sees them."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .const import ARC_DOMAIN


@dataclass(frozen=True)
class Tv:
    device_id: str
    name: str
    host: str
    status: dict[str, Any]


def arc_tvs(hass: HomeAssistant) -> dict[str, Tv]:
    """Every TV set up in arc_launcher, by its Arc device id."""
    tvs: dict[str, Tv] = {}
    for entry in hass.config_entries.async_entries(ARC_DOMAIN):
        device_id = entry.unique_id or entry.entry_id
        status: dict[str, Any] = {}
        if entry.state is ConfigEntryState.LOADED and getattr(entry.runtime_data, "data", None):
            status = entry.runtime_data.data
        tvs[device_id] = Tv(device_id, status.get("name") or entry.title, entry.data[CONF_HOST], status)
    return tvs


def derive_leader(tvs: dict[str, Tv]) -> str | None:
    """The TV the others follow in Arc, else one that shares its layout, else the first one."""
    followed: Counter[str] = Counter()
    for tv in tvs.values():
        sync = tv.status.get("sync") or {}
        if not sync.get("url"):
            continue
        host = urlparse(sync["url"]).hostname
        for other in tvs.values():
            if other is not tv and (host == other.host or sync.get("following") in (other.device_id, other.name)):
                followed[other.device_id] += 1
                break
    if followed:
        return followed.most_common(1)[0][0]
    for tv in tvs.values():
        if tv.status.get("sharing"):
            return tv.device_id
    return next(iter(tvs), None)

"""Diagnostics for Arc Launcher App Sync."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from .coordinator import AppSyncConfigEntry, resolve_leader
from .tvs import arc_tvs


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: AppSyncConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    tvs = arc_tvs(hass)
    return {
        "options": dict(entry.options),
        # Host addresses stay out: diagnostics end up in public issues.
        "tvs": {device_id: tv.name for device_id, tv in tvs.items()},
        "leader": resolve_leader(hass, dict(entry.options), tvs),
        "running": coordinator.running,
        "last_run": coordinator.data,
        "play_store_opened": coordinator.play_store_opened,
    }

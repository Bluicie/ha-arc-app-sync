"""Arc Launcher App Sync: mirror the apps of a leader TV to the other Arc Launcher TVs over ADB."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util import dt as dt_util

from .const import CONF_DRY_RUN, CONF_SYNC_TIME, DEFAULT_SYNC_TIME
from .coordinator import AppSyncConfigEntry, AppSyncCoordinator

PLATFORMS = [Platform.BUTTON, Platform.SENSOR, Platform.SWITCH]


async def async_setup_entry(hass: HomeAssistant, entry: AppSyncConfigEntry) -> bool:
    coordinator = AppSyncCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    sync_time = dt_util.parse_time(entry.options.get(CONF_SYNC_TIME, DEFAULT_SYNC_TIME))
    if sync_time is not None:

        async def _scheduled_run(_now) -> None:
            await coordinator.async_run()

        entry.async_on_unload(
            async_track_time_change(
                hass, _scheduled_run, hour=sync_time.hour, minute=sync_time.minute, second=sync_time.second
            )
        )
    options = dict(entry.options)
    entry.async_on_unload(entry.add_update_listener(lambda hass, entry: _async_options_updated(hass, entry, options)))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: AppSyncConfigEntry, before: dict) -> None:
    # The dry-run switch changes an option too; it needs no reload.
    if {**entry.options, CONF_DRY_RUN: None} != {**before, CONF_DRY_RUN: None}:
        await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: AppSyncConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

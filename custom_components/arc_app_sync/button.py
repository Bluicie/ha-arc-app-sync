"""The "Sync apps now" button."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import AppSyncConfigEntry
from .entity import AppSyncEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AppSyncConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([SyncNowButton(entry.runtime_data, "sync_now")])


class SyncNowButton(AppSyncEntity, ButtonEntity):
    @property
    def available(self) -> bool:
        return super().available and not self.coordinator.running

    async def async_press(self) -> None:
        # A run can take many minutes (copying APKs); don't keep the frontend waiting for it.
        self.coordinator.config_entry.async_create_background_task(
            self.hass, self.coordinator.async_run(), "arc_app_sync run"
        )

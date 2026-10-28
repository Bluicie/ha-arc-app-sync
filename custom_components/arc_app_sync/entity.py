"""Base entities for Arc Launcher App Sync."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ARC_DOMAIN, DOMAIN
from .coordinator import AppSyncCoordinator


class AppSyncEntity(CoordinatorEntity[AppSyncCoordinator]):
    """An entity of the integration itself (sync button, dry-run switch)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AppSyncCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_translation_key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            entry_type=DeviceEntryType.SERVICE,
            manufacturer="Arc Launcher",
            model="App sync",
            name="Arc App Sync",
        )


class TvEntity(CoordinatorEntity[AppSyncCoordinator]):
    """An entity on the device of an Arc Launcher TV."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AppSyncCoordinator, device_id: str, key: str) -> None:
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_translation_key = key
        self._attr_unique_id = f"{device_id}_app_sync_{key}"
        self._attr_device_info = DeviceInfo(identifiers={(ARC_DOMAIN, device_id)})

    @property
    def result(self) -> dict[str, Any] | None:
        """This TV's part of the last run; None before the first run."""
        return (self.coordinator.data or {}).get("tvs", {}).get(self.device_id)

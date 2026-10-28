"""Per-TV sensors: apps missing, apps to remove, last app sync, status."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import STATUS_NEVER, STATUSES
from .coordinator import AppSyncConfigEntry, profiles
from .entity import TvEntity
from .tvs import arc_device, arc_tvs


@dataclass(frozen=True, kw_only=True)
class AppSyncSensorDescription(SensorEntityDescription):
    value: Callable[[dict[str, Any]], Any]
    attributes: Callable[[dict[str, Any]], dict[str, Any]] = lambda result: {}


def _timestamp(value: str | None) -> datetime | None:
    return dt_util.parse_datetime(value) if value else None


SENSORS = (
    AppSyncSensorDescription(
        key="apps_missing",
        value=lambda result: len(result.get("missing") or []),
        attributes=lambda result: {
            "packages": result.get("missing") or [],
            "needs_play_store": result.get("needs_play_store") or [],
            "installed": result.get("installed") or [],
        },
    ),
    AppSyncSensorDescription(
        key="apps_to_remove",
        value=lambda result: len(result.get("to_remove") or []),
        attributes=lambda result: {"packages": result.get("to_remove") or [], "removed": result.get("removed") or []},
    ),
    AppSyncSensorDescription(
        key="last_app_sync",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=lambda result: _timestamp(result.get("last_sync")),
    ),
    AppSyncSensorDescription(
        key="app_sync_status",
        device_class=SensorDeviceClass.ENUM,
        options=STATUSES,
        value=lambda result: result.get("status", STATUS_NEVER),
        attributes=lambda result: {"problems": result.get("problems") or []},
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AppSyncConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    # Every TV with a profile, also one that is the leader right now: the leader can change.
    targets = profiles(dict(entry.options), None)
    tvs = arc_tvs(hass)
    devices = {device_id: arc_device(hass, tvs[device_id]) if device_id in tvs else None for device_id in targets}
    async_add_entities(
        AppSyncSensor(coordinator, device_id, device, description)
        for device_id, device in devices.items()
        for description in SENSORS
    )


class AppSyncSensor(TvEntity, SensorEntity):
    entity_description: AppSyncSensorDescription

    def __init__(self, coordinator, device_id: str, device, description: AppSyncSensorDescription) -> None:
        super().__init__(coordinator, device_id, device, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        result = self.result
        if result is None:
            return STATUS_NEVER if self.entity_description.key == "app_sync_status" else None
        return self.entity_description.value(result)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        return self.entity_description.attributes(self.result) if self.result else None

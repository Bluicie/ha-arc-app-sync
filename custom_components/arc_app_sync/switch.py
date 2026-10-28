"""The dry-run switch: on = only report what a run would change."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_DRY_RUN
from .coordinator import AppSyncConfigEntry
from .entity import AppSyncEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AppSyncConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([DryRunSwitch(entry.runtime_data, "dry_run")])


class DryRunSwitch(AppSyncEntity, SwitchEntity):
    _attr_entity_category = EntityCategory.CONFIG

    @property
    def is_on(self) -> bool:
        return self.coordinator.config_entry.options.get(CONF_DRY_RUN, True)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._set(False)

    def _set(self, dry_run: bool) -> None:
        entry = self.coordinator.config_entry
        self.hass.config_entries.async_update_entry(entry, options={**entry.options, CONF_DRY_RUN: dry_run})
        self.async_write_ha_state()

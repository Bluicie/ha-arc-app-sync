"""Config and options flow: leader, profile per TV, then apps and schedule."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TimeSelector,
)

from .adb import AdbError, AdbTv, async_get_signer
from .const import (
    CONF_DRY_RUN,
    CONF_FULL_TVS,
    CONF_KIDS_ALLOWLIST,
    CONF_KIDS_TVS,
    CONF_LEADER,
    CONF_MAX_REMOVALS,
    CONF_MUST_HAVE,
    CONF_SYNC_TIME,
    DEFAULT_MAX_REMOVALS,
    DEFAULT_SYNC_TIME,
    DOMAIN,
    LEADER_AUTO,
)
from .coordinator import resolve_leader
from .tvs import Tv, arc_tvs

_LOGGER = logging.getLogger(__name__)

# Reading the leader's apps may first need "Allow USB debugging?" on the TV.
READ_APPS_TIMEOUT = 20
AUTOMATIC = {"nl": "Automatisch"}


async def async_read_apps(hass, host: str) -> list[str] | None:
    """The leader's user-installed apps, or None when ADB does not get in."""
    try:
        async with asyncio.timeout(READ_APPS_TIMEOUT):
            tv = AdbTv(host, await async_get_signer(hass))
            await tv.connect()
            try:
                return sorted(await tv.packages(third_party=True))
            finally:
                await tv.close()
    except (AdbError, TimeoutError) as err:
        _LOGGER.debug("Could not read the apps of %s: %s", host, err)
        return None


def _tv_options(tvs: dict[str, Tv], skip: str | None = None) -> list[SelectOptionDict]:
    return [SelectOptionDict(value=device_id, label=tv.name) for device_id, tv in tvs.items() if device_id != skip]


def _package_selector(packages: list[str]) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=packages, multiple=True, custom_value=True, sort=True, mode=SelectSelectorMode.DROPDOWN
        )
    )


class _AppSyncFlow:
    """The steps the config flow and the options flow share. Collects self.options, then calls _finish."""

    hass: Any
    options: dict[str, Any]
    async_show_form: Any  # from the flow class

    def _finish(self) -> ConfigFlowResult:
        raise NotImplementedError

    async def async_step_leader(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        tvs = arc_tvs(self.hass)
        if user_input is not None:
            self.options.update(user_input)
            return await self.async_step_tvs()
        auto = resolve_leader(self.hass, {}, tvs)
        automatic = AUTOMATIC.get(self.hass.config.language, "Automatic")
        choices = [SelectOptionDict(value=LEADER_AUTO, label=f"{automatic} ({tvs[auto].name})"), *_tv_options(tvs)]
        return self.async_show_form(
            step_id="leader",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LEADER, default=self.options.get(CONF_LEADER, LEADER_AUTO)): SelectSelector(
                        SelectSelectorConfig(options=choices, mode=SelectSelectorMode.LIST)
                    )
                }
            ),
        )

    async def async_step_tvs(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        tvs = arc_tvs(self.hass)
        leader = resolve_leader(self.hass, self.options, tvs)
        errors: dict[str, str] = {}
        if user_input is not None:
            if set(user_input[CONF_FULL_TVS]) & set(user_input[CONF_KIDS_TVS]):
                errors["base"] = "both_profiles"
            else:
                self.options.update(user_input)
                return await self.async_step_apps()
        others = [device_id for device_id in tvs if device_id != leader]
        known = set(self.options.get(CONF_FULL_TVS, [])) | set(self.options.get(CONF_KIDS_TVS, []))
        # New TVs (and every TV on first setup) start as "full"; dry run is on by default anyway.
        full = [d for d in others if d in self.options.get(CONF_FULL_TVS, []) or d not in known]
        kids = [d for d in others if d in self.options.get(CONF_KIDS_TVS, [])]
        tv_selector = SelectSelector(
            SelectSelectorConfig(options=_tv_options(tvs, leader), multiple=True, mode=SelectSelectorMode.LIST)
        )
        return self.async_show_form(
            step_id="tvs",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_FULL_TVS, default=full): tv_selector,
                    vol.Optional(CONF_KIDS_TVS, default=kids): tv_selector,
                }
            ),
            errors=errors,
            description_placeholders={"leader": tvs[leader].name},
        )

    async def async_step_apps(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self.options.update(user_input)
            self.options.setdefault(CONF_KIDS_ALLOWLIST, [])
            return self._finish()
        tvs = arc_tvs(self.hass)
        leader = tvs[resolve_leader(self.hass, self.options, tvs)]
        errors: dict[str, str] = {}
        apps = await async_read_apps(self.hass, leader.host)
        if apps is None:
            errors["base"] = "leader_apps_unavailable"
            apps = []
        must_have = self.options.get(CONF_MUST_HAVE, [])
        allowlist = self.options.get(CONF_KIDS_ALLOWLIST, [])
        schema: dict[Any, Any] = {
            vol.Optional(CONF_MUST_HAVE, default=must_have): _package_selector(sorted({*apps, *must_have})),
        }
        if self.options.get(CONF_KIDS_TVS):
            schema[vol.Optional(CONF_KIDS_ALLOWLIST, default=allowlist)] = _package_selector(
                sorted({*apps, *allowlist})
            )
        schema.update(
            {
                vol.Required(
                    CONF_MAX_REMOVALS, default=self.options.get(CONF_MAX_REMOVALS, DEFAULT_MAX_REMOVALS)
                ): vol.All(
                    NumberSelector(NumberSelectorConfig(min=0, max=100, step=1, mode=NumberSelectorMode.BOX)),
                    vol.Coerce(int),
                ),
                vol.Required(CONF_SYNC_TIME, default=self.options.get(CONF_SYNC_TIME, DEFAULT_SYNC_TIME)): TimeSelector(),
                vol.Required(CONF_DRY_RUN, default=self.options.get(CONF_DRY_RUN, True)): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="apps",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={"leader": leader.name},
        )


class AppSyncConfigFlow(_AppSyncFlow, ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self.options: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AppSyncOptionsFlow:
        return AppSyncOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if not arc_tvs(self.hass):
            return self.async_abort(reason="no_tvs")
        return await self.async_step_leader()

    def _finish(self) -> ConfigFlowResult:
        return self.async_create_entry(title="Arc App Sync", data={}, options=self.options)


class AppSyncOptionsFlow(_AppSyncFlow, OptionsFlow):
    def __init__(self) -> None:
        self.options: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if not arc_tvs(self.hass):
            return self.async_abort(reason="no_tvs")
        self.options = dict(self.config_entry.options)
        return await self.async_step_leader()

    def _finish(self) -> ConfigFlowResult:
        return self.async_create_entry(data=self.options)

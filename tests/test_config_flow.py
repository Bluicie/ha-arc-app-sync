"""Config flow, options flow and diagnostics."""

from __future__ import annotations

from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import get_diagnostics_for_config_entry

from custom_components.arc_app_sync.const import (
    CONF_DRY_RUN,
    CONF_FULL_TVS,
    CONF_KIDS_ALLOWLIST,
    CONF_KIDS_TVS,
    CONF_LEADER,
    CONF_MAX_REMOVALS,
    CONF_MUST_HAVE,
    CONF_SYNC_TIME,
    DOMAIN,
    LEADER_AUTO,
)
from custom_components.arc_app_sync.tvs import arc_tvs as read_arc_tvs, derive_leader
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import BEDROOM, KIDS, LIVING, FakeTv

APPS = {CONF_MUST_HAVE: ["com.stremio.one"], CONF_MAX_REMOVALS: 3, CONF_SYNC_TIME: "20:30:00", CONF_DRY_RUN: True}


async def test_no_tvs(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_tvs"


def test_leader_is_the_tv_the_others_follow(hass: HomeAssistant, arc_tvs) -> None:
    assert derive_leader(read_arc_tvs(hass)) == LIVING[1]


async def test_full_flow(hass: HomeAssistant, arc_tvs, fake_adb: dict[str, FakeTv]) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["step_id"] == "leader"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_LEADER: LEADER_AUTO})
    assert result["step_id"] == "tvs"
    assert result["description_placeholders"] == {"leader": LIVING[0]}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_FULL_TVS: [BEDROOM[1], KIDS[1]], CONF_KIDS_TVS: [KIDS[1]]}
    )
    assert result["errors"] == {"base": "both_profiles"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_FULL_TVS: [BEDROOM[1]], CONF_KIDS_TVS: [KIDS[1]]}
    )
    assert result["step_id"] == "apps"
    assert result["errors"] == {}
    # The package lists offer the leader's user-installed apps.
    must_have = next(key for key in result["data_schema"].schema if key == CONF_MUST_HAVE)
    selector = result["data_schema"].schema[must_have]
    assert "com.disney.disneyplus" in selector.config["options"]

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**APPS, CONF_KIDS_ALLOWLIST: ["com.disney.disneyplus"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {
        CONF_LEADER: LEADER_AUTO,
        CONF_FULL_TVS: [BEDROOM[1]],
        CONF_KIDS_TVS: [KIDS[1]],
        CONF_KIDS_ALLOWLIST: ["com.disney.disneyplus"],
        **APPS,
    }


async def test_leader_apps_unavailable(hass: HomeAssistant, arc_tvs, fake_adb: dict[str, FakeTv]) -> None:
    fake_adb[BEDROOM[2]].reachable = False
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_LEADER: BEDROOM[1]})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_FULL_TVS: [LIVING[1]], CONF_KIDS_TVS: []}
    )
    assert result["step_id"] == "apps"
    assert result["errors"] == {"base": "leader_apps_unavailable"}
    # No kids TVs: no allowlist to fill in.
    assert CONF_KIDS_ALLOWLIST not in result["data_schema"].schema
    result = await hass.config_entries.flow.async_configure(result["flow_id"], APPS)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_KIDS_ALLOWLIST] == []


async def test_options_flow(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    result = await hass.config_entries.options.async_init(setup_entry.entry_id)
    assert result["step_id"] == "leader"
    result = await hass.config_entries.options.async_configure(result["flow_id"], {CONF_LEADER: LIVING[1]})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_FULL_TVS: [BEDROOM[1], KIDS[1]], CONF_KIDS_TVS: []}
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], APPS)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert setup_entry.options[CONF_FULL_TVS] == [BEDROOM[1], KIDS[1]]
    assert setup_entry.options[CONF_LEADER] == LIVING[1]
    # The kids allowlist is kept for when a TV gets the kids profile again.
    assert setup_entry.options[CONF_KIDS_ALLOWLIST] == ["com.disney.disneyplus", "com.google.android.youtube.tv"]


async def test_single_instance(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_diagnostics(hass: HomeAssistant, hass_client, setup_entry: MockConfigEntry) -> None:
    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, setup_entry)
    assert diagnostics["leader"] == LIVING[1]
    assert diagnostics["tvs"][BEDROOM[1]] == BEDROOM[0]
    assert BEDROOM[2] not in str(diagnostics)

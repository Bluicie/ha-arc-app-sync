"""The sync rules and a run against fake TVs."""

from __future__ import annotations

from unittest.mock import patch

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.arc_app_sync.const import (
    CONF_DRY_RUN,
    CONF_MAX_REMOVALS,
    CONF_SYNC_TIME,
    PROFILE_FULL,
    PROFILE_KIDS,
)
from custom_components.arc_app_sync.sync import plan_apps
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from .conftest import BEDROOM, KIDS, LIVING, OPTIONS, FakeTv

LEADER_ALL = {"android", "com.netflix.ninja", "com.a", "com.b"}
LEADER_3P = {"com.a", "com.b"}


def test_plan_full() -> None:
    install, remove = plan_apps(
        PROFILE_FULL,
        LEADER_ALL,
        LEADER_3P,
        target_all={"android", "com.a", "com.c", "com.bluicie.arc", "com.keep"},
        target_3p={"com.a", "com.c", "com.bluicie.arc", "com.keep"},
        must_have=frozenset({"com.netflix.ninja", "com.keep", "com.not.on.leader"}),
        kids_allowlist=frozenset(),
    )
    # Netflix is a system app on the leader but must-have, so it is copied; must-haves the leader lacks are not.
    assert install == ["com.b", "com.netflix.ninja"]
    # Arc Launcher and must-have apps are never removed.
    assert remove == ["com.c"]


def test_plan_full_keeps_what_the_leader_has_as_system_app() -> None:
    _, remove = plan_apps(PROFILE_FULL, LEADER_ALL, LEADER_3P, {"com.netflix.ninja"}, {"com.netflix.ninja"},
                          frozenset(), frozenset())
    assert remove == []


def test_plan_kids() -> None:
    install, remove = plan_apps(
        PROFILE_KIDS,
        LEADER_ALL,
        LEADER_3P,
        target_all={"android", "com.x", "com.allowed", "com.spocky.projengmenu", "com.netflix.ninja"},
        target_3p={"com.x", "com.allowed", "com.spocky.projengmenu", "com.netflix.ninja"},
        must_have=frozenset({"com.netflix.ninja"}),
        kids_allowlist=frozenset({"com.a", "com.allowed"}),
    )
    assert install == ["com.a"]
    assert remove == ["com.x"]


def _state(hass: HomeAssistant, device_id: str, key: str):
    entity_id = er.async_get(hass).async_get_entity_id("sensor", "arc_app_sync", f"{device_id}_app_sync_{key}")
    return hass.states.get(entity_id) if entity_id else None


async def _press(hass: HomeAssistant) -> None:
    entity_id = er.async_get(hass).async_get_entity_id("button", "arc_app_sync", _unique(hass, "sync_now"))
    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)
    await hass.async_block_till_done(wait_background_tasks=True)


def _unique(hass: HomeAssistant, key: str) -> str:
    entry = hass.config_entries.async_entries("arc_app_sync")[0]
    return f"{entry.entry_id}_{key}"


async def test_entities_before_first_run(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    assert _state(hass, BEDROOM[1], "app_sync_status").state == "never"
    assert _state(hass, BEDROOM[1], "apps_missing").state == "unknown"
    # The sensors sit on the TV's own Arc Launcher device.
    entry = er.async_get(hass).async_get(_state(hass, KIDS[1], "apps_missing").entity_id)
    assert entry.device_id is not None
    assert _state(hass, LIVING[1], "apps_missing") is None


async def test_dry_run_changes_nothing(
    hass: HomeAssistant, setup_entry: MockConfigEntry, fake_adb: dict[str, FakeTv]
) -> None:
    await _press(hass)

    missing = _state(hass, BEDROOM[1], "apps_missing")
    assert missing.state == "2"
    assert missing.attributes["packages"] == ["com.disney.disneyplus", "com.netflix.ninja"]
    to_remove = _state(hass, BEDROOM[1], "apps_to_remove")
    assert to_remove.attributes["packages"] == ["com.game.crossy"]
    assert _state(hass, BEDROOM[1], "app_sync_status").state == "dry_run"
    assert _state(hass, KIDS[1], "apps_missing").attributes["packages"] == ["com.disney.disneyplus"]
    assert _state(hass, KIDS[1], "apps_to_remove").attributes["packages"] == ["com.tf1.plus"]
    assert _state(hass, KIDS[1], "last_app_sync").state != "unknown"
    assert not any(call[0] in ("install", "uninstall") for tv in fake_adb.values() for call in tv.calls)


async def test_sync(hass: HomeAssistant, setup_entry: MockConfigEntry, fake_adb: dict[str, FakeTv]) -> None:
    hass.config_entries.async_update_entry(setup_entry, options={**setup_entry.options, CONF_DRY_RUN: False})
    bedroom, kids = fake_adb[BEDROOM[2]], fake_adb[KIDS[2]]
    bedroom.refuse = {"com.netflix.ninja"}
    await _press(hass)

    assert "com.disney.disneyplus" in bedroom.user and "com.game.crossy" not in bedroom.user
    assert ("play_store", "com.netflix.ninja") in bedroom.calls
    assert kids.user == {"com.google.android.youtube.tv", "com.disney.disneyplus"}
    # Disney+ was pulled from the leader once, for both TVs.
    assert fake_adb[LIVING[2]].calls.count(("pull", "/data/app/com.disney.disneyplus/base.apk")) == 1
    status = _state(hass, BEDROOM[1], "app_sync_status")
    assert status.state == "ok"
    missing = _state(hass, BEDROOM[1], "apps_missing")
    assert missing.attributes["packages"] == ["com.netflix.ninja"]
    assert missing.attributes["installed"] == ["com.disney.disneyplus"]

    # The Play Store page opens only once per app and TV.
    bedroom.calls.clear()
    await _press(hass)
    assert bedroom.calls == []
    assert _state(hass, BEDROOM[1], "apps_missing").attributes["needs_play_store"] == ["com.netflix.ninja"]


async def test_removal_limit(hass: HomeAssistant, setup_entry: MockConfigEntry, fake_adb: dict[str, FakeTv]) -> None:
    hass.config_entries.async_update_entry(
        setup_entry, options={**setup_entry.options, CONF_DRY_RUN: False, CONF_MAX_REMOVALS: 0}
    )
    await hass.async_block_till_done()
    await _press(hass)
    assert "com.game.crossy" in fake_adb[BEDROOM[2]].user
    status = _state(hass, BEDROOM[1], "app_sync_status")
    assert status.state == "attention"
    assert "limit of 0" in status.attributes["problems"][0]


async def test_skips_asleep_and_unreachable(
    hass: HomeAssistant, setup_entry: MockConfigEntry, fake_adb: dict[str, FakeTv]
) -> None:
    await _press(hass)
    fake_adb[BEDROOM[2]].awake = False
    fake_adb[KIDS[2]].reachable = False
    await _press(hass)
    assert _state(hass, BEDROOM[1], "app_sync_status").state == "asleep"
    # What the last run found is kept.
    assert _state(hass, BEDROOM[1], "apps_missing").state == "2"
    kids = _state(hass, KIDS[1], "app_sync_status")
    assert kids.state == "unreachable"
    assert "connection refused" in kids.attributes["problems"][0]


async def test_leader_unreachable(
    hass: HomeAssistant, setup_entry: MockConfigEntry, fake_adb: dict[str, FakeTv]
) -> None:
    fake_adb[LIVING[2]].reachable = False
    await _press(hass)
    assert _state(hass, BEDROOM[1], "app_sync_status").state == "leader_unavailable"
    assert _state(hass, BEDROOM[1], "last_app_sync").state == "unknown"


async def test_leader_without_apps_is_not_mirrored(
    hass: HomeAssistant, setup_entry: MockConfigEntry, fake_adb: dict[str, FakeTv]
) -> None:
    hass.config_entries.async_update_entry(setup_entry, options={**setup_entry.options, CONF_DRY_RUN: False})
    fake_adb[LIVING[2]].user = set()
    await _press(hass)
    assert "com.game.crossy" in fake_adb[BEDROOM[2]].user
    assert _state(hass, BEDROOM[1], "app_sync_status").state == "leader_unavailable"


async def test_daily_schedule(hass: HomeAssistant, arc_tvs, fake_adb: dict[str, FakeTv]) -> None:
    entry = MockConfigEntry(domain="arc_app_sync", data={}, options={**OPTIONS, CONF_SYNC_TIME: "04:30:00"})
    entry.add_to_hass(hass)
    with patch("custom_components.arc_app_sync.async_track_time_change") as track:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert track.call_args.kwargs == {"hour": 4, "minute": 30, "second": 0}
    await track.call_args.args[1](dt_util.now())
    await hass.async_block_till_done()
    assert _state(hass, BEDROOM[1], "app_sync_status").state == "dry_run"


async def test_dry_run_switch(hass: HomeAssistant, setup_entry: MockConfigEntry) -> None:
    entity_id = er.async_get(hass).async_get_entity_id("switch", "arc_app_sync", _unique(hass, "dry_run"))
    assert hass.states.get(entity_id).state == "on"
    await hass.services.async_call("switch", "turn_off", {"entity_id": entity_id}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "off"
    assert setup_entry.options[CONF_DRY_RUN] is False

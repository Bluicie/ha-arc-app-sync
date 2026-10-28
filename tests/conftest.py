"""Fixtures: three Arc Launcher TVs (mocked HTTP) and fake ADB connections."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.arc_app_sync.adb import AdbError
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
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_TOKEN
from homeassistant.core import HomeAssistant

# name, device id, host; the living room TV shares its layout and the others follow it.
LIVING = ("Woonkamer", "dev-living", "192.0.2.10")
BEDROOM = ("Slaapkamer", "dev-bedroom", "192.0.2.11")
KIDS = ("Kinderen", "dev-kids", "192.0.2.12")
TVS = (LIVING, BEDROOM, KIDS)

OPTIONS = {
    CONF_LEADER: LEADER_AUTO,
    CONF_FULL_TVS: [BEDROOM[1]],
    CONF_KIDS_TVS: [KIDS[1]],
    CONF_MUST_HAVE: ["com.netflix.ninja"],
    CONF_KIDS_ALLOWLIST: ["com.disney.disneyplus", "com.google.android.youtube.tv"],
    CONF_MAX_REMOVALS: 5,
    CONF_SYNC_TIME: "19:00:00",
    CONF_DRY_RUN: True,
}


def arc_status(name: str, device_id: str, host: str) -> dict[str, Any]:
    leader = (name, device_id, host) == LIVING
    return {
        "app": "arc-launcher",
        "name": name,
        "id": device_id,
        "api": 1,
        "sharing": leader,
        "control": True,
        "appVersion": "1.2.0",
        "sync": {
            "url": "" if leader else f"http://{LIVING[2]}:47474/arc-launcher/v1/backup",
            "following": None if leader else LIVING[0],
            "enabled": not leader,
            "syncing": False,
            "lastCheck": None,
            "lastError": None,
        },
        "layout": {"hash": "abc", "sections": 2, "apps": 5},
    }


@dataclass
class FakeTv:
    """What adb.AdbTv offers, for one TV."""

    host: str
    system: set[str] = field(default_factory=lambda: {"android", "com.android.vending", "com.android.settings"})
    user: set[str] = field(default_factory=set)
    reachable: bool = True
    awake: bool = True
    # Packages whose install fails on this TV.
    refuse: set[str] = field(default_factory=set)
    calls: list[tuple[str, ...]] = field(default_factory=list)

    async def connect(self) -> None:
        if not self.reachable:
            raise AdbError(f"{self.host}: connection refused")

    async def close(self) -> None:
        pass

    async def packages(self, third_party: bool = False) -> set[str]:
        return set(self.user) if third_party else self.system | self.user

    async def is_awake(self) -> bool:
        return self.awake

    async def apk_paths(self, package: str) -> list[str]:
        if package not in self.system | self.user:
            return []
        return [f"/data/app/{package}/base.apk", f"/data/app/{package}/split_config.apk"]

    async def pull(self, device_path: str, local_path: str) -> None:
        self.calls.append(("pull", device_path))

    async def install(self, package: str, apks: list[str]) -> str | None:
        self.calls.append(("install", package))
        if package in self.refuse:
            return "INSTALL_FAILED_VERSION_DOWNGRADE"
        self.user.add(package)
        return None

    async def uninstall(self, package: str) -> bool:
        self.calls.append(("uninstall", package))
        self.user.discard(package)
        return True

    async def open_play_store(self, package: str) -> None:
        self.calls.append(("play_store", package))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def fake_tvs() -> dict[str, FakeTv]:
    """By host. The leader has Netflix as a system app; the bedroom TV has an extra game."""
    return {
        LIVING[2]: FakeTv(
            LIVING[2],
            system={"android", "com.android.vending", "com.netflix.ninja"},
            user={"com.disney.disneyplus", "com.stremio.one", "com.spocky.projengmenu"},
        ),
        BEDROOM[2]: FakeTv(BEDROOM[2], user={"com.stremio.one", "com.game.crossy", "com.bluicie.arc"}),
        KIDS[2]: FakeTv(KIDS[2], user={"com.google.android.youtube.tv", "com.tf1.plus"}),
    }


@pytest.fixture
def fake_adb(fake_tvs: dict[str, FakeTv]) -> Generator[dict[str, FakeTv]]:
    def make(host: str, signer: Any = None) -> FakeTv:
        return fake_tvs[host]

    with (
        patch("custom_components.arc_app_sync.coordinator.AdbTv", side_effect=make),
        patch("custom_components.arc_app_sync.config_flow.AdbTv", side_effect=make),
        patch("custom_components.arc_app_sync.coordinator.async_get_signer", return_value=None),
        patch("custom_components.arc_app_sync.config_flow.async_get_signer", return_value=None),
    ):
        yield fake_tvs


@pytest.fixture
async def arc_tvs(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> list[MockConfigEntry]:
    entries = []
    for name, device_id, host in TVS:
        aioclient_mock.get(f"http://{host}:47474/arc-launcher/v1/status", json=arc_status(name, device_id, host))
        entry = MockConfigEntry(
            domain="arc_launcher",
            title=name,
            unique_id=device_id,
            data={CONF_HOST: host, CONF_PORT: 47474, CONF_TOKEN: "token"},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        entries.append(entry)
    await hass.async_block_till_done()
    return entries


@pytest.fixture
async def setup_entry(hass: HomeAssistant, arc_tvs: list[MockConfigEntry], fake_adb) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="Arc App Sync", data={}, options=dict(OPTIONS))
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry

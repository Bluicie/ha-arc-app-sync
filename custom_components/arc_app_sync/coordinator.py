"""Coordinator: runs the app sync and keeps the last result."""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .adb import AdbError, AdbTv, async_get_signer
from .const import (
    CONF_DRY_RUN,
    CONF_FULL_TVS,
    CONF_KIDS_ALLOWLIST,
    CONF_KIDS_TVS,
    CONF_LEADER,
    CONF_MAX_REMOVALS,
    CONF_MUST_HAVE,
    DEFAULT_MAX_REMOVALS,
    DOMAIN,
    LEADER_AUTO,
    PROFILE_FULL,
    PROFILE_KIDS,
    STATUS_ASLEEP,
    STATUS_LEADER_UNAVAILABLE,
    STATUS_UNREACHABLE,
)
from .sync import SyncPlan, run_sync
from .tvs import Tv, arc_tvs, derive_leader

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
SKIPPED = {STATUS_ASLEEP, STATUS_LEADER_UNAVAILABLE, STATUS_UNREACHABLE}

type AppSyncConfigEntry = ConfigEntry[AppSyncCoordinator]


def resolve_leader(hass: HomeAssistant, options: dict[str, Any], tvs: dict[str, Tv] | None = None) -> str | None:
    tvs = arc_tvs(hass) if tvs is None else tvs
    leader = options.get(CONF_LEADER, LEADER_AUTO)
    return derive_leader(tvs) if leader == LEADER_AUTO or leader not in tvs else leader


def profiles(options: dict[str, Any], leader: str | None) -> dict[str, str]:
    """Device id -> profile, for every TV that follows the leader."""
    result = {device_id: PROFILE_FULL for device_id in options.get(CONF_FULL_TVS, [])}
    result.update({device_id: PROFILE_KIDS for device_id in options.get(CONF_KIDS_TVS, [])})
    result.pop(leader, None)
    return result


class AppSyncCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Data is the last run: {"last_run", "dry_run", "leader", "problem", "tvs": {device id: result}}."""

    config_entry: AppSyncConfigEntry

    def __init__(self, hass: HomeAssistant, entry: AppSyncConfigEntry) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=None)
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._lock = asyncio.Lock()
        self.play_store_opened: dict[str, list[str]] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        """Only the stored result: a run happens on schedule or on request, never on refresh."""
        stored = await self._store.async_load() or {}
        self.play_store_opened = stored.get("play_store_opened", {})
        return stored.get("last_run") or {"tvs": {}}

    @property
    def running(self) -> bool:
        return self._lock.locked()

    def _plan(self) -> SyncPlan | None:
        options = self.config_entry.options
        tvs = arc_tvs(self.hass)
        leader = resolve_leader(self.hass, options, tvs)
        if leader is None:
            return None
        return SyncPlan(
            leader=tvs[leader],
            targets={
                device_id: (tvs[device_id], profile)
                for device_id, profile in profiles(options, leader).items()
                if device_id in tvs
            },
            must_have=frozenset(options.get(CONF_MUST_HAVE, [])),
            kids_allowlist=frozenset(options.get(CONF_KIDS_ALLOWLIST, [])),
            max_removals=int(options.get(CONF_MAX_REMOVALS, DEFAULT_MAX_REMOVALS)),
            dry_run=options.get(CONF_DRY_RUN, True),
            play_store_opened=self.play_store_opened,
        )

    async def async_run(self) -> None:
        """One sync run; a second request while one runs is ignored."""
        if self._lock.locked():
            _LOGGER.debug("App sync already running")
            return
        async with self._lock:
            plan = self._plan()
            if plan is None:
                _LOGGER.warning("App sync: no Arc Launcher TVs set up")
                return
            self.async_update_listeners()  # show "running"
            signer = await async_get_signer(self.hass)

            async def connect(host: str) -> AdbTv:
                tv = AdbTv(host, signer)
                await tv.connect()
                return tv

            tmp_dir = await self.hass.async_add_executor_job(tempfile.mkdtemp, None, DOMAIN)
            try:
                result = await run_sync(plan, connect, tmp_dir)
            except AdbError as err:  # pragma: no cover - run_sync handles these itself
                _LOGGER.error("App sync failed: %s", err)
                return
            finally:
                await self.hass.async_add_executor_job(shutil.rmtree, tmp_dir, True)
            self.play_store_opened = plan.play_store_opened
            # A TV that was skipped keeps what the last run found out about it.
            previous = (self.data or {}).get("tvs", {})
            for device_id, tv_result in result["tvs"].items():
                if tv_result["status"] in SKIPPED and device_id in previous:
                    for key in ("missing", "to_remove", "last_sync"):
                        tv_result[key] = previous[device_id].get(key)
                elif tv_result["status"] in SKIPPED:
                    tv_result["last_sync"] = None
            await self._store.async_save({"last_run": result, "play_store_opened": self.play_store_opened})
        self.async_set_updated_data(result)

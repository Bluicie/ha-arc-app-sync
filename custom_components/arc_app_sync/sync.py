"""One app sync run: mirror the leader's apps to the other TVs over ADB."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
import logging
from typing import Any

from homeassistant.util import dt as dt_util

from .adb import AdbError, AdbTv
from .const import (
    ALWAYS_PROTECTED,
    PROFILE_KIDS,
    STATUS_ASLEEP,
    STATUS_ATTENTION,
    STATUS_DRY_RUN,
    STATUS_LEADER_UNAVAILABLE,
    STATUS_OK,
    STATUS_UNREACHABLE,
)
from .tvs import Tv

_LOGGER = logging.getLogger(__name__)


@dataclass
class SyncPlan:
    leader: Tv
    # device id -> (TV, profile)
    targets: dict[str, tuple[Tv, str]]
    must_have: frozenset[str]
    kids_allowlist: frozenset[str]
    max_removals: int
    dry_run: bool
    # device id -> packages whose Play Store page was opened already; updated by the run.
    play_store_opened: dict[str, list[str]] = field(default_factory=dict)


def plan_apps(
    profile: str,
    leader_all: set[str],
    leader_3p: set[str],
    target_all: set[str],
    target_3p: set[str],
    must_have: frozenset[str],
    kids_allowlist: frozenset[str],
) -> tuple[list[str], list[str]]:
    """What to install on and remove from one TV. Only user-installed apps are ever removed."""
    protected = ALWAYS_PROTECTED | must_have
    if profile == PROFILE_KIDS:
        want = leader_3p & kids_allowlist
        keep = kids_allowlist | protected
    else:
        # Must-have apps count when the leader has them in any form (some are system apps on one TV only).
        want = (must_have & leader_all) | leader_3p
        keep = leader_all | protected
    return sorted(want - target_all), sorted(target_3p - keep)


def _tv_result(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "missing": [],
        "to_remove": [],
        "installed": [],
        "removed": [],
        "needs_play_store": [],
        "problems": [],
        "last_sync": dt_util.utcnow().isoformat(),
        **values,
    }


async def run_sync(
    plan: SyncPlan, connect: Callable[[str], Awaitable[AdbTv]], tmp_dir: str
) -> dict[str, Any]:
    """Run once. Returns {"last_run", "dry_run", "leader", "problem", "tvs": {device id: result}}."""
    result: dict[str, Any] = {
        "last_run": dt_util.utcnow().isoformat(),
        "dry_run": plan.dry_run,
        "leader": plan.leader.device_id,
        "problem": None,
        "tvs": {},
    }
    try:
        leader = await connect(plan.leader.host)
    except AdbError as err:
        result["problem"] = f"leader {plan.leader.name} unreachable: {err}"
    else:
        try:
            leader_3p = await leader.packages(third_party=True)
            leader_all = await leader.packages()
            if not leader_3p:
                # Never mirror an empty list: it would remove everything.
                result["problem"] = f"no apps read from leader {plan.leader.name}"
            else:
                apks = _ApkCache(leader, tmp_dir)
                for device_id, (tv, profile) in plan.targets.items():
                    result["tvs"][device_id] = await _sync_tv(plan, tv, profile, leader_all, leader_3p, apks, connect)
        except AdbError as err:
            result["problem"] = f"lost leader {plan.leader.name}: {err}"
        finally:
            await leader.close()
    if result["problem"]:
        _LOGGER.warning("App sync: %s", result["problem"])
        for device_id in plan.targets:
            result["tvs"].setdefault(device_id, _tv_result(STATUS_LEADER_UNAVAILABLE))
    return result


class _ApkCache:
    """Pulls each app from the leader once per run, however many TVs need it."""

    def __init__(self, leader: AdbTv, tmp_dir: str) -> None:
        self._leader = leader
        self._tmp_dir = tmp_dir
        self._apks: dict[str, list[str] | str] = {}

    async def get(self, package: str) -> list[str] | str:
        """The local APK files, or why they could not be copied."""
        if package not in self._apks:
            paths = await self._leader.apk_paths(package)
            if not paths:
                self._apks[package] = "not found on the leader"
            else:
                local = []
                try:
                    for index, path in enumerate(paths):
                        local.append(f"{self._tmp_dir}/{package}_{index}.apk")
                        await self._leader.pull(path, local[-1])
                except AdbError as err:
                    self._apks[package] = str(err)
                else:
                    self._apks[package] = local
        return self._apks[package]


async def _sync_tv(
    plan: SyncPlan,
    tv: Tv,
    profile: str,
    leader_all: set[str],
    leader_3p: set[str],
    apks: _ApkCache,
    connect: Callable[[str], Awaitable[AdbTv]],
) -> dict[str, Any]:
    try:
        target = await connect(tv.host)
    except AdbError as err:
        _LOGGER.info("App sync: skipping %s: %s", tv.name, err)
        return _tv_result(STATUS_UNREACHABLE, problems=[str(err)])
    try:
        if not await target.is_awake():
            return _tv_result(STATUS_ASLEEP)
        install, remove = plan_apps(
            profile,
            leader_all,
            leader_3p,
            await target.packages(),
            await target.packages(third_party=True),
            plan.must_have,
            plan.kids_allowlist,
        )
        if plan.dry_run:
            return _tv_result(STATUS_DRY_RUN, missing=install, to_remove=remove)
        return await _apply(plan, tv, target, install, remove, apks)
    except AdbError as err:
        return _tv_result(STATUS_UNREACHABLE, problems=[f"connection lost: {err}"])
    finally:
        await target.close()


async def _apply(
    plan: SyncPlan, tv: Tv, target: AdbTv, install: list[str], remove: list[str], apks: _ApkCache
) -> dict[str, Any]:
    installed: list[str] = []
    manual: list[str] = []
    removed: list[str] = []
    problems: list[str] = []
    opened = plan.play_store_opened.setdefault(tv.device_id, [])
    for package in install:
        if package in opened:
            # Copying failed before; waiting for someone to press Install in the Play Store.
            manual.append(package)
            continue
        files = await apks.get(package)
        error = files if isinstance(files, str) else await target.install(package, files)
        if error is None:
            installed.append(package)
            _LOGGER.info("App sync: installed %s on %s", package, tv.name)
            continue
        _LOGGER.info("App sync: copying %s to %s failed (%s), opening the Play Store", package, tv.name, error)
        manual.append(package)
        await target.open_play_store(package)
        opened.append(package)

    if len(remove) > plan.max_removals:
        problems.append(f"{len(remove)} apps to remove, more than the limit of {plan.max_removals}: skipped")
    else:
        for package in remove:
            if await target.uninstall(package):
                removed.append(package)
                _LOGGER.info("App sync: removed %s from %s", package, tv.name)
            else:
                problems.append(f"uninstall {package} failed")
    # Installed in the meantime by hand: no need to remember the Play Store page any more.
    opened[:] = [package for package in opened if package in manual]
    return _tv_result(
        STATUS_ATTENTION if problems else STATUS_OK,
        missing=manual,
        to_remove=[package for package in remove if package not in removed],
        installed=installed,
        removed=removed,
        needs_play_store=manual,
        problems=problems,
    )

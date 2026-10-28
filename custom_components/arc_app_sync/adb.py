"""ADB access to one TV, on top of adb-shell (the library Home Assistant's androidtv integration uses)."""

from __future__ import annotations

import os
import re
import shlex

from adb_shell.adb_device_async import AdbDeviceTcpAsync
from adb_shell.auth.keygen import keygen
from adb_shell.auth.sign_pythonrsa import PythonRSASigner
from adb_shell.exceptions import (
    AdbCommandFailureException,
    AdbConnectionError,
    AdbTimeoutError,
    DeviceAuthError,
    InvalidChecksumError,
    InvalidCommandError,
    InvalidResponseError,
    PushFailedError,
    TcpTimeoutException,
)

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import STORAGE_DIR

from .const import ADB_PORT, DOMAIN, PLAY_STORE

TRANSPORT_TIMEOUT = 10
# How long the TV may take to answer "Allow USB debugging?" before a run gives up on it.
AUTH_TIMEOUT = 10
SHELL_TIMEOUT = 60
# Copying a big APK over Wi-Fi takes a while.
FILE_TIMEOUT = 600
TMP_DIR = "/data/local/tmp"

_SESSION = re.compile(r"\[(\d+)\]")
ADB_ERRORS = (
    AdbCommandFailureException,
    AdbConnectionError,
    AdbTimeoutError,
    DeviceAuthError,
    InvalidChecksumError,
    InvalidCommandError,
    InvalidResponseError,
    PushFailedError,
    TcpTimeoutException,
    OSError,
    TimeoutError,
)


class AdbError(Exception):
    """The TV could not be reached over ADB, or refused Home Assistant's key."""


def key_path(hass: HomeAssistant) -> str:
    return hass.config.path(STORAGE_DIR, DOMAIN, "adbkey")


def load_signer(path: str) -> PythonRSASigner:
    """Home Assistant's ADB key, made on first use. Runs in the executor."""
    if not os.path.isfile(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        keygen(path)
    with open(path, encoding="utf-8") as priv, open(f"{path}.pub", encoding="utf-8") as pub:
        return PythonRSASigner(pub.read(), priv.read())


async def async_get_signer(hass: HomeAssistant) -> PythonRSASigner:
    return await hass.async_add_executor_job(load_signer, key_path(hass))


class AdbTv:
    """One ADB connection. Every method raises AdbError when the connection breaks."""

    def __init__(self, host: str, signer: PythonRSASigner, port: int = ADB_PORT) -> None:
        self.host = host
        self._signer = signer
        self._device = AdbDeviceTcpAsync(host, port, default_transport_timeout_s=TRANSPORT_TIMEOUT)

    async def connect(self) -> None:
        try:
            await self._device.connect(rsa_keys=[self._signer], auth_timeout_s=AUTH_TIMEOUT)
        except ADB_ERRORS as err:
            await self.close()
            raise AdbError(f"{self.host}: {err or type(err).__name__}") from err

    async def close(self) -> None:
        try:
            await self._device.close()
        except ADB_ERRORS:
            pass

    async def shell(self, command: str) -> str:
        try:
            output = await self._device.shell(command, read_timeout_s=SHELL_TIMEOUT, timeout_s=SHELL_TIMEOUT)
        except ADB_ERRORS as err:
            raise AdbError(f"{self.host}: {err or type(err).__name__}") from err
        return str(output).replace("\r", "")

    async def packages(self, third_party: bool = False) -> set[str]:
        output = await self.shell("pm list packages -3" if third_party else "pm list packages")
        return {line[8:].strip() for line in output.splitlines() if line.startswith("package:")}

    async def is_awake(self) -> bool:
        """False while the screen is off (asleep or dozing)."""
        output = await self.shell("dumpsys power | grep mWakefulness=")
        return "Awake" in output or "mWakefulness=" not in output

    async def apk_paths(self, package: str) -> list[str]:
        output = await self.shell(f"pm path {shlex.quote(package)}")
        return [line[8:].strip() for line in output.splitlines() if line.startswith("package:")]

    async def pull(self, device_path: str, local_path: str) -> None:
        try:
            await self._device.pull(device_path, local_path, read_timeout_s=FILE_TIMEOUT)
        except ADB_ERRORS as err:
            raise AdbError(f"{self.host}: pull {device_path}: {err or type(err).__name__}") from err

    async def push(self, local_path: str, device_path: str) -> None:
        try:
            await self._device.push(local_path, device_path, read_timeout_s=FILE_TIMEOUT)
        except ADB_ERRORS as err:
            raise AdbError(f"{self.host}: push {device_path}: {err or type(err).__name__}") from err

    async def install(self, package: str, apks: list[str]) -> str | None:
        """Install the APK splits like `adb install-multiple -r`; None on success, else the reason.

        Play Store is named as installer so the app keeps getting updates; if the TV refuses that, a plain install.
        """
        remote = []
        try:
            for index, apk in enumerate(apks):
                path = f"{TMP_DIR}/arc_app_sync_{index}.apk"
                await self.push(apk, path)
                remote.append(path)
            error = await self._install_session(remote, f"-i {PLAY_STORE}")
            if error is not None:
                error = await self._install_session(remote, "")
            return error
        finally:
            if remote:
                await self.shell("rm -f " + " ".join(remote))

    async def _install_session(self, remote: list[str], installer: str) -> str | None:
        output = await self.shell(f"pm install-create -r {installer}".strip())
        match = _SESSION.search(output)
        if match is None:
            return output.strip() or "install-create failed"
        session = match.group(1)
        for index, path in enumerate(remote):
            output = await self.shell(f"pm install-write {session} split_{index}.apk {path}")
            if "Success" not in output:
                await self.shell(f"pm install-abandon {session}")
                return output.strip() or "install-write failed"
        output = await self.shell(f"pm install-commit {session}")
        return None if "Success" in output else output.strip() or "install-commit failed"

    async def uninstall(self, package: str) -> bool:
        return "Success" in await self.shell(f"pm uninstall {shlex.quote(package)}")

    async def open_play_store(self, package: str) -> None:
        url = shlex.quote(f"market://details?id={package}")
        await self.shell(f"am start -a android.intent.action.VIEW -d {url} -p {PLAY_STORE}")

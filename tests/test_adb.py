"""The ADB commands, against a mocked adb-shell device."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from adb_shell.exceptions import TcpTimeoutException
import pytest

from custom_components.arc_app_sync.adb import AdbError, AdbTv, load_signer


def _tv(replies: dict[str, str]) -> tuple[AdbTv, AsyncMock]:
    device = AsyncMock()

    async def shell(command: str, **kwargs) -> str:
        for prefix, reply in replies.items():
            if command.startswith(prefix):
                return reply
        return ""

    device.shell.side_effect = shell
    with patch("custom_components.arc_app_sync.adb.AdbDeviceTcpAsync", return_value=device):
        return AdbTv("192.0.2.10", signer=None), device


def _commands(device: AsyncMock) -> list[str]:
    return [call.args[0] for call in device.shell.call_args_list]


async def test_packages_and_awake() -> None:
    tv, _ = _tv(
        {
            "pm list packages -3": "package:com.a\r\npackage:com.b\r\n",
            "pm list packages": "package:com.a\npackage:com.b\npackage:android\n",
            "dumpsys power": "  mWakefulness=Dozing\n",
        }
    )
    assert await tv.packages(third_party=True) == {"com.a", "com.b"}
    assert await tv.packages() == {"com.a", "com.b", "android"}
    assert not await tv.is_awake()


async def test_install_with_play_store_as_installer() -> None:
    tv, device = _tv(
        {
            "pm install-create": "Success: created install session [42]",
            "pm install-write": "Success: streamed 100 bytes",
            "pm install-commit": "Success",
        }
    )
    assert await tv.install("com.a", ["/tmp/a_0.apk", "/tmp/a_1.apk"]) is None
    assert device.push.await_count == 2
    commands = _commands(device)
    assert commands[0] == "pm install-create -r -i com.android.vending"
    assert commands[1] == "pm install-write 42 split_0.apk /data/local/tmp/arc_app_sync_0.apk"
    assert commands[3] == "pm install-commit 42"
    assert commands[-1].startswith("rm -f /data/local/tmp/arc_app_sync_0.apk")


async def test_install_falls_back_to_plain_install() -> None:
    tv, device = _tv(
        {
            "pm install-create -r -i": "Error: no permission",
            "pm install-create -r": "Success: created install session [7]",
            "pm install-write": "Success",
            "pm install-commit": "Failure [INSTALL_FAILED_NO_MATCHING_ABIS]",
        }
    )
    assert await tv.install("com.a", ["/tmp/a_0.apk"]) == "Failure [INSTALL_FAILED_NO_MATCHING_ABIS]"
    assert "pm install-create -r" in _commands(device)


async def test_connection_errors_become_adb_error() -> None:
    tv, device = _tv({})
    device.connect.side_effect = TcpTimeoutException("timed out")
    with pytest.raises(AdbError, match="timed out"):
        await tv.connect()
    device.shell.side_effect = ConnectionResetError()
    with pytest.raises(AdbError, match="ConnectionResetError"):
        await tv.shell("true")


def test_key_is_made_once(tmp_path) -> None:
    path = str(tmp_path / "arc_app_sync" / "adbkey")
    load_signer(path)
    with open(path, encoding="utf-8") as key:
        first = key.read()
    load_signer(path)
    with open(path, encoding="utf-8") as key:
        assert key.read() == first

# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the pure parts of the live DFU backend.

The subprocess/serial paths (flash/reset/dfu/read) run on the bench; these cover
the version parsing and the command construction that would otherwise only be
validated against hardware.
"""

from fw_hil.backends.live_dfu import LiveDfuOps, parse_app_version


def test_parse_app_version_extracts_line():
    out = "\x1b[mfm> version\r\nAPP-VERSION 01.00.00-01\r\nfm> "
    assert parse_app_version(out) == "APP-VERSION 01.00.00-01"


def test_parse_app_version_none_when_absent():
    assert parse_app_version("fm> help\r\nuptime\r\n") is None
    assert parse_app_version("") is None
    assert parse_app_version(None) is None


def _ops():
    return LiveDfuOps(
        fw_repo_dir="/home/hil/zephyrproject/FW-RemoteStation", probe_serial="35FF7006"
    )


def test_usb_id_is_lowercase_hex():
    assert _ops()._usb_id == "2fe3:0012"


def test_reset_delegates_to_stlink_probe():
    # reset() must go through the shared ST-Link probe, not a duplicated argv.
    class SpyProbe:
        def __init__(self):
            self.resets = 0

        def reset(self):
            self.resets += 1

    spy = SpyProbe()
    ops = LiveDfuOps(fw_repo_dir="/repo", probe_serial="X", boot_settle_s=0, probe=spy)
    ops.reset()
    assert spy.resets == 1


def test_default_probe_is_stlink_backend_with_same_uid():
    from fw_hil.backends.stlink import STLinkBackend

    ops = _ops()
    assert isinstance(ops.probe, STLinkBackend)
    assert ops.probe.probe_serial == "35FF7006"
    assert "35FF7006" in ops.probe.reset_command()


def test_dfu_download_cmd_targets_slot_alt_and_image():
    cmd = _ops().dfu_download_cmd("/tmp/v2.signed.bin")
    assert cmd[0] == "dfu-util"
    assert "-a" in cmd and "0" in cmd  # default slot1_image alt
    assert "2fe3:0012" in cmd
    assert cmd[-1] == "/tmp/v2.signed.bin"


def test_dfu_download_cmd_alt_override():
    cmd = _ops().dfu_download_cmd("/tmp/x.bin", alt=1)
    i = cmd.index("-a")
    assert cmd[i + 1] == "1"


def test_default_west_backend_targets_workspace():
    from fw_hil.backends.west import WestBackend

    ops = _ops()
    assert isinstance(ops.west, WestBackend)
    assert ops.west.workspace_dir == "/home/hil/zephyrproject/FW-RemoteStation"


def test_flash_baseline_delegates_to_west_with_probe_and_build_dir(tmp_path):
    calls = []

    class SpyWest:
        def flash(self, runner="pyocd", dev_id=None, build_dir=None):
            calls.append((runner, dev_id, build_dir))

    ops = LiveDfuOps(fw_repo_dir="/repo", probe_serial="X", boot_settle_s=0, west_backend=SpyWest())
    build = str(tmp_path)
    ops.flash_baseline(build)
    assert calls == [("pyocd", "X", build)]


def test_flash_baseline_rejects_raw_artifact_path():
    import pytest

    ops = LiveDfuOps(fw_repo_dir="/repo", probe_serial="X", run=lambda *a, **k: None)
    with pytest.raises(ValueError):
        ops.flash_baseline("/tmp/zephyr.signed.bin")  # a file, not a build dir

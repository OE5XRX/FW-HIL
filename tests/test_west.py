# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the west CLI backend command construction (no hardware)."""

from fw_hil.backends.west import WestBackend


def _west(**kw):
    return WestBackend(workspace_dir="/repo", **kw)


def test_flash_cmd_default():
    assert _west().flash_cmd() == ["west", "flash", "-r", "pyocd"]


def test_flash_cmd_with_dev_id_and_build_dir():
    cmd = _west().flash_cmd(dev_id="066EFF", build_dir="/repo/build")
    assert cmd == ["west", "flash", "-r", "pyocd", "--dev-id", "066EFF", "-d", "/repo/build"]


def test_flash_cmd_runner_override():
    assert _west().flash_cmd(runner="jlink")[:4] == ["west", "flash", "-r", "jlink"]


def test_flash_runs_in_workspace():
    calls = []
    west = WestBackend(workspace_dir="/repo", run=lambda cmd, **kw: calls.append((cmd, kw)))
    west.flash(dev_id="Z")
    cmd, kw = calls[0]
    assert cmd == ["west", "flash", "-r", "pyocd", "--dev-id", "Z"]
    assert kw.get("cwd") == "/repo"
    assert kw.get("check") is True

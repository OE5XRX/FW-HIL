# SPDX-License-Identifier: GPL-3.0-or-later
from fw_hil.backends.stlink import STLinkBackend


def test_flash_command_includes_target_serial_and_image():
    be = STLinkBackend(probe_serial="066EFF51", target="stm32u575citx", runner="pyocd")
    cmd = be.flash_command("/tmp/app.bin")
    assert cmd[0] == "pyocd"
    assert "stm32u575citx" in cmd
    assert "066EFF51" in cmd
    assert cmd[-1] == "/tmp/app.bin"


def test_mass_erase_command():
    be = STLinkBackend(probe_serial="066EFF51")
    cmd = be.mass_erase_command()
    assert "erase" in cmd and "--mass" in " ".join(cmd)
    assert "066EFF51" in cmd


def test_flash_invokes_injected_runner():
    calls = []
    be = STLinkBackend(probe_serial="X", run=lambda cmd, **kw: calls.append(cmd))
    be.flash("/tmp/app.bin")
    assert calls and calls[0] == be.flash_command("/tmp/app.bin")


def test_power_cycle_maps_to_reset_on_mvp_backend():
    calls = []
    be = STLinkBackend(probe_serial="X", run=lambda cmd, **kw: calls.append(cmd))
    be.power_cycle()
    assert calls == [be.reset_command()]

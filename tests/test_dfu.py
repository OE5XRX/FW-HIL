# SPDX-License-Identifier: GPL-3.0-or-later
from fw_hil.dfu import UpdateResult, run_revert_cycle, run_update_cycle

_VERSIONS = {"base.bin": "APP-VERSION 26.09.25-01", "v2.bin": "APP-VERSION 26.09.25-02"}


class FakeDfuOps:
    """Simulates the board's production DFU behavior.

    ``reset`` boots the SWD-flashed baseline; ``dfu_download`` self-completes
    (firmware self-reboot + MCUboot swap) with NO external reset — a healthy
    image sticks, an unhealthy one (``revert_on``) is reverted by MCUboot after
    the gate deadline, leaving the previous baseline running.
    """

    def __init__(self, revert_on=()):
        self.current = None
        self.revert_on = set(revert_on)  # images that fail the health-gate
        self.log = []
        self._flashed = None

    def flash_baseline(self, image_path):
        self.log.append(("flash", image_path))
        self._flashed = image_path

    def reset(self):
        self.log.append(("reset",))
        self.current = _VERSIONS[self._flashed]  # boot the flashed baseline

    def dfu_download(self, image_path, alt):
        self.log.append(("dfu", image_path, alt))
        # self-reboot + swap + (confirm | deadline revert): no reset needed.
        if image_path not in self.revert_on:
            self.current = _VERSIONS[image_path]
        # else: unhealthy -> reverted -> current (baseline) unchanged

    def read_app_version(self, timeout_s=20.0):
        return self.current


def test_happy_path_new_version_sticks():
    ops = FakeDfuOps()
    res = run_update_cycle(
        ops, "base.bin", "APP-VERSION 26.09.25-01", "v2.bin", "APP-VERSION 26.09.25-02"
    )
    assert isinstance(res, UpdateResult)
    assert res.ok and res.final_version == "APP-VERSION 26.09.25-02"
    assert not res.reverted


def test_revert_cycle_rolls_back_unhealthy_image():
    _VERSIONS["bad.bin"] = "APP-VERSION 26.09.25-99"
    ops = FakeDfuOps(revert_on={"bad.bin"})
    res = run_revert_cycle(ops, "base.bin", "APP-VERSION 26.09.25-01", "bad.bin")
    assert res.ok and res.reverted
    assert res.final_version == "APP-VERSION 26.09.25-01"


def test_update_cycle_image_never_boots_is_failure_not_hang():
    # Review Focus: no readable version -> classified failure.
    class DeadOps(FakeDfuOps):
        def read_app_version(self, timeout_s=20.0):
            return None

    res = run_update_cycle(
        DeadOps(), "base.bin", "APP-VERSION 26.09.25-01", "v2.bin", "APP-VERSION 26.09.25-02"
    )
    assert res.ok is False
    assert "no version" in res.detail.lower()

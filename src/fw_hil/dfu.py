# SPDX-License-Identifier: GPL-3.0-or-later
"""DFU/MCUboot update-cycle orchestration. Backend supplies the real ops (Plan 2).

Models the production update path: after a DFU download the firmware self-reboots
and MCUboot applies (or, for an unhealthy image, later reverts) the swap on its
own — the cycles never reset the device to apply an update. ``reset`` is used
only to boot the SWD-flashed baseline.
"""

from dataclasses import dataclass
from typing import Protocol


class DfuOps(Protocol):
    def flash_baseline(self, image_path: str) -> None: ...
    def dfu_download(self, image_path: str, alt: int) -> None:
        """Download the image and wait for its post-DFU outcome to settle.

        The device self-reboots and MCUboot swaps the trial in; a healthy image
        confirms, an unhealthy one is reverted after the gate deadline. On return
        the device runs its final image (confirmed-new or reverted-baseline).
        """
        ...

    def reset(self) -> None: ...
    def read_app_version(self, timeout_s: float = 20.0) -> "str | None": ...


@dataclass
class UpdateResult:
    ok: bool
    final_version: str | None
    reverted: bool
    detail: str


def run_update_cycle(ops, baseline_image, baseline_version, new_image, new_version, alt=0):
    ops.flash_baseline(baseline_image)
    ops.reset()
    base_seen = ops.read_app_version()
    if base_seen is None:
        return UpdateResult(False, None, False, "no version after baseline flash")
    if base_seen != baseline_version:
        return UpdateResult(
            False, base_seen, False, f"baseline version {base_seen!r} != {baseline_version!r}"
        )
    # No reset here: the firmware self-reboots after the download and MCUboot
    # swaps the image in (production path — the station has no debugger).
    # dfu_download waits for the outcome to settle (confirm or revert).
    ops.dfu_download(new_image, alt)
    final = ops.read_app_version()
    if final is None:
        return UpdateResult(False, None, False, "no version after DFU update (image never booted)")
    if final == new_version:
        return UpdateResult(True, final, False, "updated")
    if final == baseline_version:
        return UpdateResult(False, final, True, "unexpected revert during happy-path update")
    return UpdateResult(False, final, False, f"unexpected version {final!r}")


def run_revert_cycle(ops, baseline_image, baseline_version, unhealthy_image, alt=0):
    ops.flash_baseline(baseline_image)
    ops.reset()
    if ops.read_app_version() != baseline_version:
        return UpdateResult(False, None, False, "baseline not established before revert test")
    # No reset: the unhealthy trial boots, fails the health gate, and MCUboot
    # reverts it after the gate deadline on its own. dfu_download waits out that
    # window so read_app_version sees the reverted baseline.
    ops.dfu_download(unhealthy_image, alt)
    final = ops.read_app_version()
    if final is None:
        return UpdateResult(False, None, False, "no version after revert window")
    if final == baseline_version:
        return UpdateResult(True, final, True, "reverted to baseline as expected")
    return UpdateResult(False, final, False, f"expected revert to baseline, got {final!r}")

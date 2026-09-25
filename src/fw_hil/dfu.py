# SPDX-License-Identifier: GPL-3.0-or-later
"""DFU/MCUboot update-cycle orchestration. Backend supplies the real ops (Plan 2)."""

from dataclasses import dataclass
from typing import Protocol


class DfuOps(Protocol):
    def flash_baseline(self, image_path: str) -> None: ...
    def dfu_download(self, image_path: str, alt: int) -> None: ...
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
    ops.dfu_download(new_image, alt)
    ops.reset()
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
    ops.dfu_download(unhealthy_image, alt)
    ops.reset()
    final = ops.read_app_version()
    if final is None:
        return UpdateResult(False, None, False, "no version after revert window")
    if final == baseline_version:
        return UpdateResult(True, final, True, "reverted to baseline as expected")
    return UpdateResult(False, final, False, f"expected revert to baseline, got {final!r}")

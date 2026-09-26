# SPDX-License-Identifier: GPL-3.0-or-later
"""Live :class:`~fw_hil.dfu.DfuOps` backend for the fm_board HIL bench (Baustein 2).

Implements the DFU update/revert primitives against real hardware:

- ``flash_baseline`` — flash the mcuboot + signed-app baseline over SWD
  (``west flash -r pyocd``); ST-Link is only used to establish a known
  confirmed baseline, never to apply a DFU update.
- ``dfu_download`` — detach to DFU mode and ``dfu-util`` download to the
  ``slot1_image`` alt. The firmware self-reboots (FW-RemoteStation
  ``dfu_mode`` schedules a delayed ``sys_reboot``) so MCUboot swaps the image
  in **without any external reset** — exactly the production path (the remote
  station has no debugger). This method waits for that swap+boot+confirm to
  settle.
- ``reset`` — cold-reset over SWD. In ``run_update_cycle`` it reboots the
  already-confirmed new image; in ``run_revert_cycle`` it forces the still-
  unconfirmed trial to reboot so MCUboot reverts (faster than the 30 s gate
  deadline).
- ``read_app_version`` — the CDC ``version`` shell command.

Feed this into :func:`fw_hil.dfu.run_update_cycle` / ``run_revert_cycle``.
Hardware-only: shells out to west/pyocd/dfu-util and reads the CDC via
pyserial (``hw`` extra); not exercised in host CI.
"""

import re
import subprocess
import time

_VERSION_RE = re.compile(r"APP-VERSION\s+\d{2}\.\d{2}\.\d{2}-\d{2}")


def parse_app_version(console_text: str) -> "str | None":
    """Extract the ``APP-VERSION YY.MM.DD-NN`` line from CDC console output."""
    m = _VERSION_RE.search(console_text or "")
    return m.group(0) if m else None


class LiveDfuOps:
    """DfuOps implementation driving the physical fm_board on the bench."""

    def __init__(
        self,
        *,
        fw_repo_dir: str,
        probe_serial: str,
        cdc_path: str = "/dev/fm-board-cdc",
        target: str = "stm32u575citx",
        vid: int = 0x2FE3,
        pid: int = 0x0012,
        dfu_alt: int = 0,
        pyocd: str = "pyocd",
        dfu_util: str = "dfu-util",
        west: str = "west",
        swap_settle_s: float = 9.0,
        boot_settle_s: float = 6.0,
        run=subprocess.run,
    ):
        self.fw_repo_dir = fw_repo_dir
        self.probe_serial = probe_serial
        self.cdc_path = cdc_path
        self.target = target
        self.vid = vid
        self.pid = pid
        self.dfu_alt = dfu_alt
        self.pyocd = pyocd
        self.dfu_util = dfu_util
        self.west = west
        self.swap_settle_s = swap_settle_s
        self.boot_settle_s = boot_settle_s
        self._run = run

    # ── command builders (pure; unit-tested) ─────────────────────────────────
    @property
    def _usb_id(self) -> str:
        return f"{self.vid:04x}:{self.pid:04x}"

    def flash_baseline_cmd(self) -> list:
        return [self.west, "flash", "-r", "pyocd"]

    def reset_cmd(self) -> list:
        return [self.pyocd, "reset", "-t", self.target, "-u", self.probe_serial]

    def dfu_detach_cmd(self) -> list:
        return [self.dfu_util, "-e", "-d", self._usb_id]

    def dfu_download_cmd(self, image_path: str, alt: "int | None" = None) -> list:
        return [
            self.dfu_util,
            "-a",
            str(self.dfu_alt if alt is None else alt),
            "-d",
            self._usb_id,
            "-D",
            image_path,
        ]

    # ── DfuOps protocol ──────────────────────────────────────────────────────
    def flash_baseline(self, image_path: "str | None" = None) -> None:
        # image_path is unused: the baseline is the mcuboot+signed build in the
        # FW-RemoteStation build dir; west flash programs both to their slots.
        self._run(self.flash_baseline_cmd(), cwd=self.fw_repo_dir, check=True)
        time.sleep(self.boot_settle_s)

    def reset(self) -> None:
        self._run(self.reset_cmd(), check=True)
        time.sleep(self.boot_settle_s)

    def dfu_download(self, image_path: str, alt: "int | None" = None) -> None:
        # Detach to DFU mode (best effort; already-DFU is fine), then download.
        self._run(self.dfu_detach_cmd(), check=False)
        time.sleep(3.0)
        self._run(self.dfu_download_cmd(image_path, alt), check=True)
        # Firmware self-reboots (~500 ms) -> MCUboot swap -> trial boot -> the
        # health gate confirms a healthy image within its dwell. Wait it out so
        # a healthy image is confirmed before the caller's reset() reboots it
        # (an unconfirmed reboot would revert).
        time.sleep(self.swap_settle_s)

    def read_app_version(self, timeout_s: float = 20.0) -> "str | None":
        import os

        import serial

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if os.path.exists(self.cdc_path):
                try:
                    with serial.Serial(self.cdc_path, 115200, timeout=1) as s:
                        time.sleep(0.3)
                        s.reset_input_buffer()
                        s.write(b"version\r\n")
                        time.sleep(1.0)
                        out = s.read(4000).decode(errors="replace")
                    version = parse_app_version(out)
                    if version:
                        return version
                except Exception:
                    pass
            time.sleep(0.5)
        return None

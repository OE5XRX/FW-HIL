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

import os
import re
import subprocess
import time

from fw_hil.backends.stlink import STLinkBackend

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
        probe: "STLinkBackend | None" = None,
    ):
        self.fw_repo_dir = fw_repo_dir
        self.probe_serial = probe_serial
        self.cdc_path = cdc_path
        self.vid = vid
        self.pid = pid
        self.dfu_alt = dfu_alt
        self.dfu_util = dfu_util
        self.west = west
        self.swap_settle_s = swap_settle_s
        self.boot_settle_s = boot_settle_s
        self._run = run
        # The SWD probe (pyocd) is the single owner of reset/erase — reuse the
        # ST-Link backend instead of re-building pyocd argv here.
        self.probe = probe or STLinkBackend(
            probe_serial=probe_serial, target=target, runner=pyocd, run=run
        )

    # ── command builders (pure; unit-tested) ─────────────────────────────────
    @property
    def _usb_id(self) -> str:
        return f"{self.vid:04x}:{self.pid:04x}"

    def flash_baseline_cmd(self, build_dir: "str | None" = None) -> list:
        # --dev-id pins the flash to the configured probe (same UID reset uses),
        # so a multi-probe bench can't program the wrong board.
        cmd = [self.west, "flash", "-r", "pyocd", "--dev-id", self.probe_serial]
        if build_dir:
            cmd += ["-d", build_dir]
        return cmd

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
        # This backend flashes a west *sysbuild* (mcuboot + signed app), not a
        # single artifact — the two go to different slots. ``image_path`` is
        # therefore interpreted as an optional west build DIRECTORY to flash
        # (``west flash -d``); when None the default build in ``fw_repo_dir`` is
        # used. Passing a raw .bin/.hex path is unsupported and raises, so a
        # caller can't silently flash the wrong image.
        if image_path is not None and not os.path.isdir(image_path):
            raise ValueError(
                f"flash_baseline expects a west build directory (sysbuild), got {image_path!r}; "
                "pass the build dir or None to use the default build in fw_repo_dir"
            )
        self._run(self.flash_baseline_cmd(image_path), cwd=self.fw_repo_dir, check=True)
        time.sleep(self.boot_settle_s)

    def reset(self) -> None:
        # Cold-reset via the shared ST-Link (pyocd) probe — no duplicated argv.
        self.probe.reset()
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

# SPDX-License-Identifier: GPL-3.0-or-later
"""ST-Link (pyocd) backend: builds argv, executes via an injected runner."""

import subprocess

from fw_hil.driver import BenchDriver


class STLinkBackend(BenchDriver):
    def __init__(self, probe_serial, target="stm32u575citx", runner="pyocd", run=subprocess.run):
        self.probe_serial = probe_serial
        self.target = target
        self.runner = runner
        self._run = run

    def flash_command(self, image_path):
        return [
            self.runner,
            "flash",
            "--target",
            self.target,
            "--uid",
            self.probe_serial,
            image_path,
        ]

    def reset_command(self):
        return [self.runner, "reset", "--target", self.target, "--uid", self.probe_serial]

    def mass_erase_command(self):
        return [self.runner, "erase", "--mass", "--target", self.target, "--uid", self.probe_serial]

    def flash(self, image_path):
        self._run(self.flash_command(image_path), check=True)

    def reset(self):
        self._run(self.reset_command(), check=True)

    def mass_erase(self):
        self._run(self.mass_erase_command(), check=True)

    def power_cycle(self):
        # MVP: no switchable VBUS (spec §12) -> reset is the strongest recovery.
        self._run(self.reset_command(), check=True)

# SPDX-License-Identifier: GPL-3.0-or-later
"""west CLI backend: flash a Zephyr application from a west workspace.

Wraps the ``west`` invocations the bench needs (currently ``west flash``) so the
build-tool calls live in one place — the same way :class:`STLinkBackend` owns the
pyocd probe. Hardware/bench-only: shells out to ``west`` in the workspace
directory; not exercised in host CI.
"""

import subprocess


class WestBackend:
    """Run ``west`` commands in a given workspace (build directory root)."""

    def __init__(self, workspace_dir: str, west: str = "west", run=subprocess.run):
        self.workspace_dir = workspace_dir
        self.west = west
        self._run = run

    def flash_cmd(
        self,
        runner: str = "pyocd",
        dev_id: "str | None" = None,
        build_dir: "str | None" = None,
    ) -> list:
        # --dev-id pins the flash to a specific probe (multi-probe benches);
        # -d selects a non-default build directory.
        cmd = [self.west, "flash", "-r", runner]
        if dev_id:
            cmd += ["--dev-id", dev_id]
        if build_dir:
            cmd += ["-d", build_dir]
        return cmd

    def flash(
        self,
        runner: str = "pyocd",
        dev_id: "str | None" = None,
        build_dir: "str | None" = None,
    ) -> None:
        self._run(self.flash_cmd(runner, dev_id, build_dir), cwd=self.workspace_dir, check=True)

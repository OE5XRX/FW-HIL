# FW-HIL Bench Bring-up (hardware-gated) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. **DO NOT START until the physical bench exists** (Letsung host provisioned, ST-Link + fm_board + DeviceTester attached). Tasks here are verified **on the bench**, not by in-session TDD; each task's "test" is an on-bench run with an observable pass condition. Granular test code is filled in at bench time, when real device paths, probe serials and UAC2 endpoint addresses are known.

**Goal:** Wire the `fw_hil` library (Plan 1) to the real `fm_board` and turn the four bausteine (flash → DFU → USB-enum → audio-loopback) into a green, self-hosted CI gate on FW-RemoteStation PRs.

**Architecture:** The Letsung mini-PC is provisioned as bench-as-code (Ansible) and registered as an org-scoped self-hosted runner. `fw_hil` gains the *live* backends that Plan 1 stubbed: a pyusb descriptor reader, an ALSA capture/playback helper, and a real `DfuOps` implementation (dfu-util + twister console). FW-RemoteStation grows a `hil` CI job and a Kconfig-gated FW loopback test-mode.

**Tech Stack:** Ansible, GitHub Actions self-hosted runner, pyocd/openocd, dfu-util, pyusb, ALSA (alsa-utils / python-sounddevice), Zephyr twister `--device-testing`, `fw_hil` (Plan 1).

**Spec:** `docs/superpowers/specs/2026-09-25-fw-hil-ci-gate-design.md`

## Global Constraints

Inherits all of Plan 1's Global Constraints, plus:
- **Security (blocking, before the runner touches the LAN):** GitHub "Require approval for fork-PR workflows" ON; the `hil` job gated behind a label (`hil-ok`). Verify a fork PR does **not** auto-run on the bench before wiring anything else.
- **Concurrency:** runner concurrency 1 + a GH `concurrency:` group on the `hil` job.
- **No PTT/TX** in any test (no RF, no dummy load). If a future test keys the SA818, it moves to a separate RF plan.
- **Repo split:** live backends + Ansible + hardware-map live in `FW-HIL`; the twister testcases, the `hil` workflow job, and the FW loopback test-mode live in `FW-RemoteStation`.

## Task outline (refine granularity at bench time)

### Task 1: Provision the Letsung as bench-as-code (Ansible)
- **Deliverable:** an idempotent Ansible playbook in `FW-HIL/ansible/` that takes a fresh Debian install to a ready bench: Zephyr SDK + west, pyocd/openocd, dfu-util, alsa-utils, `pip install -e` of `fw_hil`, ST-Link udev rules, and stable symlinks for the ST-Link (by probe serial) and the board CDC (by VID/PID+serial).
- **On-bench pass:** re-running the playbook is a no-op; `pyocd list` shows the probe at its stable id; the board CDC appears at its stable symlink.
- **Note:** capture the real ST-Link probe serial and board iSerial into `FW-HIL/hardware-map.yaml` here.

### Task 2: Baustein 1 — flash on real silicon
- **Deliverable:** `west flash` / twister `--device-testing` programs `fm_board` from the bench, resets, and the CDC console banner appears deterministically. Confirm the existing `fm.usb_audio.stream` boot-log test passes on real hardware.
- **On-bench pass:** green run of the existing boot-sequence test through twister on the bench, ten times, no `by-id` race.

### Task 3: Baustein 2 — DFU / MCUboot cycle
- **Deliverable:** a live `DfuOps` implementation in `fw_hil` (dfu-util for download, twister console for `version`, ST-Link for baseline flash + reset), driven by Plan 1's `run_update_cycle` / `run_revert_cycle`. Build two prod images with distinct `app/VERSION`. The revert test uses an image built with SA818 disabled so the health-gate fails.
- **On-bench pass:** happy-path shows the bumped `APP-VERSION`; revert-path shows MCUboot rolls back to baseline `APP-VERSION`.

### Task 4: Baustein 3 — USB-enumeration descriptor assertion
- **Deliverable:** a pyusb reader in `fw_hil` that parses the live `fm_board` into a `UsbComposite`, fed into Plan 1's `assert_composite(..., ExpectedComposite.fm_board())`. Read the *real* UAC2 endpoint/altsetting layout here and lock the expected values.
- **On-bench pass:** assertion green on a good build; flipping a USB Kconfig (e.g. dropping UAC2) turns it red with the distinct "UAC2 interface missing" message.

### Task 5: Baustein 4 — FW loopback test-mode + audio-loopback gate
- **Deliverable (FW-RemoteStation):** a Kconfig-gated (`CONFIG_*_TEST_LOOPBACK`) + shell-commanded test-mode that bridges UAC2 TX→RX internally, bypassing the SA818. **Deliverable (FW-HIL):** an ALSA helper that plays a `generate_sine` signal into the UAC2 playback endpoint and captures the capture endpoint, fed into Plan 1's `analyze_loopback`.
- **On-bench pass:** clean build → `analyze_loopback().ok is True`; reverting the STM32-UDC iso-OUT recovery patch → `ok is False` (iso stall detected). This is Erfolgskriterium #1.

### Task 6: Wire the `hil` CI job + security gate
- **Deliverable (FW-RemoteStation):** a `hil` workflow job `runs-on: [self-hosted, hil, fm_board]`, gated behind the `hil-ok` label + fork-PR approval, concurrency 1, running bausteine 1–4 via twister on the bench.
- **On-bench pass:** a PR with the label runs the full HIL suite on the bench and reports status; a fork PR without approval does **not** execute.

## Done criteria for Plan 2

- All five Erfolgskriterien from the spec §11 hold on real hardware.
- The bench is reproducible from the Ansible playbook.
- Migrating to the HW-DebugBoard later means adding a `DebugBoardBackend` in `fw_hil` — no testcase change (Erfolgskriterium #5).

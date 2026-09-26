# FW-HIL Bench Provisioning (Ansible)

Idempotent playbook that configures a fresh **Ubuntu Server 24.04 LTS** host
as the OE5XRX Hardware-in-the-Loop CI bench.

## What gets installed

| Component | Method | Notes |
|-----------|--------|-------|
| Zephyr SDK 1.0.1 (ARM only) | tar.xz extracted to `/opt` | minimal install + `arm-zephyr-eabi` toolchain; matches the Zephyr rev the firmware pins |
| `west`, `pyocd` | pip venv `/opt/fw-hil-venv` | |
| `openocd`, `dfu-util`, `alsa-utils` | apt | |
| `fw_hil` (this repo) | `pip install -e` in venv | cloned to `/opt/fw-hil` |
| ST-Link udev rules | `/etc/udev/rules.d/99-stlink.rules` | symlink `/dev/stlink-hil` |
| FM-Board udev rules | `/etc/udev/rules.d/99-fw-hil-board.rules` | symlink `/dev/fm-board-cdc` |
| GitHub Actions runner | systemd `gh-actions-runner.service` | org-scoped, labels `self-hosted,hil,fm_board` |
| `hardware-map.yaml` | `/etc/fw-hil/hardware-map.yaml` | initial template with placeholders |

## Dry-run (no host required)

Syntax check only — verifies playbook YAML and Ansible grammar without
connecting to any host:

```sh
cd ansible/
ansible-playbook --syntax-check -i inventory/hosts.example site.yml
```

Check mode — connects but makes no changes:

```sh
ansible-playbook --check -i inventory/hosts.example site.yml \
  --extra-vars "gh_runner_token=CHANGEME"
```

## Provision without registering the runner

If `gh_runner_token` is **not** supplied, the box is fully provisioned
(packages, Zephyr SDK, venv, `fw_hil`, udev rules, `hil` user) but the GitHub
Actions runner is neither downloaded nor started. Use this to prepare the bench
before a token exists and before "Require approval for fork-PR workflows" is
enabled:

```sh
cd ansible/
ansible-playbook -i inventory/hosts site.yml
```

Supply the token on a later (idempotent) re-run to register and start the runner.

## Full apply

1. Copy `inventory/hosts.example` to `inventory/hosts` and set the bench IP.
2. Obtain a runner registration token from
   `https://github.com/organizations/OE5XRX/settings/actions/runners/new`.
3. Run:

```sh
cd ansible/
ansible-playbook -i inventory/hosts site.yml \
  --extra-vars "gh_runner_token=<token>"
```

Re-running is always safe — all tasks are idempotent.

## After provisioning

1. Connect the ST-Link V3 and the FM-Board DeviceTester to the bench.
2. Find the probe serial: `pyocd list --uid`
3. Find the board serial: `lsusb -v -d 2fe3:0012 | grep iSerial`
4. Edit `/etc/fw-hil/hardware-map.yaml` on the bench (fill in both `CHANGEME` values).
5. Re-run the playbook (the `force: false` on hardware-map.yaml preserves your edits).

## Linting

```sh
cd ansible/
ansible-lint .
```

CI runs `ansible-lint` + `--syntax-check` on every push (see `.github/workflows/ci.yml`).

## Building & flashing firmware (build-env)

The playbook makes the box **build-capable** (Zephyr SDK, `west`/`pyocd` venv owned
by the bench user, `acl`, udev, pyocd STM32U5 pack). It does **not** set up a
per-firmware west workspace — that is repo/revision-specific and belongs to the
build step (the `hil` CI job, or a manual run). The one-time workspace setup:

```sh
sudo -u hil -H bash -lc '
  export PATH=/opt/fw-hil-venv/bin:$PATH
  export ZEPHYR_SDK_INSTALL_DIR=/opt/zephyr-sdk-1.0.1
  cd ~ && west init -m https://github.com/OE5XRX/FW-RemoteStation --mr main zephyrproject
  cd zephyrproject && west update && west patch apply
  west packages pip --install      # installs the Zephyr rev'"'"'s Python build deps into the venv
  cd FW-RemoteStation && west build -b fm_board app && west flash -r pyocd
'
```

`ZEPHYR_SDK_INSTALL_DIR` must be exported for the build (the SDK is installed but
not globally registered). `west packages pip --install` needs the venv writable by
the bench user — the playbook's ownership handoff ensures that.

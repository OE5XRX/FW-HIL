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
| Host egress firewall (nftables) | `/etc/nftables.conf` + `nftables.service` | **opt-in**, off by default — see below |

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

## Host egress firewall (defense-in-depth)

The bench runs untrusted PR code as the `hil` user in the CI job.

**Division of labour:**

- **UniFi CI-VLAN (box-wide, primary)** — the operator configures the switch so
  the whole bench is isolated: LAN↔CI blocked, admin→CI:22 allowed, CI→internet
  allowed. This is the authoritative network control for the machine.
- **This host firewall (`hil`-user-scoped, defense-in-depth)** — an nftables
  ruleset (`templates/nftables.conf.j2`, deployed by `tasks/egress-firewall.yml`)
  that fences the egress of **only the `hil` user**. Admin (`pbuchegger`), root,
  and system services (apt, NTP, systemd-resolved, …) are **not** restricted —
  they keep full egress. The point is to bound exactly the untrusted code, not
  to firewall the box (the VLAN does that).

The ruleset uses a single **OUTPUT** chain with `policy accept`:

- Traffic **not** owned by `hil` (`meta skuid != <hil-uid>`) is accepted
  immediately — everyone else is unaffected.
- `hil`'s traffic is then filtered: loopback, established/related, outbound
  ICMPv6 **control messages** (NDP/MLD/PMTU — not echo-request, so `hil` can't
  tunnel out via ping), DNS (53) **to the effective resolver(s)**, NTP (123), and
  HTTPS/HTTP **to the allowlist** are accepted; everything else `hil` sends — the
  home LAN, arbitrary internet hosts — is **dropped**.

There is **no INPUT or FORWARD filtering** — the table exists solely to fence
`hil`'s egress. Because admin/ssh/management traffic is never touched, there is
**no lockout risk** (this replaces the earlier "ssh-first, default-drop input"
design). The `hil` UID is resolved at apply time via `getent` (not hardcoded).

The DNS allowlist is derived from `egress_dns_servers` (default: the host's
`/etc/resolv.conf` nameservers). On a **systemd-resolved** host (the Ubuntu
default) `hil` resolves via the `127.0.0.53` stub over loopback (accepted) and
root does the real upstream forwarding (unrestricted), so the allowlist chiefly
matters where `hil` resolves *directly* against an external resolver; there the
task reads the real upstreams from `/run/systemd/resolve/resolv.conf` and strips
loopback. If no upstream is discoverable it falls back to allowing port 53 to any.

The allowlist is GitHub's own published ranges, materialized at apply time from
`https://api.github.com/meta` — only the groups a **self-hosted** runner egresses
to (`api`/`web`/`git`/`packages`, ~110 CIDRs), plus any operator-supplied
`egress_extra_cidrs_v4`/`_v6`. The `actions` group (GitHub-*hosted* runner IPs,
thousands of Azure CIDRs) is deliberately excluded — the bench never egresses to
those, and including them would broadly permit exfil to Azure.

### Off by default — enable with the VLAN migration

`egress_firewall_enabled` defaults to **`false`**: the firewall tasks are skipped
entirely and the host is untouched. Turn it on *together with the VLAN cutover*
(the box IP changes then anyway), on the same idempotent run:

```sh
ansible-playbook -i inventory/hosts site.yml \
  --extra-vars "egress_firewall_enabled=true"
```

On a real apply the rendered ruleset is validated with `nft -c` (against a temp
file) *before* it is installed, so a syntax error fails the task rather than
loading a broken ruleset. `--check` is a lighter dry run — it reports the diff
but does not install `nftables` or run the `validate` command (Ansible skips
`validate` in check mode), so it is safe to run even on a fresh host:

```sh
ansible-playbook --check -i inventory/hosts site.yml \
  --extra-vars "egress_firewall_enabled=true"
```

> ℹ️ **No lockout:** only `hil`'s egress is filtered; admin/ssh/management
> traffic is never matched, so enabling the firewall cannot lock anyone out.

### Maintaining an already-firewalled host

Provisioning tasks run as root, so once the firewall is live they are **not**
affected by it (only `hil`'s egress is filtered). A full re-run is therefore
safe. To refresh just the ruleset — e.g. to pick up rotated GitHub ranges — the
`egress-firewall` tag skips every other task:

```sh
ansible-playbook -i inventory/hosts site.yml \
  --tags egress-firewall --extra-vars "egress_firewall_enabled=true"
```

### Honest limitations

- **CDN-hosted destinations cannot be reliably pinned.** PyPI
  (`files.pythonhosted.org` → Fastly), `objects.githubusercontent.com`,
  `codeload`, and the Ubuntu apt mirrors resolve to rotating CDN IPs with no
  stable published range. They are **not** in the allowlist. If a live CI job
  needs them, add the current CIDRs to `egress_extra_cidrs_v4`/`_v6`, or rely on
  the fact that apt/pip provisioning happens *before* the firewall is enabled.
  The UniFi VLAN — not this host firewall — is the authoritative egress control.
- **The GitHub set is a snapshot.** It is refreshed each time the playbook runs;
  GitHub rotates ranges occasionally, so a long-lived bench should be
  re-provisioned periodically (or extend the tasks with a refresh timer) to
  avoid the allowlist going stale and silently blocking checkout.

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

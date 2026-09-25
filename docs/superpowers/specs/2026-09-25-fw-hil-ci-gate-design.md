# FW-HIL — Hardware-in-the-Loop CI-Gate für STM32-Module

- **Status:** Draft (Review ausstehend)
- **Datum:** 2026-09-25
- **Repo:** `OE5XRX/FW-HIL`
- **Scope dieser Iteration:** `fm_board` (STM32U575, FM-Transceiver-Modul). Framework so gebaut, dass weitere STM32-Module später ohne Umbau andocken.

---

## 1. Problem & Kontext

Die Firmware in `FW-RemoteStation` (Zephyr, STM32U575) hat eine gute
`native_sim`-Abdeckung für Logik, Shell, Modul-Interface, ETL und das
SA818-AT-Protokoll (via `SA818Simulator`). Was `native_sim` **nicht** kann, ist
alles, was echte Peripherie braucht: **USB** (UAC2 + CDC-ACM + DFU Composite auf
dem `USB_DEVICE_STACK_NEXT`), der **Audio-Datenpfad** (isochrones Streaming) und
der **DFU/MCUboot-Update-Zyklus** auf echtem Silizium.

Genau in dieser Lücke treten wiederkehrend Bugs auf — zuletzt am Audio-Interface
(iso-OUT-Streaming; vgl. den downstream `west patch` für die STM32-UDC
iso-OUT-Incomplete-Recovery, der für UAC2-Host→Device-Playback zwingend ist).
Ein zurückgedrehter oder regressierter Patch dieser Art wird heute von **keinem**
automatischen Gate gefangen.

Heute existiert zwar ein Runtime-Test `fm.usb_audio.stream` (twister,
`harness: pytest`, Tag `hardware`), aber:

- Er läuft in CI nur als **`build_only`** — es gibt keinen Runner mit
  angestecktem Board, der ihn real ausführt.
- Selbst wenn er liefe, prüft er nur die **Boot-/Init-Sequenz** aus dem
  CDC-ACM-Log („USB device enabled / SA818 device ready / USB Audio Bridge
  enabled / System ready"). Über die tatsächliche **Datenpfad-Gesundheit**
  (kommen Samples sauber durch, stallt iso nach N Frames?) sagt er nichts.

## 2. Ziele & Nicht-Ziele

### Ziele

Ein automatisiertes HW-CI-Gate, das auf echtem `fm_board` die Fehlerklassen
fängt, die rein über USB vom Host beobachtbar sind:

1. **Flashen** deterministisch vom Bench-Host (Fundament für alles Weitere).
2. **DFU/MCUboot-Update-Zyklus** — Happy-Path *und* Revert.
3. **USB-Enumeration** — Composite-Deskriptoren korrekt.
4. **Audio-Datenpfad-Integrität** — iso-Streaming stabil, Samples intakt.

Das Ganze **nachbaubar/scriptbar** (Bench-as-Code) und so entkoppelt, dass die
Fixture später ohne Test-Änderung auf das `HW-DebugBoard` migriert.

### Nicht-Ziele (bewusst zurückgestellt)

- **Analog-/RF-Audioqualität** (Pegel, Verzerrung, moduliertes NF-Signal über
  die SA818-Luftschnittstelle) — braucht Messtechnik/Loopback-Dämpfung; separate
  spätere Ausbaustufe.
- **Echter SA818-TX / PTT-Keying** im Test — kein HF, kein Dummy-Load nötig
  (siehe §9 Safety).
- **Linux-/CM4-/x64-OTA-HIL** — das ist die getrennte Vision aus der
  `linux-image`-CLAUDE.md und gehört nicht hierher.

## 3. Was schon existiert

**Firmware (`FW-RemoteStation`):**

- `board.cmake` für `fm_board`: Runner `pyocd` / `openocd` / `jlink`, Target
  `STM32U575CIT`, `connect_mode=under-reset`.
- twister `dut`-Fixture (pytest-twister-harness) flasht unter `--device-testing`
  automatisch und liefert `readlines()/write()` auf die CDC-Konsole.
- `--sysbuild`-Prod-Build → signiertes Image (`zephyr.signed.bin`) +
  MCUboot-Hex; MCUboot Trial-Boot mit IWDG-Revert.
- **Health-gated Self-Confirm:** Image bestätigt sich erst nach (1) USB
  enumeriert, (2) CDC-ACM-Shell aktiv, (3) SA818 `AT+DMOCONNECT`-Handshake ok.
- `tests/usb_audio` mit `fm.usb_audio.stream` (real-HW-Boot-Log-Test) und
  `build_only`-Variante; `tests/unit_audio` (native).

**Hardware:**

- `HW-Module-DeviceTester` — Bringup-/Test-Board: Modul steckt in `J203`,
  Versorgung +5V (USB-C `J201`) / +12V (Phoenix `J101`), CM4-Flash-Header.
- `HW-DebugBoard` (Schematic-Phase) — die spätere integrierte HIL-Fixture:
  USB-Hub (Debug-STM32 + ST-Link + DUT-USB in einem USB-C), **DUT-Power-Control
  per TPS22917-Lastschalter**, `DUT_RESET`, **INA226-Strommessung**, OLED.

**Deployment-Muster (Projektkonvention):** self-hosted GitHub Actions Runner,
kein SSH/Watchtower.

## 4. Die Lücke (Zusammenfassung)

Kein CI-Job führt die `hardware`-Tests real aus, und der vorhandene Test
verifiziert nur „bootet & enumeriert", nicht „Datenpfad gesund". Die Bugs sitzen
**unterhalb** dessen, was `native_sim` und der Boot-Log-Test sehen.

## 5. Design-Überblick — Test-Suite-first, Bench-abstrahiert, phasenweise

Leitidee: **Test-Logik von der Fixture entkoppeln.** Die Tests brauchen nur vier
Primitive:

| Primitiv | MVP-Backend | DebugBoard-Backend (später) |
|---|---|---|
| **flash** | ST-Link (SWD) via pyocd/openocd | on-board ST-Link-Rückführung |
| **reset** | ST-Link `nRST` | Debug-STM32 → `DUT_RESET` |
| **power-cycle** | ST-Link-Reset; optional `uhubctl`-Hub für VBUS-Cut | TPS22917-Lastschalter (EN via Debug-STM32) |
| **usb-talk** | Host-USB direkt an Board-USB-C | on-board USB-Hub |

Liegen diese hinter einem dünnen **Bench-Driver-Interface**, läuft dieselbe
Test-Suite heute auf einer Billig-Bench und später unverändert auf dem
DebugBoard. Der DebugBoard-Umstieg ist ein **Backend-Swap**, kein Test-Rewrite.

**Wichtige Präzisierung:** twisters `dut`-Fixture liefert **flash + reset +
Konsole** bereits (Baustein 8.1). Der Bench-Driver baut das *nicht* nach — er
liefert nur die Primitive, die twister **nicht** hat: USB-Descriptor-Zugriff,
ALSA-Loopback, DFU-Orchestrierung und power-cycle-über-Reset-hinaus (Bausteine
8.2–8.4).

**Form (entschieden):** Der Bench-Driver ist eine dünne, importierbare
Python-Lib **`fw_hil`** in *diesem* Repo. Sie definiert das
`BenchDriver`-Interface + Backends (`STLinkBackend` jetzt, `DebugBoardBackend`
später) und die Host-Verify-Helfer (USB-Descriptors, Audio-Analyse). Auf der
Bench per Ansible `pip install -e` installiert; `FW-RemoteStation`-conftest
importiert `fw_hil` und verdrahtet es in die twister-Fixtures. So lebt die
Abstraktion + der Backend-Swap im Bench-Repo (Erfolgskriterium #5: DebugBoard =
neue Backend-Klasse hier, null FW-Repo-Änderung).

### Repo-Split (bewusst, unvermeidbar)

- **`FW-RemoteStation` (bleibt dort):** der FW-Loopback-Testmode (§8.4), die
  Twister-Testcases, und der `hil`-Job in der CI-Workflow-YAML. Muss im FW-Repo
  liegen — es ist Firmware und gated FW-PRs.
- **`FW-HIL` (dieses Repo):** Konzept/Spec, Ansible-Playbook (Bench-as-Code),
  `hardware-map.yaml`, udev-Rules, Runner-Setup, Bench-Driver-Abstraktion +
  host-only Verify-Tooling (USB-Descriptor-Checker, ALSA-Loopback-Analyzer).

Der org-scoped Runner verbindet beide.

## 6. Bench-Hardware (MVP) + DebugBoard-Mapping

| Rolle | MVP | Anmerkung | → DebugBoard |
|---|---|---|---|
| Bench-Host | **Letsung GoLite 11** (x86, N100-Klasse, vorhanden) | baut Zephyr *und* flasht in einem twister-Lauf; dediziert, per Ansible plattmachbar; always-on (~6–10 W idle) | bleibt (Host extern) |
| Debug-Probe | **ST-Link V3** | SWD-Flash + `nRST` + Mass-Erase-Recovery; openocd/pyocd nativ | on-board ST-Link |
| DUT-Fixture | vorhandenes **DeviceTester** | Modul in `J203`, +5V/+12V | DebugBoard ersetzt DeviceTester |
| Board-USB | USB-C `fm_board` → Host | DUT-Interface **und** Konsole (CDC-ACM), separat vom ST-Link-USB | on-board USB-Hub |
| +12V | Labornetzteil/12V-Brick an Phoenix | SA818-TX-Stromspitzen (auch ohne aktives Keying gibt es Einschaltströme) | bleibt extern |
| Recovery (VBUS-Cut) | *optional, empfohlen:* billiger `uhubctl`-Hub (~€30) | ST-Link-Reset deckt die meisten Hänger; ein toter USB-Stack braucht echten VBUS-Cut | TPS22917 |

**Kein Neukauf zwingend nötig** (Host + Probe + DeviceTester vorhanden; Hub
optionale Versicherung). Jedes MVP-Teil hat ein DebugBoard-Gegenstück →
kein Wegwerf-Invest.

## 7. Plattform & Reproduzierbarkeit

- **Runner:** GitHub Actions **self-hosted**, **org-scoped** (OE5XRX), Labels
  `self-hosted, hil, fm_board`. Der FW-Workflow bekommt einen `hil`-Job
  `runs-on: [self-hosted, hil, fm_board]`.
- **Nachbaubar → Ansible (Bench-as-Code), kein Fix-Image.** Idempotentes
  Playbook provisioniert einen frischen Debian-Host: Zephyr-SDK + west,
  pyocd/openocd, `dfu-util`, `alsa-utils`, ST-Link-udev-Rules, Runner als
  systemd-Service, `hardware-map.yaml`. Re-runnbar, diff-bar.
  - *Fix-Image* verworfen (driftet, opak). *Docker-Runner* verworfen: USB
    re-enumeriert nach jedem Reflash, der `/dev/serial/by-id`-Race wird durch
    die Container-Schicht schlimmer.
- **Deterministische Geräte-Adressierung:** udev-Rules → stabile Symlinks für
  ST-Link (per Serial) und Board-CDC (per VID/PID+Serial); twister
  `hardware-map.yaml` pinnt die Probe-Serial. Killt den `by-id`-Race an der
  Wurzel.
- **Build-Modell (MVP):** Bench baut selbst (ein twister-Flow, kein
  Artefakt-Handoff). Später optional: Build im Cloud-Runner, nur Flash/Test auf
  der Bench.

## 8. Bausteine in Prioritätsreihenfolge

Reihenfolge = fundamental/billig zuerst, teuer/FW-abhängig zuletzt.

### 8.1 Flashen *(Fundament)*

- **Existiert:** board.cmake-Runner, twister-`dut`-Auto-Flash.
- **Fehlt:** Bench + ST-Link am SWD; udev-Rules + `hardware-map.yaml`;
  Verifikation dass pyocd/openocd auf echtem Silizium flasht; Runner-Label.
- **DoD:** Vom Host flasht `fm_board`, resettet, CDC-Konsole erscheint
  deterministisch. **Erstes grünes Licht.**

### 8.2 DFU / MCUboot-Update

- **Existiert:** signiertes Image + mcuboot-hex, DFU-Alt-Settings, health-gated
  Self-Confirm, Trial/Revert, Dev-Key.
- **Fehlt:** Host-Test der orchestriert: SWD-Baseline flashen → v2 bauen
  (Version-Bump) → `dfu-util --download` in slot1 → reset → assert v2
  bootet + confirmt (Version via Shell über CDC lesen). **Plus Revert-Test:**
  Image das den Health-Gate absichtlich reißt (z.B. Build mit deaktiviertem
  SA818 → AT-Handshake failt) → assert MCUboot rollt auf slot0 zurück → assert
  Baseline-Version zurück.
- **DoD:** Happy-Path **und** Revert auf echter HW asserted. *Kein neuer
  FW-Code* nötig (Revert nutzt den bestehenden Health-Gate).

### 8.3 USB-Enumeration

- **Existiert:** Boot-Log-Test (liest CDC-Log).
- **Fehlt:** host-seitige **Descriptor-Assertion** via pyusb/lsusb: Composite
  hat UAC2 (korrekte Sample-Rate, Kanalzahl), CDC-ACM, DFU-Alt-Settings; VID/PID;
  iSerial vorhanden.
- **DoD:** Descriptor-Snapshot asserted; kaputte USB-Config (fehlendes
  UAC2-Iface, falsche Sample-Rate) färbt das Gate rot.

### 8.4 Audio-Loopback *(die Schmerzklasse — zuletzt, braucht FW)*

- **Existiert:** nichts auf HW; `unit_audio` nur native.
- **Fehlt:**
  - **(a) FW-Loopback-Testmode:** UAC2 TX (host→device) wird intern auf UAC2 RX
    (device→host) zurückgeschleift, SA818 umgangen. Hinter Kconfig
    (`CONFIG_*_TEST_LOOPBACK`) + Shell-Command gated, damit der Prod-Build
    unberührt bleibt.
  - **(b) Host-Test** via ALSA (`aplay`/`arecord`) oder `python-sounddevice`:
    bekanntes Signal (Sinus/PRBS) in den UAC2-Playback-Endpoint spielen, den
    Capture-Endpoint zurückfangen, Kreuzkorrelation / Dropout / Latenz / SNR
    berechnen. Assert: keine iso-Stalls (kontinuierliche Frames über N s) +
    Sample-Integrität.
- **DoD:** fängt die iso-OUT-Stall-Klasse deterministisch; ein zurückgedrehter
  UDC-iso-Patch färbt das Gate rot.

## 9. Querschnittsthemen

- **🔒 Security (nicht verhandelbar, vor dem ersten LAN-Kontakt):** self-hosted
  Runner + PRs = Fork-PRs führen sonst beliebigen Code auf Bench/LAN aus.
  Mitigation: GitHub „Require approval for fork-PR workflows" **an**; den
  `hil`-Job zusätzlich hinter ein Label (`hil-ok`) gaten. Erst dann darf der
  Runner ans Netz.
- **Concurrency:** ein Board = ein Job. Runner-Concurrency 1 + GH-`concurrency:`
  -Group → Pushes queuen statt auf der HW zu kollidieren.
- **Cadence:** flash + enum + DFU sind schnell/robust → **per-PR-Gate**.
  Audio-Loopback ggf. länger/zickiger → per-PR wenn stabil, sonst nightly +
  on-demand-Label. Nach ersten Stabilitätsdaten entscheiden.
- **PTT/12V-Safety:** enum/dfu/audio-loopback tasten **nie** TX → kein HF, kein
  Dummy-Load. Erst ein echter SA818-TX-Test bräuchte Dummy-Load — das ist die
  zurückgestellte Analog/RF-Klasse.

## 10. Phasenplan

- **Phase 0 (Tage, Schreibtisch):** Bausteine 8.1 + 8.2 manuell mit dem
  vorhandenen ST-Link durchspielen — noch ohne Letsung/Runner. Hilft dem
  aktuellen Audio-Bug am schnellsten, validiert flash + DFU-Flow.
- **Phase 1 (Wochen, CI-Gate):** Letsung per Ansible provisionieren, Runner
  registrieren, Bausteine 8.1–8.4 als PR-Gate wired. Recovery via
  ST-Link-Reset/Mass-Erase (+ optional uhubctl).
- **Phase 2 (langfristig):** Bench-Backend auf `HW-DebugBoard` umstellen —
  Power-Cycle über TPS22917, INA226-Strom als Zusatz-Assertion (z.B. „SA818
  keyed up?" am TX-Stromsprung). **Test-Suite bleibt unverändert.**

## 11. Erfolgskriterien

1. Ein FW-PR, der die STM32-UDC-iso-Recovery zurückdreht, wird vom Gate **rot**.
2. Ein FW-PR, der die UAC2-Sample-Rate/Deskriptoren kaputtmacht, wird **rot**.
3. Ein DFU-Update mit unhealthy Image wird sauber zurückgerollt und der Test
   bestätigt den Rollback.
4. Die Bench ist aus dem Ansible-Playbook heraus von Grund auf reproduzierbar.
5. Der Umstieg auf das DebugBoard erfordert **keine** Änderung an den Testcases,
   nur am Bench-Driver-Backend.

## 12. Geklärte Punkte

- **Bench-Driver-Form → entschieden: dünne Python-Lib `fw_hil`** in diesem Repo
  (Option B, siehe §5). twister bleibt für flash/reset zuständig; `fw_hil`
  liefert USB/Audio/DFU/power-cycle.
- **`uhubctl`-Hub → zurückgestellt.** MVP-Ziel ist „schnell was zum Laufen
  bringen"; Recovery vorerst nur via ST-Link-Reset/Mass-Erase. Hub nachrüsten,
  falls ein echter USB-VBUS-Hang auftritt.
- **Version-Ausleseweg → gefunden:** Shell-Command `version` gibt
  `APP-VERSION YY.MM.DD-NN` aus, gestempelt aus `app/VERSION`
  (Chain `app/VERSION → app_version.h → version`, vgl.
  `tests/sim_shell/pytest/test_version.py`). DFU-Test baut v1/v2 mit
  unterschiedlichen `app/VERSION`-Werten und asserted nach dem Swap den
  gebumpten Wert über CDC.

### Noch im Plan zu klären

- Exakte UAC2-Parameter für die Descriptor-Assertion (Sample-Rate, Kanäle,
  Endpoint-Adressen) — aus der FW-Config/Deskriptoren ziehen, nicht raten.
- Genaue Form des FW-Loopback-Testmode (Kconfig-Symbol, Shell-Command-Name,
  wo im UAC2-Datenpfad die Rückschleife sitzt).

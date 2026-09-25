# FW-HIL Foundation (host-testable `fw_hil` lib) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `fw_hil`, a hardware-free Python library holding all the HIL verification *logic* (audio-loopback analysis, USB-descriptor assertion, DFU orchestration) plus the bench-driver interface, fully unit-tested without any board attached.

**Architecture:** A `src/`-layout Python package. Every unit of logic is pure and backend-agnostic: signal math runs on numpy arrays, descriptor checks run on a plain dataclass model, DFU orchestration runs against an injected `DfuOps` protocol, and the ST-Link backend *builds* command argv lists without executing them (execution is an injected runner). This makes 100% of Plan 1 testable on the Letsung-less dev host and leaves only the wiring-to-real-hardware for Plan 2 (`2026-09-25-fw-hil-bench-bringup.md`).

**Tech Stack:** Python ≥3.11, numpy (only runtime dep), pytest + ruff (dev). GPL-3.0-or-later.

**Spec:** `docs/superpowers/specs/2026-09-25-fw-hil-ci-gate-design.md`

## Global Constraints

- **License:** GPL-3.0-or-later; SPDX header `# SPDX-License-Identifier: GPL-3.0-or-later` on every `.py` file.
- **Package name / layout:** `fw_hil` under `src/fw_hil/`; importable as `import fw_hil`.
- **No hardware dependency in Plan 1.** No `pyusb`, `dfu-util`, `pyocd` *execution*, or serial I/O in this plan. Real device access is Plan 2. Logic is exercised against models, fakes, and command-argv assertions only.
- **Real firmware constants (verbatim, from `boards/oe5xrx/fm_board/USB_CONFIGURATION.md`):** VID `0x2fe3`, PID `0x0100`; UAC2 = 8000 Hz, 16-bit PCM (`S16_LE`), 1 channel, bidirectional (OUT=playback, IN=capture); classes CDC-ACM `0x02`, UAC2 `0x01`, DFU `0xFE`; DFU alt setting `0`; ALSA card name `OE5XRX`. Flash target `stm32u575citx`.
- **Version string format (verbatim):** `APP-VERSION YY.MM.DD-NN` — the `version` shell command output; the DFU cycle distinguishes images by this.
- **Formatting:** ruff format + ruff check clean; CI fails on any diff or lint error.
- **Commits:** end every commit message with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Work on branch `feature/hil-ci-gate`; one PR at the end.

## Review Focus

Failure modes the spec implies but which a naive happy-path test would miss — each is pinned to a test in the owning task:

- **Empty / truncated capture** (iso stream never started or stalled immediately): `analyze_loopback` must return a *failed* result, not raise or hang — Task 3.
- **All-silence capture** (total iso stall mid-stream): dropout detection must flag near-total dropout and correlation ≈ 0 — Task 3.
- **Amplitude/DC-offset mismatch** between reference and capture (host gain, codec bias): normalized cross-correlation must still align correctly — Task 2.
- **Entirely-missing USB interface** vs **present-but-wrong-parameter** (e.g. UAC2 absent vs UAC2 at 48 kHz): must produce distinct, clear messages, not one generic failure — Task 4.
- **DFU image that never boots** (no readable version / timeout): the update cycle must classify it as failure and stop, never loop forever — Task 5.

---

## Task 1: Repo scaffolding, package skeleton & tooling

**Files:**
- Create: `LICENSE` (GPL-3.0-or-later full text)
- Create: `README.md`
- Create: `.gitignore`
- Create: `pyproject.toml`
- Create: `src/fw_hil/__init__.py`
- Create: `src/fw_hil/py.typed` (empty marker)
- Create: `tests/test_smoke.py`
- Create: `.github/workflows/ci.yml`
- Create: `.github/dependabot.yml`

**Interfaces:**
- Consumes: nothing.
- Produces: an installable `fw_hil` package (`pip install -e .[dev]`), a green `pytest`, a clean `ruff`, and CI + dependabot config that later tasks extend.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "fw_hil"
version = "0.1.0"
description = "Hardware-in-the-loop verification library for OE5XRX STM32 firmware modules"
readme = "README.md"
requires-python = ">=3.11"
license = "GPL-3.0-or-later"
dependencies = ["numpy>=2.1"]

[project.optional-dependencies]
dev = ["pytest>=8.3", "ruff>=0.6"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.ruff]
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create `LICENSE`, `.gitignore`, `README.md`, package markers**

`LICENSE`: full GPL-3.0 text (fetch canonical text). `.gitignore`: Python defaults (`__pycache__/`, `*.egg-info/`, `.venv/`, `.pytest_cache/`, `.ruff_cache/`, `build/`, `dist/`). `README.md`: one-paragraph purpose (from spec §1), install (`pip install -e .[dev]`), test (`pytest`, `ruff check .`), and a pointer to the spec + both plans. `src/fw_hil/__init__.py`:

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Hardware-in-the-loop verification library for OE5XRX STM32 firmware."""

__version__ = "0.1.0"
```

Create empty `src/fw_hil/py.typed`.

- [ ] **Step 3: Write the smoke test**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
import fw_hil


def test_package_imports():
    assert fw_hil.__version__ == "0.1.0"
```

- [ ] **Step 4: Write CI + dependabot**

`.github/workflows/ci.yml` — on push/PR: matrix nothing fancy, one job: checkout, `actions/setup-python@v5` (3.11), `pip install -e .[dev]`, `ruff format --check .`, `ruff check .`, `pytest -v`.

`.github/dependabot.yml`:

```yaml
version: 2
updates:
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
```

- [ ] **Step 5: Verify install + green**

Run: `pip install -e .[dev] && ruff format --check . && ruff check . && pytest -v`
Expected: install succeeds, ruff clean, `test_package_imports` PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: scaffold fw_hil package, tooling, CI, dependabot"
```

---

## Task 2: Audio — signal generation & cross-correlation alignment

**Files:**
- Create: `src/fw_hil/audio_analysis.py`
- Test: `tests/test_audio_analysis.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `generate_sine(freq_hz: float, duration_s: float, sample_rate: int = 8000, amplitude: float = 0.5) -> np.ndarray` — float32 mono in [-1, 1].
  - `find_lag(reference: np.ndarray, captured: np.ndarray, sample_rate: int = 8000) -> tuple[int, float]` — returns `(lag_samples, normalized_correlation)` where correlation ∈ [0, 1] is the peak of the normalized cross-correlation; robust to amplitude scaling and DC offset.
  - `lag_to_latency_s(lag_samples: int, sample_rate: int = 8000) -> float`.

- [ ] **Step 1: Write failing tests**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
import numpy as np
from fw_hil.audio_analysis import generate_sine, find_lag, lag_to_latency_s


def test_generate_sine_shape_and_range():
    sig = generate_sine(1000.0, 0.1, sample_rate=8000, amplitude=0.5)
    assert sig.dtype == np.float32
    assert sig.shape == (800,)
    assert np.max(np.abs(sig)) <= 0.5 + 1e-6


def test_find_lag_recovers_known_delay():
    ref = generate_sine(1000.0, 0.2)
    delay = 40
    captured = np.concatenate([np.zeros(delay, np.float32), ref])
    lag, corr = find_lag(ref, captured)
    assert lag == delay
    assert corr > 0.99


def test_find_lag_robust_to_gain_and_dc_offset():
    # Review Focus: host gain + codec DC bias must not defeat alignment.
    ref = generate_sine(1000.0, 0.2)
    delay = 25
    captured = 0.3 * np.concatenate([np.zeros(delay, np.float32), ref]) + 0.1
    lag, corr = find_lag(ref, captured)
    assert lag == delay
    assert corr > 0.99


def test_lag_to_latency():
    assert lag_to_latency_s(80, 8000) == 0.01
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_audio_analysis.py -v`
Expected: FAIL (module/functions not defined).

- [ ] **Step 3: Implement**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Audio-loopback signal analysis (numpy-only, no hardware)."""
import numpy as np


def generate_sine(freq_hz, duration_s, sample_rate=8000, amplitude=0.5):
    n = int(round(duration_s * sample_rate))
    t = np.arange(n, dtype=np.float32) / sample_rate
    return (amplitude * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)


def _normalize(x):
    x = x.astype(np.float64)
    x = x - x.mean()
    norm = np.linalg.norm(x)
    return x / norm if norm > 0 else x


def find_lag(reference, captured, sample_rate=8000):
    r = _normalize(reference)
    c = _normalize(captured)
    corr = np.correlate(c, r, mode="full")
    peak = int(np.argmax(corr))
    lag = peak - (len(r) - 1)
    return lag, float(np.clip(corr[peak], 0.0, 1.0))


def lag_to_latency_s(lag_samples, sample_rate=8000):
    return lag_samples / sample_rate
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_audio_analysis.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/fw_hil/audio_analysis.py tests/test_audio_analysis.py
git commit -m "feat: audio signal gen + cross-correlation alignment"
```

---

## Task 3: Audio — dropout detection, SNR & `analyze_loopback`

**Files:**
- Modify: `src/fw_hil/audio_analysis.py`
- Test: `tests/test_audio_analysis.py` (extend)

**Interfaces:**
- Consumes: `find_lag`, `lag_to_latency_s`, `generate_sine` from Task 2.
- Produces:
  - `detect_dropouts(captured: np.ndarray, sample_rate: int = 8000, silence_threshold: float = 0.02, min_gap_s: float = 0.005) -> list[tuple[int, int]]` — runs of near-silence longer than `min_gap_s`, as `(start_sample, end_sample)`.
  - `@dataclass LoopbackResult` with fields: `ok: bool`, `lag_samples: int`, `latency_s: float`, `correlation: float`, `dropout_count: int`, `dropout_fraction: float`, `snr_db: float`.
  - `analyze_loopback(reference, captured, sample_rate=8000, min_correlation=0.9, max_dropout_fraction=0.01, min_snr_db=20.0) -> LoopbackResult` — aligns, scores, and sets `ok` against the thresholds. Never raises on empty/short input; returns `ok=False`.

- [ ] **Step 1: Write failing tests**

```python
from fw_hil.audio_analysis import detect_dropouts, analyze_loopback, LoopbackResult


def test_detect_dropouts_finds_silent_gap():
    sig = generate_sine(1000.0, 0.1).copy()
    sig[400:480] = 0.0  # 10 ms gap at 8 kHz
    gaps = detect_dropouts(sig, min_gap_s=0.005)
    assert len(gaps) == 1
    start, end = gaps[0]
    assert start <= 400 and end >= 480


def test_analyze_loopback_clean_signal_ok():
    ref = generate_sine(1000.0, 0.5)
    captured = np.concatenate([np.zeros(16, np.float32), ref])
    res = analyze_loopback(ref, captured)
    assert isinstance(res, LoopbackResult)
    assert res.ok
    assert res.correlation > 0.99
    assert res.dropout_count == 0


def test_analyze_loopback_empty_capture_fails_gracefully():
    # Review Focus: iso never started -> failed result, no exception.
    ref = generate_sine(1000.0, 0.5)
    res = analyze_loopback(ref, np.zeros(0, np.float32))
    assert res.ok is False


def test_analyze_loopback_all_silence_flags_dropout():
    # Review Focus: total mid-stream stall.
    ref = generate_sine(1000.0, 0.5)
    res = analyze_loopback(ref, np.zeros(len(ref), np.float32))
    assert res.ok is False
    assert res.dropout_fraction > 0.9
    assert res.correlation < 0.5
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_audio_analysis.py -v`
Expected: FAIL (new names undefined).

- [ ] **Step 3: Implement**

```python
from dataclasses import dataclass


def detect_dropouts(captured, sample_rate=8000, silence_threshold=0.02, min_gap_s=0.005):
    if captured.size == 0:
        return []
    min_gap = max(1, int(round(min_gap_s * sample_rate)))
    silent = np.abs(captured) < silence_threshold
    gaps = []
    run_start = None
    for i, s in enumerate(silent):
        if s and run_start is None:
            run_start = i
        elif not s and run_start is not None:
            if i - run_start >= min_gap:
                gaps.append((run_start, i))
            run_start = None
    if run_start is not None and len(silent) - run_start >= min_gap:
        gaps.append((run_start, len(silent)))
    return gaps


@dataclass
class LoopbackResult:
    ok: bool
    lag_samples: int
    latency_s: float
    correlation: float
    dropout_count: int
    dropout_fraction: float
    snr_db: float


def _snr_db(reference, captured, lag):
    # Align, least-squares scale the reference onto the capture, measure residual.
    r = reference.astype(np.float64)
    c = captured.astype(np.float64)
    if lag >= 0:
        c = c[lag:]
    else:
        r = r[-lag:]
    n = min(len(r), len(c))
    if n == 0:
        return -np.inf
    r, c = r[:n], c[:n]
    denom = float(r @ r)
    scale = (r @ c) / denom if denom > 0 else 0.0
    noise = c - scale * r
    sig_p = float(np.mean((scale * r) ** 2))
    noise_p = float(np.mean(noise ** 2))
    if noise_p <= 0:
        return np.inf
    if sig_p <= 0:
        return -np.inf
    return 10.0 * np.log10(sig_p / noise_p)


def analyze_loopback(reference, captured, sample_rate=8000,
                     min_correlation=0.9, max_dropout_fraction=0.01, min_snr_db=20.0):
    if captured.size == 0:
        return LoopbackResult(False, 0, 0.0, 0.0, 0, 1.0, -np.inf)
    lag, corr = find_lag(reference, captured, sample_rate)
    gaps = detect_dropouts(captured, sample_rate)
    dropped = sum(e - s for s, e in gaps)
    frac = dropped / captured.size
    snr = _snr_db(reference, captured, lag)
    ok = (corr >= min_correlation and frac <= max_dropout_fraction and snr >= min_snr_db)
    return LoopbackResult(ok, lag, lag_to_latency_s(lag, sample_rate), corr,
                          len(gaps), frac, snr)
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_audio_analysis.py -v`
Expected: PASS (all Task 2 + Task 3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/fw_hil/audio_analysis.py tests/test_audio_analysis.py
git commit -m "feat: audio dropout/SNR analysis + analyze_loopback verdict"
```

---

## Task 4: USB — descriptor model & composite assertion

**Files:**
- Create: `src/fw_hil/usb_descriptors.py`
- Test: `tests/test_usb_descriptors.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `@dataclass UsbInterface(class_code: int, subclass: int, protocol: int, alt_settings: tuple[int, ...] = (0,))`
  - `@dataclass UsbComposite(vid: int, pid: int, serial: str | None, interfaces: list[UsbInterface], uac2_sample_rate_hz: int | None, uac2_channels: int | None)`
  - `@dataclass ExpectedComposite(vid: int, pid: int, require_serial: bool, uac2_sample_rate_hz: int, uac2_channels: int, dfu_alt_settings: tuple[int, ...])` with a classmethod `fm_board()` pre-filled from the Global Constraints.
  - `check_composite(actual: UsbComposite, expected: ExpectedComposite) -> list[str]` — returns human-readable mismatch messages (empty list ⇒ pass). Distinguishes *missing interface* from *wrong parameter*.
  - `assert_composite(actual, expected) -> None` — raises `AssertionError` joining the messages.

- [ ] **Step 1: Write failing tests**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
import pytest
from fw_hil.usb_descriptors import (
    UsbInterface, UsbComposite, ExpectedComposite, check_composite, assert_composite,
)

CDC, UAC2, DFU = 0x02, 0x01, 0xFE


def _good():
    return UsbComposite(
        vid=0x2fe3, pid=0x0100, serial="OE5XRX-0001",
        interfaces=[UsbInterface(CDC, 0x02, 0x01), UsbInterface(UAC2, 0x01, 0x00),
                    UsbInterface(DFU, 0x01, 0x02, alt_settings=(0,))],
        uac2_sample_rate_hz=8000, uac2_channels=1,
    )


def test_good_composite_passes():
    assert check_composite(_good(), ExpectedComposite.fm_board()) == []


def test_missing_uac2_interface_reported_distinctly():
    # Review Focus: entirely-absent interface.
    dev = _good()
    dev.interfaces = [i for i in dev.interfaces if i.class_code != UAC2]
    msgs = check_composite(dev, ExpectedComposite.fm_board())
    assert any("UAC2" in m and "missing" in m.lower() for m in msgs)


def test_wrong_sample_rate_reported_distinctly():
    # Review Focus: present-but-wrong-parameter, not the same as missing.
    dev = _good()
    dev.uac2_sample_rate_hz = 48000
    msgs = check_composite(dev, ExpectedComposite.fm_board())
    assert any("sample rate" in m.lower() and "48000" in m for m in msgs)
    assert not any("missing" in m.lower() for m in msgs)


def test_assert_composite_raises_on_wrong_vid():
    dev = _good()
    dev.vid = 0x1234
    with pytest.raises(AssertionError):
        assert_composite(dev, ExpectedComposite.fm_board())
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_usb_descriptors.py -v`
Expected: FAIL (module undefined).

- [ ] **Step 3: Implement**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""USB composite descriptor model + assertion (no hardware; pyusb capture is Plan 2)."""
from dataclasses import dataclass, field

CLASS_CDC_ACM = 0x02
CLASS_UAC2 = 0x01
CLASS_DFU = 0xFE


@dataclass
class UsbInterface:
    class_code: int
    subclass: int
    protocol: int
    alt_settings: tuple = (0,)


@dataclass
class UsbComposite:
    vid: int
    pid: int
    serial: str | None
    interfaces: list = field(default_factory=list)
    uac2_sample_rate_hz: int | None = None
    uac2_channels: int | None = None

    def has_class(self, class_code):
        return any(i.class_code == class_code for i in self.interfaces)

    def interface(self, class_code):
        return next((i for i in self.interfaces if i.class_code == class_code), None)


@dataclass
class ExpectedComposite:
    vid: int
    pid: int
    require_serial: bool
    uac2_sample_rate_hz: int
    uac2_channels: int
    dfu_alt_settings: tuple

    @classmethod
    def fm_board(cls):
        return cls(vid=0x2fe3, pid=0x0100, require_serial=True,
                   uac2_sample_rate_hz=8000, uac2_channels=1, dfu_alt_settings=(0,))


def check_composite(actual, expected):
    msgs = []
    if actual.vid != expected.vid:
        msgs.append(f"VID mismatch: {actual.vid:#06x} != {expected.vid:#06x}")
    if actual.pid != expected.pid:
        msgs.append(f"PID mismatch: {actual.pid:#06x} != {expected.pid:#06x}")
    if expected.require_serial and not actual.serial:
        msgs.append("iSerial missing")

    if not actual.has_class(CLASS_CDC_ACM):
        msgs.append("CDC-ACM interface missing")
    if not actual.has_class(CLASS_DFU):
        msgs.append("DFU interface missing")
    else:
        dfu = actual.interface(CLASS_DFU)
        if tuple(dfu.alt_settings) != tuple(expected.dfu_alt_settings):
            msgs.append(f"DFU alt settings {tuple(dfu.alt_settings)} != "
                        f"{tuple(expected.dfu_alt_settings)}")

    if not actual.has_class(CLASS_UAC2):
        msgs.append("UAC2 interface missing")
    else:
        if actual.uac2_sample_rate_hz != expected.uac2_sample_rate_hz:
            msgs.append(f"UAC2 sample rate {actual.uac2_sample_rate_hz} != "
                        f"{expected.uac2_sample_rate_hz}")
        if actual.uac2_channels != expected.uac2_channels:
            msgs.append(f"UAC2 channels {actual.uac2_channels} != {expected.uac2_channels}")
    return msgs


def assert_composite(actual, expected):
    msgs = check_composite(actual, expected)
    if msgs:
        raise AssertionError("USB composite mismatch:\n  " + "\n  ".join(msgs))
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_usb_descriptors.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/fw_hil/usb_descriptors.py tests/test_usb_descriptors.py
git commit -m "feat: USB composite model + fm_board descriptor assertion"
```

---

## Task 5: DFU — update-cycle orchestration (backend-agnostic)

**Files:**
- Create: `src/fw_hil/dfu.py`
- Test: `tests/test_dfu.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class DfuOps(Protocol)` with: `flash_baseline(image_path: str) -> None`, `dfu_download(image_path: str, alt: int) -> None`, `reset() -> None`, `read_app_version(timeout_s: float = 20.0) -> str | None` (None ⇒ no version readable / boot failed).
  - `@dataclass UpdateResult(ok: bool, final_version: str | None, reverted: bool, detail: str)`.
  - `run_update_cycle(ops, baseline_image, baseline_version, new_image, new_version, alt=0) -> UpdateResult` — flash baseline, confirm baseline version, DFU-download new, reset, confirm `new_version`. `ok` iff final == new_version.
  - `run_revert_cycle(ops, baseline_image, baseline_version, unhealthy_image, alt=0) -> UpdateResult` — flash baseline, DFU-download unhealthy, reset; MCUboot health-gate must revert. `ok` iff final == baseline_version (i.e. `reverted=True`); a `None` read ⇒ `ok=False` with detail "no version after revert window".

- [ ] **Step 1: Write failing tests**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
from fw_hil.dfu import run_update_cycle, run_revert_cycle, UpdateResult


class FakeDfuOps:
    """Simulates a board: tracks the version the next boot will report."""
    def __init__(self, revert_on=()):
        self.current = None
        self.revert_on = set(revert_on)  # images that fail the health-gate
        self.log = []

    def flash_baseline(self, image_path):
        self.log.append(("flash", image_path))
        self._pending = image_path

    def dfu_download(self, image_path, alt):
        self.log.append(("dfu", image_path, alt))
        self._pending = image_path

    def reset(self):
        self.log.append(("reset",))
        # unhealthy image reverts to whatever was 'current' before it
        if self._pending in self.revert_on:
            pass  # current unchanged -> reverted
        else:
            self.current = _VERSIONS[self._pending]

    def read_app_version(self, timeout_s=20.0):
        return self.current


_VERSIONS = {"base.bin": "APP-VERSION 26.09.25-01", "v2.bin": "APP-VERSION 26.09.25-02"}


def test_happy_path_new_version_sticks():
    ops = FakeDfuOps()
    res = run_update_cycle(ops, "base.bin", "APP-VERSION 26.09.25-01",
                           "v2.bin", "APP-VERSION 26.09.25-02")
    assert isinstance(res, UpdateResult)
    assert res.ok and res.final_version == "APP-VERSION 26.09.25-02"
    assert not res.reverted


def test_revert_cycle_rolls_back_unhealthy_image():
    ops = FakeDfuOps(revert_on={"bad.bin"})
    _VERSIONS["bad.bin"] = "APP-VERSION 26.09.25-99"
    # baseline first so 'current' is the baseline before the bad image
    ops.flash_baseline("base.bin"); ops.reset()
    res = run_revert_cycle(ops, "base.bin", "APP-VERSION 26.09.25-01", "bad.bin")
    assert res.ok and res.reverted
    assert res.final_version == "APP-VERSION 26.09.25-01"


def test_update_cycle_image_never_boots_is_failure_not_hang():
    # Review Focus: no readable version -> classified failure.
    class DeadOps(FakeDfuOps):
        def read_app_version(self, timeout_s=20.0):
            return None
    res = run_update_cycle(DeadOps(), "base.bin", "APP-VERSION 26.09.25-01",
                           "v2.bin", "APP-VERSION 26.09.25-02")
    assert res.ok is False
    assert "no version" in res.detail.lower()
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_dfu.py -v`
Expected: FAIL (module undefined).

- [ ] **Step 3: Implement**

```python
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
        return UpdateResult(False, base_seen, False,
                            f"baseline version {base_seen!r} != {baseline_version!r}")
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
```

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_dfu.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/fw_hil/dfu.py tests/test_dfu.py
git commit -m "feat: DFU update + revert cycle orchestration (backend-agnostic)"
```

---

## Task 6: Bench-driver interface & ST-Link command construction

**Files:**
- Create: `src/fw_hil/driver.py`
- Create: `src/fw_hil/backends/__init__.py`
- Create: `src/fw_hil/backends/stlink.py`
- Test: `tests/test_stlink_backend.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class BenchDriver(ABC)` with abstract `flash(image_path: str) -> None`, `reset() -> None`, `mass_erase() -> None`, `power_cycle() -> None`.
  - `class STLinkBackend(BenchDriver)` — `__init__(self, probe_serial: str, target: str = "stm32u575citx", runner: str = "pyocd", run=subprocess.run)`. Command-builders return `list[str]`: `flash_command(image_path)`, `reset_command()`, `mass_erase_command()`. The action methods call the injected `run`. `power_cycle()` on this backend maps to `reset()` (no VBUS control in the MVP — documented, matches spec §12 deferred hub).

- [ ] **Step 1: Write failing tests**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
from fw_hil.backends.stlink import STLinkBackend


def test_flash_command_includes_target_serial_and_image():
    be = STLinkBackend(probe_serial="066EFF51", target="stm32u575citx", runner="pyocd")
    cmd = be.flash_command("/tmp/app.bin")
    assert cmd[0] == "pyocd"
    assert "stm32u575citx" in cmd
    assert "066EFF51" in cmd
    assert cmd[-1] == "/tmp/app.bin"


def test_mass_erase_command():
    be = STLinkBackend(probe_serial="066EFF51")
    cmd = be.mass_erase_command()
    assert "erase" in cmd and "--mass" in " ".join(cmd)
    assert "066EFF51" in cmd


def test_flash_invokes_injected_runner():
    calls = []
    be = STLinkBackend(probe_serial="X", run=lambda cmd, **kw: calls.append(cmd))
    be.flash("/tmp/app.bin")
    assert calls and calls[0] == be.flash_command("/tmp/app.bin")


def test_power_cycle_maps_to_reset_on_mvp_backend():
    calls = []
    be = STLinkBackend(probe_serial="X", run=lambda cmd, **kw: calls.append(cmd))
    be.power_cycle()
    assert calls == [be.reset_command()]
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `pytest tests/test_stlink_backend.py -v`
Expected: FAIL (module undefined).

- [ ] **Step 3: Implement**

`src/fw_hil/driver.py`:

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Bench-driver interface. Backends implement the four HW primitives."""
from abc import ABC, abstractmethod


class BenchDriver(ABC):
    @abstractmethod
    def flash(self, image_path: str) -> None: ...
    @abstractmethod
    def reset(self) -> None: ...
    @abstractmethod
    def mass_erase(self) -> None: ...
    @abstractmethod
    def power_cycle(self) -> None: ...
```

`src/fw_hil/backends/__init__.py`: `# SPDX-License-Identifier: GPL-3.0-or-later`

`src/fw_hil/backends/stlink.py`:

```python
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
        return [self.runner, "flash", "--target", self.target,
                "--uid", self.probe_serial, image_path]

    def reset_command(self):
        return [self.runner, "reset", "--target", self.target, "--uid", self.probe_serial]

    def mass_erase_command(self):
        return [self.runner, "erase", "--mass", "--target", self.target,
                "--uid", self.probe_serial]

    def flash(self, image_path):
        self._run(self.flash_command(image_path), check=True)

    def reset(self):
        self._run(self.reset_command(), check=True)

    def mass_erase(self):
        self._run(self.mass_erase_command(), check=True)

    def power_cycle(self):
        # MVP: no switchable VBUS (spec §12) -> reset is the strongest recovery.
        self._run(self.reset_command(), check=True)
```

Note: the injected-runner tests pass `run=lambda cmd, **kw: ...`, so `check=True` is swallowed by `**kw`.

- [ ] **Step 4: Run tests, verify pass**

Run: `pytest tests/test_stlink_backend.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/fw_hil/driver.py src/fw_hil/backends/ tests/test_stlink_backend.py
git commit -m "feat: BenchDriver interface + ST-Link command backend"
```

---

## Task 7: Public API surface, README quickstart & full green

**Files:**
- Modify: `src/fw_hil/__init__.py`
- Modify: `README.md`
- Test: `tests/test_smoke.py` (extend)

**Interfaces:**
- Consumes: all prior modules.
- Produces: a curated `fw_hil` top-level namespace so consumers (`FW-RemoteStation` conftest in Plan 2) import from one place.

- [ ] **Step 1: Write failing test**

```python
def test_public_api_surface():
    from fw_hil import (
        analyze_loopback, LoopbackResult, generate_sine,
        UsbComposite, ExpectedComposite, assert_composite,
        run_update_cycle, run_revert_cycle, UpdateResult,
        BenchDriver, STLinkBackend,
    )
    assert ExpectedComposite.fm_board().uac2_sample_rate_hz == 8000
```

- [ ] **Step 2: Run test, verify it fails**

Run: `pytest tests/test_smoke.py::test_public_api_surface -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement re-exports**

Extend `src/fw_hil/__init__.py`:

```python
from fw_hil.audio_analysis import analyze_loopback, LoopbackResult, generate_sine
from fw_hil.usb_descriptors import UsbComposite, ExpectedComposite, assert_composite
from fw_hil.dfu import run_update_cycle, run_revert_cycle, UpdateResult
from fw_hil.driver import BenchDriver
from fw_hil.backends.stlink import STLinkBackend

__all__ = [
    "analyze_loopback", "LoopbackResult", "generate_sine",
    "UsbComposite", "ExpectedComposite", "assert_composite",
    "run_update_cycle", "run_revert_cycle", "UpdateResult",
    "BenchDriver", "STLinkBackend",
]
```

Update `README.md` with a short usage block showing `analyze_loopback` and `assert_composite` on synthetic data, and a note that live capture/flash wiring is Plan 2.

- [ ] **Step 4: Run the whole suite + lint**

Run: `ruff format --check . && ruff check . && pytest -v`
Expected: all PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/fw_hil/__init__.py README.md tests/test_smoke.py
git commit -m "feat: curate fw_hil public API + README quickstart"
```

---

## Done criteria for Plan 1

- `pip install -e .[dev]` on any host (no board) → `ruff check .` clean, `pytest -v` all green.
- CI workflow runs the same on GitHub-hosted runners (no self-hosted needed yet).
- `fw_hil` exposes audio-loopback analysis, USB-composite assertion, DFU orchestration, and the ST-Link backend — every piece unit-tested against synthetic data / fakes / argv assertions.
- Plan 2 (`2026-09-25-fw-hil-bench-bringup.md`) consumes this library and wires it to the real board.

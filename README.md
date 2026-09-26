# fw_hil — Hardware-in-the-Loop Verification Library

`fw_hil` is a host-testable Python library that implements all HIL verification logic for
OE5XRX STM32 firmware modules (starting with `fm_board`). It covers:

- **Audio loopback analysis**: generate reference tones, cross-correlate against captured
  UAC2 audio, detect dropouts, measure SNR — pure numpy, no audio hardware required.
- **USB composite assertion**: model the expected descriptor layout (VID/PID, CDC-ACM,
  UAC2 at 8 kHz/mono, DFU with alt-0) and verify it against an enumerated device.
- **DFU/MCUboot orchestration**: update-cycle and revert-cycle logic against an injected
  `DfuOps` backend — testable without a board.
- **Bench-driver interface**: `BenchDriver` ABC + `STLinkBackend` (pyocd argv builder,
  injection-testable).

Live capture, USB enumeration, and flashing wiring to real hardware are Plan 2
(`docs/superpowers/plans/2026-09-25-fw-hil-bench-bringup.md`).

See the design spec: `docs/superpowers/specs/2026-09-25-fw-hil-ci-gate-design.md`

## Install

```bash
pip install -e .[dev]
```

## Run tests & lint

```bash
pytest -v
ruff check .
ruff format --check .
```

## Quickstart

```python
import numpy as np
from fw_hil import generate_sine, analyze_loopback, ExpectedComposite, assert_composite

# Audio loopback analysis (synthetic example)
ref = generate_sine(1000.0, 0.5)
captured = np.concatenate([np.zeros(16, np.float32), ref])  # 16-sample delay
result = analyze_loopback(ref, captured)
print(result)  # LoopbackResult(ok=True, lag_samples=16, ...)

# USB composite check (against a model; real enumeration wired in Plan 2)
from fw_hil import UsbComposite, UsbInterface

device = UsbComposite(
    vid=0x2FE3,
    pid=0x0012,
    serial="OE5XRX-0001",
    interfaces=[
        UsbInterface(0x02, 0x02, 0x01),  # CDC-ACM
        UsbInterface(0x01, 0x01, 0x00),  # UAC2
        UsbInterface(0xFE, 0x01, 0x02, alt_settings=(0,)),  # DFU
    ],
    uac2_sample_rate_hz=8000,
    uac2_channels=1,
)
assert_composite(device, ExpectedComposite.fm_board())  # passes
```

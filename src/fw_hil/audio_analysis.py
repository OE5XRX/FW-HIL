# SPDX-License-Identifier: GPL-3.0-or-later
"""Audio-loopback signal analysis (numpy-only, no hardware)."""
from dataclasses import dataclass

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
    noise_p = float(np.mean(noise**2))
    if noise_p <= 0:
        return np.inf
    if sig_p <= 0:
        return -np.inf
    return 10.0 * np.log10(sig_p / noise_p)


def analyze_loopback(
    reference,
    captured,
    sample_rate=8000,
    min_correlation=0.9,
    max_dropout_fraction=0.01,
    min_snr_db=20.0,
):
    if captured.size == 0:
        return LoopbackResult(False, 0, 0.0, 0.0, 0, 1.0, -np.inf)
    lag, corr = find_lag(reference, captured, sample_rate)
    gaps = detect_dropouts(captured, sample_rate)
    dropped = sum(e - s for s, e in gaps)
    frac = dropped / captured.size
    snr = _snr_db(reference, captured, lag)
    ok = corr >= min_correlation and frac <= max_dropout_fraction and snr >= min_snr_db
    return LoopbackResult(ok, lag, lag_to_latency_s(lag, sample_rate), corr, len(gaps), frac, snr)

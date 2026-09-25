# SPDX-License-Identifier: GPL-3.0-or-later
import numpy as np

from fw_hil.audio_analysis import (
    LoopbackResult,
    analyze_loopback,
    detect_dropouts,
    find_lag,
    generate_sine,
    lag_to_latency_s,
)


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

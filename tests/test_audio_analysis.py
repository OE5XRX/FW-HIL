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

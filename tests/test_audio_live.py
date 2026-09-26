# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the pure parts + injected orchestration of the audio-loopback
bench backend.

The real ALSA I/O (aplay/arecord) and serial paths run on the bench; these cover
the CDC command / argv construction, the ``aplay -l`` device resolution, the
int16<->float conversion and the orchestration wired to *injected* play/capture/
serial fakes (no hardware, no numpy-import surprises).
"""

import numpy as np
import pytest

from fw_hil.audio_analysis import analyze_loopback, generate_sine
from fw_hil.audio_live import (
    LiveAudioLoopback,
    align_capture,
    float_to_s16le,
    parse_alsa_cards,
    resolve_alsa_device,
    s16le_to_float,
)

# ── ALSA `aplay -l` / `arecord -l` sample output ──────────────────────────────
_APLAY_L = """**** List of PLAYBACK Hardware Devices ****
card 0: PCH [HDA Intel PCH], device 0: ALC892 Analog [ALC892 Analog]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
card 2: Board [FM Board], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
"""


def test_parse_alsa_cards_extracts_entries():
    cards = parse_alsa_cards(_APLAY_L)
    assert len(cards) == 2
    fm = cards[1]
    assert fm["card_index"] == 2
    assert fm["card_id"] == "Board"
    assert fm["card_name"] == "FM Board"
    assert fm["device_index"] == 0


def test_resolve_alsa_device_matches_by_name_hint():
    # Robust: match the USB board by its card name, not a fixed hw:1,0.
    assert resolve_alsa_device(_APLAY_L, "fm board") == "hw:2,0"


def test_resolve_alsa_device_matches_by_card_id():
    assert resolve_alsa_device(_APLAY_L, "board") == "hw:2,0"


def test_resolve_alsa_device_raises_when_absent():
    with pytest.raises(RuntimeError):
        resolve_alsa_device(_APLAY_L, "nonexistent-card")


# ── int16 <-> float conversion ────────────────────────────────────────────────
def test_float_s16_roundtrip_preserves_signal():
    ref = generate_sine(1000.0, 0.05)
    raw = float_to_s16le(ref)
    assert isinstance(raw, (bytes, bytearray))
    assert len(raw) == ref.size * 2  # S16 = 2 bytes/sample
    back = s16le_to_float(raw)
    # quantisation error is bounded by 1 LSB / full-scale
    assert np.max(np.abs(back - ref)) < 1e-3


# ── capture-window alignment (Copilot: expected pre/post-roll silence) ────────
def test_align_capture_trims_pre_and_post_roll_silence():
    # A realistic capture: arecord brackets the tone with leading + trailing
    # silence. Scored raw, that silence reads as dropouts and fails a clean
    # board; aligned, it must score ok.
    ref = generate_sine(1000.0, 0.5)
    captured = np.concatenate(
        [
            np.zeros(1600, np.float32),  # ~0.2 s pre-roll (arecord before aplay)
            ref,
            np.zeros(4000, np.float32),  # ~0.5 s post-roll (arecord after aplay)
        ]
    )
    raw = analyze_loopback(ref, captured)
    assert raw.ok is False  # the bug Copilot flagged: silence counted as dropouts
    lag, aligned = align_capture(ref, captured)
    assert lag == 1600  # onset located = real latency, reported separately
    assert aligned.shape == ref.shape
    good = analyze_loopback(ref, aligned)
    assert good.ok is True
    assert good.dropout_count == 0


def test_align_capture_passes_through_when_no_signal():
    # All-silence capture -> no locatable tone -> returned unchanged so a real
    # failure still scores as a failure (not masked by trimming).
    ref = generate_sine(1000.0, 0.5)
    silent = np.zeros(ref.size, np.float32)
    lag, out = align_capture(ref, silent)
    assert lag is None
    assert analyze_loopback(ref, out).ok is False


def test_align_capture_rejects_out_of_bounds_lag():
    # A late onset that leaves no room for a full reference window must be
    # treated as unlocatable, not sliced into a short high-correlation overlap.
    ref = generate_sine(1000.0, 0.5)
    captured = np.concatenate([np.zeros(200, np.float32), ref])[: ref.size + 50]
    assert captured.size >= ref.size  # first guard doesn't apply
    lag, out = align_capture(ref, captured)
    assert lag is None
    assert out.size == captured.size  # unchanged, not truncated


# ── channel-count guard (Copilot: mono-only processing) ───────────────────────
def test_multichannel_is_rejected():
    with pytest.raises(ValueError, match="mono only"):
        LiveAudioLoopback(channels=2)


# ── CDC loopback command construction ─────────────────────────────────────────
def test_loopback_commands_default():
    lb = LiveAudioLoopback()
    assert lb.loopback_on_command() == "audio loopback on"
    assert lb.loopback_off_command() == "audio loopback off"


def test_loopback_commands_configurable():
    lb = LiveAudioLoopback(loopback_on_cmd="lb 1", loopback_off_cmd="lb 0")
    assert lb.loopback_on_command() == "lb 1"
    assert lb.loopback_off_command() == "lb 0"


# ── aplay / arecord argv construction ─────────────────────────────────────────
def test_aplay_cmd_builds_argv():
    lb = LiveAudioLoopback()
    cmd = lb.aplay_cmd("hw:2,0", "/tmp/ref.raw")
    assert cmd[0] == "aplay"
    assert "-D" in cmd and "hw:2,0" in cmd
    assert "S16_LE" in cmd
    assert "8000" in cmd  # sample rate
    i = cmd.index("-c")
    assert cmd[i + 1] == "1"  # mono
    assert cmd[-1] == "/tmp/ref.raw"


def test_arecord_cmd_includes_duration():
    lb = LiveAudioLoopback(sample_rate=8000, channels=1)
    cmd = lb.arecord_cmd("hw:2,0", "/tmp/cap.raw", duration_s=1.5)
    assert cmd[0] == "arecord"
    assert "hw:2,0" in cmd
    # duration is passed as a rounded-up integer seconds count for arecord -d
    assert cmd[cmd.index("-d") + 1] == "2"  # ceil(1.5) -> 2
    assert cmd[-1] == "/tmp/cap.raw"


def test_explicit_devices_skip_resolution():
    # Explicit hw:C,D overrides mean no aplay -l call is ever made.
    def boom(*a, **k):  # pragma: no cover - must not run
        raise AssertionError("resolution should not be invoked when device is explicit")

    lb = LiveAudioLoopback(playback_device="hw:9,0", capture_device="hw:9,0", run=boom)
    assert lb.resolve_playback_device() == "hw:9,0"
    assert lb.resolve_capture_device() == "hw:9,0"


# ── orchestration with injected fakes ─────────────────────────────────────────
class _Recorder:
    def __init__(self, capture_fn):
        self.commands = []
        self._capture_fn = capture_fn

    def send_command(self, cmd):
        self.commands.append(cmd)

    def play_capture(self, reference):
        return self._capture_fn(reference)


def test_run_loopback_success_synthetic():
    # A synthetic "good" loopback: reference returned delayed by 16 samples.
    def good_capture(reference):
        return np.concatenate([np.zeros(16, np.float32), reference])

    rec = _Recorder(good_capture)
    lb = LiveAudioLoopback(send_command=rec.send_command, play_capture=rec.play_capture, settle_s=0)
    result = lb.run_loopback()
    assert result.ok is True
    assert result.correlation > 0.99
    # the real playback->capture latency is preserved on the result even though
    # scoring runs on the trimmed (lag-reset) window
    assert result.lag_samples == 16
    assert result.latency_s == 16 / 8000
    # on before off, both sent
    assert rec.commands == ["audio loopback on", "audio loopback off"]


def test_run_loopback_failure_synthetic():
    # Silence captured -> analyze_loopback flags failure, ok is passed through.
    def silent_capture(reference):
        return np.zeros(reference.size, np.float32)

    rec = _Recorder(silent_capture)
    lb = LiveAudioLoopback(send_command=rec.send_command, play_capture=rec.play_capture, settle_s=0)
    result = lb.run_loopback()
    assert result.ok is False
    # loopback must still be turned off after a failed capture
    assert rec.commands == ["audio loopback on", "audio loopback off"]


def test_run_loopback_turns_off_even_on_capture_error():
    commands = []

    def failing_capture(reference):
        raise RuntimeError("arecord died")

    lb = LiveAudioLoopback(
        send_command=commands.append,
        play_capture=failing_capture,
        settle_s=0,
    )
    with pytest.raises(RuntimeError, match="arecord died"):
        lb.run_loopback()
    # off command must still have run despite the capture blowing up
    assert commands == ["audio loopback on", "audio loopback off"]


def test_run_loopback_uses_configured_tone_and_rate():
    seen = {}

    def capture(reference):
        seen["ref"] = reference
        return reference.copy()

    lb = LiveAudioLoopback(
        send_command=lambda c: None,
        play_capture=capture,
        settle_s=0,
        sample_rate=8000,
        tone_freq_hz=1200.0,
        tone_duration_s=0.25,
    )
    lb.run_loopback()
    # 0.25 s @ 8000 Hz -> 2000 samples handed to the player
    assert seen["ref"].shape == (2000,)
    assert seen["ref"].dtype == np.float32

# SPDX-License-Identifier: GPL-3.0-or-later
"""Bench-side ALSA audio-loopback backend for the fm_board HIL bench (Baustein 8.4b).

Drives an end-to-end UAC2 loopback check against the physical board:

1. enable the firmware loopback test-mode over the CDC shell,
2. play a reference tone on the board's UAC2 **playback** ALSA device while
   simultaneously recording from its UAC2 **capture** device,
3. score the recording against the reference with
   :func:`fw_hil.audio_analysis.analyze_loopback`,
4. disable the loopback test-mode again.

The firmware loopback test-mode (Baustein 8.4a) routes UAC2 OUT (host->device)
straight back to UAC2 IN (device->host) — no analog path, no PTT/TX. It does not
exist yet; this backend is built against the *assumed* host<->FW contract below
and keeps every contract detail configurable so a later change is cheap:

- activation via a CDC shell command over ``/dev/fm-board-cdc`` (pyserial);
  the command strings default to ``audio loopback on`` / ``audio loopback off``
  but are constructor parameters, not hardcoded;
- stream format 8000 Hz / 1 channel / 16-bit (``ExpectedComposite.fm_board()``).

Structure mirrors :mod:`fw_hil.usb_live` / :mod:`fw_hil.backends.live_dfu`: the
pure, host-testable logic (command/argv construction, ``aplay -l`` device
resolution, int16<->float conversion, orchestration with injected play/capture/
serial callables) is separated from the real ALSA/serial I/O, which is lazily
imported and injectable — so host CI runs this without ALSA, pyserial or a board.
"""

import math
import re
import subprocess
from dataclasses import replace

import numpy as np

from fw_hil.audio_analysis import (
    analyze_loopback,
    find_lag,
    generate_sine,
    lag_to_latency_s,
)

FM_BOARD_VID = 0x2FE3
FM_BOARD_PID = 0x0012

# `card 2: Board [FM Board], device 0: USB Audio [USB Audio]`
_ALSA_CARD_RE = re.compile(r"card (\d+): (\S+) \[([^\]]+)\], device (\d+): .+? \[([^\]]+)\]")


def parse_alsa_cards(listing: str) -> list:
    """Parse ``aplay -l`` / ``arecord -l`` output into card/device entries.

    Returns a list of dicts with ``card_index``, ``card_id``, ``card_name``,
    ``device_index`` and ``device_name`` — the fields needed to build a stable
    ``hw:CARD,DEVICE`` selector without hardcoding a card number.
    """
    entries = []
    for m in _ALSA_CARD_RE.finditer(listing or ""):
        entries.append(
            {
                "card_index": int(m.group(1)),
                "card_id": m.group(2),
                "card_name": m.group(3),
                "device_index": int(m.group(4)),
                "device_name": m.group(5),
            }
        )
    return entries


def resolve_alsa_device(listing: str, name_hint: str) -> str:
    """Return ``hw:CARD,DEVICE`` for the first card matching ``name_hint``.

    ``name_hint`` is matched case-insensitively against both the ALSA card id
    and the human card name, so the USB board is found by name rather than a
    brittle fixed ``hw:1,0``. Raises :class:`RuntimeError` if nothing matches.
    """
    hint = (name_hint or "").lower()
    for entry in parse_alsa_cards(listing):
        if hint in entry["card_id"].lower() or hint in entry["card_name"].lower():
            return f"hw:{entry['card_index']},{entry['device_index']}"
    raise RuntimeError(f"no ALSA card matching {name_hint!r} in:\n{listing}")


def float_to_s16le(samples) -> bytes:
    """Convert a float array in [-1, 1] to little-endian signed 16-bit PCM."""
    clipped = np.clip(np.asarray(samples, dtype=np.float64), -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()


def s16le_to_float(raw: bytes):
    """Convert little-endian signed 16-bit PCM bytes to a float32 array in [-1, 1)."""
    return (np.frombuffer(bytes(raw), dtype="<i2").astype(np.float32) / 32768.0).copy()


def align_capture(reference, captured, sample_rate=8000):
    """Locate the played tone in ``captured``; return ``(lag, window)``.

    ``arecord`` is started before ``aplay`` and stopped after it, so a real
    capture brackets the played tone with pre/post-roll silence. Handed straight
    to :func:`analyze_loopback`, that silence is scored as dropouts across the
    full buffer and even a clean board exceeds the dropout limit. We use the
    cross-correlation lag to slice out just the played window before scoring.

    ``lag`` is the samples from capture start to the tone onset — i.e. the real
    playback->capture latency — and is meant to be reported on the result even
    though scoring runs on the trimmed ``window``. Returns ``(None, captured)``
    (capture unchanged) when the tone can't be confidently located: a capture
    shorter than the reference, a negative lag, or a lag so late that a full
    reference-length window won't fit (which would otherwise let a cut-off tone
    score on a short, misleadingly high-correlation overlap). Leaving it
    untrimmed keeps a genuine failure scoring as a failure.
    """
    captured = np.asarray(captured)
    if captured.size < reference.size:
        return None, captured
    lag, _corr = find_lag(reference, captured, sample_rate)
    if lag < 0 or lag + reference.size > captured.size:
        return None, captured
    return lag, captured[lag : lag + reference.size]


class LiveAudioLoopback:
    """Orchestrate a UAC2 loopback check against the physical fm_board.

    The serial send and the duplex play+capture are injectable (``send_command``
    / ``play_capture``); when not injected they are built lazily from pyserial
    and ``aplay``/``arecord`` on first use, so importing and unit-testing this
    class needs neither hardware nor those extras.
    """

    def __init__(
        self,
        *,
        cdc_path: str = "/dev/fm-board-cdc",
        card_hint: str = "FM Board",
        playback_device: "str | None" = None,
        capture_device: "str | None" = None,
        sample_rate: int = 8000,
        channels: int = 1,
        loopback_on_cmd: str = "audio loopback on",
        loopback_off_cmd: str = "audio loopback off",
        tone_freq_hz: float = 1000.0,
        tone_duration_s: float = 1.0,
        tone_amplitude: float = 0.5,
        aplay: str = "aplay",
        arecord: str = "arecord",
        settle_s: float = 0.5,
        baudrate: int = 115200,
        run=subprocess.run,
        send_command=None,
        play_capture=None,
    ):
        # The fm_board UAC2 stream is mono (ExpectedComposite.fm_board()), and the
        # reference/capture path here is single-channel end to end: generate_sine
        # yields a 1-D array and s16le_to_float returns interleaved samples as-is.
        # Multichannel would need interleave/deinterleave that isn't built, so we
        # reject it up front rather than silently mis-scoring a stereo buffer.
        if channels != 1:
            raise ValueError(
                f"channels={channels} unsupported: the loopback path is mono only "
                "(interleave/deinterleave is not implemented)"
            )
        self.cdc_path = cdc_path
        self.card_hint = card_hint
        self._playback_device = playback_device
        self._capture_device = capture_device
        self.sample_rate = sample_rate
        self.channels = channels
        self.loopback_on_cmd = loopback_on_cmd
        self.loopback_off_cmd = loopback_off_cmd
        self.tone_freq_hz = tone_freq_hz
        self.tone_duration_s = tone_duration_s
        self.tone_amplitude = tone_amplitude
        self.aplay = aplay
        self.arecord = arecord
        self.settle_s = settle_s
        self.baudrate = baudrate
        self._run = run
        self._send_command = send_command
        self._play_capture = play_capture

    # ── CDC command builders (pure; unit-tested) ─────────────────────────────
    def loopback_on_command(self) -> str:
        return self.loopback_on_cmd

    def loopback_off_command(self) -> str:
        return self.loopback_off_cmd

    # ── ALSA argv builders (pure; unit-tested) ───────────────────────────────
    def aplay_cmd(self, device: str, raw_path: str) -> list:
        return [
            self.aplay,
            "-D",
            device,
            "-t",
            "raw",
            "-f",
            "S16_LE",
            "-r",
            str(self.sample_rate),
            "-c",
            str(self.channels),
            raw_path,
        ]

    def arecord_cmd(self, device: str, raw_path: str, duration_s: float) -> list:
        # arecord -d takes whole seconds; round up so the capture window always
        # covers the full reference tone plus loopback latency.
        return [
            self.arecord,
            "-D",
            device,
            "-t",
            "raw",
            "-f",
            "S16_LE",
            "-r",
            str(self.sample_rate),
            "-c",
            str(self.channels),
            "-d",
            str(math.ceil(duration_s)),
            raw_path,
        ]

    # ── device resolution (pure logic; live listing is HW-only) ──────────────
    def resolve_playback_device(self) -> str:
        return self._playback_device or resolve_alsa_device(
            self._list_alsa(self.aplay), self.card_hint
        )

    def resolve_capture_device(self) -> str:
        return self._capture_device or resolve_alsa_device(
            self._list_alsa(self.arecord), self.card_hint
        )

    def _list_alsa(self, tool: str) -> str:
        # HW-only: shell out to `aplay -l` / `arecord -l`; not exercised in CI.
        proc = self._run([tool, "-l"], check=True, capture_output=True, text=True)
        return proc.stdout

    # ── orchestration (pure control flow; deps injected/lazy) ────────────────
    def run_loopback(self):
        """Run one loopback measurement and return a ``LoopbackResult``.

        Enables the firmware loopback, plays the reference tone while recording,
        analyses the recording, and — always, even if capture raises — disables
        the loopback again before returning or propagating.
        """
        reference = generate_sine(
            self.tone_freq_hz,
            self.tone_duration_s,
            sample_rate=self.sample_rate,
            amplitude=self.tone_amplitude,
        )
        send = self._send_command or self._serial_send
        play_capture = self._play_capture or self._alsa_play_capture

        send(self.loopback_on_command())
        try:
            if self.settle_s:
                self._sleep(self.settle_s)
            captured = play_capture(reference)
        finally:
            send(self.loopback_off_command())
        # Score dropouts/SNR/correlation on the trimmed window (pre/post-roll
        # silence removed), but report the *original* capture lag as the real
        # playback->capture latency — trimming resets the window's own lag to ~0.
        lag, aligned = align_capture(reference, captured, sample_rate=self.sample_rate)
        result = analyze_loopback(reference, aligned, sample_rate=self.sample_rate)
        if lag is not None:
            result = replace(
                result,
                lag_samples=lag,
                latency_s=lag_to_latency_s(lag, self.sample_rate),
            )
        return result

    # ── real hardware I/O (lazy import; injectable; not run in host CI) ───────
    def _sleep(self, seconds: float) -> None:
        import time

        time.sleep(seconds)

    def _serial_send(self, command: str) -> None:
        import serial

        with serial.Serial(self.cdc_path, self.baudrate, timeout=1) as s:
            self._sleep(0.2)
            s.reset_input_buffer()
            s.write(command.encode() + b"\r\n")
            self._sleep(0.2)

    def _alsa_play_capture(self, reference):
        """Play ``reference`` while recording the loopback; return captured floats.

        Starts ``arecord`` first, then ``aplay``, so recording is already live
        when playback begins. Uses temp raw S16_LE files and the argv builders
        above; ALSA/subprocess-only, never exercised in host CI.
        """
        import tempfile

        playback = self.resolve_playback_device()
        capture = self.resolve_capture_device()
        # Record a touch longer than playback to absorb loopback latency.
        capture_s = self.tone_duration_s + max(self.settle_s, 0.5)
        with tempfile.TemporaryDirectory() as tmp:
            ref_path = f"{tmp}/ref.raw"
            cap_path = f"{tmp}/cap.raw"
            with open(ref_path, "wb") as fh:
                fh.write(float_to_s16le(reference))
            rec = subprocess.Popen(self.arecord_cmd(capture, cap_path, capture_s))
            try:
                self._sleep(0.2)  # let arecord open the device before we play
                self._run(self.aplay_cmd(playback, ref_path), check=True)
            finally:
                rc = rec.wait()
            # Don't score a capture that never happened: a non-zero arecord exit
            # means the recording failed (device busy, wrong format, …) and
            # cap_path is empty/garbage, so surface it instead of a bogus result.
            if rc != 0:
                raise RuntimeError(f"arecord exited with status {rc}")
            with open(cap_path, "rb") as fh:
                return s16le_to_float(fh.read())

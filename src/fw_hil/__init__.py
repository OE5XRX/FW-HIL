# SPDX-License-Identifier: GPL-3.0-or-later
"""Hardware-in-the-loop verification library for OE5XRX STM32 firmware."""

from fw_hil.audio_analysis import LoopbackResult, analyze_loopback, generate_sine
from fw_hil.backends.stlink import STLinkBackend
from fw_hil.dfu import UpdateResult, run_revert_cycle, run_update_cycle
from fw_hil.driver import BenchDriver
from fw_hil.usb_descriptors import ExpectedComposite, UsbComposite, assert_composite

__version__ = "0.1.0"

__all__ = [
    "analyze_loopback",
    "LoopbackResult",
    "generate_sine",
    "UsbComposite",
    "ExpectedComposite",
    "assert_composite",
    "run_update_cycle",
    "run_revert_cycle",
    "UpdateResult",
    "BenchDriver",
    "STLinkBackend",
]

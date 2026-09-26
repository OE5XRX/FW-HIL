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
        return cls(
            vid=0x2FE3,
            pid=0x0012,
            require_serial=True,
            uac2_sample_rate_hz=8000,
            uac2_channels=1,
            dfu_alt_settings=(0,),
        )


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
            msgs.append(
                f"DFU alt settings {tuple(dfu.alt_settings)} != {tuple(expected.dfu_alt_settings)}"
            )

    if not actual.has_class(CLASS_UAC2):
        msgs.append("UAC2 interface missing")
    else:
        if actual.uac2_sample_rate_hz != expected.uac2_sample_rate_hz:
            msgs.append(
                f"UAC2 sample rate {actual.uac2_sample_rate_hz} != {expected.uac2_sample_rate_hz}"
            )
        if actual.uac2_channels != expected.uac2_channels:
            msgs.append(f"UAC2 channels {actual.uac2_channels} != {expected.uac2_channels}")
    return msgs


def assert_composite(actual, expected):
    msgs = check_composite(actual, expected)
    if msgs:
        raise AssertionError("USB composite mismatch:\n  " + "\n  ".join(msgs))

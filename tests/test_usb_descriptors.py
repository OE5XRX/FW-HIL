# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

from fw_hil.usb_descriptors import (
    ExpectedComposite,
    UsbComposite,
    UsbInterface,
    assert_composite,
    check_composite,
)

CDC, UAC2, DFU = 0x02, 0x01, 0xFE


def _good():
    return UsbComposite(
        vid=0x2FE3,
        pid=0x0012,
        serial="OE5XRX-0001",
        interfaces=[
            UsbInterface(CDC, 0x02, 0x01),
            UsbInterface(UAC2, 0x01, 0x00),
            UsbInterface(DFU, 0x01, 0x02, alt_settings=(0,)),
        ],
        uac2_sample_rate_hz=8000,
        uac2_channels=1,
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

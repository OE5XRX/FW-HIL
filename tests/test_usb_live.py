# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the pure descriptor-parsing helpers in usb_live.

The hardware paths (read_composite / _read_sample_rate) need pyusb + a board and
are exercised on the bench; these tests cover the byte-level parsing that would
otherwise only be validated against hardware.
"""

from fw_hil.usb_live import (
    split_class_specific,
    uac2_channels,
    uac2_clock_id,
)

# UAC2 AS_GENERAL: 16 bytes, bNrChannels at offset 10
_AS_GENERAL_1CH = bytes([0x10, 0x24, 0x01, 0x02, 0x00, 0x01, 0x01, 0, 0, 0, 1, 0, 0, 0, 0, 0])
_AS_GENERAL_2CH = bytes([0x10, 0x24, 0x01, 0x02, 0x00, 0x01, 0x01, 0, 0, 0, 2, 0, 0, 0, 0, 0])
# UAC2 Type I FORMAT_TYPE: 6 bytes, bBitResolution at offset 5
_FORMAT_TYPE_16 = bytes([0x06, 0x24, 0x02, 0x01, 0x02, 0x10])
# UAC2 CLOCK_SOURCE: 8 bytes, bClockID at offset 3
_CLOCK_SOURCE_ID1 = bytes([0x08, 0x24, 0x0A, 0x01, 0x07, 0x07, 0x00, 0x00])


def test_split_class_specific_splits_concatenated_descriptors():
    blob = _AS_GENERAL_1CH + _FORMAT_TYPE_16
    descs = split_class_specific(blob)
    assert len(descs) == 2
    assert descs[0] == _AS_GENERAL_1CH
    assert descs[1] == _FORMAT_TYPE_16


def test_split_class_specific_stops_on_zero_length():
    # a stray zero-length byte must terminate, not loop forever
    assert split_class_specific(_AS_GENERAL_1CH + b"\x00\x24") == [_AS_GENERAL_1CH]


def test_split_class_specific_empty():
    assert split_class_specific(b"") == []
    assert split_class_specific(None) == []


def test_uac2_channels_reads_bnrchannels():
    assert uac2_channels(split_class_specific(_AS_GENERAL_1CH + _FORMAT_TYPE_16)) == 1
    assert uac2_channels([_AS_GENERAL_2CH]) == 2


def test_uac2_channels_none_when_absent():
    # only a FORMAT_TYPE present, no AS_GENERAL -> unknown
    assert uac2_channels([_FORMAT_TYPE_16]) is None


def test_uac2_clock_id_reads_bclockid():
    assert uac2_clock_id([_CLOCK_SOURCE_ID1, _AS_GENERAL_1CH]) == 1


def test_uac2_clock_id_none_when_absent():
    assert uac2_clock_id([_AS_GENERAL_1CH, _FORMAT_TYPE_16]) is None

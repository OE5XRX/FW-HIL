# SPDX-License-Identifier: GPL-3.0-or-later
"""Read a live USB composite from a connected board into a ``UsbComposite``.

Hardware-only: ``pyusb`` is an optional dependency (install extra ``hw``) and is
imported lazily, so the pure descriptor-parsing helpers in this module stay
importable and unit-testable without pyusb or a board attached.

Baustein 3 (USB enumeration): feed the result into
``fw_hil.usb_descriptors.assert_composite(comp, ExpectedComposite.fm_board())``.
"""

from fw_hil.usb_descriptors import (
    ExpectedComposite,
    UsbComposite,
    UsbInterface,
    assert_composite,
)

# USB Audio Class 2 descriptor constants
CS_INTERFACE = 0x24
UAC2_AS_GENERAL = 0x01
UAC2_CLOCK_SOURCE = 0x0A
AUDIO_SUBCLASS_CONTROL = 0x01
AUDIO_SUBCLASS_STREAMING = 0x02
CLASS_AUDIO = 0x01

# UAC2 clock GET_CUR (Sampling Frequency Control) control-transfer parameters
_GET_CUR = 0x01
_CS_SAM_FREQ_CONTROL = 0x01
_CTRL_IN_CLASS_INTERFACE = 0xA1

FM_BOARD_VID = 0x2FE3
FM_BOARD_PID = 0x0012


def split_class_specific(extra: bytes) -> list:
    """Split a USB ``extra_descriptors`` blob into its TLV descriptors.

    Each descriptor starts with a length byte; a zero length terminates.
    """
    out = []
    i = 0
    extra = bytes(extra or b"")
    while i < len(extra):
        length = extra[i]
        if length == 0:
            break
        out.append(extra[i : i + length])
        i += length
    return out


def uac2_channels(cs_descriptors) -> "int | None":
    """Return ``bNrChannels`` from a UAC2 AS_GENERAL class-specific descriptor.

    AS_GENERAL (UAC2) is 16 bytes; ``bNrChannels`` is at offset 10.
    """
    for cd in cs_descriptors:
        if len(cd) >= 16 and cd[1] == CS_INTERFACE and cd[2] == UAC2_AS_GENERAL:
            return cd[10]
    return None


def uac2_clock_id(cs_descriptors) -> "int | None":
    """Return ``bClockID`` from a UAC2 CLOCK_SOURCE class-specific descriptor."""
    for cd in cs_descriptors:
        if len(cd) >= 8 and cd[1] == CS_INTERFACE and cd[2] == UAC2_CLOCK_SOURCE:
            return cd[3]
    return None


def _read_sample_rate(dev, clock_id, ac_interface) -> "int | None":
    """Best-effort UAC2 sampling-frequency GET_CUR (4-byte LE Hz).

    Detaches the kernel driver on the AudioControl interface for the read and
    always reattaches. Returns ``None`` if the clock can't be read (e.g. the
    interface is claimed and the driver can't be detached without privilege).
    """
    import usb.util

    if clock_id is None or ac_interface is None:
        return None
    reattach = False
    try:
        if dev.is_kernel_driver_active(ac_interface):
            dev.detach_kernel_driver(ac_interface)
            reattach = True
        ret = dev.ctrl_transfer(
            _CTRL_IN_CLASS_INTERFACE,
            _GET_CUR,
            _CS_SAM_FREQ_CONTROL << 8,
            (clock_id << 8) | ac_interface,
            4,
        )
        return int.from_bytes(bytes(ret), "little")
    except Exception:
        return None
    finally:
        usb.util.dispose_resources(dev)
        if reattach:
            try:
                dev.attach_kernel_driver(ac_interface)
            except Exception:
                pass


def read_composite(vid: int, pid: int, serial: "str | None" = None) -> UsbComposite:
    """Enumerate a connected device and build a :class:`UsbComposite`.

    Reads VID/PID/iSerial, per-interface class/subclass/protocol and alternate
    settings, and the UAC2 channel count and current sample rate. Requires
    pyusb (extra ``hw``) and access to the USB device node.
    """
    import usb.core
    import usb.util

    kwargs = {"idVendor": vid, "idProduct": pid}
    if serial is not None:
        kwargs["serial_number"] = serial
    dev = usb.core.find(**kwargs)
    if dev is None:
        raise RuntimeError(f"USB device {vid:#06x}:{pid:#06x} not found")

    iserial = usb.util.get_string(dev, dev.iSerialNumber) if dev.iSerialNumber else None
    cfg = dev.get_active_configuration()

    by_number = {}
    for intf in cfg:
        by_number.setdefault(intf.bInterfaceNumber, []).append(intf)

    all_cs = []
    interfaces = []
    for _num, alts in sorted(by_number.items()):
        first = alts[0]
        interfaces.append(
            UsbInterface(
                first.bInterfaceClass,
                first.bInterfaceSubClass,
                first.bInterfaceProtocol,
                alt_settings=tuple(sorted(i.bAlternateSetting for i in alts)),
            )
        )
        for intf in alts:
            all_cs.extend(split_class_specific(intf.extra_descriptors))

    channels = uac2_channels(all_cs)
    clock_id = uac2_clock_id(all_cs)
    ac_interface = next(
        (
            i.bInterfaceNumber
            for i in cfg
            if i.bInterfaceClass == CLASS_AUDIO and i.bInterfaceSubClass == AUDIO_SUBCLASS_CONTROL
        ),
        None,
    )
    sample_rate = _read_sample_rate(dev, clock_id, ac_interface)

    return UsbComposite(
        vid=dev.idVendor,
        pid=dev.idProduct,
        serial=iserial,
        interfaces=interfaces,
        uac2_sample_rate_hz=sample_rate,
        uac2_channels=channels,
    )


def assert_fm_board(serial: "str | None" = None) -> UsbComposite:
    """Read the connected fm_board and assert it matches the expected composite."""
    comp = read_composite(FM_BOARD_VID, FM_BOARD_PID, serial)
    assert_composite(comp, ExpectedComposite.fm_board())
    return comp

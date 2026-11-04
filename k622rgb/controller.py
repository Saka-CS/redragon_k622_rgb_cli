"""Device discovery and HID report-descriptor handling for the Redragon K622.

The keyboard exposes two HID interfaces; the vendor control interface is IF1
(``bInterfaceNumber = 01``). Its report descriptor declares only these reports:

    report 1  input    1 byte
    report 2  input    2 bytes
    report 3  input    3 bytes
    report 4  input   15 bytes
    report 5  feature  5 bytes
    report 6  feature  1031 bytes
    report 7  input    7 bytes

There is **no** feature report 0x08 on this board. Earlier revisions of this
project sent one; that request timed out because the kernel/device do not know
it.

Reads use ``HIDIOCGFEATURE``. The vendor configuration is read through
report ``0x05`` mailbox commands (the same handshake used by the official
software). Writes are limited to the exact report-0x06 shapes captured from
the official K622 software: ``09 cc`` per-key frames, ``03 c6`` config
blocks, ``08 c8`` effect palettes, and the two custom frames. Every write is
validated before it reaches the kernel; there is no generic "send arbitrary
feature report" entry point.
"""

import errno
import fcntl
import glob
import hashlib
import os
import time
from collections import namedtuple
from functools import lru_cache
from typing import Dict, List, Mapping, Optional, Tuple

VENDOR_ID = 0x258A
PRODUCT_ID = 0x0049
CONTROL_INTERFACE = "01"
HID_ID_TOKEN = "HID_ID=0003:0000258A:00000049"

NUM_SLOTS = 126

#: The IF1 report descriptor captured from the physical K622. Any descriptor
#: that does not match this hash must be reviewed before it is trusted.
K622_DESCRIPTOR_SIZE = 227
K622_DESCRIPTOR_SHA256 = (
    "32771137a995e90b6fa9d210761c23ce61e60a21accd033b86f484f198a5061c"
)

#: Feature reports this tool is allowed to read. The descriptor must agree with
#: these sizes; anything else is refused rather than guessed.
ALLOWED_FEATURE_REPORTS = {0x05: 5, 0x06: 1031}

#: Lighting frames captured from the official software. The report is 1032
#: bytes including the report ID; the three 126-byte planes start at these
#: offsets and cover slots 0..125 in R, G, B order.
COLOR_REPORT_ID = 0x06
COLOR_TEMPLATE_FILE = "template_color.bin"
COLOR_TEMPLATE_SIZE = 1032
COLOR_TEMPLATE_SHA256 = (
    "5d922916bdeadf7bfc3676a00855b8c0b9e05562e083d344d67dd58c73e4626a"
)
COLOR_PACKET_HEADER = bytes.fromhex("06 09 cc 00 40 00 00 00")
COLOR_PLANE_BASES = (8, 134, 260)  # R, G, B
COLOR_REGION_START = COLOR_PLANE_BASES[0]
COLOR_REGION_END = COLOR_PLANE_BASES[-1] + NUM_SLOTS
PACKET_SIZE = COLOR_TEMPLATE_SIZE

_HIDIOCGFEATURE_NR = 0x07
_HIDIOCSFEATURE_NR = 0x06
_MAX_INTERFACE_WALK = 6

_REPORT_KIND_ORDER = {"input": 0, "output": 1, "feature": 2}
_MAIN_REPORT_KINDS = {0x8: "input", 0x9: "output", 0xB: "feature"}

Color = Tuple[int, int, int]

DeviceInfo = namedtuple("DeviceInfo", "node sysfs interface hid_id")
ReportInfo = namedtuple("ReportInfo", "report_id kind size")


class DeviceError(RuntimeError):
    """Any device/protocol problem, with an actionable message."""


class DeviceNotFound(DeviceError):
    """No K622 control interface was found."""


class MultipleDevices(DeviceError):
    """More than one candidate control interface; the user must pick one."""


class PermissionDenied(DeviceError):
    """The hidraw node cannot be opened by this user."""


class ProtocolError(DeviceError):
    """The descriptor or the keyboard did not match the known protocol."""


def permission_hint(node: str) -> str:
    """Actionable fixes for a root-only hidraw node."""
    return (
        "Cannot open %s: permission denied.\n"
        "Fix (pick one):\n"
        "  1. install the udev rule, then replug the keyboard:\n"
        "       sudo cp udev/60-k622rgb.rules /etc/udev/rules.d/\n"
        "       sudo udevadm control --reload-rules\n"
        "       sudo udevadm trigger --subsystem-match=hidraw\n"
        "  2. temporary, resets on replug:\n"
        "       sudo chmod 666 %s\n"
        "  3. run this command once as root:\n"
        "       sudo ./bin/k622rgb ..." % (node, node)
    )


def hidiocgfeature(length: int) -> int:
    """ioctl request number for HIDIOCGFEATURE(length).

    ``_IOC(READ|WRITE, 'H', 0x07, length)``; 1032 bytes gives 0xC4084807.
    """
    if isinstance(length, bool) or not isinstance(length, int):
        raise ValueError("invalid HIDIOCGFEATURE length: %r" % (length,))
    if not 1 <= length <= 0x3FFF:
        raise ValueError("invalid HIDIOCGFEATURE length: %r" % (length,))
    return (3 << 30) | (length << 16) | (ord("H") << 8) | _HIDIOCGFEATURE_NR


def hidiocsfeature(length: int) -> int:
    """ioctl request number for HIDIOCSFEATURE(length).

    ``_IOC(READ|WRITE, 'H', 0x06, length)``; 1032 bytes gives 0xC4084806.
    """
    if isinstance(length, bool) or not isinstance(length, int):
        raise ValueError("invalid HIDIOCSFEATURE length: %r" % (length,))
    if not 1 <= length <= 0x3FFF:
        raise ValueError("invalid HIDIOCSFEATURE length: %r" % (length,))
    return (3 << 30) | (length << 16) | (ord("H") << 8) | _HIDIOCSFEATURE_NR


# --------------------------------------------------------------------------
# HID report-descriptor parsing
# --------------------------------------------------------------------------


def parse_report_descriptor(data: bytes) -> List[ReportInfo]:
    """Parse a HID report descriptor into the reports it declares.

    Only the global items needed to size reports are tracked (Report ID, Report
    Size, Report Count). Multiple main items sharing one report ID accumulate,
    which is how the K622's 1-byte report 1 and 7-byte report 7 are built.
    """
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("descriptor must be bytes-like")
    data = bytes(data)

    bits = {}
    report_id = 0
    report_size = 0
    report_count = 0

    index = 0
    while index < len(data):
        prefix = data[index]
        index += 1

        if prefix == 0xFE:  # long item: FE, data size, long-item tag, data
            if index + 1 > len(data):
                raise ValueError("truncated long HID item at byte %d" % (index - 1))
            data_size = data[index]
            index += 1
            if index + 1 + data_size > len(data):
                raise ValueError("truncated long HID item at byte %d" % (index - 1))
            index += 1 + data_size
            continue

        size = prefix & 0x03
        if size == 3:
            size = 4
        item_type = (prefix >> 2) & 0x03
        tag = prefix >> 4

        if index + size > len(data):
            raise ValueError("truncated HID item at byte %d" % (index - 1))
        value = int.from_bytes(data[index : index + size], "little")
        index += size

        if item_type == 0:  # main item
            kind = _MAIN_REPORT_KINDS.get(tag)
            if kind is not None:
                key = (report_id, kind)
                bits[key] = bits.get(key, 0) + report_size * report_count
        elif item_type == 1:  # global item
            if tag == 0x07:  # Report Size
                report_size = value
            elif tag == 0x08:  # Report ID
                report_id = value
            elif tag == 0x09:  # Report Count
                report_count = value

    return [
        ReportInfo(rid, kind, (count + 7) // 8)
        for (rid, kind), count in sorted(
            bits.items(), key=lambda item: (item[0][0], _REPORT_KIND_ORDER[item[0][1]])
        )
    ]


def descriptor_sha256(data: bytes) -> str:
    return hashlib.sha256(bytes(data)).hexdigest()


def is_known_descriptor(data: bytes) -> bool:
    """True when the bytes are the captured K622 IF1 descriptor."""
    return (
        len(data) == K622_DESCRIPTOR_SIZE
        and descriptor_sha256(data) == K622_DESCRIPTOR_SHA256
    )


def find_feature_report(reports: List[ReportInfo], report_id: int) -> ReportInfo:
    for report in reports:
        if report.report_id == report_id and report.kind == "feature":
            return report
    raise ProtocolError(
        "Report 0x%02X is not declared as a feature report by this descriptor. "
        "Only declared reports may be used; do not guess report IDs." % report_id
    )


def feature_report_size(reports: List[ReportInfo], report_id: int) -> int:
    """Return the declared size, refusing reports outside the allowlist."""
    if report_id not in ALLOWED_FEATURE_REPORTS:
        raise ProtocolError(
            "Report 0x%02X is outside the allowlist (%s). Refusing to touch it."
            % (
                report_id,
                ", ".join("0x%02X" % rid for rid in sorted(ALLOWED_FEATURE_REPORTS)),
            )
        )
    report = find_feature_report(reports, report_id)
    expected = ALLOWED_FEATURE_REPORTS[report_id]
    if report.size != expected:
        raise ProtocolError(
            "Report 0x%02X is declared as %d bytes, but the captured K622 "
            "descriptor says %d. Refusing to guess."
            % (report_id, report.size, expected)
        )
    return report.size


# --------------------------------------------------------------------------
# sysfs discovery
# --------------------------------------------------------------------------


def _read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return None


def interface_number(sysfs_dir: str, levels: int = _MAX_INTERFACE_WALK) -> Optional[str]:
    """Walk up from a hidraw sysfs dir to its USB interface's bInterfaceNumber."""
    path = os.path.realpath(os.path.join(sysfs_dir, "device"))
    for _ in range(levels):
        value = _read_text(os.path.join(path, "bInterfaceNumber"))
        if value is not None:
            return value.strip()
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return None


def iter_devices(
    sysfs_root: str = "/sys", dev_root: str = "/dev"
) -> List[DeviceInfo]:
    """Return every hidraw node whose HID id matches the K622 (IF0 and IF1)."""
    found = []
    pattern = os.path.join(sysfs_root, "class", "hidraw", "hidraw*")
    for sysfs in sorted(glob.glob(pattern)):
        uevent = _read_text(os.path.join(sysfs, "device", "uevent"))
        if uevent is None:
            continue
        if HID_ID_TOKEN not in uevent.upper():
            continue
        found.append(
            DeviceInfo(
                node=os.path.join(dev_root, os.path.basename(sysfs)),
                sysfs=sysfs,
                interface=interface_number(sysfs),
                hid_id=HID_ID_TOKEN.split("=", 1)[1],
            )
        )
    return found


def find_device(sysfs_root: str = "/sys", dev_root: str = "/dev") -> str:
    """Return the /dev/hidrawN path of the keyboard's control interface (IF1)."""
    candidates = iter_devices(sysfs_root, dev_root)
    if not candidates:
        raise DeviceNotFound(
            "No Redragon K622 found (USB %04x:%04x). Plug it in and check `lsusb -d %04x:%04x`."
            % (VENDOR_ID, PRODUCT_ID, VENDOR_ID, PRODUCT_ID)
        )

    control = [info for info in candidates if info.interface == CONTROL_INTERFACE]
    if len(control) == 1:
        return control[0].node
    if len(control) > 1:
        nodes = ", ".join(info.node for info in control)
        raise MultipleDevices(
            "Multiple K622 control interfaces found (%s); pick one with --device." % nodes
        )

    # Interface number can be unreadable on unusual kernels; accept a single
    # candidate in that case, but never guess between several.
    unknown = [info for info in candidates if info.interface is None]
    if len(candidates) == 1 and unknown:
        return unknown[0].node

    interfaces = ", ".join(
        "%s(IF %s)" % (info.node, info.interface if info.interface is not None else "?")
        for info in candidates
    )
    raise DeviceNotFound(
        "Found %04x:%04x but no control interface 01: %s. Replug the keyboard; "
        "use --device to override." % (VENDOR_ID, PRODUCT_ID, interfaces)
    )


def sysfs_dir_for_node(node: str, sysfs_root: str = "/sys") -> str:
    return os.path.join(sysfs_root, "class", "hidraw", os.path.basename(node))


def descriptor_path(sysfs_dir: str) -> str:
    return os.path.join(sysfs_dir, "device", "report_descriptor")


def load_descriptor(sysfs_dir: str) -> bytes:
    """Read the raw report descriptor for a hidraw sysfs directory."""
    path = descriptor_path(sysfs_dir)
    try:
        with open(path, "rb") as handle:
            data = handle.read(4096)
    except OSError as exc:
        raise DeviceError(
            "Cannot read the HID report descriptor at %s: %s"
            % (path, exc.strerror or exc)
        ) from exc
    if not data:
        raise DeviceError("The HID report descriptor at %s is empty." % path)
    return data


# --------------------------------------------------------------------------
# hidraw access (read-only)
# --------------------------------------------------------------------------


def _map_open_error(node: str, exc: OSError) -> DeviceError:
    if exc.errno in (errno.EACCES, errno.EPERM):
        return PermissionDenied(permission_hint(node))
    if exc.errno in (errno.ENOENT, errno.ENODEV, errno.ENXIO):
        return DeviceNotFound(
            "Cannot open %s: device not present. Replug the keyboard and retry." % node
        )
    if exc.errno == errno.EBUSY:
        return DeviceError(
            "Cannot open %s: device is busy (another program owns it)." % node
        )
    return DeviceError("Cannot open %s: %s" % (node, exc.strerror or exc))


def open_device(node: str, writable: bool = False) -> int:
    """Open a hidraw node read-only (default) or read/write, mapping errno."""
    if not isinstance(node, str) or not node:
        raise ValueError("device node must be a path, e.g. /dev/hidraw6")
    try:
        return os.open(node, os.O_RDWR if writable else os.O_RDONLY)
    except OSError as exc:
        raise _map_open_error(node, exc) from exc


def _map_read_error(report_id: int, exc: OSError) -> DeviceError:
    label = "feature report 0x%02X" % report_id
    if exc.errno in (errno.EACCES, errno.EPERM):
        return PermissionDenied(
            "Permission denied while reading %s: %s" % (label, exc.strerror or exc)
        )
    if exc.errno == errno.EINVAL:
        return ProtocolError(
            "The kernel or the keyboard rejected a read of %s (EINVAL). Only "
            "reports declared in the descriptor may be read; do not guess "
            "report IDs." % label
        )
    if exc.errno in (errno.EPIPE, errno.ESHUTDOWN, errno.ECONNRESET):
        return ProtocolError(
            "The keyboard stalled or dropped the read of %s (%s). It may have "
            "been unplugged; replug it and retry."
            % (label, errno.errorcode.get(exc.errno, exc.errno))
        )
    if exc.errno in (errno.ENODEV, errno.ENXIO, errno.ENOENT):
        return DeviceError(
            "Device disconnected while reading %s; replug it." % label
        )
    if exc.errno == errno.ETIMEDOUT:
        return ProtocolError(
            "Timed out waiting for %s. Replug the keyboard, then retry once." % label
        )
    if exc.errno == errno.EBUSY:
        return DeviceError("The device is busy (another program is using it).")
    if exc.errno == errno.ENOTTY:
        return DeviceError(
            "%s does not look like a hidraw device (ENOTTY)." % label
        )
    return ProtocolError("Failed to read %s: %s" % (label, exc))


def read_feature(fd: int, report_id: int, size: int) -> bytes:
    """Read one feature report with ``HIDIOCGFEATURE``.

    ``size`` is the payload size declared by the descriptor, excluding the
    report ID. The returned bytes are the kernel's full response: report ID in
    byte 0 followed by ``size`` payload bytes, total ``size + 1``.
    """
    if isinstance(report_id, bool) or not isinstance(report_id, int):
        raise ValueError("report ID must be an integer, got %r" % (report_id,))
    if not 0x01 <= report_id <= 0xFF:
        raise ValueError("report ID must be 0x01-0xFF, got %r" % (report_id,))
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise ValueError("report size must be a positive integer, got %r" % (size,))

    length = size + 1
    buffer = bytearray(length)
    buffer[0] = report_id
    try:
        copied = fcntl.ioctl(fd, hidiocgfeature(length), buffer)
    except OSError as exc:
        raise _map_read_error(report_id, exc) from exc

    # The kernel mutates the bytearray in place and returns the number of bytes
    # it copied (the full report length for HIDIOCGFEATURE).
    if copied != length:
        raise ProtocolError(
            "GetFeature copied %s bytes for report 0x%02X; expected %d."
            % (copied, report_id, length)
        )
    result = bytes(buffer)
    if result[0] != report_id:
        raise ProtocolError(
            "GetFeature returned report ID 0x%02X for a 0x%02X request; the "
            "device may not support this report." % (result[0], report_id)
        )
    return result


# --------------------------------------------------------------------------
# captured lighting frame (write path)
# --------------------------------------------------------------------------


def _data_path(name: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", name)


@lru_cache(maxsize=None)
def load_color_template() -> bytes:
    """Load and verify the all-off ``09 cc`` frame captured from the K622 app."""
    path = _data_path(COLOR_TEMPLATE_FILE)
    try:
        with open(path, "rb") as handle:
            data = handle.read(COLOR_TEMPLATE_SIZE + 1)
    except OSError as exc:
        raise ProtocolError(
            "cannot read the captured lighting template at %s: %s"
            % (path, exc.strerror or exc)
        ) from exc
    if len(data) != COLOR_TEMPLATE_SIZE:
        raise ProtocolError(
            "the captured lighting template at %s is %d bytes; expected %d"
            % (path, len(data), COLOR_TEMPLATE_SIZE)
        )
    digest = descriptor_sha256(data)
    if digest != COLOR_TEMPLATE_SHA256:
        raise ProtocolError(
            "the captured lighting template at %s has sha256 %s; expected %s. "
            "Refusing to build writes from an unknown frame."
            % (path, digest, COLOR_TEMPLATE_SHA256)
        )
    if data[:COLOR_REGION_START] != COLOR_PACKET_HEADER:
        raise ProtocolError(
            "the captured lighting template has an unexpected header: %s"
            % data[:COLOR_REGION_START].hex(" ")
        )
    return data


def _checked_color(color) -> Color:
    try:
        red, green, blue = color
    except (TypeError, ValueError):
        raise ValueError(
            "color must be an (r, g, b) triple, got %r" % (color,)
        ) from None
    checked = []
    for value in (red, green, blue):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("color channels must be integers, got %r" % (value,))
        if not 0 <= value <= 255:
            raise ValueError("color channel %d is outside 0..255" % value)
        checked.append(value)
    return (checked[0], checked[1], checked[2])


def build_color_packet(colors: Optional[Mapping[int, Color]] = None) -> bytes:
    """Build a report-6 ``09 cc`` frame from the captured all-off template.

    ``colors`` maps slot (0..125) to ``(red, green, blue)``. Slots that are
    absent stay black. Bytes outside the 378-byte colour region are copied
    from the captured template unchanged.
    """
    packet = bytearray(load_color_template())
    if colors:
        for slot, color in colors.items():
            if isinstance(slot, bool) or not isinstance(slot, int):
                raise ValueError("slot must be an integer, got %r" % (slot,))
            if not 0 <= slot < NUM_SLOTS:
                raise ValueError(
                    "slot %d is outside 0..%d" % (slot, NUM_SLOTS - 1)
                )
            red, green, blue = _checked_color(color)
            for base, value in zip(COLOR_PLANE_BASES, (red, green, blue)):
                packet[base + slot] = value
    return bytes(packet)


def validate_color_packet(packet) -> bytes:
    """Refuse anything that is not a captured-shape ``09 cc`` lighting frame."""
    if not isinstance(packet, (bytes, bytearray, memoryview)):
        raise TypeError("packet must be bytes-like")
    packet = bytes(packet)
    if len(packet) != COLOR_TEMPLATE_SIZE:
        raise ProtocolError(
            "lighting frame is %d bytes; expected %d (report 0x06 + 1031 data)"
            % (len(packet), COLOR_TEMPLATE_SIZE)
        )
    template = load_color_template()
    if packet[:COLOR_REGION_START] != COLOR_PACKET_HEADER:
        raise ProtocolError(
            "refusing to write: only the captured report 0x06 lighting header "
            "is allowed (expected %s, got %s)"
            % (
                COLOR_PACKET_HEADER.hex(" "),
                packet[:COLOR_REGION_START].hex(" "),
            )
        )
    if packet[COLOR_REGION_END:] != template[COLOR_REGION_END:]:
        raise ProtocolError(
            "refusing to write: bytes after the 378-byte colour region must "
            "match the captured template"
        )
    return packet


def colors_from_packet(packet) -> Dict[int, Color]:
    """Extract the 126 RGB triples from a validated lighting frame."""
    packet = validate_color_packet(packet)
    red_base, green_base, blue_base = COLOR_PLANE_BASES
    return {
        slot: (
            packet[red_base + slot],
            packet[green_base + slot],
            packet[blue_base + slot],
        )
        for slot in range(NUM_SLOTS)
    }


def lit_slots(colors: Mapping[int, Color]) -> List[int]:
    """Slots whose colour is not black, in ascending order."""
    return [
        slot
        for slot in range(NUM_SLOTS)
        if tuple(colors.get(slot, (0, 0, 0))) != (0, 0, 0)
    ]


def _map_write_error(exc: OSError) -> DeviceError:
    if exc.errno in (errno.EACCES, errno.EPERM):
        return PermissionDenied(
            "Permission denied while writing the lighting frame: %s"
            % (exc.strerror or exc)
        )
    if exc.errno == errno.EINVAL:
        return ProtocolError(
            "The kernel or keyboard rejected the lighting write (EINVAL). The "
            "report ID or size may no longer match the descriptor; stop and "
            "re-check it instead of guessing."
        )
    if exc.errno in (errno.EPIPE, errno.ESHUTDOWN, errno.ECONNRESET):
        return ProtocolError(
            "The keyboard stalled or dropped the lighting write (%s). It may "
            "have been unplugged; replug it and retry once."
            % errno.errorcode.get(exc.errno, exc.errno)
        )
    if exc.errno == errno.ETIMEDOUT:
        return ProtocolError(
            "Timed out waiting for the keyboard to accept the lighting frame. "
            "Replug it, then retry once."
        )
    if exc.errno in (errno.ENODEV, errno.ENXIO, errno.ENOENT):
        return DeviceError(
            "Device disconnected while writing the lighting frame; replug it."
        )
    if exc.errno == errno.EBUSY:
        return DeviceError("The device is busy (another program is using it).")
    return ProtocolError(
        "Failed to write the lighting frame: %s" % (exc,)
    )


def write_feature(fd: int, packet) -> int:
    """Send one validated lighting frame with ``HIDIOCSFEATURE``.

    This is the only write path in the package. It refuses every packet whose
    header is not the captured ``09 cc 00 40`` header or whose bytes outside
    the colour planes differ from the captured template.
    """
    packet = validate_color_packet(packet)
    # CPython's fcntl module refuses an immutable ``bytes`` ioctl buffer larger
    # than 1024 bytes ("ioctl argument 3 is too long"). A writable bytearray
    # takes the direct-buffer path with no such limit, so 1032-byte frames must
    # go through it. The kernel reads the buffer for HIDIOCSFEATURE; any
    # resize it reports is irrelevant to us.
    buffer = bytearray(packet)
    try:
        return fcntl.ioctl(fd, hidiocsfeature(len(buffer)), buffer)
    except OSError as exc:
        raise _map_write_error(exc) from exc


# --------------------------------------------------------------------------
# Vendor configuration mailbox (verified on the K622)
# --------------------------------------------------------------------------
#
# The official K622 app reads the lighting configuration through report 0x05:
#
#     SET5  05 83 c6 00 00 00
#     GET6  06 83 c6 ...              (262 bytes)
#
# The returned buffer contains the 136-byte configuration block at offset
# 0x08.  Writing it back uses report 0x06 with header ``06 03 c6 00 40`` and
# the 136 bytes at payload offset 8.  A no-op round trip was verified on the
# physical keyboard: config -> maybe modified -> config returns the same bytes.
#
# The effect palette uses:
#
#     SET5  05 88 c8 00 00 00
#     GET6  06 88 00 ...              (1032 bytes)
#
# and writes with header ``06 08 c8 00 40`` plus 441 bytes.  The table is 21
# blocks of 21 bytes; block 0 is OFF, blocks 1..20 are the 20 effects, and each
# block holds seven RGB triples (colour index 0..6).

MAILBOX_REPORT_ID = 0x05
CONFIG_REPORT_ID = 0x06

CONFIG_READ_COMMAND = bytes.fromhex("05 83 c6 00 00 00")
COLOR_READ_COMMAND = bytes.fromhex("05 88 c8 00 00 00")
CUSTOM1_READ_COMMAND = bytes.fromhex("05 89 cc 00 00 00")
CUSTOM2_READ_COMMAND = bytes.fromhex("05 89 d0 00 00 00")
PROFILE_READ_COMMAND = bytes.fromhex("05 84 d8 00 00 00")

ALLOWED_MAILBOX_COMMANDS = {
    CONFIG_READ_COMMAND: "config",
    COLOR_READ_COMMAND: "effect palette",
    CUSTOM1_READ_COMMAND: "custom frame 1",
    CUSTOM2_READ_COMMAND: "custom frame 2",
    PROFILE_READ_COMMAND: "profile table",
}

CONFIG_RESPONSE_OFFSET = 0x08
CONFIG_SIZE = 136
CONFIG_WRITE_HEADER = bytes.fromhex("06 03 c6 00 40 00 00 00")
CONFIG_MODE_INDEX = 0x0D
CONFIG_PER_KEY_INDEX = 0x0C
CONFIG_PAIR_BASE = 0x1E
CONFIG_PAIR_COUNT = 20
CONFIG_TRAILER = bytes.fromhex("5a a5")
CONFIG_TRAILER_INDEX = 0x46
CONFIG_TRAILER_INDEX_ALT = 0x81
CONFIG_READ_RESPONSE_SIZE = 262

COLOR_WRITE_HEADER = bytes.fromhex("06 08 c8 00 40 00 00 00")
COLOR_TABLE_SIZE = 441
COLOR_BLOCK_SIZE = 21
COLOR_BLOCKS = 21
COLOR_INDEX_MAX = 6
COLOR_RANDOM = 7

PER_KEY_MODE = 21
OFF_MODE = 0
MAX_MODE = PER_KEY_MODE

#: Optional parameters exposed by the official K622 UI.  Taken from the
#: ``LedOpt1`` ... ``LedOpt20`` rows in the official ``Cfg.ini``:
#:   LedOptN = hw, effect, speed, light, direct, random, color
#: ``speed``/``light`` mean the UI offers those sliders; ``random``/``color``
#: mean the effect can use a random palette or one of the seven colours.
ModeInfo = namedtuple(
    "ModeInfo", "value key name aliases speed brightness random color"
)


def _mode(value, key, name, aliases, speed, brightness, random, color):
    return ModeInfo(value, key, name, aliases, speed, brightness, random, color)


MODES = (
    _mode(0, "off", "OFF", ("none", "dark"), False, False, False, False),
    _mode(1, "static", "Fixed_on", ("fixed_on", "fixed", "solid", "static"), False, True, True, True),
    _mode(2, "respire", "Respire", ("breathing", "breathe"), True, True, True, True),
    _mode(3, "rainbow", "Rainbow", (), True, True, False, False),
    _mode(4, "flash_away", "Flash_away", ("flash", "flashaway"), True, True, True, True),
    _mode(5, "raindrops", "Raindrops", ("rain",), True, True, True, True),
    _mode(6, "rainbow_wheel", "Rainbow_wheel", ("wheel",), True, True, False, False),
    _mode(7, "ripples_shining", "Ripples_shining", ("ripples", "ripple"), True, True, True, True),
    _mode(8, "stars_twinkle", "Stars_twinkle", ("stars", "twinkle"), True, True, True, True),
    _mode(9, "shadow_disappear", "Shadow_disappear", ("shadow",), True, True, True, True),
    _mode(10, "retro_snake", "Retro_snake", ("snake", "retro"), True, True, True, True),
    _mode(11, "neon_stream", "Neon_stream", ("neon", "stream"), True, True, True, True),
    _mode(12, "reaction", "Reaction", ("reactive",), True, True, True, True),
    _mode(13, "sine_wave", "Sine_wave", ("sine", "wave"), True, True, True, True),
    _mode(14, "retinue_scanning", "Retinue scanning", ("retinue", "scanning"), True, True, True, True),
    _mode(15, "rotating_windmill", "Rotating windmill", ("windmill",), True, True, True, True),
    _mode(16, "colorful_waterfall", "Colorful waterfall", ("waterfall",), True, True, False, False),
    _mode(17, "blossoming", "Blossoming", ("blossom",), True, True, False, False),
    _mode(18, "rotating_storm", "Rotating storm", ("storm",), True, True, True, True),
    _mode(19, "collision", "Collision", ("collide",), True, True, True, True),
    _mode(20, "perfect", "Perfect", (), True, True, True, True),
    _mode(21, "per_key", "Self-define", ("per-key", "self_define", "selfdefine", "custom"), False, False, False, True),
)

MODE_BY_VALUE = {mode.value: mode for mode in MODES}
MODE_BY_KEY = {}
for _info in MODES:
    MODE_BY_KEY[_info.key] = _info
    for _alias in _info.aliases:
        MODE_BY_KEY[_alias] = _info
del _info, _alias


def lookup_mode(name) -> ModeInfo:
    """Resolve a mode name, alias or number to a :class:`ModeInfo`."""
    if isinstance(name, bool):
        raise ValueError("mode must be a name or an integer")
    if isinstance(name, int):
        try:
            return MODE_BY_VALUE[name]
        except KeyError:
            raise ValueError("unknown mode %r (valid: 0..21)" % (name,)) from None
    if not isinstance(name, str) or not name.strip():
        raise ValueError("mode must be a non-empty name")
    stripped = name.strip()
    if stripped.isdigit():
        return lookup_mode(int(stripped, 10))
    key = stripped.lower().replace("-", "_").replace(" ", "_")
    try:
        return MODE_BY_KEY[key]
    except KeyError:
        raise ValueError(
            "unknown mode %r; use `k622rgb mode list`" % (name,)
        ) from None


#: Per-mode speed and brightness ranges shown by the official UI.
SPEED_MIN, SPEED_MAX = 1, 4
BRIGHTNESS_MIN, BRIGHTNESS_MAX = 0, 9


def _map_command_error(exc: OSError) -> DeviceError:
    if exc.errno in (errno.EACCES, errno.EPERM):
        return PermissionDenied(
            "Permission denied while sending a vendor mailbox command: %s"
            % (exc.strerror or exc)
        )
    if exc.errno in (errno.EPIPE, errno.ESHUTDOWN, errno.ECONNRESET):
        return ProtocolError(
            "The keyboard stalled the mailbox command (%s). Replug it and retry."
            % errno.errorcode.get(exc.errno, exc.errno)
        )
    if exc.errno == errno.ETIMEDOUT:
        return ProtocolError("Timed out sending a vendor mailbox command.")
    if exc.errno in (errno.ENODEV, errno.ENXIO, errno.ENOENT):
        return DeviceError("Device disconnected while sending a mailbox command.")
    if exc.errno == errno.EINVAL:
        return ProtocolError("The device rejected the mailbox command (EINVAL).")
    return ProtocolError("Failed to send a mailbox command: %s" % (exc,))


def send_mailbox(fd: int, command) -> int:
    """Send one allow-listed 6-byte report-0x05 vendor command.

    Only the read commands captured from the official K622 app (and verified
    on hardware) are accepted.  This function is the only report-0x05 write
    path, and it cannot send arbitrary bytes.
    """
    command = bytes(command)
    if command not in ALLOWED_MAILBOX_COMMANDS:
        raise ProtocolError(
            "refusing unknown report 0x05 command %s; only captured read "
            "commands are allowed" % command.hex(" ")
        )
    buffer = bytearray(command)
    try:
        return fcntl.ioctl(fd, hidiocsfeature(len(buffer)), buffer)
    except OSError as exc:
        raise _map_command_error(exc) from exc


def read_feature_partial(fd: int, report_id: int, max_size: int) -> bytes:
    """Read a feature report whose device response may be shorter than declared.

    The K622 answers ``HIDIOCGFEATURE(1032)`` with a 262-byte configuration
    response.  ``read_feature`` deliberately insists on the declared size, so
    mailbox reads use this function instead.
    """
    if not 1 <= max_size <= 0x3FFF:
        raise ValueError("invalid feature read size: %r" % (max_size,))
    buffer = bytearray(max_size)
    buffer[0] = report_id
    try:
        copied = fcntl.ioctl(fd, hidiocgfeature(max_size), buffer)
    except OSError as exc:
        raise _map_read_error(report_id, exc) from exc
    if copied <= 0:
        raise ProtocolError(
            "GetFeature returned no data for report 0x%02X." % report_id
        )
    return bytes(buffer[: min(copied, max_size)])


def mailbox_read(fd: int, command, expected: int = CONFIG_READ_RESPONSE_SIZE,
                 delay: float = 0.05) -> bytes:
    """Send an allow-listed read command, wait, then read report 0x06."""
    send_mailbox(fd, command)
    if delay:
        time.sleep(delay)
    return read_feature_partial(fd, CONFIG_REPORT_ID, 1032)


def read_config_response(fd: int) -> bytes:
    """Return the 262-byte report-0x06 response for the lighting config."""
    response = mailbox_read(fd, CONFIG_READ_COMMAND)
    if len(response) < CONFIG_RESPONSE_OFFSET + CONFIG_SIZE:
        raise ProtocolError(
            "the config response is only %d bytes; expected at least %d"
            % (len(response), CONFIG_RESPONSE_OFFSET + CONFIG_SIZE)
        )
    return response


def config_from_response(response) -> bytes:
    """Extract the 136-byte writable config block from a read response."""
    response = bytes(response)
    end = CONFIG_RESPONSE_OFFSET + CONFIG_SIZE
    if len(response) < end:
        raise ProtocolError(
            "config response is %d bytes; need at least %d" % (len(response), end)
        )
    return response[CONFIG_RESPONSE_OFFSET:end]


def read_config(fd: int) -> bytes:
    """Read and return the 136-byte lighting configuration block."""
    return config_from_response(read_config_response(fd))


def read_effect_palette(fd: int) -> bytes:
    """Read and return the 441-byte effect-colour table."""
    response = mailbox_read(fd, COLOR_READ_COMMAND)
    end = CONFIG_RESPONSE_OFFSET + COLOR_TABLE_SIZE
    if len(response) < end:
        raise ProtocolError(
            "the effect-colour response is only %d bytes; expected at least %d"
            % (len(response), end)
        )
    return response[CONFIG_RESPONSE_OFFSET:end]


def read_custom_frame(fd: int, which: int = 1) -> bytes:
    """Read one 1024-byte custom (per-key) frame: 1 -> ``09 cc``, 2 -> ``09 d0``."""
    command = CUSTOM1_READ_COMMAND if which == 1 else CUSTOM2_READ_COMMAND
    if which not in (1, 2):
        raise ValueError("custom frame must be 1 or 2")
    response = mailbox_read(fd, command)
    end = CONFIG_RESPONSE_OFFSET + 1024
    if len(response) < end:
        raise ProtocolError(
            "the custom-frame response is only %d bytes; expected at least %d"
            % (len(response), end)
        )
    return response[CONFIG_RESPONSE_OFFSET:end]


def read_profile(fd: int) -> bytes:
    """Read the 1024-byte profile/keymap table (not modified by this tool)."""
    response = mailbox_read(fd, PROFILE_READ_COMMAND)
    end = CONFIG_RESPONSE_OFFSET + 1024
    if len(response) < end:
        raise ProtocolError(
            "the profile response is only %d bytes; expected at least %d"
            % (len(response), end)
        )
    return response[CONFIG_RESPONSE_OFFSET:end]


# --------------------------------------------------------------------------
# Configuration parsing and building
# --------------------------------------------------------------------------


class ConfigError(ProtocolError):
    """The config block does not have the shape captured from the K622."""


ModeParams = namedtuple("ModeParams", "color speed brightness")


def _check_byte(value, label):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("%s must be an integer" % label)
    if not 0 <= value <= 255:
        raise ValueError("%s must be 0..255" % label)
    return value


def validate_config(config) -> bytes:
    """Refuse a config that is not the captured K622 136-byte block shape."""
    if not isinstance(config, (bytes, bytearray, memoryview)):
        raise TypeError("config must be bytes-like")
    config = bytes(config)
    if len(config) != CONFIG_SIZE:
        raise ConfigError(
            "config block is %d bytes; expected %d" % (len(config), CONFIG_SIZE)
        )
    if config[0x08:0x0A] != b"\x03\x03":
        raise ConfigError(
            "refusing config without the captured 03 03 marker at offset 0x08"
        )
    if (
        config[CONFIG_TRAILER_INDEX:CONFIG_TRAILER_INDEX + 2] != CONFIG_TRAILER
        and config[
            CONFIG_TRAILER_INDEX_ALT:CONFIG_TRAILER_INDEX_ALT + 2
        ] != CONFIG_TRAILER
    ):
        raise ConfigError(
            "refusing config without the captured 5a a5 marker at offset "
            "0x%02x or 0x%02x"
            % (CONFIG_TRAILER_INDEX, CONFIG_TRAILER_INDEX_ALT)
        )
    mode = config[CONFIG_MODE_INDEX]
    if mode > MAX_MODE:
        raise ConfigError("refusing config with unknown mode id %d" % mode)
    if config[CONFIG_PER_KEY_INDEX] not in (0, 1):
        raise ConfigError(
            "refusing config with non-boolean per-key flag %d"
            % config[CONFIG_PER_KEY_INDEX]
        )
    return config


def parse_config(config) -> "ConfigState":
    """Decode the 136-byte config into mode, per-key flag and per-mode params."""
    config = validate_config(config)
    pairs = []
    for index in range(CONFIG_PAIR_COUNT):
        base = CONFIG_PAIR_BASE + index * 2
        packed = config[base + 1]
        pairs.append(
            ModeParams(
                color=config[base] & 0x0F,
                speed=(packed >> 4) & 0x0F,
                brightness=packed & 0x0F,
            )
        )
    return ConfigState(
        mode=config[CONFIG_MODE_INDEX],
        per_key=bool(config[CONFIG_PER_KEY_INDEX]),
        pairs=tuple(pairs),
        raw=config,
    )


class ConfigState:
    """Decoded lighting config."""

    __slots__ = ("mode", "per_key", "pairs", "raw")

    def __init__(self, mode, per_key, pairs, raw):
        self.mode = mode
        self.per_key = per_key
        self.pairs = pairs
        self.raw = raw

    @property
    def info(self) -> ModeInfo:
        return MODE_BY_VALUE[self.mode]

    def params(self, mode) -> ModeParams:
        info = lookup_mode(mode)
        if not 1 <= info.value <= 20:
            raise ValueError("mode %s has no per-mode parameters" % info.name)
        return self.pairs[info.value - 1]

    def __repr__(self):
        return "ConfigState(mode=%d, per_key=%r, pairs=%r)" % (
            self.mode, self.per_key, self.pairs
        )


def build_config(base, *, mode=None, per_key=None, brightness=None,
                 speed=None, color=None) -> bytes:
    """Return a modified copy of ``base`` with the requested mode settings."""
    config = bytearray(validate_config(base))
    info = None
    if mode is not None:
        info = lookup_mode(mode)
        config[CONFIG_MODE_INDEX] = info.value
        config[CONFIG_PER_KEY_INDEX] = 1 if info.value == PER_KEY_MODE else 0
    if per_key is not None:
        config[CONFIG_PER_KEY_INDEX] = 1 if per_key else 0
    if info is None:
        info = MODE_BY_VALUE[config[CONFIG_MODE_INDEX]]
    if brightness is not None or speed is not None or color is not None:
        if not 1 <= info.value <= 20:
            raise ValueError(
                "mode %s does not have brightness/speed/colour parameters"
                % info.name
            )
        base_index = CONFIG_PAIR_BASE + (info.value - 1) * 2
        current = ModeParams(
            color=config[base_index] & 0x0F,
            speed=(config[base_index + 1] >> 4) & 0x0F,
            brightness=config[base_index + 1] & 0x0F,
        )
        if brightness is not None:
            if isinstance(brightness, bool) or not isinstance(brightness, int):
                raise ValueError("brightness must be an integer")
            if not BRIGHTNESS_MIN <= brightness <= BRIGHTNESS_MAX:
                raise ValueError(
                    "brightness must be %d..%d"
                    % (BRIGHTNESS_MIN, BRIGHTNESS_MAX)
                )
        if speed is not None:
            if isinstance(speed, bool) or not isinstance(speed, int):
                raise ValueError("speed must be an integer")
            if not SPEED_MIN <= speed <= SPEED_MAX:
                raise ValueError("speed must be %d..%d" % (SPEED_MIN, SPEED_MAX))
        if color is not None:
            if isinstance(color, bool) or not isinstance(color, int):
                raise ValueError("colour index must be an integer")
            if not 0 <= color <= COLOR_RANDOM:
                raise ValueError(
                    "colour index must be 0..%d (7 = random)" % COLOR_INDEX_MAX
                )
            if color == COLOR_RANDOM and not info.random:
                raise ValueError("mode %s does not support random colour" % info.name)
            if color != COLOR_RANDOM and not info.color:
                raise ValueError("mode %s does not support a specific colour" % info.name)
        new_color = current.color if color is None else color
        new_brightness = (
            current.brightness if brightness is None else brightness
        )
        new_speed = current.speed if speed is None else speed
        config[base_index] = new_color & 0x0F
        config[base_index + 1] = ((new_speed & 0x0F) << 4) | (new_brightness & 0x0F)
    return bytes(config)


def build_config_packet(config) -> bytes:
    """Build the report-0x06 ``03 c6`` frame around a 136-byte config block."""
    config = validate_config(config)
    packet = bytearray(PACKET_SIZE)
    packet[: len(CONFIG_WRITE_HEADER)] = CONFIG_WRITE_HEADER
    packet[len(CONFIG_WRITE_HEADER):len(CONFIG_WRITE_HEADER) + CONFIG_SIZE] = config
    return bytes(packet)


def write_config(fd: int, config) -> int:
    """Write a validated 136-byte config block with report 0x06."""
    packet = build_config_packet(config)
    buffer = bytearray(packet)
    try:
        return fcntl.ioctl(fd, hidiocsfeature(len(buffer)), buffer)
    except OSError as exc:
        raise _map_write_error(exc) from exc


def validate_effect_palette(palette) -> bytes:
    if not isinstance(palette, (bytes, bytearray, memoryview)):
        raise TypeError("palette must be bytes-like")
    palette = bytes(palette)
    if len(palette) != COLOR_TABLE_SIZE:
        raise ConfigError(
            "effect palette is %d bytes; expected %d"
            % (len(palette), COLOR_TABLE_SIZE)
        )
    return palette


def build_effect_palette_packet(palette) -> bytes:
    palette = validate_effect_palette(palette)
    packet = bytearray(PACKET_SIZE)
    packet[: len(COLOR_WRITE_HEADER)] = COLOR_WRITE_HEADER
    packet[len(COLOR_WRITE_HEADER):len(COLOR_WRITE_HEADER) + COLOR_TABLE_SIZE] = palette
    return bytes(packet)


def write_effect_palette(fd: int, palette) -> int:
    packet = build_effect_palette_packet(palette)
    buffer = bytearray(packet)
    try:
        return fcntl.ioctl(fd, hidiocsfeature(len(buffer)), buffer)
    except OSError as exc:
        raise _map_write_error(exc) from exc


def palette_color(palette, mode, index) -> Color:
    """Return ``(r, g, b)`` for one effect palette entry."""
    mode = lookup_mode(mode).value
    if not 1 <= mode <= COLOR_BLOCKS - 1:
        raise ValueError("mode %d has no effect palette block" % mode)
    if not 0 <= index <= COLOR_INDEX_MAX:
        raise ValueError("colour index must be 0..%d" % COLOR_INDEX_MAX)
    palette = validate_effect_palette(palette)
    base = mode * COLOR_BLOCK_SIZE + index * 3
    return tuple(palette[base:base + 3])


def set_palette_color(palette, mode, index, color) -> bytes:
    """Return a copy of ``palette`` with one entry set to ``color``."""
    palette = bytearray(validate_effect_palette(palette))
    mode = lookup_mode(mode).value
    if not 1 <= mode <= COLOR_BLOCKS - 1:
        raise ValueError("mode %d has no effect palette block" % mode)
    if not 0 <= index <= COLOR_INDEX_MAX:
        raise ValueError("colour index must be 0..%d" % COLOR_INDEX_MAX)
    red, green, blue = _checked_color(color)
    base = mode * COLOR_BLOCK_SIZE + index * 3
    palette[base:base + 3] = bytes((red, green, blue))
    return bytes(palette)


# --------------------------------------------------------------------------
# Custom (per-key) frames: read and write
# --------------------------------------------------------------------------

CUSTOM_HEADERS = {
    1: bytes.fromhex("06 09 cc 00 40 00 00 00"),
    2: bytes.fromhex("06 09 d0 00 40 00 00 00"),
}
CUSTOM_PAYLOAD_SIZE = 1024


def validate_custom_payload(payload) -> bytes:
    """Return a checked 1024-byte custom-frame payload."""
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError("custom frame payload must be bytes-like")
    payload = bytes(payload)
    if len(payload) != CUSTOM_PAYLOAD_SIZE:
        raise ConfigError(
            "custom frame payload is %d bytes; expected %d"
            % (len(payload), CUSTOM_PAYLOAD_SIZE)
        )
    return payload


def build_custom_packet(payload, which: int = 1) -> bytes:
    """Build a ``09 cc`` (which=1) or ``09 d0`` (which=2) frame."""
    if which not in CUSTOM_HEADERS:
        raise ValueError("custom frame must be 1 or 2")
    payload = validate_custom_payload(payload)
    packet = bytearray(PACKET_SIZE)
    header = CUSTOM_HEADERS[which]
    packet[: len(header)] = header
    packet[len(header):len(header) + CUSTOM_PAYLOAD_SIZE] = payload
    return bytes(packet)


def write_custom_frame(fd: int, payload, which: int = 1) -> int:
    packet = build_custom_packet(payload, which)
    buffer = bytearray(packet)
    try:
        return fcntl.ioctl(fd, hidiocsfeature(len(buffer)), buffer)
    except OSError as exc:
        raise _map_write_error(exc) from exc


def palette_from_response(response) -> bytes:
    """Extract the 441-byte effect palette from a ``88 c8`` read response."""
    response = bytes(response)
    end = CONFIG_RESPONSE_OFFSET + COLOR_TABLE_SIZE
    if len(response) < end:
        raise ProtocolError(
            "palette response is %d bytes; need at least %d" % (len(response), end)
        )
    return response[CONFIG_RESPONSE_OFFSET:end]


def payload_from_response(response, size: int) -> bytes:
    """Extract ``size`` payload bytes from a report-0x06 read response."""
    if not isinstance(size, int) or size <= 0:
        raise ValueError("payload size must be a positive integer")
    response = bytes(response)
    end = CONFIG_RESPONSE_OFFSET + size
    if len(response) < end:
        raise ProtocolError(
            "response is %d bytes; need at least %d" % (len(response), end)
        )
    return response[CONFIG_RESPONSE_OFFSET:end]

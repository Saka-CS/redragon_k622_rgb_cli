"""Command-line interface for the Redragon K622.

Read-only commands:

* ``info``  — resolve the device, read its HID report descriptor and print the
  reports it declares.
* ``dump``  — issue ``HIDIOCGFEATURE`` for report 0x05 or 0x06 and write the
  bytes to a file or print them as hex.
* ``check`` — verify discovery, permissions and the descriptor hash without
  reading or writing any feature report.

The single write command:

* ``set`` — build the captured report-0x06 ``09 cc`` lighting frame and send
  it with ``HIDIOCSFEATURE``. It refuses an unknown descriptor, any packet
  whose header or tail differs from the captured template, and any use without
  an explicit list of changes (or ``--all``/``--off``). ``--dry-run`` prints
  the exact frame without opening the device.
"""

import argparse
import os
import stat
import sys
from typing import Dict, List, Optional, Tuple

from . import __version__, colors, controller, layout, state

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130

DUMP_REPORTS = tuple(sorted(controller.ALLOWED_FEATURE_REPORTS))


# --------------------------------------------------------------------------
# argparse plumbing
# --------------------------------------------------------------------------


def _add_global_flags(parser: argparse.ArgumentParser, suppress_defaults: bool = False) -> None:
    """Register --device/--dry-run/--verbose.

    The top-level parser owns the real defaults; the subparser copy uses
    argparse.SUPPRESS so flags given before the subcommand are not overwritten
    by the subparser's defaults.
    """
    device_default = argparse.SUPPRESS if suppress_defaults else None
    flag_default = argparse.SUPPRESS if suppress_defaults else False
    parser.add_argument(
        "--device",
        metavar="PATH",
        default=device_default,
        help="use this /dev/hidrawN instead of auto-detection",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=flag_default,
        help="describe what would happen; do not open the device",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=flag_default,
        help="print discovery details",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="k622rgb",
        description=(
            "Inspect the Redragon K622 keyboard and set its per-key RGB "
            "lighting with the captured vendor frame."
        ),
    )
    _add_global_flags(parser)
    parser.add_argument(
        "--version", action="version", version="k622rgb " + __version__
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    info = subparsers.add_parser(
        "info",
        help="show the HID report descriptor and declared reports",
        description=(
            "Read the control interface's HID report descriptor from sysfs and "
            "list every report it declares. Touches nothing on the device."
        ),
    )
    _add_global_flags(info, suppress_defaults=True)
    info.set_defaults(func=cmd_info)

    dump = subparsers.add_parser(
        "dump",
        help="read a declared feature report (read-only)",
        description=(
            "Read feature report 0x05 (5 bytes) or 0x06 (1031 bytes) with "
            "HIDIOCGFEATURE. The report ID is included as byte 0 of the output. "
            "Nothing is written to the keyboard."
        ),
    )
    _add_global_flags(dump, suppress_defaults=True)
    dump.add_argument(
        "--report",
        type=lambda text: int(text, 0),
        choices=DUMP_REPORTS,
        required=True,
        metavar="{5,6}",
        help="feature report ID to read (0x05 or 0x06)",
    )
    dump.add_argument(
        "--out",
        metavar="FILE",
        help="write the raw response to FILE instead of printing hex",
    )
    dump.add_argument(
        "--hex",
        action="store_true",
        help="also print hex when --out is given",
    )
    dump.set_defaults(func=cmd_dump)

    check = subparsers.add_parser(
        "check",
        help="verify device, permissions and descriptor hash",
        description=(
            "Open the hidraw node read-only, read the descriptor from sysfs and "
            "check it against the captured K622 descriptor. Reads and writes no "
            "feature reports."
        ),
    )
    _add_global_flags(check, suppress_defaults=True)
    check.set_defaults(func=cmd_check)

    set_parser = subparsers.add_parser(
        "set",
        help="set per-key colours (the only write command)",
        description=(
            "Build a 126-slot lighting frame from the captured report-0x06 "
            "'09 cc' template and send it with HIDIOCSFEATURE. Unspecified "
            "keys keep the colour from the last frame this tool saved, or "
            "stay black on the first run. The descriptor must match the "
            "captured K622 IF1 hash. Use --dry-run to print the exact frame "
            "without opening the device."
        ),
    )
    _add_global_flags(set_parser, suppress_defaults=True)
    set_parser.add_argument(
        "assignments",
        nargs="*",
        metavar="KEY=COLOR",
        help="key assignment, e.g. Esc=ff0000 1=#00ff00 slot:6=ffffff",
    )
    set_parser.add_argument(
        "--all",
        dest="fill",
        metavar="COLOR",
        help="fill all 126 slots before applying KEY=COLOR overrides",
    )
    set_parser.add_argument(
        "--off",
        action="store_true",
        help="start from all black before applying KEY=COLOR overrides",
    )
    set_parser.add_argument(
        "--reset",
        action="store_true",
        help="ignore the saved last frame and start from the captured all-off frame",
    )
    set_parser.add_argument(
        "--state",
        metavar="FILE",
        help="use FILE for the saved last frame (default: XDG state directory)",
    )
    set_parser.add_argument(
        "--no-state",
        action="store_true",
        help="do not read or write the saved last frame",
    )
    set_parser.add_argument(
        "--hex",
        action="store_true",
        help="print the full 1032-byte frame even when writing",
    )
    set_parser.set_defaults(func=cmd_set)

    return parser


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _resolve_device(
    args: argparse.Namespace,
) -> Tuple[str, Optional[controller.DeviceInfo], str]:
    """Return (node, device info if matched, sysfs dir for the descriptor)."""
    candidates = controller.iter_devices()
    if args.device:
        node = args.device
        if not os.path.exists(node):
            raise controller.DeviceNotFound("device node %s does not exist" % node)
    else:
        node = controller.find_device()
    info = next((item for item in candidates if item.node == node), None)
    sysfs = info.sysfs if info is not None else controller.sysfs_dir_for_node(node)
    return node, info, sysfs


def _load_reports(
    sysfs: str,
) -> Tuple[bytes, List[controller.ReportInfo]]:
    data = controller.load_descriptor(sysfs)
    return data, controller.parse_report_descriptor(data)


def _descriptor_label(data: bytes) -> str:
    if controller.is_known_descriptor(data):
        return "known K622 IF1 descriptor"
    return "UNKNOWN descriptor (does not match the captured K622 IF1 hash)"


def _print_descriptor(data: bytes, reports: List[controller.ReportInfo]) -> None:
    print("descriptor: %d bytes" % len(data))
    print("descriptor sha256: %s" % controller.descriptor_sha256(data))
    print("descriptor: %s" % _descriptor_label(data))
    print()
    print("reports declared by the descriptor:")
    print("  %-7s %-4s %s" % ("kind", "id", "size"))
    for report in reports:
        print("  %-7s 0x%02X %d byte%s" % (
            report.kind,
            report.report_id,
            report.size,
            "" if report.size == 1 else "s",
        ))
    print()
    print("feature reports this tool may read:")
    for report_id in sorted(controller.ALLOWED_FEATURE_REPORTS):
        expected = controller.ALLOWED_FEATURE_REPORTS[report_id]
        try:
            size = controller.feature_report_size(reports, report_id)
        except controller.ProtocolError:
            print("  0x%02X  REFUSED (descriptor does not declare %d bytes)"
                  % (report_id, expected))
            continue
        print(
            "  0x%02X  %d bytes  HIDIOCGFEATURE(%d) = 0x%08X"
            % (
                report_id,
                size,
                size + 1,
                controller.hidiocgfeature(size + 1),
            )
        )


def _print_node(
    node: str,
    info: Optional[controller.DeviceInfo],
) -> None:
    print("device: %s" % node)
    if info is None:
        print("hid id: unknown (node does not match %04x:%04x)"
              % (controller.VENDOR_ID, controller.PRODUCT_ID))
        return
    print("hid id: %s" % info.hid_id)
    print(
        "interface: %s%s"
        % (
            info.interface or "?",
            " (IF1 control)" if info.interface == controller.CONTROL_INTERFACE else "",
        )
    )
    print("sysfs: %s" % info.sysfs)


def _print_mode(node: str) -> None:
    try:
        node_stat = os.stat(node)
    except OSError as exc:
        print("node mode: unavailable (%s)" % (exc.strerror or exc))
        return
    print(
        "node mode: %s %d:%d%s"
        % (
            stat.filemode(node_stat.st_mode),
            node_stat.st_uid,
            node_stat.st_gid,
            " (writable)" if os.access(node, os.W_OK) else " (read-only for you)",
        )
    )


def _hex_lines(data: bytes, width: int = 32) -> List[str]:
    lines = []
    for start in range(0, len(data), width):
        chunk = data[start : start + width]
        lines.append("%08x  %s" % (start, chunk.hex(" ")))
    return lines


def _write_bytes(path: str, data: bytes) -> None:
    target = os.path.expanduser(path)
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(target, "wb") as handle:
        handle.write(data)


def _print_report_hex(report_id: int, data: bytes) -> None:
    print("report 0x%02X: %d bytes returned (byte 0 is the report ID)"
          % (report_id, len(data)))
    for line in _hex_lines(data):
        print(line)


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------


def cmd_info(args: argparse.Namespace) -> int:
    node, info, sysfs = _resolve_device(args)
    if args.verbose:
        for candidate in controller.iter_devices():
            print(
                "verbose: %s interface=%s sysfs=%s"
                % (candidate.node, candidate.interface, candidate.sysfs)
            )
    _print_node(node, info)
    print()
    data, reports = _load_reports(sysfs)
    _print_descriptor(data, reports)
    print()
    print("report 0x08: not declared by this descriptor; this tool never uses it.")
    if not controller.is_known_descriptor(data):
        print(
            "warning: this descriptor differs from the captured K622 IF1 "
            "descriptor. Do not trust writes on this firmware until reviewed.",
            file=sys.stderr,
        )
    return EXIT_OK


def cmd_dump(args: argparse.Namespace) -> int:
    report_id = args.report
    expected = controller.ALLOWED_FEATURE_REPORTS[report_id]
    if args.dry_run:
        print("dry run: no device access, no feature report read")
        print(
            "would read feature report 0x%02X (%d payload bytes, %d with the "
            "report ID) via HIDIOCGFEATURE(0x%08X)"
            % (
                report_id,
                expected,
                expected + 1,
                controller.hidiocgfeature(expected + 1),
            )
        )
        if args.out:
            print("would write the raw response to %s" % os.path.expanduser(args.out))
        else:
            print("would print the raw response as hex")
        return EXIT_OK

    node, info, sysfs = _resolve_device(args)
    if args.verbose:
        for candidate in controller.iter_devices():
            print(
                "verbose: %s interface=%s sysfs=%s"
                % (candidate.node, candidate.interface, candidate.sysfs)
            )
    print("device: %s" % node)
    data, reports = _load_reports(sysfs)
    if not controller.is_known_descriptor(data):
        print(
            "warning: descriptor does not match the captured K622 IF1 hash "
            "(sha256 %s)" % controller.descriptor_sha256(data),
            file=sys.stderr,
        )
    size = controller.feature_report_size(reports, report_id)

    fd = controller.open_device(node)
    try:
        response = controller.read_feature(fd, report_id, size)
    finally:
        try:
            os.close(fd)
        except OSError:
            pass

    if args.out:
        _write_bytes(args.out, response)
        print(
            "wrote %d bytes to %s"
            % (len(response), os.path.expanduser(args.out))
        )
        if not args.hex:
            return EXIT_OK
    _print_report_hex(report_id, response)
    return EXIT_OK


def cmd_check(args: argparse.Namespace) -> int:
    node, info, sysfs = _resolve_device(args)
    if args.verbose:
        for candidate in controller.iter_devices():
            print(
                "verbose: %s interface=%s sysfs=%s"
                % (candidate.node, candidate.interface, candidate.sysfs)
            )
    _print_node(node, info)
    _print_mode(node)

    data, reports = _load_reports(sysfs)
    print("descriptor: %d bytes" % len(data))
    print("descriptor sha256: %s" % controller.descriptor_sha256(data))
    known = controller.is_known_descriptor(data)
    print("descriptor: %s" % _descriptor_label(data))

    ok = known
    for report_id in sorted(controller.ALLOWED_FEATURE_REPORTS):
        expected = controller.ALLOWED_FEATURE_REPORTS[report_id]
        try:
            size = controller.feature_report_size(reports, report_id)
        except controller.ProtocolError as exc:
            print("report 0x%02X: FAIL — %s" % (report_id, exc))
            ok = False
            continue
        print(
            "report 0x%02X: declared feature report, %d bytes (expected %d) — ok"
            % (report_id, size, expected)
        )
    if any(
        report.report_id == 0x08 and report.kind == "feature"
        for report in reports
    ):
        print("report 0x08: UNEXPECTED feature report declared; investigate before use")
        ok = False
    else:
        print("report 0x08: not declared (expected; this tool never uses it)")

    if args.dry_run:
        print("dry run: not opening %s" % node)
    else:
        fd = controller.open_device(node)
        try:
            print("device open: ok (read-only)")
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

    if not ok:
        print("check: FAIL")
        return EXIT_ERROR
    print("check: ok (no feature reports read or written)")
    return EXIT_OK


def cmd_set(args: argparse.Namespace) -> int:
    if args.fill is not None and args.off:
        raise ValueError("--all and --off are mutually exclusive")
    if args.no_state and args.state:
        raise ValueError("--state and --no-state are mutually exclusive")

    changes = _parse_assignments(args.assignments)
    if not (changes or args.fill is not None or args.off):
        raise ValueError(
            "nothing to set: give KEY=COLOR, --all COLOR, or --off"
        )

    state_path = None if args.no_state else _state_path(args)

    # Start from the saved frame when possible. The keyboard cannot be read
    # back, so this is the only way to make successive `set` calls additive.
    if args.no_state or args.reset:
        base_colors = _all_black()
        base_label = "captured all-off frame"
    else:
        saved = state.load_frame(state_path)
        if saved is None:
            base_colors = _all_black()
            base_label = "captured all-off frame (no saved frame yet)"
        else:
            try:
                base_colors = controller.colors_from_packet(saved)
            except controller.ProtocolError as exc:
                raise controller.ProtocolError(
                    "the saved frame at %s is not a valid lighting frame (%s); "
                    "use --reset to start from black" % (state_path, exc)
                ) from exc
            base_label = "saved frame %s" % state_path

    if args.off:
        base_colors = _all_black()
        base_label = "all black"
    elif args.fill is not None:
        fill = colors.parse_color(args.fill)
        base_colors = {
            slot: fill for slot in range(controller.NUM_SLOTS)
        }
        base_label = "filled with %s" % colors.format_color(fill)

    base_colors.update(changes)
    packet = controller.build_color_packet(base_colors)
    controller.validate_color_packet(packet)

    print("frame: report 0x%02X lighting (%s), %d bytes"
          % (controller.COLOR_REPORT_ID,
             controller.COLOR_PACKET_HEADER.hex(" "),
             len(packet)))
    print("base: %s" % base_label)
    for slot in sorted(changes):
        print(
            "set: %s (slot %d) = %s"
            % (layout.canonical_name(slot), slot, colors.format_color(changes[slot]))
        )
    print(
        "lit slots: %d of %d"
        % (len(controller.lit_slots(base_colors)), controller.NUM_SLOTS)
    )

    if args.dry_run:
        print()
        print(
            "dry run: would send %d bytes with HIDIOCSFEATURE(%d) = 0x%08X"
            % (
                len(packet),
                len(packet),
                controller.hidiocsfeature(len(packet)),
            )
        )
        print("dry run: device not opened; saved frame not updated")
        _print_packet_hex(packet)
        return EXIT_OK

    node, info, sysfs = _resolve_device(args)
    if args.verbose:
        for candidate in controller.iter_devices():
            print(
                "verbose: %s interface=%s sysfs=%s"
                % (candidate.node, candidate.interface, candidate.sysfs)
            )
    print("device: %s" % node)

    data, reports = _load_reports(sysfs)
    if not controller.is_known_descriptor(data):
        raise controller.ProtocolError(
            "descriptor sha256 %s does not match the captured K622 IF1 "
            "descriptor; refusing to write. Run `k622rgb info` and review it "
            "before trying again." % controller.descriptor_sha256(data)
        )
    size = controller.feature_report_size(reports, controller.COLOR_REPORT_ID)
    print(
        "descriptor: %s (report 0x%02X is %d payload bytes)"
        % (
            _descriptor_label(data),
            controller.COLOR_REPORT_ID,
            size,
        )
    )

    fd = controller.open_device(node, writable=True)
    try:
        controller.write_feature(fd, packet)
    finally:
        try:
            os.close(fd)
        except OSError:
            pass

    print(
        "sent %d-byte report 0x%02X lighting frame (%d lit slots)"
        % (
            len(packet),
            controller.COLOR_REPORT_ID,
            len(controller.lit_slots(base_colors)),
        )
    )
    if args.hex:
        _print_packet_hex(packet)
    if not args.no_state:
        try:
            state.save_frame(state_path, packet)
            print("saved frame to %s" % state_path)
        except state.StateError as exc:
            print("warning: %s" % exc, file=sys.stderr)
    return EXIT_OK


def _all_black() -> Dict[int, controller.Color]:
    return {slot: (0, 0, 0) for slot in range(controller.NUM_SLOTS)}


def _state_path(args: argparse.Namespace) -> str:
    if args.state:
        return os.path.expanduser(args.state)
    return state.default_frame_path()


def _parse_assignments(items: List[str]) -> Dict[int, controller.Color]:
    changes = {}
    for item in items:
        if "=" not in item:
            raise ValueError(
                "expected KEY=COLOR, got %r (use Esc=ff0000)" % item
            )
        key_text, color_text = item.rsplit("=", 1)
        if not key_text:
            raise ValueError(
                "missing key before '=' in %r (use Equals=ff0000 for the = key)"
                % item
            )
        slot = layout.resolve_key(key_text)
        changes[slot] = colors.parse_color(color_text)
    return changes


def _print_packet_hex(packet: bytes) -> None:
    print("packet: %d bytes (byte 0 is the report ID)" % len(packet))
    for line in _hex_lines(packet):
        print(line)


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except controller.DeviceError as exc:
        print("k622rgb: %s" % exc, file=sys.stderr)
        return EXIT_ERROR
    except state.StateError as exc:
        print("k622rgb: %s" % exc, file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(
            "k622rgb: I/O error: %s" % (exc.strerror or exc),
            file=sys.stderr,
        )
        return EXIT_ERROR
    except ValueError as exc:
        print("k622rgb: %s" % exc, file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("k622rgb: interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())

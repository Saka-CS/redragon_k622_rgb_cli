"""Command-line interface for the Redragon K622.

Read-only commands:

* ``info``    — resolve the device and print its HID report descriptor.
* ``dump``    — issue ``HIDIOCGFEATURE`` for report 0x05 or 0x06.
* ``check``   — verify discovery, permissions and the descriptor hash.
* ``list``    — show the packet-slot map: keys, logo zones, aliases and dead slots.

Lighting commands:

* ``mode``    — list/show/set the 20 effects, Self-define and OFF, including
  brightness (0-9), speed (1-4), random or a specific colour.
* ``color``   — inspect or edit the seven-colour palette of an effect.
* ``set``     — build the captured report-0x06 ``09 cc`` per-key frame.
* ``group``   — manage named per-key colour groups and overlays.
* ``off``     — select the built-in OFF mode.
* ``config``  — dump/show/restore the config, palette and custom frames.
* ``profile`` — save/load/list/delete local lighting profiles.

Every config/palette write is preceded by a full read-back backup unless
``--no-backup`` is given. Writes are limited to the exact report-0x06 shapes
captured from the official K622 software.
"""

import argparse
import os
import stat
import sys
import time
from typing import Dict, List, Optional, Tuple

from . import __version__, colors, controller, groups, layout, profiles, state

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


def _add_frame_flags(parser: argparse.ArgumentParser) -> None:
    """Register the frame-building flags shared by ``set`` and ``group apply``."""
    parser.add_argument(
        "--all",
        dest="fill",
        metavar="COLOR",
        help="fill all 126 slots before applying group/key overrides",
    )
    parser.add_argument(
        "--off",
        action="store_true",
        help="start from all black before applying group/key overrides",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="ignore the saved last frame and start from the captured all-off frame",
    )
    parser.add_argument(
        "--state",
        metavar="FILE",
        help="use FILE for the saved last frame (default: XDG state directory)",
    )
    parser.add_argument(
        "--no-state",
        action="store_true",
        help="do not read or write the saved last frame",
    )
    parser.add_argument(
        "--hex",
        action="store_true",
        help="print the full 1032-byte frame even when writing",
    )
    parser.add_argument(
        "--from-device",
        action="store_true",
        help="start from the custom frame read back from the keyboard (09 cc)",
    )
    parser.add_argument(
        "--activate",
        dest="activate",
        action="store_true",
        default=True,
        help="switch to Self-define mode after writing the frame (default)",
    )
    parser.add_argument(
        "--no-activate",
        dest="activate",
        action="store_false",
        help="leave the current lighting mode unchanged",
    )
    parser.add_argument(
        "--brightness",
        type=int,
        metavar="0-9",
        help="software-scale the final frame to brightness level 0-9",
    )
    parser.add_argument(
        "--game-flag",
        action="store_true",
        help=(
            "experimental: also send the 09 d0 companion with a game byte "
            "written (default offset %d, value 1); see --game-flag-offset/"
            "--game-flag-value" % controller.GAME_FLAG_OFFSET
        ),
    )
    parser.add_argument(
        "--game-flag-offset",
        type=int,
        metavar="0-1023",
        help=(
            "experimental: byte offset inside the 09 d0 payload "
            "(default: %d)" % controller.GAME_FLAG_OFFSET
        ),
    )
    parser.add_argument(
        "--game-flag-value",
        type=int,
        metavar="0-255",
        help="experimental: value for the game byte (default: 1)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="k622rgb",
        description=(
            "Inspect the Redragon K622 keyboard and control its RGB lighting: "
            "per-key colours, the 20 built-in effects, brightness/speed, the "
            "effect palette, config backups and local profiles."
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
            "Report 0x06 normally stalls unless the vendor read handshake is "
            "sent first; use `config show`/`config dump` for lighting tables. "
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
        help="set per-key colours (write)",
        description=(
            "Build a 126-slot lighting frame from the captured report-0x06 "
            "'09 cc' template and send it with HIDIOCSFEATURE. Unspecified "
            "keys keep the colour from the last frame this tool saved, or "
            "stay black on the first run. The keyboard is switched to "
            "Self-define mode by default, because per-key frames are ignored "
            "in an effect mode; use --no-activate to leave the current mode. "
            "Repeat --group NAME=COLOR to paint stored groups before explicit "
            "KEY=COLOR overrides. The descriptor must match the captured K622 "
            "IF1 hash. Use --dry-run to print the exact frame without opening "
            "the device."
        ),
    )
    _add_global_flags(set_parser, suppress_defaults=True)
    set_parser.add_argument(
        "assignments",
        nargs="*",
        metavar="KEY=COLOR",
        help="key assignment, e.g. Esc=ff0000 1=#00ff00 slot:6=ffffff",
    )
    _add_frame_flags(set_parser)
    set_parser.add_argument(
        "--group",
        dest="group_overlays",
        action="append",
        default=[],
        metavar="NAME=COLOR",
        help="paint a stored group before applying KEY=COLOR overrides",
    )
    set_parser.set_defaults(func=cmd_set)

    list_parser = subparsers.add_parser(
        "list",
        help="show the packet-slot LED map",
        description=(
            "Print the packet-slot LED map: main keys, the three addressable "
            "logo zones, aliases and dead slots. The K622's G1-G4/MR/RGB/media "
            "keys are not RGB. Reads no feature reports."
        ),
    )
    _add_global_flags(list_parser, suppress_defaults=True)
    list_parser.add_argument(
        "--all",
        action="store_true",
        help="print every packet slot, including dead and alias positions",
    )
    list_parser.set_defaults(func=cmd_list)

    group_parser = subparsers.add_parser(
        "group",
        help="manage named per-key colour groups",
        description=(
            "The official software's Color Group -> Define1..5 feature paints "
            "lists of keys from a 09 cc per-key frame. This command stores "
            "those groups locally, imports the vendor groups from Cfg.ini, "
            "and paints them. It never writes a keymap or macro table."
        ),
    )
    group_sub = group_parser.add_subparsers(
        dest="group_command", metavar="SUBCOMMAND", required=True
    )

    group_list = group_sub.add_parser(
        "list", help="show the five define groups, presets and local groups"
    )
    _add_global_flags(group_list, suppress_defaults=True)
    group_list.add_argument(
        "--file", metavar="FILE", help="group store override"
    )
    group_list.set_defaults(func=cmd_group_list)

    group_set = group_sub.add_parser(
        "set", help="recolour or define a group"
    )
    _add_global_flags(group_set, suppress_defaults=True)
    group_set.add_argument(
        "items",
        nargs="+",
        metavar="NAME=COLOR|KEY",
        help=(
            "NAME=COLOR to recolour an existing group, optionally followed by "
            "keys to define/replace them; several NAME=COLOR pairs are allowed"
        ),
    )
    group_set.add_argument(
        "--file", metavar="FILE", help="group store override"
    )
    group_set.set_defaults(func=cmd_group_set)

    group_apply = group_sub.add_parser(
        "apply", help="paint stored groups into the per-key frame"
    )
    _add_global_flags(group_apply, suppress_defaults=True)
    group_apply.add_argument(
        "names",
        nargs="*",
        metavar="NAME",
        help="groups to apply in order (default: define1..define5)",
    )
    group_apply.add_argument(
        "--file", metavar="FILE", help="group store override"
    )
    _add_frame_flags(group_apply)
    group_apply.set_defaults(func=cmd_group_apply)

    group_import = group_sub.add_parser(
        "import", help="import GaoshouKey1..5 from a vendor Cfg.ini"
    )
    _add_global_flags(group_import, suppress_defaults=True)
    group_import.add_argument("path", metavar="Cfg.ini", help="vendor Cfg.ini")
    group_import.add_argument(
        "--file", metavar="FILE", help="group store override"
    )
    group_import.set_defaults(func=cmd_group_import)

    mode_parser = subparsers.add_parser(
        "mode",
        help="inspect or set the built-in lighting effects",
        description=(
            "The K622 has 20 built-in effects, a self-define (per-key) mode "
            "and OFF. 'mode set' writes the same report-0x06 '03 c6' config "
            "block as the official app; every write is preceded by a full "
            "config/palette backup unless --no-backup is given."
        ),
    )
    mode_sub = mode_parser.add_subparsers(
        dest="mode_command", metavar="SUBCOMMAND", required=True
    )

    mode_list = mode_sub.add_parser(
        "list", help="list every built-in mode and the parameters it supports"
    )
    _add_global_flags(mode_list, suppress_defaults=True)
    mode_list.set_defaults(func=cmd_mode_list)

    mode_show = mode_sub.add_parser(
        "show", help="read and print the current mode configuration"
    )
    _add_global_flags(mode_show, suppress_defaults=True)
    mode_show.set_defaults(func=cmd_mode_show)

    mode_set = mode_sub.add_parser(
        "set", help="select a mode and optionally set brightness/speed/colour"
    )
    _add_global_flags(mode_set, suppress_defaults=True)
    mode_set.add_argument("mode", help="mode name or number (see `mode list`)")
    mode_set.add_argument(
        "--brightness",
        type=int,
        metavar="0-9",
        help="brightness level 0-9 (modes 1-20)",
    )
    mode_set.add_argument(
        "--speed",
        type=int,
        metavar="1-4",
        help="effect speed 1-4 (some effects ignore it)",
    )
    mode_set.add_argument(
        "--color",
        metavar="COLOR",
        help=(
            "set a specific colour for the mode (e.g. ff0000); the palette "
            "entry is updated and selected"
        ),
    )
    mode_set.add_argument(
        "--color-index",
        type=int,
        metavar="0-6",
        help="select an existing palette entry 0-6",
    )
    mode_set.add_argument(
        "--random",
        action="store_true",
        help="use the mode's random/multicolour palette (index 7)",
    )
    mode_set.add_argument(
        "--no-backup",
        action="store_true",
        help="do not save a config/palette backup before writing",
    )
    mode_set.add_argument(
        "--hex", action="store_true", help="print the 1032-byte config frame"
    )
    mode_set.set_defaults(func=cmd_mode_set)

    color_parser = subparsers.add_parser(
        "color",
        help="inspect or edit the seven-colour effect palette",
        description=(
            "Each of the 20 effects has seven palette entries (RGB). The "
            "effect uses one of them when its colour byte is 0-6, or the "
            "random palette when it is 7."
        ),
    )
    color_sub = color_parser.add_subparsers(
        dest="color_command", metavar="SUBCOMMAND", required=True
    )
    color_list = color_sub.add_parser(
        "list", help="list palette entries for every effect"
    )
    _add_global_flags(color_list, suppress_defaults=True)
    color_list.add_argument(
        "--mode", help="only show this mode (name or number)"
    )
    color_list.set_defaults(func=cmd_color_list)

    color_show = color_sub.add_parser(
        "show", help="show the seven palette entries for one effect"
    )
    _add_global_flags(color_show, suppress_defaults=True)
    color_show.add_argument("mode", help="mode name or number")
    color_show.set_defaults(func=cmd_color_show)

    color_set = color_sub.add_parser(
        "set", help="write one palette entry for an effect"
    )
    _add_global_flags(color_set, suppress_defaults=True)
    color_set.add_argument("mode", help="mode name or number")
    color_set.add_argument(
        "index", type=int, metavar="0-6", help="palette entry index"
    )
    color_set.add_argument("color", help="colour (e.g. ff0000)")
    color_set.add_argument(
        "--no-backup",
        action="store_true",
        help="do not save a config/palette backup before writing",
    )
    color_set.add_argument(
        "--hex", action="store_true", help="print the 1032-byte palette frame"
    )
    color_set.set_defaults(func=cmd_color_set)

    config_parser = subparsers.add_parser(
        "config",
        help="dump, show or restore the device lighting configuration",
        description=(
            "Dump the readable vendor tables (config, effect palette, custom "
            "frames and profile) to a backup directory, or restore a previous "
            "backup. Restoring is the recovery path for every write command."
        ),
    )
    config_sub = config_parser.add_subparsers(
        dest="config_command", metavar="SUBCOMMAND", required=True
    )
    config_dump = config_sub.add_parser(
        "dump", help="read all lighting tables into a timestamped backup"
    )
    _add_global_flags(config_dump, suppress_defaults=True)
    config_dump.add_argument(
        "--out", metavar="DIR", help="write the backup to DIR instead of the XDG state dir"
    )
    config_dump.add_argument(
        "--hex", action="store_true", help="also print the config block as hex"
    )
    config_dump.set_defaults(func=cmd_config_dump)

    config_show = config_sub.add_parser(
        "show", help="read and print the current configuration"
    )
    _add_global_flags(config_show, suppress_defaults=True)
    config_show.add_argument(
        "--hex", action="store_true", help="print the raw 136-byte config block"
    )
    config_show.set_defaults(func=cmd_config_show)

    config_restore = config_sub.add_parser(
        "restore", help="restore a config/palette backup"
    )
    _add_global_flags(config_restore, suppress_defaults=True)
    config_restore.add_argument(
        "path", metavar="DIR|FILE", help="backup directory or config file"
    )
    config_restore.add_argument(
        "--custom",
        action="store_true",
        help="also restore the two custom per-key frames if present",
    )
    config_restore.add_argument(
        "--no-backup",
        action="store_true",
        help="do not back up the current state before restoring",
    )
    config_restore.set_defaults(func=cmd_config_restore)

    off_parser = subparsers.add_parser(
        "off",
        help="turn the lighting off (mode OFF)",
        description=(
            "Select the built-in OFF mode with a '03 c6' config write. Unlike "
            "'set --off', this does not change the stored per-key frame."
        ),
    )
    _add_global_flags(off_parser, suppress_defaults=True)
    off_parser.add_argument(
        "--no-backup",
        action="store_true",
        help="do not save a config/palette backup before writing",
    )
    off_parser.set_defaults(func=cmd_off)

    profile_parser = subparsers.add_parser(
        "profile",
        help="save, load, list or delete local lighting profiles",
        description=(
            "Profiles store the exact config block, effect palette and "
            "(optionally) the custom per-key frame as JSON under "
            "~/.config/k622rgb/profiles. They are local lighting profiles; "
            "the keyboard's keymap/macro table is never written."
        ),
    )
    profile_sub = profile_parser.add_subparsers(
        dest="profile_command", metavar="SUBCOMMAND", required=True
    )

    profile_list = profile_sub.add_parser("list", help="list saved profiles")
    _add_global_flags(profile_list, suppress_defaults=True)
    profile_list.add_argument("--dir", metavar="DIR", help="profile directory override")
    profile_list.set_defaults(func=cmd_profile_list)

    profile_show = profile_sub.add_parser("show", help="show one saved profile")
    _add_global_flags(profile_show, suppress_defaults=True)
    profile_show.add_argument("name", help="profile name")
    profile_show.add_argument("--dir", metavar="DIR", help="profile directory override")
    profile_show.set_defaults(func=cmd_profile_show)

    profile_save = profile_sub.add_parser(
        "save", help="capture the current config/palette/frame"
    )
    _add_global_flags(profile_save, suppress_defaults=True)
    profile_save.add_argument("name", help="profile name")
    profile_save.add_argument(
        "--no-frame", action="store_true",
        help="do not include the custom per-key frame",
    )
    profile_save.add_argument("--dir", metavar="DIR", help="profile directory override")
    profile_save.set_defaults(func=cmd_profile_save)

    profile_load = profile_sub.add_parser(
        "load", help="apply a saved profile"
    )
    _add_global_flags(profile_load, suppress_defaults=True)
    profile_load.add_argument("name", help="profile name")
    profile_load.add_argument(
        "--no-frame", action="store_true",
        help="do not restore the custom per-key frame",
    )
    profile_load.add_argument(
        "--no-backup", action="store_true",
        help="do not back up the current config/palette first",
    )
    profile_load.add_argument("--dir", metavar="DIR", help="profile directory override")
    profile_load.set_defaults(func=cmd_profile_load)

    profile_delete = profile_sub.add_parser("delete", help="delete a saved profile")
    _add_global_flags(profile_delete, suppress_defaults=True)
    profile_delete.add_argument("name", help="profile name")
    profile_delete.add_argument("--dir", metavar="DIR", help="profile directory override")
    profile_delete.set_defaults(func=cmd_profile_delete)

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


def _read_device_custom_colors(args: argparse.Namespace):
    """Read the custom 09 cc frame from the keyboard and decode its colours."""
    fd, node, _data = _open_mailbox(args)
    try:
        payload = controller.read_custom_frame(fd, 1)
    finally:
        os.close(fd)
    frame = controller.COLOR_PACKET_HEADER + payload
    return controller.colors_from_packet(frame), node


def cmd_set(args: argparse.Namespace) -> int:
    changes = _parse_assignments(args.assignments)
    group_layers = (
        groups.resolve_group_layers(args.group_overlays)
        if args.group_overlays
        else []
    )
    return _run_set(args, changes, group_layers)


def _run_set(
    args: argparse.Namespace,
    changes: Dict[int, controller.Color],
    group_layers: List[Tuple[str, controller.Color, List[int]]],
) -> int:
    """Build, print and (unless dry-run) write one per-key lighting frame."""
    if args.fill is not None and args.off:
        raise ValueError("--all and --off are mutually exclusive")
    if args.no_state and args.state:
        raise ValueError("--state and --no-state are mutually exclusive")
    if args.brightness is not None and not 0 <= args.brightness <= 9:
        raise ValueError("--brightness must be 0..9")
    game_offset = controller.GAME_FLAG_OFFSET
    game_value = controller.GAME_FLAG_ON
    if args.game_flag_offset is not None:
        if not args.game_flag:
            raise ValueError("--game-flag-offset requires --game-flag")
        game_offset = args.game_flag_offset
    if args.game_flag_value is not None:
        if not args.game_flag:
            raise ValueError("--game-flag-value requires --game-flag")
        game_value = args.game_flag_value
    if args.game_flag:
        controller.validate_game_flag(game_offset, game_value)
    if not (changes or group_layers or args.fill is not None or args.off):
        raise ValueError(
            "nothing to set: give KEY=COLOR, --group NAME=COLOR, "
            "--all COLOR, or --off"
        )

    state_path = None if args.no_state else _state_path(args)

    # Start from the saved frame when possible. The keyboard cannot be read
    # back, so this is the only way to make successive `set` calls additive.
    if args.from_device and not args.dry_run:
        try:
            base_colors, source_node = _read_device_custom_colors(args)
            base_label = "device frame (%s)" % source_node
        except controller.ProtocolError as exc:
            raise controller.ProtocolError(
                "--from-device could not read the custom frame (%s); retry "
                "with --reset or without --from-device" % exc
            ) from exc
    elif args.no_state or args.reset:
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

    # Groups form a reusable layer. Later --group arguments win over earlier
    # ones on overlapping keys; explicit KEY=COLOR assignments win over both.
    for name, color, slots in group_layers:
        for slot in slots:
            base_colors[slot] = color
    base_colors.update(changes)

    render_colors = base_colors
    if args.brightness is not None:
        render_colors = _scale_colors(base_colors, args.brightness)
    packet = controller.build_color_packet(render_colors)
    controller.validate_color_packet(packet)

    print("frame: report 0x%02X lighting (%s), %d bytes"
          % (controller.COLOR_REPORT_ID,
             controller.COLOR_PACKET_HEADER.hex(" "),
             len(packet)))
    print("base: %s" % base_label)
    for name, color, slots in group_layers:
        print(
            "group: %s = %s (%d slot%s)"
            % (name, colors.format_color(color), len(slots),
               "" if len(slots) == 1 else "s")
        )
    for slot in sorted(changes):
        name = layout.canonical_name(slot)
        print(
            "set: %s (slot %d) = %s"
            % (
                name,
                slot,
                colors.format_color(changes[slot]),
            )
        )
        if name in layout.UNLIT:
            print(
                "warning: %s did not light during calibration on this unit "
                "(slot %d); the LED may be defective." % (name, slot),
                file=sys.stderr,
            )
    if args.brightness is not None:
        print("brightness: software level %d/9" % args.brightness)
    print(
        "lit slots: %d of %d"
        % (len(controller.lit_slots(render_colors)), controller.NUM_SLOTS)
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
        if args.game_flag:
            print(
                "dry run: would read the current 09 d0 companion and set "
                "payload[%d] = 0x%02X" % (game_offset, game_value)
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
    backup_path = None
    activation_needed = False
    activation_failed = False
    game_payload = None
    game_written = False
    game_failed = False
    try:
        # Read the config before writing the colour frame. The keyboard can
        # stall a report-5 mailbox command if it arrives immediately after a
        # 09 cc transfer, so do the read first and reuse the result.
        current = None
        if args.activate:
            current = controller.read_config(fd)
            parsed = controller.parse_config(current)
            activation_needed = (
                parsed.mode != controller.PER_KEY_MODE or not parsed.per_key
            )

        if args.game_flag:
            base_frame = controller.read_custom_frame(fd, 2)
            old_value = controller.read_game_flag(base_frame, game_offset)
            game_payload = controller.set_game_flag(
                base_frame, game_value, game_offset
            )
            print(
                "game flag: 09 d0 payload[%d] 0x%02X -> 0x%02X "
                "(frame sha256 %s)"
                % (
                    game_offset,
                    old_value,
                    game_value,
                    controller.descriptor_sha256(game_payload),
                )
            )

        if activation_needed or game_payload is not None:
            if activation_needed and game_payload is not None:
                note = "game flag + activate per-key"
            elif game_payload is not None:
                note = "game flag"
            else:
                note = "activate per-key"
            backup_path = _save_lighting_backup(
                fd, data, note, custom=game_payload is not None
            )
            print("backup: %s" % backup_path)

        controller.write_feature(fd, packet)

        if game_payload is not None:
            try:
                time.sleep(0.05)
                controller.write_custom_frame(fd, game_payload, 2)
                game_written = True
            except controller.DeviceError as exc:
                game_failed = True
                print(
                    "warning: colour frame sent, but the experimental 09 d0 "
                    "game-flag write failed: %s" % exc,
                    file=sys.stderr,
                )
                print(
                    "warning: run `k622rgb config restore --custom %s` to "
                    "recover the stored frames" % backup_path,
                    file=sys.stderr,
                )

        if activation_needed and not game_failed:
            try:
                time.sleep(0.05)
                controller.write_config(
                    fd,
                    controller.build_config(
                        current, mode=controller.PER_KEY_MODE
                    ),
                )
            except controller.DeviceError as exc:
                activation_failed = True
                print(
                    "warning: colour frame sent, but switching to "
                    "Self-define mode failed: %s" % exc,
                    file=sys.stderr,
                )
                print(
                    "warning: run `k622rgb mode set per-key` and retry",
                    file=sys.stderr,
                )
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
            len(controller.lit_slots(render_colors)),
        )
    )
    if args.game_flag:
        if game_failed:
            pass
        elif game_written:
            print(
                "wrote 09 d0 companion; game byte payload[%d] = 0x%02X"
                % (game_offset, game_value)
            )
    if args.activate:
        if activation_failed:
            pass
        elif activation_needed:
            print("activated Self-define mode; backup: %s" % backup_path)
        else:
            print("Self-define mode already active")
    if args.hex:
        _print_packet_hex(packet)
    if not args.no_state:
        try:
            state.save_frame(state_path, packet)
            print("saved frame to %s" % state_path)
        except state.StateError as exc:
            print("warning: %s" % exc, file=sys.stderr)
    return EXIT_ERROR if (activation_failed or game_failed) else EXIT_OK


def _group_summary(name: str, group: Dict) -> str:
    color = (
        "unset"
        if group.get("color") is None
        else colors.format_color(group["color"])
    )
    keys = ", ".join(group["keys"]) or "(no keys)"
    return "  %-10s %-10s %s" % (name, color, keys)


def _print_group(name: str, group: Dict, local: bool = False) -> None:
    suffix = "  (local)" if local else ""
    print(_group_summary(name, group) + suffix)


def cmd_group_list(args: argparse.Namespace) -> int:
    path = groups.group_path(args.file)
    local = groups.load_local_groups(args.file)
    effective = groups.effective_groups(local)

    print("group file: %s" % path)
    print()
    print("define groups:")
    for name in groups.VENDOR_GROUP_NAMES:
        _print_group(name, effective[name], name in local)
    print()
    print("presets:")
    for name in groups.PRESET_GROUP_NAMES:
        _print_group(name, effective[name], name in local)
    print()
    print("local groups:")
    custom = [
        name for name in local
        if name not in groups.BUILTIN_GROUP_NAMES
    ]
    if not custom:
        print("  (none)")
    else:
        for name in custom:
            _print_group(name, effective[name], True)
    return EXIT_OK


def cmd_group_set(args: argparse.Namespace) -> int:
    assignments, keys = groups.parse_set_items(args.items)
    local = groups.load_local_groups(args.file)
    results = []
    for name, color in assignments:
        group = groups.update_local_group(local, name, color, keys)
        results.append((name, group))

    if args.dry_run:
        print("dry run: would update %d group%s"
              % (len(results), "" if len(results) == 1 else "s"))
        for name, group in results:
            print(_group_summary(name, group))
        print("dry run: group file not written")
        return EXIT_OK

    path = groups.save_local_groups(local, args.file)
    for name, group in results:
        print(_group_summary(name, group).lstrip())
    print("saved groups to %s" % path)
    return EXIT_OK


def cmd_group_apply(args: argparse.Namespace) -> int:
    local = groups.load_local_groups(args.file)
    effective = groups.effective_groups(local)
    names = args.names or list(groups.DEFAULT_APPLY_ORDER)
    layers = []
    for raw_name in names:
        name = groups.canonical_group_name(raw_name)
        group = effective.get(name)
        if group is None:
            raise ValueError(
                "unknown group %r; available groups: %s"
                % (name, ", ".join(sorted(effective)))
            )
        if group["color"] is None:
            print(
                "warning: group %s has no colour; skipping (use "
                "`group set %s=COLOR`)" % (name, name),
                file=sys.stderr,
            )
            continue
        slots = []
        for key in group["keys"]:
            slot = layout.resolve_key(key)
            if slot not in slots:
                slots.append(slot)
        layers.append((name, group["color"], slots))

    if not layers:
        raise ValueError(
            "no group colours configured; run `k622rgb group set "
            "NAME=COLOR` first"
        )
    return _run_set(args, {}, layers)


def cmd_group_import(args: argparse.Namespace) -> int:
    local = groups.load_local_groups(args.file)
    existing = groups.effective_groups(local)
    imported, warnings = groups.import_cfg_ini(args.path, existing)
    for warning in warnings:
        print("warning: %s" % warning, file=sys.stderr)

    for name, group in imported.items():
        local[name] = group

    if args.dry_run:
        print("dry run: parsed %d group%s from %s"
              % (len(imported), "" if len(imported) == 1 else "s", args.path))
        for name in groups.VENDOR_GROUP_NAMES:
            if name in imported:
                print(_group_summary(name, imported[name]))
        print("dry run: group file not written")
        return EXIT_OK

    path = groups.save_local_groups(local, args.file)
    print("imported: %s" % os.path.expanduser(args.path))
    print("group file: %s" % path)
    for name in groups.VENDOR_GROUP_NAMES:
        if name in imported:
            print(_group_summary(name, imported[name]))
    return EXIT_OK


def cmd_list(args: argparse.Namespace) -> int:
    print(
        "keys: %d mapped, %d logo zones, %d aliases, %d dead slots "
        "(packet slots 0-%d)"
        % (
            len(layout.SLOT_NAMES),
            len(layout.ZONE_NAMES),
            len(layout.ALIAS_SLOTS),
            len(layout.DEAD_SLOTS),
            controller.NUM_SLOTS - 1,
        )
    )
    print()
    print(
        "packet slots are row-major 21-column indices; Cfg.ini uses a "
        "different column-major numbering."
    )
    print(
        "G1-G4, MR, the RGB toggle, Previous, Play/Pause, Next and Mute have "
        "no individually addressable RGB LEDs."
    )
    print(
        "logo zones: %s"
        % ", ".join(
            "%s=%d" % (name, slot)
            for slot, name in sorted(layout.ZONE_NAMES.items())
        )
    )
    if layout.UNLIT:
        print(
            "unlit during calibration: %s (mapped but did not light)"
            % ", ".join(sorted(layout.UNLIT))
        )
    if args.all:
        print()
        print("packet slots:")
        for slot in range(controller.NUM_SLOTS):
            kind = layout.slot_kind(slot)
            name = layout.canonical_name(slot)
            if kind == "dead":
                name = "-"
            elif kind == "key" and name in layout.UNLIT:
                kind = "key (unlit)"
            print("  %3d  %-12s %s" % (slot, name, kind))
    return EXIT_OK


def _all_black() -> Dict[int, controller.Color]:
    return {slot: (0, 0, 0) for slot in range(controller.NUM_SLOTS)}


def _scale_colors(
    colors: Dict[int, controller.Color], level: int
) -> Dict[int, controller.Color]:
    """Scale every channel by an integer brightness level 0..9."""
    factor = level / 9.0
    return {
        slot: tuple(int(round(channel * factor)) for channel in color)
        for slot, color in colors.items()
    }


def _state_path(args: argparse.Namespace) -> str:
    if args.state:
        return os.path.expanduser(args.state)
    return state.default_frame_path()


def _parse_assignments(
    items: List[str],
) -> Dict[int, controller.Color]:
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
# lighting configuration / effects
# --------------------------------------------------------------------------


def _open_mailbox(args: argparse.Namespace):
    """Open the control interface read/write and verify its descriptor."""
    node, info, sysfs = _resolve_device(args)
    if args.verbose:
        for candidate in controller.iter_devices():
            print(
                "verbose: %s interface=%s sysfs=%s"
                % (candidate.node, candidate.interface, candidate.sysfs)
            )
    data, reports = _load_reports(sysfs)
    if not controller.is_known_descriptor(data):
        raise controller.ProtocolError(
            "descriptor sha256 %s does not match the captured K622 IF1 "
            "descriptor; refusing to touch the lighting config."
            % controller.descriptor_sha256(data)
        )
    controller.feature_report_size(reports, controller.CONFIG_REPORT_ID)
    fd = controller.open_device(node, writable=True)
    return fd, node, data


def _save_lighting_backup(fd, data, note, config_response=None,
                          palette_response=None, custom=False, profile=False):
    """Read (if needed) and persist a full lighting backup."""
    if config_response is None:
        config_response = controller.read_config_response(fd)
    if palette_response is None:
        palette_response = controller.mailbox_read(
            fd, controller.COLOR_READ_COMMAND
        )
    files = {
        "config-response.bin": config_response,
        "colors-response.bin": palette_response,
    }
    if custom:
        files["custom1-response.bin"] = controller.mailbox_read(
            fd, controller.CUSTOM1_READ_COMMAND
        )
        files["custom2-response.bin"] = controller.mailbox_read(
            fd, controller.CUSTOM2_READ_COMMAND
        )
    if profile:
        files["profile-response.bin"] = controller.mailbox_read(
            fd, controller.PROFILE_READ_COMMAND
        )
    meta = {
        "kind": note,
        "descriptor_sha256": controller.descriptor_sha256(data),
        "tool": "k622rgb " + __version__,
    }
    return state.save_backup(files, meta)


def _print_config(config: bytes, palette: Optional[bytes] = None) -> None:
    parsed = controller.parse_config(config)
    info = parsed.info
    print(
        "mode: %s (%d)%s"
        % (
            info.name,
            info.value,
            "  [per-key flag set]" if parsed.per_key else "",
        )
    )
    if palette is not None and 1 <= info.value <= 20:
        entries = [
            colors.format_color(controller.palette_color(palette, info.value, i))
            for i in range(controller.COLOR_INDEX_MAX + 1)
        ]
        print("palette: %s" % "  ".join(entries))
        print(
            "colour: %s"
            % (
                "random" if parsed.params(info.value).color == controller.COLOR_RANDOM
                else "index %d" % parsed.params(info.value).color
            )
        )
    print()
    print("effect parameters:")
    print("  %-4s %-20s %-8s %-10s %s" % ("id", "mode", "colour", "speed", "brightness"))
    for mode in controller.MODES:
        if not 1 <= mode.value <= 20:
            continue
        params = parsed.pairs[mode.value - 1]
        colour = (
            "random" if params.color == controller.COLOR_RANDOM
            else "index %d" % params.color
        )
        print(
            "  %-4d %-20s %-8s %-10d %d"
            % (mode.value, mode.name, colour, params.speed, params.brightness)
        )


def _parse_mode_arg(text: str):
    try:
        return controller.lookup_mode(text)
    except ValueError:
        return controller.lookup_mode(int(text, 0))


def cmd_mode_list(args: argparse.Namespace) -> int:
    print("K622 built-in lighting modes")
    print()
    print("  %-4s %-22s %s" % ("id", "name", "official options"))
    for mode in controller.MODES:
        if mode.value == 0:
            continue
        flags = []
        if mode.speed:
            flags.append("speed")
        if mode.brightness:
            flags.append("brightness")
        if mode.random:
            flags.append("random")
        if mode.color:
            flags.append("7-colour")
        print(
            "  %-4d %-22s %s"
            % (mode.value, mode.name, ", ".join(flags) or "-")
        )
    print()
    print("  %-4d %-22s %s" % (0, "OFF", "off"))
    print()
    print(
        "Speed and brightness are stored for every effect mode; the list "
        "shows which effects actually use them."
    )
    print()
    print("Aliases are accepted by `mode set` (e.g. static, breathing, wave).")
    return EXIT_OK


def cmd_mode_show(args: argparse.Namespace) -> int:
    fd, node, data = _open_mailbox(args)
    try:
        config = controller.read_config(fd)
        palette = None
        info = controller.parse_config(config).info
        if 1 <= info.value <= 20:
            palette = controller.read_effect_palette(fd)
    finally:
        os.close(fd)
    print("device: %s" % node)
    print("descriptor: %s" % _descriptor_label(data))
    _print_config(config, palette)
    return EXIT_OK


def cmd_mode_set(args: argparse.Namespace) -> int:
    info = _parse_mode_arg(args.mode)

    if args.random and args.color_index is not None:
        raise ValueError("--random and --color-index are mutually exclusive")
    if args.color and (args.random or args.color_index is not None):
        raise ValueError("--color cannot be combined with --random/--color-index")
    if info.value in (controller.OFF_MODE, controller.PER_KEY_MODE):
        if args.brightness is not None or args.speed is not None:
            raise ValueError("%s has no brightness/speed setting" % info.name)
        if args.color or args.random or args.color_index is not None:
            raise ValueError(
                "%s has no effect palette; use `k622rgb set` for per-key colours"
                % info.name
            )
    if args.color and not info.color:
        raise ValueError("%s does not support a specific colour" % info.name)
    if args.random and not info.random:
        raise ValueError("%s does not support random colour" % info.name)
    if args.color_index is not None:
        if not 0 <= args.color_index <= controller.COLOR_INDEX_MAX:
            raise ValueError("--color-index must be 0..%d" % controller.COLOR_INDEX_MAX)
        if not info.color:
            raise ValueError("%s does not support a specific colour" % info.name)

    color_index = None
    rgb = None
    if args.random:
        color_index = controller.COLOR_RANDOM
    elif args.color_index is not None:
        color_index = args.color_index
    elif args.color:
        rgb = colors.parse_color(args.color)
        color_index = 0

    if args.dry_run:
        print("dry run: mode=%s (%d)" % (info.name, info.value))
        if args.brightness is not None:
            print("dry run: brightness=%d" % args.brightness)
        if args.speed is not None:
            print("dry run: speed=%d" % args.speed)
        if color_index is not None:
            print(
                "dry run: colour=%s"
                % ("random" if color_index == controller.COLOR_RANDOM
                   else "index %d" % color_index)
            )
        if rgb is not None:
            print("dry run: palette[%d] = %s" % (color_index, colors.format_color(rgb)))
        print("dry run: device not opened; no backup written")
        return EXIT_OK

    fd, node, data = _open_mailbox(args)
    try:
        config_response = controller.read_config_response(fd)
        palette_response = None
        palette = None
        if rgb is not None or (
            1 <= info.value <= 20 and args.color_index is not None
        ):
            palette_response = controller.mailbox_read(
                fd, controller.COLOR_READ_COMMAND
            )
            palette = controller.palette_from_response(palette_response)
        backup = None
        if not args.no_backup:
            backup = _save_lighting_backup(
                fd, data, "mode set %s" % info.key,
                config_response=config_response,
                palette_response=palette_response,
            )
        base = controller.config_from_response(config_response)

        if rgb is not None:
            palette = controller.set_palette_color(palette, info.value, color_index, rgb)
            controller.write_effect_palette(fd, palette)

        new_config = controller.build_config(
            base,
            mode=info.value,
            brightness=args.brightness,
            speed=args.speed,
            color=color_index,
        )
        controller.write_config(fd, new_config)
        packet = controller.build_config_packet(new_config)
    finally:
        os.close(fd)

    print("device: %s" % node)
    if backup:
        print("backup: %s" % backup)
    print(
        "mode: %s (%d)%s"
        % (
            info.name,
            info.value,
            "  [per-key flag set]" if info.value == controller.PER_KEY_MODE else "",
        )
    )
    if 1 <= info.value <= 20:
        params = controller.parse_config(new_config).params(info.value)
        print(
            "parameters: colour=%s speed=%d brightness=%d"
            % (
                "random" if params.color == controller.COLOR_RANDOM
                else "index %d" % params.color,
                params.speed,
                params.brightness,
            )
        )
        if palette is not None:
            print(
                "palette: %s"
                % "  ".join(
                    colors.format_color(
                        controller.palette_color(palette, info.value, index)
                    )
                    for index in range(controller.COLOR_INDEX_MAX + 1)
                )
            )
    print(
        "sent: %d-byte report 0x%02X config frame"
        % (len(packet), controller.CONFIG_REPORT_ID)
    )
    if args.hex:
        _print_packet_hex(packet)
    return EXIT_OK


def _palette_rows(palette: bytes, only=None) -> None:
    for mode in controller.MODES:
        if not 1 <= mode.value <= 20:
            continue
        if only is not None and mode.value != only:
            continue
        entries = [
            colors.format_color(controller.palette_color(palette, mode.value, index))
            for index in range(controller.COLOR_INDEX_MAX + 1)
        ]
        print("  %-4d %-20s %s" % (mode.value, mode.name, "  ".join(entries)))


def cmd_color_list(args: argparse.Namespace) -> int:
    only = None
    if args.mode:
        only = _parse_mode_arg(args.mode).value
        if not 1 <= only <= 20:
            raise ValueError("only effect modes 1-20 have a palette")
    fd, node, data = _open_mailbox(args)
    try:
        palette = controller.read_effect_palette(fd)
        config = controller.read_config(fd)
    finally:
        os.close(fd)
    print("device: %s" % node)
    print("mode: %s" % controller.parse_config(config).info.name)
    print()
    print("  %-4s %-20s %s" % ("id", "mode", "colours 0..6"))
    _palette_rows(palette, only)
    return EXIT_OK


def cmd_color_show(args: argparse.Namespace) -> int:
    info = _parse_mode_arg(args.mode)
    if not 1 <= info.value <= 20:
        raise ValueError("only effect modes 1-20 have a palette")
    fd, node, data = _open_mailbox(args)
    try:
        palette = controller.read_effect_palette(fd)
        config = controller.read_config(fd)
    finally:
        os.close(fd)
    print("device: %s" % node)
    print("mode: %s" % controller.parse_config(config).info.name)
    print()
    print("%s (%d):" % (info.name, info.value))
    _palette_rows(palette, info.value)
    return EXIT_OK


def cmd_color_set(args: argparse.Namespace) -> int:
    info = _parse_mode_arg(args.mode)
    if not 1 <= info.value <= 20:
        raise ValueError("only effect modes 1-20 have a palette")
    if not 0 <= args.index <= controller.COLOR_INDEX_MAX:
        raise ValueError("palette index must be 0..%d" % controller.COLOR_INDEX_MAX)
    rgb = colors.parse_color(args.color)

    if args.dry_run:
        print(
            "dry run: palette[%d][%d] = %s"
            % (info.value, args.index, colors.format_color(rgb))
        )
        print("dry run: device not opened; no backup written")
        return EXIT_OK

    fd, node, data = _open_mailbox(args)
    try:
        config_response = controller.read_config_response(fd)
        palette_response = controller.mailbox_read(
            fd, controller.COLOR_READ_COMMAND
        )
        backup = None
        if not args.no_backup:
            backup = _save_lighting_backup(
                fd, data, "palette set %s[%d]" % (info.key, args.index),
                config_response=config_response,
                palette_response=palette_response,
            )
        palette = controller.palette_from_response(palette_response)
        new_palette = controller.set_palette_color(
            palette, info.value, args.index, rgb
        )
        controller.write_effect_palette(fd, new_palette)
        packet = controller.build_effect_palette_packet(new_palette)
    finally:
        os.close(fd)

    print("device: %s" % node)
    if backup:
        print("backup: %s" % backup)
    print(
        "palette: mode %s (%d), entry %d = %s"
        % (info.name, info.value, args.index, colors.format_color(rgb))
    )
    print(
        "sent: %d-byte report 0x%02X palette frame"
        % (len(packet), controller.CONFIG_REPORT_ID)
    )
    if args.hex:
        _print_packet_hex(packet)
    return EXIT_OK


def _write_dump_dir(path: str, files: Dict[str, bytes], meta: dict) -> None:
    import json

    os.makedirs(path, exist_ok=True)
    for name, data in files.items():
        if not name or "/" in name or name in (".", ".."):
            raise ValueError("invalid dump filename %r" % (name,))
        with open(os.path.join(path, name), "wb") as handle:
            handle.write(data)
    meta = dict(meta)
    meta.setdefault("version", 1)
    with open(os.path.join(path, "meta.json"), "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2, sort_keys=True)
        handle.write("\n")


def cmd_config_dump(args: argparse.Namespace) -> int:
    if args.dry_run:
        print("dry run: would read the config, palette, custom frames and profile")
        print("dry run: device not opened; no backup written")
        return EXIT_OK
    fd, node, data = _open_mailbox(args)
    try:
        files = {
            "config-response.bin": controller.read_config_response(fd),
            "colors-response.bin": controller.mailbox_read(
                fd, controller.COLOR_READ_COMMAND
            ),
            "custom1-response.bin": controller.mailbox_read(
                fd, controller.CUSTOM1_READ_COMMAND
            ),
            "custom2-response.bin": controller.mailbox_read(
                fd, controller.CUSTOM2_READ_COMMAND
            ),
            "profile-response.bin": controller.mailbox_read(
                fd, controller.PROFILE_READ_COMMAND
            ),
        }
    finally:
        os.close(fd)
    meta = {
        "kind": "config dump",
        "descriptor_sha256": controller.descriptor_sha256(data),
        "tool": "k622rgb " + __version__,
    }
    if args.out:
        path = os.path.expanduser(args.out)
        _write_dump_dir(path, files, meta)
    else:
        path = state.save_backup(files, meta)
    print("device: %s" % node)
    print("dump: %s" % path)
    for name in sorted(files):
        print("  %-24s %d bytes" % (name, len(files[name])))
    if args.hex:
        print()
        _print_packet_hex(controller.config_from_response(files["config-response.bin"]))
    return EXIT_OK


def cmd_config_show(args: argparse.Namespace) -> int:
    fd, node, data = _open_mailbox(args)
    try:
        config = controller.read_config(fd)
        palette = controller.read_effect_palette(fd)
    finally:
        os.close(fd)
    print("device: %s" % node)
    print("descriptor: %s" % _descriptor_label(data))
    _print_config(config, palette)
    if args.hex:
        print()
        _print_packet_hex(config)
    return EXIT_OK


def _read_backup_file(path: str, names: List[str]) -> Optional[bytes]:
    for name in names:
        candidate = os.path.join(path, name)
        if os.path.isfile(candidate):
            with open(candidate, "rb") as handle:
                return handle.read()
    return None


def _config_from_any(data: bytes) -> bytes:
    if len(data) == controller.CONFIG_SIZE:
        return data
    if len(data) >= controller.CONFIG_RESPONSE_OFFSET + controller.CONFIG_SIZE:
        return controller.config_from_response(data)
    raise ValueError(
        "config file is %d bytes; expected %d or a full read response"
        % (len(data), controller.CONFIG_SIZE)
    )


def _palette_from_any(data: bytes) -> bytes:
    if len(data) == controller.COLOR_TABLE_SIZE:
        return data
    if len(data) >= controller.CONFIG_RESPONSE_OFFSET + controller.COLOR_TABLE_SIZE:
        return data[
            controller.CONFIG_RESPONSE_OFFSET:
            controller.CONFIG_RESPONSE_OFFSET + controller.COLOR_TABLE_SIZE
        ]
    raise ValueError(
        "palette file is %d bytes; expected %d or a full read response"
        % (len(data), controller.COLOR_TABLE_SIZE)
    )


def cmd_config_restore(args: argparse.Namespace) -> int:
    path = os.path.expanduser(args.path)
    if os.path.isdir(path):
        config_data = _read_backup_file(
            path, ["config-response.bin", "config.bin"]
        )
        palette_data = _read_backup_file(
            path, ["colors-response.bin", "colors.bin"]
        )
        custom1 = _read_backup_file(path, ["custom1-response.bin"]) if args.custom else None
        custom2 = _read_backup_file(path, ["custom2-response.bin"]) if args.custom else None
    else:
        with open(path, "rb") as handle:
            config_data = handle.read()
        palette_data = None
        custom1 = custom2 = None
    if config_data is None:
        raise ValueError("no config-response.bin or config.bin in %s" % path)
    config = _config_from_any(config_data)
    controller.validate_config(config)
    palette = _palette_from_any(palette_data) if palette_data is not None else None

    if args.dry_run:
        print("dry run: would restore config from %s" % path)
        if palette is not None:
            print("dry run: would restore the effect palette")
        if custom1 is not None:
            print("dry run: would restore custom frame 1")
        if custom2 is not None:
            print("dry run: would restore custom frame 2")
        return EXIT_OK

    fd, node, data = _open_mailbox(args)
    try:
        if not args.no_backup:
            backup = _save_lighting_backup(fd, data, "restore")
            print("backup: %s" % backup)
        if palette is not None:
            controller.write_effect_palette(fd, palette)
        if custom1 is not None:
            time.sleep(0.05)
            controller.write_custom_frame(
                fd,
                controller.payload_from_response(custom1, controller.CUSTOM_PAYLOAD_SIZE),
                1,
            )
        if custom2 is not None:
            time.sleep(0.05)
            controller.write_custom_frame(
                fd,
                controller.payload_from_response(custom2, controller.CUSTOM_PAYLOAD_SIZE),
                2,
            )
        time.sleep(0.05)
        controller.write_config(fd, config)
    finally:
        os.close(fd)
    print("device: %s" % node)
    print("restored: %s" % path)
    return EXIT_OK


def cmd_off(args: argparse.Namespace) -> int:
    if args.dry_run:
        print("dry run: would select OFF mode with a 03 c6 config write")
        print("dry run: device not opened; no backup written")
        return EXIT_OK
    fd, node, data = _open_mailbox(args)
    try:
        config_response = controller.read_config_response(fd)
        backup = None
        if not args.no_backup:
            backup = _save_lighting_backup(
                fd, data, "off", config_response=config_response
            )
        config = controller.config_from_response(config_response)
        new_config = controller.build_config(config, mode=controller.OFF_MODE)
        controller.write_config(fd, new_config)
        packet = controller.build_config_packet(new_config)
    finally:
        os.close(fd)
    print("device: %s" % node)
    if backup:
        print("backup: %s" % backup)
    print("mode: OFF")
    print(
        "sent: %d-byte report 0x%02X config frame"
        % (len(packet), controller.CONFIG_REPORT_ID)
    )
    return EXIT_OK


def cmd_profile_list(args: argparse.Namespace) -> int:
    entries = profiles.list_profiles(args.dir)
    print("profile directory: %s" % (os.path.expanduser(args.dir) if args.dir else profiles.profile_dir()))
    if not entries:
        print("no profiles saved")
        return EXIT_OK
    print()
    print("  %-24s %-22s %s" % ("name", "mode", "created"))
    for entry in entries:
        if entry.get("error"):
            print("  %-24s %-22s %s" % (entry["name"], "INVALID", entry.get("path", "")))
            continue
        parsed = controller.parse_config(entry["config"])
        print(
            "  %-24s %-22s %s"
            % (entry["name"], parsed.info.name, entry.get("created") or "-")
        )
    return EXIT_OK


def cmd_profile_show(args: argparse.Namespace) -> int:
    entry = profiles.load_profile(args.name, args.dir)
    parsed = controller.parse_config(entry["config"])
    print("profile: %s" % entry["name"])
    print("path: %s" % entry["path"])
    print("created: %s" % (entry.get("created") or "-"))
    print("mode: %s (%d)" % (parsed.info.name, parsed.mode))
    if 1 <= parsed.mode <= 20:
        params = parsed.params(parsed.mode)
        print(
            "parameters: colour=%s speed=%d brightness=%d"
            % (
                "random" if params.color == controller.COLOR_RANDOM
                else "index %d" % params.color,
                params.speed,
                params.brightness,
            )
        )
        print(
            "palette: %s"
            % "  ".join(
                colors.format_color(
                    controller.palette_color(entry["palette"], parsed.mode, index)
                )
                for index in range(controller.COLOR_INDEX_MAX + 1)
            )
        )
    print("custom frame: %s" % ("yes" if entry.get("custom_frame") else "no"))
    return EXIT_OK


def cmd_profile_save(args: argparse.Namespace) -> int:
    if args.dry_run:
        print("dry run: would save profile %r" % args.name)
        print("dry run: device not opened; no file written")
        return EXIT_OK
    fd, node, data = _open_mailbox(args)
    try:
        config_response = controller.read_config_response(fd)
        palette_response = controller.mailbox_read(
            fd, controller.COLOR_READ_COMMAND
        )
        frame = None
        if not args.no_frame:
            frame = controller.payload_from_response(
                controller.mailbox_read(fd, controller.CUSTOM1_READ_COMMAND),
                controller.CUSTOM_PAYLOAD_SIZE,
            )
    finally:
        os.close(fd)
    path = profiles.save_profile(
        args.name,
        controller.config_from_response(config_response),
        controller.palette_from_response(palette_response),
        frame,
        args.dir,
    )
    print("device: %s" % node)
    print("profile: %s" % path)
    print("mode: %s" % controller.parse_config(
        controller.config_from_response(config_response)
    ).info.name)
    return EXIT_OK


def cmd_profile_load(args: argparse.Namespace) -> int:
    entry = profiles.load_profile(args.name, args.dir)
    if args.dry_run:
        print("dry run: would load profile %r" % entry["name"])
        print("dry run: device not opened; no backup written")
        return EXIT_OK
    controller.validate_config(entry["config"])
    fd, node, data = _open_mailbox(args)
    try:
        backup = None
        if not args.no_backup:
            backup = _save_lighting_backup(
                fd, data, "profile load %s" % entry["name"]
            )
        controller.write_effect_palette(fd, entry["palette"])
        if entry.get("custom_frame") and not args.no_frame:
            controller.write_custom_frame(fd, entry["custom_frame"], 1)
        controller.write_config(fd, entry["config"])
        packet = controller.build_config_packet(entry["config"])
    finally:
        os.close(fd)
    print("device: %s" % node)
    if backup:
        print("backup: %s" % backup)
    parsed = controller.parse_config(entry["config"])
    print("loaded: %s (%s)" % (entry["name"], parsed.info.name))
    print(
        "sent: %d-byte report 0x%02X config frame"
        % (len(packet), controller.CONFIG_REPORT_ID)
    )
    return EXIT_OK


def cmd_profile_delete(args: argparse.Namespace) -> int:
    if args.dry_run:
        print("dry run: would delete profile %r" % args.name)
        return EXIT_OK
    path = profiles.delete_profile(args.name, args.dir)
    print("deleted: %s" % path)
    return EXIT_OK


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
    except groups.GroupError as exc:
        print("k622rgb: %s" % exc, file=sys.stderr)
        return EXIT_ERROR
    except profiles.ProfileError as exc:
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

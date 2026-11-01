#!/usr/bin/env python3
"""Interactive LED-slot probe and keymap generator for the Redragon K622.

The keyboard's ``09 cc`` packet has 126 RGB slots.  The official ``Cfg.ini``
uses a different numbering system for the same physical LEDs:

    Cfg slot    = col * 6  + row      (column-major, 6 rows)
    packet slot = row * 21 + col      (row-major, 21 columns)

The current ``layout.py`` uses the Cfg slot as the packet index, so every key
is shifted.  This tool tests every packet slot on the physical keyboard,
records what actually lights, and writes the result to
``docs/keymap-observed.json``.

Typical use::

    python3 tools/keymap_probe.py probe
    python3 tools/keymap_probe.py report
    python3 tools/keymap_probe.py apply
    python3 tools/keymap_probe.py verify

The probe is non-destructive: it backs up the config, palette and custom frame
before writing, and restores them when it exits (including Ctrl-C).
"""

import argparse
import json
import os
import sys
import time
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from k622rgb import colors, controller, layout, state  # noqa: E402

try:  # optional: arrow-key history in the interactive prompt
    import readline  # noqa: F401
except ImportError:  # pragma: no cover - Windows/macOS without readline
    pass


ROWS = 6
COLS = 21
NUM_SLOTS = controller.NUM_SLOTS
DEFAULT_OUT = os.path.join(ROOT, "docs", "keymap-observed.json")
DEFAULT_MODULE = os.path.join(ROOT, "k622rgb", "keymap_data.py")
DEFAULT_JOURNAL = os.path.join(state.state_dir(), "keymap-probe.jsonl")

#: The official Cfg.ini main-key map, kept here so the probe still works after
#: ``layout.py`` has been switched to packet slots.  This is the *source*
#: numbering (column-major 6 rows), not the packet numbering.
CFG_SLOT_NAMES = {
    0: "Esc",
    1: "`",
    2: "Tab",
    3: "Caps",
    4: "LShift",
    5: "LCtrl",
    7: "1",
    8: "Q",
    9: "A",
    10: "Z",
    11: "Win",
    12: "F1",
    13: "2",
    14: "W",
    15: "S",
    16: "X",
    17: "LAlt",
    18: "F2",
    19: "3",
    20: "E",
    21: "D",
    22: "C",
    24: "F3",
    25: "4",
    26: "R",
    27: "F",
    28: "V",
    30: "F4",
    31: "5",
    32: "T",
    33: "G",
    34: "B",
    35: "Space",
    36: "F5",
    37: "6",
    38: "Y",
    39: "H",
    40: "N",
    42: "F6",
    43: "7",
    44: "U",
    45: "J",
    46: "M",
    48: "F7",
    49: "8",
    50: "I",
    51: "K",
    52: ",",
    53: "RAlt",
    54: "F8",
    55: "9",
    56: "O",
    57: "L",
    58: ".",
    59: "Fn",
    60: "F9",
    61: "0",
    62: "P",
    63: ";",
    64: "/",
    65: "Menu",
    66: "F10",
    67: "-",
    68: "[",
    69: "'",
    72: "F11",
    73: "=",
    74: "]",
    78: "F12",
    79: "Bksp",
    80: "\\",
    81: "Enter",
    82: "RShift",
    83: "RCtrl",
    84: "PrtSc",
    85: "Ins",
    86: "Del",
    89: "Left",
    90: "ScrLk",
    91: "Home",
    92: "End",
    94: "Up",
    95: "Down",
    96: "Pause",
    97: "PgUp",
    98: "PgDn",
    101: "Right",
}

#: The 15 Cfg.ini gaps.
CFG_DEAD_SLOTS = frozenset(
    (6, 23, 29, 41, 47, 70, 71, 75, 76, 77, 87, 88, 93, 99, 100)
)

#: Addressable non-key LED zones discovered by the probe.
ZONE_SLOTS = {
    77: "LogoLeft",
    78: "LogoCenter",
    79: "LogoRight",
}

#: Accepted spellings for the logo zones.
ZONE_ALIASES = {
    "logo1": "LogoLeft",
    "logoleft": "LogoLeft",
    "logo-left": "LogoLeft",
    "logo2": "LogoCenter",
    "logocenter": "LogoCenter",
    "logocentre": "LogoCenter",
    "logo-center": "LogoCenter",
    "logo3": "LogoRight",
    "logoright": "LogoRight",
    "logo-right": "LogoRight",
}

#: Extra-key names that may be discovered in the 24 "unknown" packet slots.
EXTRA_CANONICAL = {
    "g1": "G1",
    "g2": "G2",
    "g3": "G3",
    "g4": "G4",
    "g5": "G5",
    "mr": "MR",
    "rgb": "RGB",
    "prev": "Prev",
    "previous": "Prev",
    "play": "Play",
    "playpause": "Play",
    "next": "Next",
    "mute": "Mute",
    "volume": "Volume",
    "vol": "Volume",
    "roller": "Volume",
}

#: Accepted spellings for the extra keys above.
EXTRA_ALIASES = {
    "macro1": "G1",
    "macro2": "G2",
    "macro3": "G3",
    "macro4": "G4",
    "macro5": "G5",
    "macrorecord": "MR",
    "macro": "MR",
    "rec": "MR",
    "light": "RGB",
    "rgbtoggle": "RGB",
    "nexttrack": "Next",
    "volumemute": "Mute",
}

KNOWN_NAMES = (
    set(CFG_SLOT_NAMES.values())
    | set(layout.SLOT_NAMES.values())
    | set(EXTRA_CANONICAL.values())
    | set(ZONE_SLOTS.values())
)


# ---------------------------------------------------------------------------
# Slot arithmetic
# ---------------------------------------------------------------------------


def packet_to_cfg(packet_slot: int) -> int:
    """Return the ``Cfg.ini`` LED slot for a packet slot."""
    row, col = divmod(packet_slot, COLS)
    return col * ROWS + row


def cfg_to_packet(cfg_slot: int) -> int:
    """Return the packet slot for a ``Cfg.ini`` LED slot."""
    col, row = divmod(cfg_slot, ROWS)
    return row * COLS + col


def expected_for(packet_slot: int) -> Tuple[Optional[str], str, int]:
    """Return ``(expected key or None, category, cfg slot)`` for a packet slot.

    ``category`` is ``main`` for a Cfg.ini main key, ``dead`` for a Cfg.ini gap,
    and ``extra`` for Cfg slots 102-125, whose meaning is not known yet.
    """
    cfg = packet_to_cfg(packet_slot)
    if packet_slot in ZONE_SLOTS:
        return ZONE_SLOTS[packet_slot], "zone", cfg
    if cfg in CFG_SLOT_NAMES:
        return CFG_SLOT_NAMES[cfg], "main", cfg
    if cfg in CFG_DEAD_SLOTS:
        return None, "dead", cfg
    return None, "extra", cfg


# ---------------------------------------------------------------------------
# Input normalization
# ---------------------------------------------------------------------------


def normalize_name(text: str) -> Optional[str]:
    """Normalize a typed key name to its canonical spelling.

    Returns ``None`` for an empty answer.  Unknown names are returned as typed
    (the caller asks for confirmation).
    """
    text = text.strip()
    if not text:
        return None
    lowered = text.lower()
    if lowered in layout.ALIASES:
        return layout.ALIASES[lowered]
    if lowered in EXTRA_CANONICAL:
        return EXTRA_CANONICAL[lowered]
    if lowered in EXTRA_ALIASES:
        return EXTRA_ALIASES[lowered]
    if lowered in ZONE_ALIASES:
        return ZONE_ALIASES[lowered]
    for name in KNOWN_NAMES:
        if name.lower() == lowered:
            return name
    return text


def classify_answer(
    answer: str, expected: Optional[str]
) -> Tuple[str, Optional[str]]:
    """Classify one probe answer.

    Returns ``(action, observed)`` where ``action`` is ``help``, ``quit``,
    ``skip``, ``retry`` or ``record``.  Commands are deliberately words:
    single letters such as ``n``, ``s`` and ``q`` are valid key names.
    """
    text = answer.strip()
    lowered = text.lower()
    if lowered in ("?", "help"):
        return "help", None
    if lowered == "quit":
        return "quit", None
    if lowered == "skip":
        return "skip", None
    if lowered in ("dead", "none", "blank"):
        return "record", None
    if not text:
        return "record", expected
    observed = normalize_name(text)
    if observed is None:
        return "retry", None
    return "record", observed


def parse_slots(text: str) -> List[int]:
    """Parse ``0-10,14,44`` into a sorted list of packet slots."""
    result = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start = int(start_text, 0)
            end = int(end_text, 0)
            if start > end:
                start, end = end, start
            result.update(range(start, end + 1))
        else:
            result.add(int(part, 0))
    for slot in result:
        if not 0 <= slot < NUM_SLOTS:
            raise ValueError("slot %d is outside 0..%d" % (slot, NUM_SLOTS - 1))
    return sorted(result)


# ---------------------------------------------------------------------------
# Journal and JSON helpers
# ---------------------------------------------------------------------------


def load_journal(path: str) -> Dict[int, dict]:
    """Load a JSONL journal, keeping the latest record for each slot."""
    records: Dict[int, dict] = {}
    try:
        with open(os.path.expanduser(path), "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    slot = int(record["slot"])
                except (ValueError, KeyError, TypeError):
                    continue
                records[slot] = record
    except FileNotFoundError:
        pass
    return records


def append_journal(path: str, record: dict) -> None:
    """Append one observation to the JSONL journal and fsync it."""
    target = os.path.expanduser(path)
    parent = os.path.dirname(os.path.abspath(target))
    os.makedirs(parent, exist_ok=True)
    with open(target, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def write_text(path: str, text: str) -> None:
    """Atomically write text to ``path``."""
    target = os.path.expanduser(path)
    parent = os.path.dirname(os.path.abspath(target))
    os.makedirs(parent, exist_ok=True)
    temp = target + ".tmp-%d" % os.getpid()
    try:
        with open(temp, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    finally:
        try:
            os.unlink(temp)
        except OSError:
            pass


def write_json(path: str, data: dict) -> None:
    write_text(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Consolidation
# ---------------------------------------------------------------------------


def choose_primary(key: str, slots: Sequence[int]) -> int:
    """Pick the primary packet slot for a key.

    Prefer the packet slot derived from the official Cfg.ini main slot for the
    key.  Otherwise use the lowest observed slot.
    """
    official_cfg = [
        cfg for cfg, name in CFG_SLOT_NAMES.items() if name == key
    ]
    official_packet = {cfg_to_packet(cfg) for cfg in official_cfg}
    for slot in sorted(slots):
        if slot in official_packet:
            return slot
    return min(slots)


def _expected_slot_for_key(key: str) -> Optional[int]:
    """Return the transpose-predicted packet slot for a main key."""
    for cfg, name in CFG_SLOT_NAMES.items():
        if name == key:
            return cfg_to_packet(cfg)
    return None


def _infer_missing_keys(
    keys: Dict[str, int],
    observed_at: Dict[int, str],
    missing: List[str],
) -> Tuple[Dict[str, int], List[str]]:
    """Infer keys displaced by a local swap.

    The Z/X case on this unit is a two-cycle: slot 85 should be Z but is dead,
    while slot 86 should be X but lights Z.  When a missing key's predicted
    slot is occupied by another key whose own predicted slot is unoccupied, the
    missing key belongs there.
    """
    inferred: Dict[str, int] = {}
    remaining = list(missing)
    occupied: Set[int] = set(observed_at)
    changed = True
    while changed:
        changed = False
        for key in list(remaining):
            expected_slot = _expected_slot_for_key(key)
            if expected_slot is None:
                continue
            other = observed_at.get(expected_slot)
            if other is None or other == key:
                continue
            other_expected = _expected_slot_for_key(other)
            if other_expected is None or other_expected in occupied:
                continue
            inferred[key] = other_expected
            keys[key] = other_expected
            occupied.add(other_expected)
            remaining.remove(key)
            changed = True
    return inferred, remaining


def consolidate(
    records: Dict[int, dict],
    complete: bool,
    device: Optional[str],
    descriptor_sha: Optional[str],
) -> dict:
    """Build the mapping document from journal records."""
    slots = {}
    key_slots: Dict[str, List[int]] = {}
    zone_slots: Dict[str, List[int]] = {}
    observed_at: Dict[int, str] = {}
    dead_slots: List[int] = []
    mismatches: List[int] = []
    extra_slots: List[int] = []
    skipped: List[int] = []

    for packet_slot in range(NUM_SLOTS):
        record = records.get(packet_slot)
        if record is not None and record.get("verified"):
            expected = record.get("expected")
            category = record.get("category", "main")
            cfg = record.get("cfg_slot", packet_to_cfg(packet_slot))
        else:
            expected, category, cfg = expected_for(packet_slot)
        if record is None:
            observed = None
            status = "skipped"
            skipped.append(packet_slot)
        else:
            observed = record.get("observed")
            status = record.get("status", "")
        if packet_slot in ZONE_SLOTS and observed is not None:
            observed = ZONE_SLOTS[packet_slot]
            category = "zone"
            status = "ok"
        if observed:
            observed_at[packet_slot] = observed
            if category == "zone":
                zone_slots.setdefault(observed, []).append(packet_slot)
            else:
                key_slots.setdefault(observed, []).append(packet_slot)
        if status == "dead":
            dead_slots.append(packet_slot)
        elif status == "mismatch":
            mismatches.append(packet_slot)
        elif status == "extra":
            extra_slots.append(packet_slot)
        slot_record = {
            "cfg_slot": cfg,
            "category": category,
            "expected": expected,
            "observed": observed,
            "status": status,
        }
        if record is not None and record.get("verified"):
            slot_record["verified"] = True
            slot_record["source"] = record.get("source", "verify")
        slots[str(packet_slot)] = slot_record

    keys = {
        key: choose_primary(key, packet_slots)
        for key, packet_slots in key_slots.items()
    }
    zones = {
        name: min(packet_slots)
        for name, packet_slots in zone_slots.items()
    }
    duplicates = {
        key: sorted(packet_slots)
        for key, packet_slots in list(key_slots.items())
        + list(zone_slots.items())
        if len(packet_slots) > 1
    }
    missing_keys = sorted(set(CFG_SLOT_NAMES.values()) - set(keys))
    inferred_keys, missing_keys = _infer_missing_keys(
        keys, observed_at, missing_keys
    )
    unlit_keys = sorted(inferred_keys)

    return {
        "version": 1,
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "complete": bool(complete and not skipped),
        "device": device,
        "descriptor_sha256": descriptor_sha,
        "geometry": {
            "rows": ROWS,
            "cols": COLS,
            "cfg_order": "column-major",
            "packet_order": "row-major",
            "cfg_formula": "cfg_slot = (packet_slot % 21) * 6 + (packet_slot // 21)",
            "packet_formula": "packet_slot = (cfg_slot % 6) * 21 + (cfg_slot // 6)",
        },
        "slots": slots,
        "keys": keys,
        "zones": zones,
        "duplicates": duplicates,
        "dead_slots": sorted(dead_slots),
        "mismatches": sorted(mismatches),
        "extra_slots": sorted(extra_slots),
        "skipped_slots": sorted(skipped),
        "missing_keys": missing_keys,
        "inferred_keys": inferred_keys,
        "unlit_keys": unlit_keys,
    }


def print_summary(data: dict) -> None:
    """Print a human-readable summary of a mapping document."""
    slots = data["slots"]
    categories = {"main": 0, "dead": 0, "extra": 0, "zone": 0}
    statuses = {"ok": 0, "dead": 0, "mismatch": 0, "extra": 0, "skipped": 0}
    for record in slots.values():
        category = record.get("category", "extra")
        categories[category] = categories.get(category, 0) + 1
        status = record.get("status", "skipped")
        statuses[status] = statuses.get(status, 0) + 1

    print()
    print("mapping summary")
    print("  complete:   %s" % ("yes" if data.get("complete") else "no"))
    print("  slots:      %d" % len(slots))
    print(
        "  expected:   %d main, %d dead, %d extra, %d zone"
        % (
            categories["main"],
            categories["dead"],
            categories["extra"],
            categories["zone"],
        )
    )
    print(
        "  observed:   %d ok, %d dead, %d mismatch, %d extra, %d skipped"
        % (
            statuses["ok"],
            statuses["dead"],
            statuses["mismatch"],
            statuses["extra"],
            statuses["skipped"],
        )
    )
    print(
        "  keys:       %d primary, %d zones, %d with duplicates"
        % (len(data["keys"]), len(data.get("zones", {})), len(data["duplicates"]))
    )
    if data.get("zones"):
        print(
            "  zones:      %s"
            % ", ".join(
                "%s=%d" % (name, slot)
                for name, slot in sorted(data["zones"].items())
            )
        )
    if data["duplicates"]:
        print("  duplicates:")
        for key, packet_slots in sorted(data["duplicates"].items()):
            print("    %-8s %s" % (key, ", ".join(str(p) for p in packet_slots)))
    if data["dead_slots"]:
        print("  dead slots: %s" % ", ".join(str(p) for p in data["dead_slots"]))
    if data["extra_slots"]:
        print("  extra slots: %s" % ", ".join(str(p) for p in data["extra_slots"]))
    if data["mismatches"]:
        print("  mismatches: %s" % ", ".join(str(p) for p in data["mismatches"]))
    if data.get("inferred_keys"):
        print(
            "  inferred:   %s"
            % ", ".join(
                "%s=%d" % (name, slot)
                for name, slot in sorted(data["inferred_keys"].items())
            )
        )
    if data.get("unlit_keys"):
        print(
            "  unlit keys: %s (LED did not light during calibration)"
            % ", ".join(data["unlit_keys"])
        )
    if data["skipped_slots"]:
        print(
            "  skipped:    %s"
            % ", ".join(str(p) for p in data["skipped_slots"])
        )
    if data["missing_keys"]:
        print("  missing keys: %s" % ", ".join(data["missing_keys"]))
    if not data.get("complete"):
        print("  next: finish the probe or use --redo for the listed slots")


# ---------------------------------------------------------------------------
# Device helpers
# ---------------------------------------------------------------------------


def _resolve_device(args: argparse.Namespace):
    candidates = controller.iter_devices()
    if args.device:
        node = args.device
        if not os.path.exists(node):
            raise controller.DeviceNotFound(
                "device node %s does not exist" % node
            )
    else:
        node = controller.find_device()
    info = next((item for item in candidates if item.node == node), None)
    sysfs = (
        info.sysfs
        if info is not None
        else controller.sysfs_dir_for_node(node)
    )
    return node, info, sysfs


def _open_device(args: argparse.Namespace):
    node, info, sysfs = _resolve_device(args)
    data = controller.load_descriptor(sysfs)
    reports = controller.parse_report_descriptor(data)
    if not controller.is_known_descriptor(data):
        raise controller.ProtocolError(
            "descriptor sha256 %s does not match the captured K622 IF1 "
            "descriptor; refusing to touch the keyboard."
            % controller.descriptor_sha256(data)
        )
    controller.feature_report_size(reports, controller.COLOR_REPORT_ID)
    fd = controller.open_device(node, writable=True)
    return fd, node, data


def _backup(fd: int, data: bytes, note: str):
    config_response = controller.read_config_response(fd)
    palette_response = controller.mailbox_read(fd, controller.COLOR_READ_COMMAND)
    custom1_response = controller.mailbox_read(
        fd, controller.CUSTOM1_READ_COMMAND
    )
    files = {
        "config-response.bin": config_response,
        "colors-response.bin": palette_response,
        "custom1-response.bin": custom1_response,
    }
    meta = {
        "kind": note,
        "tool": "k622rgb keymap probe",
        "descriptor_sha256": controller.descriptor_sha256(data),
    }
    path = state.save_backup(files, meta)
    return path, config_response, custom1_response


def _restore(fd: int, config_response: bytes, custom1_response: bytes) -> None:
    config = controller.config_from_response(config_response)
    payload = controller.payload_from_response(custom1_response, 1024)
    controller.write_custom_frame(fd, payload, 1)
    time.sleep(0.05)
    controller.write_config(fd, config)


def _ensure_per_key(fd: int, config_response: bytes) -> None:
    config = controller.config_from_response(config_response)
    parsed = controller.parse_config(config)
    if parsed.mode != controller.PER_KEY_MODE or not parsed.per_key:
        controller.write_config(
            fd, controller.build_config(config, mode=controller.PER_KEY_MODE)
        )
        time.sleep(0.05)


def _write_slot(fd: int, slot: int, rgb: controller.Color) -> None:
    packet = controller.build_color_packet({slot: rgb})
    controller.write_feature(fd, packet)


def _ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return "quit"


def _print_help() -> None:
    print()
    print("  Enter  accept the expected key")
    print("  dead   no LED / dead slot")
    print("  skip   skip this slot for now")
    print("  help   show this help and the key-name list")
    print("  quit   save progress and quit")
    print("  other  the key name that actually lit")
    print()
    print("  Single letters are key names: n = N, s = S, q = Q, - = minus.")
    print()
    print("  key names: %s" % ", ".join(sorted(KNOWN_NAMES)))
    print("  extra:     %s" % ", ".join(sorted(EXTRA_CANONICAL.values())))
    print()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_probe(args: argparse.Namespace) -> int:
    journal_path = os.path.expanduser(args.journal)
    if args.fresh and os.path.exists(journal_path):
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        archived = "%s.bak-%s" % (journal_path, stamp)
        os.replace(journal_path, archived)
        print("old journal archived as %s" % archived)
    records = {} if args.fresh else load_journal(journal_path)
    redo = set(parse_slots(args.redo)) if args.redo else set()

    if args.only:
        slots = parse_slots(args.only)
    else:
        slots = list(range(NUM_SLOTS))
        if args.start is not None:
            slots = [slot for slot in slots if slot >= args.start]
        if args.end is not None:
            slots = [slot for slot in slots if slot <= args.end]

    if args.dry_run:
        print("dry run: no device access")
        for slot in slots:
            expected, category, cfg = expected_for(slot)
            label = expected if expected is not None else category
            print(
                "  packet %3d  cfg %3d  expected: %-12s (%s)"
                % (slot, cfg, label, category)
            )
        return 0

    rgb = colors.parse_color(args.color)
    fd = None
    config_response = None
    custom1_response = None
    node = None
    data = None
    quit_requested = False

    try:
        fd, node, data = _open_device(args)
        backup, config_response, custom1_response = _backup(
            fd, data, "keymap probe"
        )
        print("device: %s" % node)
        print("backup: %s" % backup)
        _ensure_per_key(fd, config_response)

        try:
            for index, slot in enumerate(slots, start=1):
                if slot in records and slot not in redo and not args.fresh:
                    continue
                expected, category, cfg = expected_for(slot)
                _write_slot(fd, slot, rgb)
                label = expected if expected is not None else category
                print()
                print(
                    "[%3d/%3d] packet slot %3d  cfg slot %3d  expected: %s"
                    % (index, len(slots), slot, cfg, label)
                )
                while True:
                    answer = _ask(
                        "key [Enter=accept expected, dead=no LED, "
                        "skip, help, quit]: "
                    )
                    action, observed = classify_answer(answer, expected)
                    if action == "help":
                        _print_help()
                        continue
                    if action == "quit":
                        quit_requested = True
                        break
                    if action == "skip":
                        print("skipped")
                        break
                    if action == "retry":
                        continue
                    if observed is not None and observed not in KNOWN_NAMES:
                        confirm = _ask(
                            "%r is not a known key name. Record it as "
                            "typed? [y/N]: " % observed
                        ).strip().lower()
                        if confirm not in ("y", "yes"):
                            continue
                    if observed is None:
                        status = "dead" if expected is None else "mismatch"
                    elif expected is None:
                        status = "extra"
                    elif observed == expected:
                        status = "ok"
                    else:
                        status = "mismatch"
                    record = {
                        "slot": slot,
                        "cfg_slot": cfg,
                        "category": category,
                        "expected": expected,
                        "observed": observed,
                        "status": status,
                        "ts": time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                        ),
                    }
                    records[slot] = record
                    append_journal(journal_path, record)
                    if status == "ok":
                        print("recorded: %s" % observed)
                    elif status == "dead":
                        print("recorded: dead")
                    elif status == "extra":
                        print("recorded: %s (extra key)" % observed)
                    else:
                        print(
                            "recorded: %s (expected %s)"
                            % (
                                "dead" if observed is None else observed,
                                "dead" if expected is None else expected,
                            )
                        )
                    if observed:
                        seen = [
                            other
                            for other, other_record in records.items()
                            if other != slot
                            and other_record.get("observed") == observed
                        ]
                        if seen:
                            print(
                                "note: %s was already seen at slot %s; it "
                                "will be an alias"
                                % (observed, ", ".join(str(s) for s in sorted(seen)))
                            )
                    break
                if quit_requested:
                    break
        except KeyboardInterrupt:
            print("\ninterrupted; saving progress")
            quit_requested = True

        complete = all(slot in records for slot in range(NUM_SLOTS))
        document = consolidate(
            records,
            complete,
            node,
            controller.descriptor_sha256(data) if data is not None else None,
        )
        write_json(args.out, document)
        print("\nwrote %s" % os.path.expanduser(args.out))
        print_summary(document)
        if quit_requested:
            print("progress saved; rerun with --resume to continue")
        return 0
    finally:
        if fd is not None:
            if config_response is not None and custom1_response is not None:
                try:
                    _restore(fd, config_response, custom1_response)
                    print("restored original lighting")
                except Exception as exc:  # noqa: BLE001 - report, do not hide
                    print(
                        "WARNING: could not restore the original lighting: %s"
                        % exc,
                        file=sys.stderr,
                    )
                    print(
                        "WARNING: restore from the backup printed above with "
                        "`k622rgb config restore <backup>`",
                        file=sys.stderr,
                    )
            try:
                os.close(fd)
            except OSError:
                pass


def cmd_report(args: argparse.Namespace) -> int:
    records = load_journal(args.journal)
    document = consolidate(records, all(slot in records for slot in range(NUM_SLOTS)),
                           None, None)
    if args.out:
        write_json(args.out, document)
        print("wrote %s" % os.path.expanduser(args.out))
    print_summary(document)
    return 0


def _render_mapping(
    mapping: dict,
) -> Tuple[Dict[int, str], Dict[int, str], Dict[int, str], List[int]]:
    keys = {name: int(slot) for name, slot in mapping["keys"].items()}
    zones = {name: int(slot) for name, slot in mapping.get("zones", {}).items()}
    slot_names = {
        slot: name for name, slot in keys.items() if name not in zones
    }
    zone_names = {slot: name for name, slot in zones.items()}
    alias_slots: Dict[int, str] = {}
    dead_slots: List[int] = []
    for slot_text, record in mapping["slots"].items():
        slot = int(slot_text)
        observed = record.get("observed")
        if observed is None:
            if slot not in slot_names and slot not in zone_names:
                dead_slots.append(slot)
        elif slot not in slot_names and slot not in zone_names:
            alias_slots[slot] = observed
    return slot_names, zone_names, alias_slots, sorted(dead_slots)


def _format_int_dict(mapping: Dict[int, str], prefix: str) -> str:
    if not mapping:
        return prefix + "{}"
    lines = [prefix + "{"]
    for slot in sorted(mapping):
        lines.append("    %d: %r," % (slot, mapping[slot]))
    lines.append("}")
    return "\n".join(lines)


def render_module(mapping: dict) -> str:
    slot_names, zone_names, alias_slots, dead_slots = _render_mapping(mapping)
    lines = [
        '"""Generated keymap data for the Redragon K622.',
        "",
        "Generated from docs/keymap-observed.json on %s." % mapping.get(
            "created", "unknown date"
        ),
        "Do not edit by hand; rerun `python3 tools/keymap_probe.py apply`.",
        '"""',
        "",
        "#: Primary packet slot -> canonical key name.",
        _format_int_dict(slot_names, "SLOT_NAMES = "),
        "",
        "#: Addressable non-key LED zones.",
        _format_int_dict(zone_names, "ZONE_NAMES = "),
        "",
        "#: Duplicate/alias packet slot -> canonical key name.",
        _format_int_dict(alias_slots, "ALIAS_SLOTS = "),
        "",
        "#: Packet slots observed with no LED.",
    ]
    if dead_slots:
        lines.append("DEAD_SLOTS = frozenset((")
        for slot in dead_slots:
            lines.append("    %d," % slot)
        lines.append("))")
    else:
        lines.append("DEAD_SLOTS = frozenset()")
    lines.append("")
    lines.append("#: Keys whose LED did not light during calibration.")
    unlit = tuple(mapping.get("unlit_keys", []))
    lines.append("UNLIT_KEYS = %r" % (unlit,))
    lines.append("")
    return "\n".join(lines)


def cmd_apply(args: argparse.Namespace) -> int:
    with open(os.path.expanduser(args.map), "r", encoding="utf-8") as handle:
        mapping = json.load(handle)
    if not mapping.get("complete") and not args.allow_incomplete:
        print(
            "mapping is incomplete (%d slots skipped); finish the probe or "
            "use --allow-incomplete"
            % len(mapping.get("skipped_slots", [])),
            file=sys.stderr,
        )
        return 1
    explained: Set[int] = set()
    for key, slot in mapping.get("inferred_keys", {}).items():
        explained.add(int(slot))
        expected_slot = _expected_slot_for_key(key)
        if expected_slot is not None:
            explained.add(expected_slot)
    unexplained = [
        slot for slot in mapping.get("mismatches", []) if slot not in explained
    ]
    if unexplained and not args.allow_mismatches:
        print(
            "mapping has unexplained mismatches at slots %s; review them with "
            "`report` or use --allow-mismatches"
            % ", ".join(str(slot) for slot in unexplained),
            file=sys.stderr,
        )
        return 1
    if mapping.get("mismatches") and not unexplained:
        print(
            "confirmed deviations at slots %s (explained by inferred keys)"
            % ", ".join(str(slot) for slot in mapping["mismatches"])
        )
    text = render_module(mapping)
    write_text(args.out, text)
    print("wrote %s" % os.path.expanduser(args.out))
    slot_names, zone_names, alias_slots, dead_slots = _render_mapping(mapping)
    print(
        "generated: %d keys, %d zones, %d aliases, %d dead slots"
        % (
            len(slot_names),
            len(zone_names),
            len(alias_slots),
            len(dead_slots),
        )
    )
    if mapping.get("unlit_keys"):
        print(
            "unlit keys: %s (mapped but not observed lighting)"
            % ", ".join(mapping["unlit_keys"])
        )
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    with open(os.path.expanduser(args.map), "r", encoding="utf-8") as handle:
        mapping = json.load(handle)
    if not mapping.get("complete"):
        print("mapping is incomplete; finish the probe first", file=sys.stderr)
        return 1

    keys = {name: int(slot) for name, slot in mapping["keys"].items()}
    unlit = set(mapping.get("unlit_keys", []))
    ordered = [
        (name, slot)
        for name, slot in sorted(keys.items(), key=lambda item: item[1])
        if name not in unlit
    ]
    if unlit:
        print(
            "skipping unlit keys: %s (LED did not light during calibration)"
            % ", ".join(sorted(unlit))
        )
    rgb = colors.parse_color(args.color)
    failures = []
    quit_requested = False
    fd = None
    config_response = None
    custom1_response = None

    try:
        fd, node, data = _open_device(args)
        backup, config_response, custom1_response = _backup(
            fd, data, "keymap verify"
        )
        print("device: %s" % node)
        print("backup: %s" % backup)
        _ensure_per_key(fd, config_response)
        try:
            for index, (key, slot) in enumerate(ordered, start=1):
                _write_slot(fd, slot, rgb)
                print()
                answer = _ask(
                    "[%3d/%3d] slot %3d should light %-8s — did it? [Y/n/q]: "
                    % (index, len(ordered), slot, key)
                ).strip().lower()
                if answer in ("q", "quit"):
                    quit_requested = True
                    break
                if answer in ("", "y", "yes"):
                    continue
                actual = _ask(
                    "what lit? (key name, or dead=no LED): "
                ).strip()
                if actual.lower() in ("dead", "none", "blank"):
                    actual = None
                else:
                    actual = normalize_name(actual)
                failures.append((key, slot, actual))
                print(
                    "recorded failure: expected %s at slot %d, saw %s"
                    % (key, slot, actual if actual else "dead")
                )
        except KeyboardInterrupt:
            print("\ninterrupted")
            quit_requested = True
        if failures:
            print()
            print("verify failures:")
            for key, slot, actual in failures:
                print(
                    "  %-8s slot %3d  saw %s"
                    % (key, slot, actual if actual else "dead")
                )
            return 1
        if quit_requested:
            print("verify stopped early")
            return 1
        print()
        print("verify: all %d keys lit correctly" % len(ordered))
        return 0
    finally:
        if fd is not None:
            if config_response is not None and custom1_response is not None:
                try:
                    _restore(fd, config_response, custom1_response)
                    print("restored original lighting")
                except Exception as exc:  # noqa: BLE001
                    print(
                        "WARNING: could not restore the original lighting: %s"
                        % exc,
                        file=sys.stderr,
                    )
            try:
                os.close(fd)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="keymap_probe",
        description=(
            "Probe every K622 LED slot, record what actually lights, and "
            "generate a corrected keymap."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe = subparsers.add_parser("probe", help="test packet slots interactively")
    probe.add_argument("--device", help="use this /dev/hidrawN")
    probe.add_argument("--color", default="ffffff", help="LED colour (default ffffff)")
    probe.add_argument("--journal", default=DEFAULT_JOURNAL, help="JSONL progress file")
    probe.add_argument("--out", default=DEFAULT_OUT, help="mapping JSON output")
    probe.add_argument("--fresh", action="store_true", help="start a new journal")
    probe.add_argument("--resume", action="store_true", help="continue from the journal")
    probe.add_argument("--only", help="only these slots, e.g. 0-10,14,44")
    probe.add_argument("--start", type=int, help="first packet slot")
    probe.add_argument("--end", type=int, help="last packet slot")
    probe.add_argument("--redo", help="re-prompt these slots, e.g. 14,44")
    probe.add_argument("--dry-run", action="store_true", help="print the sequence only")
    probe.set_defaults(func=cmd_probe)

    report = subparsers.add_parser("report", help="summarize the journal")
    report.add_argument("--journal", default=DEFAULT_JOURNAL, help="JSONL progress file")
    report.add_argument("--out", help="also write the mapping JSON here")
    report.set_defaults(func=cmd_report)

    apply = subparsers.add_parser("apply", help="generate keymap_data.py")
    apply.add_argument("--map", default=DEFAULT_OUT, help="observed mapping JSON")
    apply.add_argument("--out", default=DEFAULT_MODULE, help="generated Python module")
    apply.add_argument("--allow-incomplete", action="store_true")
    apply.add_argument("--allow-mismatches", action="store_true")
    apply.set_defaults(func=cmd_apply)

    verify = subparsers.add_parser("verify", help="check every key name on hardware")
    verify.add_argument("--device", help="use this /dev/hidrawN")
    verify.add_argument("--map", default=DEFAULT_OUT, help="observed mapping JSON")
    verify.add_argument("--color", default="ffffff", help="LED colour (default ffffff)")
    verify.set_defaults(func=cmd_verify)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (controller.DeviceError, ValueError, OSError) as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

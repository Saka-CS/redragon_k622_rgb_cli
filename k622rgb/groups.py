"""Named per-key colour groups for the Redragon K622.

The official software exposes five game-mode colour groups (``Define1..5``).
Those groups are lists of Windows virtual-key (VK) codes, and the software
paints each group's colour into a normal ``09 cc`` per-key frame.  This module
stores the same idea locally, adds a few ready-to-use presets, and imports the
vendor defaults from ``Cfg.ini`` without touching the keyboard.

Nothing here talks to the device.
"""

import json
import os
import re
import tempfile
import time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import colors, layout

GROUP_FILE_ENV = "K622RGB_GROUP_FILE"
GROUP_VERSION = 1

#: Canonical names of the five groups defined by ``GaoshouKey1..5``.
VENDOR_GROUP_NAMES = tuple("define%d" % index for index in range(1, 6))

#: Short aliases accepted for the vendor groups.
_GROUP_ALIASES = {}
for _index in range(1, 6):
    _GROUP_ALIASES[str(_index)] = "define%d" % _index
    _GROUP_ALIASES["group%d" % _index] = "define%d" % _index

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")

#: Generic Windows modifier VKs used by the vendor group lists.  The official
#: lists say "Shift", "Ctrl" and "Alt"; paint both sides of each pair.
_GENERIC_VK_KEYS = {
    0x10: ("LShift", "RShift"),
    0x11: ("LCtrl", "RCtrl"),
    0x12: ("LAlt", "RAlt"),
}

#: Vendor defaults from the documented K622 ``Cfg.ini``.  They are a
#: convenience only; ``group import`` refreshes them from a real file.
_BUILTIN_VENDOR = {
    "define1": (
        "Esc", "W", "A", "S", "D",
        "Up", "Down", "Left", "Right",
    ),
    "define2": (
        "F1", "F2", "F3", "1", "2", "3", "4", "5",
        "Tab", "Q", "W", "E", "R", "A", "S", "D", "G",
        "LShift", "RShift", "B", "LCtrl", "RCtrl", "LAlt", "RAlt", "Space",
        "PrtSc", "PgUp", "PgDn", "Home", "End",
    ),
    "define3": (
        "1", "2", "3", "4", "5", "6", "7",
        "Q", "W", "E", "R", "T", "A", "S", "D", "F", "G",
        "LShift", "RShift", "C", "V", "LCtrl", "RCtrl",
    ),
    "define4": (
        "1", "2", "3", "4", "5", "6", "7",
        "Q", "W", "E", "R", "A", "S", "D", "F",
    ),
    "define5": (
        "W", "R", "A", "S", "D",
        "LShift", "RShift", "LCtrl", "RCtrl", "LAlt", "RAlt",
        "Up", "Down", "Left", "Right",
    ),
}

#: Ready-to-use overlays.  Colours are defaults and can be changed with
#: ``group set NAME=COLOR``.
_PRESETS = {
    "wasd": (
        ("W", "A", "S", "D"),
        (255, 255, 255),
    ),
    "arrows": (
        ("Up", "Down", "Left", "Right"),
        (0, 255, 255),
    ),
    "fps": (
        ("W", "A", "S", "D", "Up", "Down", "Left", "Right"),
        (255, 0, 0),
    ),
    "moba": (
        ("Q", "W", "E", "R", "D", "F"),
        (0, 255, 0),
    ),
    "mmo": (
        ("1", "2", "3", "4", "5", "6", "LShift", "LCtrl", "LAlt"),
        (0, 0, 255),
    ),
    "typing": (
        ("A", "S", "D", "F", "J", "K", "L", ";", "Space"),
        (255, 165, 0),
    ),
}

#: Presets in display/apply order.
PRESET_GROUP_NAMES = tuple(_PRESETS)

#: Every built-in group name.
BUILTIN_GROUP_NAMES = tuple(_BUILTIN_VENDOR) + PRESET_GROUP_NAMES


class GroupError(RuntimeError):
    """A group store could not be read, written or validated."""


def _copy_group(group: Dict) -> Dict:
    return {"keys": tuple(group["keys"]), "color": group["color"]}


def _builtin_groups() -> Dict[str, Dict]:
    result = {
        name: {"keys": tuple(keys), "color": None}
        for name, keys in _BUILTIN_VENDOR.items()
    }
    for name, (keys, color) in _PRESETS.items():
        result[name] = {"keys": tuple(keys), "color": color}
    return result


def canonical_group_name(name: str) -> str:
    """Return the canonical lower-case group name or raise ``ValueError``."""
    if not isinstance(name, str):
        raise ValueError("group name must be text, got %r" % (name,))
    text = name.strip().lower()
    if not text:
        raise ValueError("group name must not be empty")
    text = _GROUP_ALIASES.get(text, text)
    if not _NAME_RE.match(text):
        raise ValueError(
            "invalid group name %r; use letters, digits, '.', '_' or '-'"
            % name
        )
    return text


def _normalize_keys(keys: Iterable[str]) -> Tuple[str, ...]:
    normalized = []
    for key in keys:
        slot = layout.resolve_key(key)
        name = layout.canonical_name(slot)
        if name not in normalized:
            normalized.append(name)
    return tuple(normalized)


def group_path(directory: Optional[str] = None) -> str:
    """Return the group-store path (``$XDG_CONFIG_HOME`` by default)."""
    if directory:
        return os.path.expanduser(directory)
    override = os.environ.get(GROUP_FILE_ENV)
    if override:
        return os.path.expanduser(override)
    base = os.environ.get("XDG_CONFIG_HOME")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(os.path.expanduser(base), "k622rgb", "groups.json")


def _read_local_groups(path: str) -> Dict[str, Dict]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise GroupError(
            "cannot read group file %s: %s" % (path, exc.strerror or exc)
        ) from exc
    except ValueError as exc:
        raise GroupError("group file %s is not valid JSON: %s" % (path, exc)) from exc

    if not isinstance(payload, dict):
        raise GroupError("group file %s is not a JSON object" % path)
    if payload.get("version") != GROUP_VERSION:
        raise GroupError(
            "group file %s has version %r; expected %d"
            % (path, payload.get("version"), GROUP_VERSION)
        )
    raw_groups = payload.get("groups")
    if raw_groups is None:
        raw_groups = {}
    if not isinstance(raw_groups, dict):
        raise GroupError("group file %s has no groups object" % path)

    result = {}
    for raw_name, raw_group in raw_groups.items():
        try:
            name = canonical_group_name(raw_name)
        except ValueError as exc:
            raise GroupError("group file %s: %s" % (path, exc)) from exc
        if not isinstance(raw_group, dict):
            raise GroupError("group %r in %s is not an object" % (name, path))
        raw_keys = raw_group.get("keys")
        if not isinstance(raw_keys, list) or not raw_keys:
            raise GroupError(
                "group %r in %s must have a non-empty keys list" % (name, path)
            )
        try:
            keys = _normalize_keys(raw_keys)
        except (TypeError, ValueError) as exc:
            raise GroupError(
                "group %r in %s has an invalid key: %s" % (name, path, exc)
            ) from exc
        color_text = raw_group.get("color")
        try:
            color = (
                None
                if color_text in (None, "")
                else colors.parse_color(color_text)
            )
        except ValueError as exc:
            raise GroupError(
                "group %r in %s has an invalid colour: %s"
                % (name, path, exc)
            ) from exc
        result[name] = {"keys": keys, "color": color}
    return result


def load_local_groups(path: Optional[str] = None) -> Dict[str, Dict]:
    """Return only the groups saved in the local group file."""
    return _read_local_groups(group_path(path))


def effective_groups(local: Optional[Dict[str, Dict]] = None) -> Dict[str, Dict]:
    """Merge built-in groups with local overrides."""
    result = _builtin_groups()
    if local:
        for name, group in local.items():
            result[name] = _copy_group(group)
    return result


def save_local_groups(
    local: Dict[str, Dict], path: Optional[str] = None
) -> str:
    """Atomically write the local group overrides."""
    target = group_path(path)
    payload = {
        "version": GROUP_VERSION,
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "groups": {
            name: {
                "keys": list(group["keys"]),
                "color": (
                    None
                    if group["color"] is None
                    else colors.format_color(group["color"])
                ),
            }
            for name, group in local.items()
        },
    }
    parent = os.path.dirname(os.path.abspath(target))
    try:
        os.makedirs(parent, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=parent,
            prefix=".groups-",
            suffix=".json",
            delete=False,
        )
        try:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        os.replace(handle.name, target)
    except OSError as exc:
        raise GroupError(
            "cannot save groups to %s: %s" % (target, exc.strerror or exc)
        ) from exc
    return target


def update_local_group(
    local: Dict[str, Dict],
    name: str,
    color: Optional[colors.Color],
    keys: Optional[Sequence[str]] = None,
) -> Dict:
    """Update one local group, preserving keys or colour when omitted."""
    canonical = canonical_group_name(name)
    effective = effective_groups(local)
    if keys is None:
        existing = effective.get(canonical)
        if existing is None:
            raise ValueError(
                "unknown group %r; give its keys with "
                "`group set %s=COLOR KEY...`" % (canonical, canonical)
            )
        resolved_keys = existing["keys"]
    else:
        resolved_keys = _normalize_keys(keys)
        if not resolved_keys:
            raise ValueError("group %r needs at least one key" % canonical)

    if color is None:
        existing = effective.get(canonical)
        color = existing["color"] if existing is not None else None

    group = {"keys": tuple(resolved_keys), "color": color}
    local[canonical] = group
    return group


def parse_set_items(
    items: Sequence[str],
) -> Tuple[List[Tuple[str, colors.Color]], Optional[List[str]]]:
    """Parse ``group set`` arguments.

    ``fps=red`` recolours an existing group.  ``custom=red W A S D`` defines a
    group and its keys.  Several ``NAME=COLOR`` pairs recolour several groups.
    """
    assignments = []
    keys = []
    for item in items:
        if "=" in item:
            if keys:
                raise ValueError(
                    "give keys after a single NAME=COLOR, not before another "
                    "assignment"
                )
            name, color_text = item.split("=", 1)
            assignments.append(
                (canonical_group_name(name), colors.parse_color(color_text))
            )
        else:
            keys.append(item)
    if not assignments:
        raise ValueError("expected NAME=COLOR, e.g. fps=ff0000")
    if keys and len(assignments) != 1:
        raise ValueError("keys may only follow a single NAME=COLOR assignment")
    return assignments, (keys or None)


def parse_overlay(text: str) -> Tuple[str, colors.Color]:
    """Parse one ``--group NAME=COLOR`` overlay."""
    if "=" not in text:
        raise ValueError(
            "expected NAME=COLOR for --group, got %r (use fps=ff0000)" % text
        )
    name, color_text = text.split("=", 1)
    return canonical_group_name(name), colors.parse_color(color_text)


def resolve_group_layers(
    overlays: Sequence[str], path: Optional[str] = None
) -> List[Tuple[str, colors.Color, List[int]]]:
    """Resolve overlays to ``(name, colour, packet slots)`` layers."""
    effective = effective_groups(load_local_groups(path))
    layers = []
    available = ", ".join(sorted(effective))
    for text in overlays:
        name, color = parse_overlay(text)
        group = effective.get(name)
        if group is None:
            raise ValueError(
                "unknown group %r; available groups: %s" % (name, available)
            )
        slots = []
        for key in group["keys"]:
            slot = layout.resolve_key(key)
            if slot not in slots:
                slots.append(slot)
        layers.append((name, color, slots))
    return layers


# --------------------------------------------------------------------------
# Cfg.ini import
# --------------------------------------------------------------------------


def _read_cfg_ini(
    path: str,
) -> Tuple[Dict[str, Dict[str, str]], Dict[str, str]]:
    """Read sections, plus the ``;Label`` comments before each ``[KEY]`` entry."""
    sections: Dict[str, Dict[str, str]] = {}
    key_labels: Dict[str, str] = {}
    current = None
    pending_label = None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                line = raw.strip()
                if not line:
                    continue
                if line.startswith("//"):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    current = line[1:-1].strip().lower()
                    sections.setdefault(current, {})
                    pending_label = None
                    continue
                if line.startswith(";"):
                    pending_label = line[1:].strip()
                    continue
                if current is None or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                if current == "key" and pending_label:
                    key_labels[key] = pending_label
                pending_label = None
                sections[current][key] = value.strip()
    except OSError as exc:
        raise GroupError(
            "cannot read %s: %s" % (path, exc.strerror or exc)
        ) from exc
    return sections, key_labels


def _vk_map_from_key_section(
    section: Dict[str, str], labels: Dict[str, str]
) -> Dict[int, List[str]]:
    """Map Windows VK codes to CLI key names using ``Cfg.ini``'s ``[KEY]``.

    The official labels are the primary source because the corrected bottom
    row is not monotonic with the old ``Cfg.ini`` LED-slot numbering.  The
    transpose formula remains a fallback, which also handles label typos such
    as ``SrcLock``.
    """
    mapping: Dict[int, List[str]] = {}
    for key, value in section.items():
        if not key.lower().startswith("k"):
            continue
        fields = [field.strip() for field in value.split(",")]
        if len(fields) < 8:
            continue
        try:
            usage = int(fields[5], 0)
            cfg_slot = int(fields[7], 0)
        except ValueError:
            continue

        name = None
        label = labels.get(key)
        if label:
            try:
                name = layout.canonical_name(layout.resolve_key(label))
            except ValueError:
                name = None
        if name is None:
            packet_slot = (cfg_slot % 6) * 21 + (cfg_slot // 6)
            if not 0 <= packet_slot < 126:
                continue
            name = layout.canonical_name(packet_slot)
        if name.startswith("slot:"):
            continue
        names = mapping.setdefault(usage, [])
        if name not in names:
            names.append(name)

    # The vendor group lists use generic modifier VKs, while [KEY] contains
    # the left/right-specific 0xA0..0xA5 codes.
    for vk, names in _GENERIC_VK_KEYS.items():
        current = mapping.setdefault(vk, [])
        for name in names:
            if name not in current:
                current.append(name)
    return mapping


def import_cfg_ini(
    path: str,
    existing: Optional[Dict[str, Dict]] = None,
) -> Tuple[Dict[str, Dict], List[str]]:
    """Read ``GaoshouKey1..5`` from a vendor ``Cfg.ini``.

    Returns ``(groups, warnings)``.  ``groups`` contains ``define1..define5``;
    colours from ``existing`` are preserved.  The file is opened read-only and
    the device is never touched.
    """
    sections, key_labels = _read_cfg_ini(path)
    options = {
        key.lower(): value for key, value in sections.get("opt", {}).items()
    }
    key_section = sections.get("key")
    if not key_section:
        raise GroupError(
            "%s has no [KEY] section; cannot map VK codes to key names" % path
        )
    vk_map = _vk_map_from_key_section(key_section, key_labels)
    existing = existing or {}
    imported: Dict[str, Dict] = {}
    warnings: List[str] = []
    unknown_vks = set()

    for index in range(1, 6):
        name = "define%d" % index
        raw = options.get("gaoshoukey%d" % index)
        if raw is None:
            warnings.append("%s is missing from %s" % (
                "GaoshouKey%d" % index, path
            ))
            continue
        keys: List[str] = []
        for token in raw.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                vk = int(token, 16)
            except ValueError:
                warnings.append(
                    "GaoshouKey%d contains invalid VK %r; skipped"
                    % (index, token)
                )
                continue
            names = vk_map.get(vk)
            if not names:
                unknown_vks.add(vk)
                continue
            for key in names:
                if key not in keys:
                    keys.append(key)
        if not keys:
            warnings.append(
                "GaoshouKey%d maps to no known keys; skipped" % index
            )
            continue
        old = existing.get(name, {})
        imported[name] = {
            "keys": tuple(keys),
            "color": old.get("color"),
        }

    if unknown_vks:
        warnings.append(
            "unknown VK code%s: %s"
            % (
                "" if len(unknown_vks) == 1 else "s",
                ", ".join("0x%02x" % vk for vk in sorted(unknown_vks)),
            )
        )
    if not imported:
        raise GroupError("no usable GaoshouKey groups found in %s" % path)
    return imported, warnings

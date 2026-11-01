"""Key names and LED-slot lookup for the Redragon K622.

The slot numbers and canonical names come from the official ``Cfg.ini``
``[KEY]`` section (normalised as described in ``docs/KEYMAP.md``). Slots
``102-125`` are not described there; ``k622rgb calibrate`` discovers them and
stores the result in ``layout.json``. Until a slot is calibrated it can still be
addressed explicitly as ``slot:N``.

This module reads the optional ``layout.json`` but never talks to the device.
"""

import json
import os
import tempfile
from typing import Dict, Optional

from .controller import NUM_SLOTS

#: Canonical key name for every LED slot that the official software maps.
SLOT_NAMES = {
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

#: Slots present in the 126-slot packet but with no LED on the K622.
DEAD_SLOTS = frozenset(
    (6, 23, 29, 41, 47, 70, 71, 75, 76, 77, 87, 88, 93, 99, 100)
)

#: Slots that ``k622rgb calibrate`` discovers (G/MR/media keys and dead slots).
EXTRA_SLOT_START = 102
EXTRA_SLOT_END = 125
EXTRA_SLOTS = range(EXTRA_SLOT_START, EXTRA_SLOT_END + 1)

#: Canonical names accepted for the extra keys. ``G5`` is kept because the
#: official ``Cfg.ini`` lists it even though the physical board has MR instead.
EXTRA_KEY_NAMES = (
    "G1",
    "G2",
    "G3",
    "G4",
    "G5",
    "MR",
    "RGB",
    "Prev",
    "Play",
    "Next",
    "Mute",
    "Volume",
)

#: Accepted spellings for the extra keys, mapped to the canonical names above.
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
    "previous": "Prev",
    "prev": "Prev",
    "playpause": "Play",
    "play": "Play",
    "nexttrack": "Next",
    "next": "Next",
    "mute": "Mute",
    "volumemute": "Mute",
    "volume": "Volume",
    "vol": "Volume",
    "roller": "Volume",
}

LAYOUT_VERSION = 1
LAYOUT_FILENAME = "layout.json"
CONFIG_DIR_ENV = "K622RGB_CONFIG_DIR"
LAYOUT_FILE_ENV = "K622RGB_LAYOUT_FILE"

_EXTRA_CANONICAL = {name.lower(): name for name in EXTRA_KEY_NAMES}
_EXTRA_LOOKUP = dict(_EXTRA_CANONICAL)
_EXTRA_LOOKUP.update(EXTRA_ALIASES)

_CALIBRATION_CACHE: Dict[str, Dict[int, str]] = {}

#: Accepted spellings that map to a canonical name above.
ALIASES = {
    "escape": "Esc",
    "capslock": "Caps",
    "caps": "Caps",
    "lwin": "Win",
    "win": "Win",
    "super": "Win",
    "meta": "Win",
    "cmd": "Win",
    "app": "Menu",
    "application": "Menu",
    "menu": "Menu",
    "backspace": "Bksp",
    "back": "Bksp",
    "bksp": "Bksp",
    "insert": "Ins",
    "ins": "Ins",
    "delete": "Del",
    "del": "Del",
    "srclock": "ScrLk",
    "scrolllock": "ScrLk",
    "scrlk": "ScrLk",
    "printscreen": "PrtSc",
    "print": "PrtSc",
    "prtsc": "PrtSc",
    "return": "Enter",
    "spacebar": "Space",
    "grave": "`",
    "backtick": "`",
    "semicolon": ";",
    "quote": "'",
    "apostrophe": "'",
    "comma": ",",
    "period": ".",
    "dot": ".",
    "slash": "/",
    "backslash": "\\",
    "leftbracket": "[",
    "rightbracket": "]",
    "minus": "-",
    "hyphen": "-",
    "equals": "=",
    "equal": "=",
    "arrowup": "Up",
    "arrowdown": "Down",
    "arrowleft": "Left",
    "arrowright": "Right",
}

_CANONICAL_TO_SLOT = {name.lower(): slot for slot, name in SLOT_NAMES.items()}
NAME_TO_SLOT = dict(_CANONICAL_TO_SLOT)
for _alias, _canonical in ALIASES.items():
    NAME_TO_SLOT[_alias] = _CANONICAL_TO_SLOT[_canonical.lower()]


class UnknownKey(ValueError):
    """An unknown or unaddressable key name."""


class LayoutError(RuntimeError):
    """The optional ``layout.json`` could not be read or validated."""


def config_dir() -> str:
    """Directory for user configuration (``$XDG_CONFIG_HOME`` by default)."""
    override = os.environ.get(CONFIG_DIR_ENV)
    if override:
        return os.path.expanduser(override)
    base = os.environ.get("XDG_CONFIG_HOME")
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(os.path.expanduser(base), "k622rgb")


def default_layout_path() -> str:
    """Path of the optional calibration file."""
    override = os.environ.get(LAYOUT_FILE_ENV)
    if override:
        return os.path.expanduser(override)
    return os.path.join(config_dir(), LAYOUT_FILENAME)


def canonical_extra_name(name: str) -> Optional[str]:
    """Return the canonical extra-key name for an alias, or ``None``."""
    if not isinstance(name, str):
        return None
    return _EXTRA_LOOKUP.get(name.strip().lower())


def normalize_label(name: str) -> str:
    """Normalize one calibration label.

    Known extra-key aliases become their canonical name, main-key names and
    aliases become the canonical main-key name, and anything else is kept as
    typed. This lets calibration record an unexpected or mistaken key without
    rejecting the answer.
    """
    if not isinstance(name, str):
        raise ValueError("key name must be text, got %r" % (name,))
    text = name.strip()
    if not text:
        raise ValueError("empty key name")
    canonical = canonical_extra_name(text)
    if canonical is not None:
        return canonical
    slot = NAME_TO_SLOT.get(text.lower())
    if slot is not None:
        return SLOT_NAMES[slot]
    return text


def describe_value(value: Optional[str]) -> str:
    """Human-readable calibration value, flagging unexpected labels."""
    if value is None:
        return "uncalibrated"
    if value == "":
        return "dead"
    labels = []
    for name in value.split(","):
        if not name:
            continue
        if name.lower() in NAME_TO_SLOT:
            labels.append("%s (main key!)" % name)
        elif canonical_extra_name(name) is None:
            labels.append("%s (unexpected)" % name)
        else:
            labels.append(name)
    return ", ".join(labels)


def clear_calibration_cache() -> None:
    """Forget cached ``layout.json`` contents (tests and ``calibrate``)."""
    _CALIBRATION_CACHE.clear()


def _layout_error(path: str, message: str) -> LayoutError:
    return LayoutError("%s: %s" % (path, message))


def _normalize_slot_value(path: str, slot: int, value: str) -> str:
    if not isinstance(value, str):
        raise _layout_error(path, "slot %d must map to a string" % slot)
    text = value.strip()
    if not text:
        return ""
    names = []
    seen = set()
    for part in text.split(","):
        try:
            canonical = normalize_label(part)
        except ValueError:
            raise _layout_error(
                path, "slot %d has an empty key name" % slot
            ) from None
        if canonical.lower() not in seen:
            seen.add(canonical.lower())
            names.append(canonical)
    return ",".join(names)


def _validate_calibration(path: str, data) -> Dict[int, str]:
    if not isinstance(data, dict):
        raise _layout_error(path, "expected a JSON object")
    version = data.get("version", LAYOUT_VERSION)
    if version != LAYOUT_VERSION:
        raise _layout_error(
            path, "unsupported version %r (expected %d)" % (version, LAYOUT_VERSION)
        )
    slots = data.get("slots")
    if not isinstance(slots, dict):
        raise _layout_error(path, "expected a 'slots' object")
    result: Dict[int, str] = {}
    for raw_slot, raw_value in slots.items():
        try:
            slot = int(str(raw_slot), 10)
        except ValueError:
            raise _layout_error(path, "invalid slot %r" % (raw_slot,)) from None
        if not EXTRA_SLOT_START <= slot <= EXTRA_SLOT_END:
            raise _layout_error(
                path,
                "slot %d is outside the calibratable range %d-%d"
                % (slot, EXTRA_SLOT_START, EXTRA_SLOT_END),
            )
        result[slot] = _normalize_slot_value(path, slot, raw_value)
    return result


def load_calibration(path: Optional[str] = None) -> Dict[int, str]:
    """Read ``layout.json`` and return ``{slot: names}``.

    Missing files are not an error (nothing is calibrated yet). An empty value
    means the slot is known to be dead; a missing slot is uncalibrated.
    """
    resolved = default_layout_path() if path is None else os.path.expanduser(path)
    key = os.path.abspath(resolved)
    if key in _CALIBRATION_CACHE:
        return dict(_CALIBRATION_CACHE[key])
    try:
        with open(resolved, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        result: Dict[int, str] = {}
    except OSError as exc:
        raise _layout_error(
            resolved, "cannot read calibration: %s" % (exc.strerror or exc)
        ) from exc
    except ValueError as exc:
        raise _layout_error(resolved, "invalid JSON: %s" % exc) from exc
    else:
        result = _validate_calibration(resolved, data)
    _CALIBRATION_CACHE[key] = result
    return dict(result)


def save_calibration(slots: Dict[int, str], path: Optional[str] = None) -> str:
    """Atomically write ``{slot: names}`` to ``layout.json``."""
    resolved = default_layout_path() if path is None else os.path.expanduser(path)
    normalized = _validate_calibration(
        resolved,
        {
            "version": LAYOUT_VERSION,
            "slots": {str(slot): value for slot, value in slots.items()},
        },
    )
    document = {
        "version": LAYOUT_VERSION,
        "slots": {
            str(slot): normalized[slot] for slot in sorted(normalized)
        },
    }
    payload = json.dumps(document, indent=2) + "\n"
    parent = os.path.dirname(os.path.abspath(resolved))
    try:
        os.makedirs(parent, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=parent,
            prefix=".layout-",
            delete=False,
        )
        try:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        os.replace(handle.name, resolved)
    except OSError as exc:
        raise _layout_error(
            resolved, "cannot write calibration: %s" % (exc.strerror or exc)
        ) from exc
    clear_calibration_cache()
    return resolved


def _calibrated_lookup(calibration: Dict[int, str]) -> Dict[str, int]:
    """Map lower-case calibrated names to slots; the lowest slot wins."""
    lookup: Dict[str, int] = {}
    for slot in sorted(calibration):
        for name in calibration[slot].split(","):
            if name:
                lookup.setdefault(name.lower(), slot)
    return lookup


def slot_status(slot: int, path: Optional[str] = None) -> str:
    """One of ``main``, ``dead``, ``calibrated``, ``dead-calibrated``, ``uncalibrated``."""
    if slot in SLOT_NAMES:
        return "main"
    if slot in DEAD_SLOTS:
        return "dead"
    calibration = load_calibration(path)
    if slot not in calibration:
        return "uncalibrated"
    return "dead-calibrated" if calibration[slot] == "" else "calibrated"


def _parse_slot(text: str) -> int:
    try:
        slot = int(text, 0)
    except ValueError:
        raise UnknownKey(
            "invalid slot number %r (use slot:0 .. slot:125)" % text
        ) from None
    if not 0 <= slot < NUM_SLOTS:
        raise UnknownKey("slot %d is outside 0..%d" % (slot, NUM_SLOTS - 1))
    return slot


def resolve_key(name: str, path: Optional[str] = None) -> int:
    """Return the LED slot for a key name or ``slot:N``.

    Lookup is case-insensitive and accepts the aliases in :data:`ALIASES` plus
    the extra-key names discovered by ``k622rgb calibrate``.
    """
    if not isinstance(name, str):
        raise UnknownKey("key name must be text, got %r" % (name,))
    text = name.strip()
    if not text:
        raise UnknownKey("empty key name")

    lowered = text.lower()
    if lowered.startswith("slot:"):
        return _parse_slot(text[5:])

    canonical = ALIASES.get(lowered, lowered)
    slot = NAME_TO_SLOT.get(canonical.lower())
    if slot is not None:
        return slot

    extra = canonical_extra_name(text)
    if extra is not None:
        calibrated = _calibrated_lookup(load_calibration(path))
        slot = calibrated.get(extra.lower())
        if slot is not None:
            return slot
        raise UnknownKey(
            "extra key %r is not calibrated yet; run `k622rgb calibrate` "
            "or use slot:N" % name
        )

    slot = _calibrated_lookup(load_calibration(path)).get(lowered)
    if slot is not None:
        return slot
    raise UnknownKey(
        "unknown key %r; see docs/KEYMAP.md (use slot:N for extras)" % name
    )


def canonical_name(slot: int, path: Optional[str] = None) -> str:
    """Human-readable name for a slot, or ``slot:N`` when uncalibrated."""
    if slot in SLOT_NAMES:
        return SLOT_NAMES[slot]
    calibration = load_calibration(path)
    if calibration.get(slot):
        return calibration[slot]
    return "slot:%d" % slot

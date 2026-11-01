"""Key names and LED-slot lookup for the Redragon K622.

Packet slots are the row-major 21-column indices used by the report-0x06
``09 cc`` frame.  The generated tables in :mod:`k622rgb.keymap_data` come from
``docs/keymap-observed.json``, produced by ``tools/keymap_probe.py``.

The K622's G1-G4/MR/RGB/media keys are not individually addressable.  The
Redragon logo has three addressable zones (``LogoLeft``, ``LogoCenter`` and
``LogoRight``).  The bottom row was corrected by a key-name verify pass:
packet slots 84-97 are LShift, dead, Z, X, C, V, B, N, M, comma, period,
slash, dead, RShift.
"""

from .controller import NUM_SLOTS
from .keymap_data import (
    ALIAS_SLOTS,
    DEAD_SLOTS,
    SLOT_NAMES,
    UNLIT_KEYS,
    ZONE_NAMES,
)

#: Addressable non-key LED zones.
ZONES = dict(ZONE_NAMES)

#: Keys whose LED did not light during calibration.
UNLIT = frozenset(UNLIT_KEYS)

#: Accepted spellings that map to a canonical main-key name.
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

#: Accepted spellings for the addressable logo zones.
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

_CANONICAL_TO_SLOT = {name.lower(): slot for slot, name in SLOT_NAMES.items()}
_CANONICAL_TO_SLOT.update(
    {name.lower(): slot for slot, name in ZONE_NAMES.items()}
)
NAME_TO_SLOT = dict(_CANONICAL_TO_SLOT)
for _alias, _canonical in ALIASES.items():
    _slot = _CANONICAL_TO_SLOT.get(_canonical.lower())
    if _slot is not None:
        NAME_TO_SLOT[_alias] = _slot
for _alias, _canonical in ZONE_ALIASES.items():
    _slot = _CANONICAL_TO_SLOT.get(_canonical.lower())
    if _slot is not None:
        NAME_TO_SLOT[_alias] = _slot


class UnknownKey(ValueError):
    """An unknown or unaddressable key name."""


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


def resolve_key(name: str) -> int:
    """Return the packet slot for a key name, zone name or ``slot:N``.

    Lookup is case-insensitive and accepts the aliases in :data:`ALIASES` and
    :data:`ZONE_ALIASES`.  Extra-key names that are not addressable are
    deliberately rejected.
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

    raise UnknownKey(
        "unknown key %r; the K622's G/MR/RGB/media keys are not RGB. "
        "Use LogoLeft/LogoCenter/LogoRight for the logo zones, or slot:N "
        "for diagnostics." % name
    )


def slot_kind(slot: int) -> str:
    """Return ``key``, ``zone``, ``alias`` or ``dead`` for a packet slot."""
    if slot in SLOT_NAMES:
        return "key"
    if slot in ZONE_NAMES:
        return "zone"
    if slot in ALIAS_SLOTS:
        return "alias"
    return "dead"


def canonical_name(slot: int) -> str:
    """Human-readable key/zone name, or ``slot:N`` for an unmapped slot."""
    if slot in SLOT_NAMES:
        return SLOT_NAMES[slot]
    if slot in ZONE_NAMES:
        return ZONE_NAMES[slot]
    if slot in ALIAS_SLOTS:
        return ALIAS_SLOTS[slot]
    return "slot:%d" % slot

"""Key names and LED-slot lookup for the Redragon K622.

The slot numbers and canonical names come from the official ``Cfg.ini``
``[KEY]`` section (normalised as described in ``docs/KEYMAP.md``). The K622's
G1-G4/MR/RGB/media keys are not RGB; slots ``102-125`` and the ``Cfg.ini`` gaps
are duplicate/dead matrix positions and can still be addressed explicitly as
``slot:N`` for diagnostics.
"""

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

#: Extra 126-slot positions; duplicate/dead on the K622 (not RGB keys).
EXTRA_SLOT_START = 102
EXTRA_SLOT_END = 125
EXTRA_SLOTS = range(EXTRA_SLOT_START, EXTRA_SLOT_END + 1)

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
    """Return the LED slot for a main key name or ``slot:N``.

    Lookup is case-insensitive and accepts the aliases in :data:`ALIASES`.
    Extra-key names are deliberately rejected: the K622's G/MR/RGB/media keys
    do not have individually addressable RGB LEDs.
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
        "Use slot:N for diagnostics." % name
    )


def canonical_name(slot: int) -> str:
    """Human-readable main-key name, or ``slot:N`` for an unmapped slot."""
    return SLOT_NAMES.get(slot, "slot:%d" % slot)

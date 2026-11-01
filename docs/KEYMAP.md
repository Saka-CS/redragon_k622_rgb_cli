# Key map — Redragon K622 RGB

The LED packet contains **126 RGB slots**. This document maps them.

- **Slots `0–101`** — 87 main keys, taken from the official `Cfg.ini`.
- **Slots `102–125`** — unknown; G/MR/media candidates and/or dead slots.
- **Dead slots in `0–101`** — 15 slots with no LED.

The official `Cfg.ini` line format is:

```ini
K58=266,148,288,173, 0x02,0x4A,0x00,45,70
```

The **eighth** field (`45`) is the LED slot. The ninth field (`70`) is a
separate internal key index (0–121), **not** the LED slot.

## Main key table (slots 0–101)

| Slot | Cfg.ini label | CLI name | Cfg key index |
|-----:|:--------------|:---------|--------------:|
| 0 | `Esc` | `Esc` | 0 |
| 1 | &#96; | &#96; | 21 |
| 2 | `Tab` | `Tab` | 42 |
| 3 | `CapsLock` | `Caps` | 63 |
| 4 | `LShift` | `LShift` | 84 |
| 5 | `LCtrl` | `LCtrl` | 105 |
| 6 | — | — | — |
| 7 | `1` | `1` | 22 |
| 8 | `Q` | `Q` | 43 |
| 9 | `A` | `A` | 64 |
| 10 | `Z` | `Z` | 86 |
| 11 | `LWin` | `Win` | 106 |
| 12 | `F1` | `F1` | 2 |
| 13 | `2` | `2` | 23 |
| 14 | `W` | `W` | 44 |
| 15 | `S` | `S` | 65 |
| 16 | `X` | `X` | 87 |
| 17 | `LAlt` | `LAlt` | 107 |
| 18 | `F2` | `F2` | 3 |
| 19 | `3` | `3` | 24 |
| 20 | `E` | `E` | 45 |
| 21 | `D` | `D` | 66 |
| 22 | `C` | `C` | 88 |
| 23 | — | — | — |
| 24 | `F3` | `F3` | 4 |
| 25 | `4` | `4` | 25 |
| 26 | `R` | `R` | 46 |
| 27 | `F` | `F` | 67 |
| 28 | `V` | `V` | 89 |
| 29 | — | — | — |
| 30 | `F4` | `F4` | 5 |
| 31 | `5` | `5` | 26 |
| 32 | `T` | `T` | 47 |
| 33 | `G` | `G` | 68 |
| 34 | `B` | `B` | 90 |
| 35 | `Space` | `Space` | 110 |
| 36 | `F5` | `F5` | 6 |
| 37 | `6` | `6` | 27 |
| 38 | `Y` | `Y` | 48 |
| 39 | `H` | `H` | 69 |
| 40 | `N` | `N` | 91 |
| 41 | — | — | — |
| 42 | `F6` | `F6` | 7 |
| 43 | `7` | `7` | 28 |
| 44 | `U` | `U` | 49 |
| 45 | `J` | `J` | 70 |
| 46 | `M` | `M` | 92 |
| 47 | — | — | — |
| 48 | `F7` | `F7` | 8 |
| 49 | `8` | `8` | 29 |
| 50 | `I` | `I` | 50 |
| 51 | `K` | `K` | 71 |
| 52 | `,` | `,` | 93 |
| 53 | `RAlt` | `RAlt` | 113 |
| 54 | `F8` | `F8` | 9 |
| 55 | `9` | `9` | 30 |
| 56 | `O` | `O` | 51 |
| 57 | `L` | `L` | 72 |
| 58 | `.` | `.` | 94 |
| 59 | `Fn` | `Fn` | 114 |
| 60 | `F9` | `F9` | 10 |
| 61 | `0` | `0` | 31 |
| 62 | `P` | `P` | 52 |
| 63 | `;` | `;` | 73 |
| 64 | `/` | `/` | 95 |
| 65 | `App` | `Menu` | 115 |
| 66 | `F10` | `F10` | 11 |
| 67 | `-` | `-` | 32 |
| 68 | `[` | `[` | 53 |
| 69 | `'` | `'` | 74 |
| 70 | — | — | — |
| 71 | — | — | — |
| 72 | `F11` | `F11` | 12 |
| 73 | `=` | `=` | 33 |
| 74 | `]` | `]` | 54 |
| 75 | — | — | — |
| 76 | — | — | — |
| 77 | — | — | — |
| 78 | `F12` | `F12` | 13 |
| 79 | `Backspace` | `Bksp` | 34 |
| 80 | `\` | `\` | 55 |
| 81 | `Enter` | `Enter` | 76 |
| 82 | `RShift` | `RShift` | 97 |
| 83 | `RCtrl` | `RCtrl` | 118 |
| 84 | `PrtSc` | `PrtSc` | 14 |
| 85 | `Insert` | `Ins` | 35 |
| 86 | `Delete` | `Del` | 56 |
| 87 | — | — | — |
| 88 | — | — | — |
| 89 | `Left` | `Left` | 119 |
| 90 | `SrcLock` | `ScrLk` | 15 |
| 91 | `Home` | `Home` | 36 |
| 92 | `End` | `End` | 57 |
| 93 | — | — | — |
| 94 | `Up` | `Up` | 99 |
| 95 | `Down` | `Down` | 120 |
| 96 | `Pause` | `Pause` | 16 |
| 97 | `PgUp` | `PgUp` | 37 |
| 98 | `PgDn` | `PgDn` | 58 |
| 99 | — | — | — |
| 100 | — | — | — |
| 101 | `Right` | `Right` | 121 |

## Dead slots

```text
6, 23, 29, 41, 47, 70, 71, 75, 76, 77, 87, 88, 93, 99, 100
```

These slots exist in the 126-slot packet but have no LED on the K622. Writing
any color to them has no visible effect.

## Extra slots (102–125)

These slots are **not** described by `Cfg.ini`'s `[KEY]` section. They may hold
the G/MR/media LEDs, may be dead, or may belong to a sibling variant. Each must
be calibrated.

| Candidate key | CLI alias | Likely slots | Status |
|---|---|---|---|
| G1 | `G1` | `102–125` | Unknown |
| G2 | `G2` | `102–125` | Unknown |
| G3 | `G3` | `102–125` | Unknown |
| G4 | `G4` | `102–125` | Unknown |
| MR | `MR` | `102–125` | Unknown |
| RGB toggle | `RGB` | `102–125` | Unknown |
| Previous track | `Prev` | `102–125` | Unknown |
| Play/Pause | `Play` | `102–125` | Unknown |
| Next track | `Next` | `102–125` | Unknown |
| Mute | `Mute` | `102–125` | Unknown |
| Volume roller | `Volume` | `102–125` | Unknown; may have no LED |

The physical board shows **G1–G4 + MR**, not a separate G5. `Cfg.ini`'s `[FN]`
section lists G1–G5; G5 may be an alias for MR or a sibling-variant entry.

## Calibration output

`k622rgb calibrate` writes `~/.config/k622rgb/layout.json`:

```json
{
  "version": 1,
  "slots": {
    "102": "G1",
    "103": "G2",
    "104": "G3",
    "105": "G4",
    "106": "MR",
    "107": "RGB",
    "108": "Prev",
    "109": "Play",
    "110": "Next",
    "111": "Mute",
    "112": ""
  }
}
```

Rules:

- `""` means “calibrated as dead”.
- A missing slot means “not yet calibrated”.
- Slots not present in the file are treated as dead/unknown.
- The file is optional; without it, only slots `0–101` are addressable.

## Aliases

Key lookup is case-insensitive. The following aliases are accepted:

| Canonical | Aliases |
|---|---|
| `Esc` | `Escape` |
| `Caps` | `CapsLock` |
| `Win` | `LWin`, `Super`, `Meta` |
| `Menu` | `App`, `Application` |
| `Bksp` | `Backspace`, `Back` |
| `Ins` | `Insert` |
| `Del` | `Delete` |
| `ScrLk` | `SrcLock`, `ScrollLock` |
| `PrtSc` | `PrintScreen`, `Print` |
| `Enter` | `Return` |
| `Space` | `Spacebar` |
| `` ` `` | `Grave`, `Backtick` |
| `;` | `Semicolon` |
| `'` | `Quote`, `Apostrophe` |
| `,` | `Comma` |
| `.` | `Period`, `Dot` |
| `/` | `Slash` |
| `\` | `Backslash` |
| `[` | `LeftBracket` |
| `]` | `RightBracket` |
| `-` | `Minus`, `Hyphen` |
| `=` | `Equals` |
| `Up` / `Down` / `Left` / `Right` | `ArrowUp`, `ArrowDown`, `ArrowLeft`, `ArrowRight` |
| `G1`–`G4`, `MR`, `RGB`, `Prev`, `Play`, `Next`, `Mute`, `Volume` | Calibration-dependent |

## Machine-readable map

Slots `0–101` as JSON (dead slots omitted):

```json
{
  "0": "Esc",
  "1": "`",
  "2": "Tab",
  "3": "Caps",
  "4": "LShift",
  "5": "LCtrl",
  "7": "1",
  "8": "Q",
  "9": "A",
  "10": "Z",
  "11": "Win",
  "12": "F1",
  "13": "2",
  "14": "W",
  "15": "S",
  "16": "X",
  "17": "LAlt",
  "18": "F2",
  "19": "3",
  "20": "E",
  "21": "D",
  "22": "C",
  "24": "F3",
  "25": "4",
  "26": "R",
  "27": "F",
  "28": "V",
  "30": "F4",
  "31": "5",
  "32": "T",
  "33": "G",
  "34": "B",
  "35": "Space",
  "36": "F5",
  "37": "6",
  "38": "Y",
  "39": "H",
  "40": "N",
  "42": "F6",
  "43": "7",
  "44": "U",
  "45": "J",
  "46": "M",
  "48": "F7",
  "49": "8",
  "50": "I",
  "51": "K",
  "52": ",",
  "53": "RAlt",
  "54": "F8",
  "55": "9",
  "56": "O",
  "57": "L",
  "58": ".",
  "59": "Fn",
  "60": "F9",
  "61": "0",
  "62": "P",
  "63": ";",
  "64": "/",
  "65": "Menu",
  "66": "F10",
  "67": "-",
  "68": "[",
  "69": "'",
  "72": "F11",
  "73": "=",
  "74": "]",
  "78": "F12",
  "79": "Bksp",
  "80": "\\",
  "81": "Enter",
  "82": "RShift",
  "83": "RCtrl",
  "84": "PrtSc",
  "85": "Ins",
  "86": "Del",
  "89": "Left",
  "90": "ScrLk",
  "91": "Home",
  "92": "End",
  "94": "Up",
  "95": "Down",
  "96": "Pause",
  "97": "PgUp",
  "98": "PgDn",
  "101": "Right"
}
```

## Notes

- The official `Cfg.ini` label `SrcLock` is a typo for `ScrLk`.
- The official `Cfg.ini` label `App` is the Menu/Application key.
- The official `Cfg.ini` label `Backspace` is normalized to `Bksp`.
- The main-key map matches the reference KS82-B map for slots `0–101`; labels
  differ slightly but the slot assignments are identical.
- The 15 dead slots are the same gaps present in the reference full-size map's
  main block.

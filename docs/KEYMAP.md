# Key map — Redragon K622 RGB

The LED packet contains **126 RGB slots**. This document maps the packet slots
to the physical keys and to the addressable logo zones.

The map was verified by writing one slot at a time and then by a key-name
verify pass on the physical keyboard (2026-11-01). The raw observations are in
[`keymap-observed.json`](keymap-observed.json).

## Two numbering systems

`Cfg.ini` and the report-0x06 `09 cc` frame use different indices for the same
physical LEDs:

```text
Cfg.ini LED slot    = col * 6  + row      (column-major, 6 rows)
packet slot         = row * 21 + col      (row-major, 21 columns)
```

Convert between them with:

```text
packet_slot = (cfg_slot % 6) * 21 + (cfg_slot // 6)
cfg_slot    = (packet_slot % 21) * 6 + (packet_slot // 21)
```

The old `layout.py` used the Cfg slot as the packet index, which shifted every
key. For example, `set W=green` wrote packet `14`, which lights **PrtSc**.
`W` is packet `44`. The old note “slot 6 lights F5” and “slot 105 lights LCtrl”
were also packet slots and fit the transpose exactly.

## Main keys

`SLOT_NAMES` contains 87 keys. The `Cfg` column is the official `Cfg.ini` LED
slot, kept for reference only.

| Packet | Cfg | CLI name |
|---:|---:|:---|
| 0 | 0 | `Esc` |
| 2 | 12 | `F1` |
| 3 | 18 | `F2` |
| 4 | 24 | `F3` |
| 5 | 30 | `F4` |
| 6 | 36 | `F5` |
| 7 | 42 | `F6` |
| 8 | 48 | `F7` |
| 9 | 54 | `F8` |
| 10 | 60 | `F9` |
| 11 | 66 | `F10` |
| 12 | 72 | `F11` |
| 13 | 78 | `F12` |
| 14 | 84 | `PrtSc` |
| 15 | 90 | `ScrLk` |
| 16 | 96 | `Pause` |
| 21 | 1 | &#96; |
| 22 | 7 | `1` |
| 23 | 13 | `2` |
| 24 | 19 | `3` |
| 25 | 25 | `4` |
| 26 | 31 | `5` |
| 27 | 37 | `6` |
| 28 | 43 | `7` |
| 29 | 49 | `8` |
| 30 | 55 | `9` |
| 31 | 61 | `0` |
| 32 | 67 | `-` |
| 33 | 73 | `=` |
| 34 | 79 | `Bksp` |
| 35 | 85 | `Ins` |
| 36 | 91 | `Home` |
| 37 | 97 | `PgUp` |
| 42 | 2 | `Tab` |
| 43 | 8 | `Q` |
| 44 | 14 | `W` |
| 45 | 20 | `E` |
| 46 | 26 | `R` |
| 47 | 32 | `T` |
| 48 | 38 | `Y` |
| 49 | 44 | `U` |
| 50 | 50 | `I` |
| 51 | 56 | `O` |
| 52 | 62 | `P` |
| 53 | 68 | `[` |
| 54 | 74 | `]` |
| 55 | 80 | `\` |
| 56 | 86 | `Del` |
| 57 | 92 | `End` |
| 58 | 98 | `PgDn` |
| 63 | 3 | `Caps` |
| 64 | 9 | `A` |
| 65 | 15 | `S` |
| 66 | 21 | `D` |
| 67 | 27 | `F` |
| 68 | 33 | `G` |
| 69 | 39 | `H` |
| 70 | 45 | `J` |
| 71 | 51 | `K` |
| 72 | 57 | `L` |
| 73 | 63 | `;` |
| 74 | 69 | `'` |
| 76 | 81 | `Enter` |
| 84 | 4 | `LShift` |
| 86 | 10 | `Z` |
| 87 | 16 | `X` |
| 88 | 22 | `C` |
| 89 | 28 | `V` |
| 90 | 34 | `B` |
| 91 | 40 | `N` |
| 92 | 46 | `M` |
| 93 | 52 | `,` |
| 94 | 58 | `.` |
| 95 | 64 | `/` |
| 97 | 82 | `RShift` |
| 99 | 94 | `Up` |
| 105 | 5 | `LCtrl` |
| 106 | 11 | `Win` |
| 107 | 17 | `LAlt` |
| 110 | 35 | `Space` |
| 113 | 53 | `RAlt` |
| 114 | 59 | `Fn` |
| 115 | 65 | `Menu` |
| 118 | 83 | `RCtrl` |
| 119 | 89 | `Left` |
| 120 | 95 | `Down` |
| 121 | 101 | `Right` |

### Bottom-row correction

The first sweep accepted the expected values for C through `/` too quickly, so
the bottom row was off by one packet slot. A key-name verify pass corrected it:

```text
84 LShift
85 dead
86 Z
87 X
88 C
89 V
90 B
91 N
92 M
93 ,
94 .
95 /
96 dead
97 RShift
```

The final map therefore uses:

- `Z` → packet `86`
- `X` → packet `87`
- `C` → packet `88`
- `V` → packet `89`
- `B` → packet `90`
- `N` → packet `91`
- `M` → packet `92`
- `,` → packet `93`
- `.` → packet `94`
- `/` → packet `95`

`X` lights normally at packet `87`; there are no unlit keys. Packet slot `85`
is a dead gap.

The `Cfg` column in the table is the key's official `Cfg.ini` slot, not the
packet slot's transposed Cfg position. For the corrected bottom row these
values are therefore not monotonic with the packet slot.

## Addressable logo zones

The Redragon logo has three independently addressable segments. They are not
keys, but they are RGB zones and can be set by name.

| Packet | Cfg | Zone |
|---:|---:|:---|
| 77 | 87 | `LogoLeft` |
| 78 | 93 | `LogoCenter` |
| 79 | 99 | `LogoRight` |

Accepted aliases: `logo1`/`logoleft`/`logo-left`, `logo2`/`logocenter`/
`logocentre`/`logo-center`, and `logo3`/`logoright`/`logo-right`.

## Alias slots

There are no alias slots in the final map. Packet slot `95` is the primary
`/` slot.

## Dead slots

These packet slots exist in the 126-slot frame but have no LED on the K622:

```text
1, 17, 18, 19, 20, 38, 39, 40, 41, 59, 60, 61, 62, 75, 80, 81, 82, 83,
85, 96, 98, 100, 101, 102, 103, 104, 108, 109, 111, 112, 116, 117, 122,
123, 124, 125
```

## Aliases

Key lookup is case-insensitive. The main aliases are:

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
| `LogoLeft` | `logo1`, `logoleft`, `logo-left` |
| `LogoCenter` | `logo2`, `logocenter`, `logocentre`, `logo-center` |
| `LogoRight` | `logo3`, `logoright`, `logo-right` |
| `G1`–`G4`, `MR`, `RGB`, `Prev`, `Play`, `Next`, `Mute`, `Volume` | Rejected: not RGB keys on the K622 |

## Machine-readable map

The full observed mapping is in
[`keymap-observed.json`](keymap-observed.json). It records every packet slot,
the Cfg slot, the expected value, the observed value, the status, and any
inferred or unlit keys (both empty in the final map).

The generated runtime tables are in
[`../k622rgb/keymap_data.py`](../k622rgb/keymap_data.py).

## Notes

- The official `Cfg.ini` label `SrcLock` is a typo for `ScrLk`.
- The official `Cfg.ini` label `App` is the Menu/Application key.
- The official `Cfg.ini` label `Backspace` is normalized to `Bksp`.
- The main-key labels match the official `Cfg.ini`; only the packet slot
  numbers differ because of the transpose.
- Slots `102–125` are not extra keyboard keys. Most are dead; the logo zones
  are the only addressable non-key LEDs found.

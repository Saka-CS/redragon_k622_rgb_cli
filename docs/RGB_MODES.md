# RGB modes and configuration — Redragon K622

Everything on this page was verified on the physical K622 on 2026-11-01.
The official `KeyboardDrv.exe` (V1.6.6) was also run under Wine 11 to confirm
the mode list and the UI option set.

## 1. Feature set

The official lighting tab exposes exactly these RGB options:

| Option | Values | Notes |
|---|---|---|
| Mode | 20 effects, **Self-define**, **OFF** | see the table below |
| Brightness | `0`–`9` | per mode |
| Speed | `1`–`4` | per mode; effects that do not animate ignore it |
| RGB (random) | on/off | on = firmware random/multicolour palette |
| Colour | custom RGB | written to palette entry 0 for the selected mode |
| Light | on/off | UI master switch; **OFF** is also a mode |

The RGB set is the **87 main keys only**. The G1–G4, MR, RGB toggle,
Previous, Play/Pause, Next, Mute and volume roller do **not** have
individually addressable RGB LEDs; they stayed dark in both Fixed_on and
Self-define modes. See [KEYMAP.md](KEYMAP.md).

There is **no direction control** on the K622. The official `Cfg.ini` has a
`direct` column in every `LedOptN` row, and it is `0` for all 22 entries.

This was also tested directly on hardware (2026-11-01): setting bit 3 of the
per-mode colour byte (the `direction_left` bit in the sibling Sinowealth K16
layout) does **not** reverse an effect. On `Rainbow_wheel` it changes the
effect to a static colour; on `Fixed_on` it selects a different fixed colour.
The K16 direction-bit hypothesis is therefore rejected for the K622. The
official K622 manual documents `Fn+←/→` as speed, not direction.

The firmware preserves the full 8-bit colour field (bits 3–7 included) when it
is written, but the official app only writes `0x00–0x07`. Bit 3 is not
direction; bits 4–7 remain undocumented, are never set by `k622rgb`, and were
not visually mapped. Do not treat them as a direction control.

The official software does not expose a per-key brightness slider: per-key
colours are sent as raw RGB values.

## 2. Built-in modes

The UI order, internal mode byte and supported parameters are:

| UI # | Mode byte | Name | Speed | Brightness | Random | 7-colour |
|---:|---:|---|:---:|:---:|:---:|:---:|
| 1 | 1 | Fixed_on | – | yes | yes | yes |
| 2 | 2 | Respire | yes | yes | yes | yes |
| 3 | 3 | Rainbow | yes | yes | – | – |
| 4 | 4 | Flash_away | yes | yes | yes | yes |
| 5 | 5 | Raindrops | yes | yes | yes | yes |
| 6 | 6 | Rainbow_wheel | yes | yes | – | – |
| 7 | 7 | Ripples_shining | yes | yes | yes | yes |
| 8 | 8 | Stars_twinkle | yes | yes | yes | yes |
| 9 | 9 | Shadow_disappear | yes | yes | yes | yes |
| 10 | 10 | Retro_snake | yes | yes | yes | yes |
| 11 | 11 | Neon_stream | yes | yes | yes | yes |
| 12 | 12 | Reaction | yes | yes | yes | yes |
| 13 | 13 | Sine_wave | yes | yes | yes | yes |
| 14 | 14 | Retinue scanning | yes | yes | yes | yes |
| 15 | 15 | Rotating windmill | yes | yes | yes | yes |
| 16 | 16 | Colorful waterfall | yes | yes | – | – |
| 17 | 17 | Blossoming | yes | yes | – | – |
| 18 | 18 | Rotating storm | yes | yes | yes | yes |
| 19 | 19 | Collision | yes | yes | yes | yes |
| 20 | 20 | Perfect | yes | yes | yes | yes |
| 21 | 21 | Self-define / per-key | – | – | – | – |
| 22 | 0 | OFF | – | – | – | – |

Aliases accepted by the CLI include `static`, `solid`, `breathing`,
`flash`, `wave`, `sine`, `snake`, `neon`, `windmill`, `waterfall`,
`blossom`, `storm`, `per-key`, `custom` and `off`. See
`k622rgb mode list`.

## 3. Config block — `03 c6`

Read it with report `0x05`:

```text
SET5  05 83 c6 00 00 00
GET6  06 83 c6 ...              (262 bytes)
```

The writable **136-byte config block** is response bytes `0x08..0x8F`.
Write it with report `0x06`:

```text
06 03 c6 00 40 00 00 00 <136-byte config> <zeros to 1032 bytes>
```

Layout of the 136-byte block:

| Offset | Meaning |
|---:|---|
| `0x0C` | per-key flag (`1` for Self-define, otherwise `0`) |
| `0x0D` | current mode (`0`–`21`) |
| `0x1E + 2*(mode-1)` | effect colour byte (`0`–`6`, `7` = random) |
| `0x1F + 2*(mode-1)` | speed/brightness byte: `(speed << 4) | brightness` |
| `0x46` or `0x81` | `5a a5` marker. The older 20-mode layout uses `0x46`; the factory-default layout extends the mode table and uses `0x81`. Both are accepted. |

The 20 effect parameter pairs used by the K622 occupy `0x1E..0x45`; the
factory-default layout has additional pairs beyond them. A no-op round trip
was verified on hardware: reading the config, writing it back unchanged, and
reading it again returns the same bytes. `Fn+Esc` factory reset changes the
layout from the 20-mode form (marker at `0x46`) to the extended form (marker at
`0x81`); both are supported.

## 4. Effect palette — `08 c8`

Read with:

```text
SET5  05 88 c8 00 00 00
GET6  06 88 00 ...              (1032 bytes)
```

The 441-byte palette starts at response offset `0x08`. It is **21 blocks of
21 bytes**:

| Block | Meaning |
|---:|---|
| 0 | OFF (normally all zero) |
| 1–20 | effects 1–20 |

Each block is seven RGB triples, colour index 0..6:

```text
block[mode] = R0 G0 B0  R1 G1 B1  ...  R6 G6 B6
```

Write it with report `0x06`:

```text
06 08 c8 00 40 00 00 00 <441-byte palette> <zeros to 1032 bytes>
```

The firmware stores the palette byte-for-byte; a write/read round trip was
verified. A typical factory palette is
`#ff0000 #0000ff #00ff00 #ffff00 #ff00ff #00ffff #ffffff`
(red, blue, green, yellow, magenta, cyan, white), but the order can differ
after a `Fn+Esc` factory reset. Always read the live palette with
`k622rgb color show <mode>`.

The official app's **RGB** checkbox is the random mode (`colour byte = 7`).
Unchecking it and applying a custom colour writes that colour to palette
entry 0 and selects entry 0.

## 5. Per-key frame — `09 cc`

The per-key path is unchanged in wire format. `k622rgb set` switches the board
to Self-define mode by default, because per-key frames are ignored while an
effect mode is active; use `--no-activate` to leave the current mode.

```text
06 09 cc 00 40 00 00 00 <1024-byte payload> (1032 bytes total)
```

The payload holds three 126-byte planes at offsets `0`, `126`, `252`:
red, green, blue. Slot 0 is Esc. This is the frame used by `k622rgb set`.

Read it back with:

```text
SET5  05 89 cc 00 00 00
GET6  06 89 00 ...              (1032 bytes)
```

The 1024-byte payload starts at response offset `0x08` and matches the frame
written by `09 cc` byte-for-byte. `k622rgb set --from-device` uses this as its
base, so successive `set` calls remain additive even after a reboot or after
the official app changed the frame.

The second custom table, `09 d0` / `89 d0`, is read by
`k622rgb config dump` but not written by the CLI. It is not needed for
per-key colours.

## 6. Persistence

Config and palette writes are applied immediately and persist across a
replug/power cycle (the official app uses the same writes and no separate
"save" step). Every write command takes a full backup first:

```bash
k622rgb config dump                 # timestamped backup in the XDG state dir
k622rgb config dump --out ./backup  # explicit directory
k622rgb config restore ./backup      # config + palette
k622rgb config restore ./backup --custom  # also the two custom frames
```

The backup contains:

```text
config-response.bin   262-byte 83 c6 response
colors-response.bin   1032-byte 88 c8 response
custom1-response.bin  1032-byte 89 cc response
custom2-response.bin  1032-byte 89 d0 response
profile-response.bin  1032-byte 84 d8 response (read-only; keymaps/macros)
meta.json
```

## 7. CLI examples

```bash
# list modes and their parameters
k622rgb mode list

# static red, full brightness
k622rgb mode set static --color ff0000 --brightness 9

# breathing blue, slow
k622rgb mode set breathing --color 0000ff --brightness 7 --speed 1

# rainbow, no colour option, speed 3
k622rgb mode set rainbow --speed 3 --brightness 9

# firmware random palette
k622rgb mode set neon-stream --random

# per-key
k622rgb mode set per-key
k622rgb set --from-device Esc=ff0000 1=00ff00

# palette entry 2 of mode 7
k622rgb color set ripples-shining 2 00ffff
k622rgb mode set ripples-shining --color-index 2

# off / dump / restore
k622rgb off
k622rgb config dump
k622rgb config restore /path/to/backup
```

## 8. Local profiles

`k622rgb profile save NAME` stores the config block, effect palette and
(optionally) the custom per-key frame as JSON under
`~/.config/k622rgb/profiles/NAME.json`. `profile load NAME` restores them and
takes a backup first. These are local lighting profiles; the keyboard's
`84 d8` keymap/macro table is never written.

```bash
k622rgb profile save gaming
k622rgb profile load gaming
k622rgb profile list
k622rgb profile show gaming
k622rgb profile delete gaming
```

## 9. Unknown / out of scope

- **Direction** is not exposed by the K622 (`direct=0` for every mode, the
  manual maps `Fn+←/→` to speed, and a direct bit-3 test produced a static
  colour instead of a reversal). It is not implemented.
- Colour-byte values `8–15` are accepted by the firmware but not exposed by
  the official app; in testing they produced static colours, not direction.
  The CLI only exposes `0–6` plus random (`7`).
- **Game-mode key groups** (`GaoshouKey1..5`) are a real per-key RGB feature,
  but the official app exposes them in the key-assignment view
  (**Color Group → Define1..5**), not the Lighting tab. The groups are lists
  of Windows VK codes; each key is painted with its group's colour and the
  result is a normal `09 cc` per-key frame shown in Self-define. `k622rgb` can
  express the same result with `set`; there is no dedicated group command.
  See [FINDINGS.md](FINDINGS.md) §12.
- The `84 d8` profile table contains keymaps/macros. It is dumped read-only
  but never written.
- The full packet-slot sweep found three addressable logo zones (packet slots
  77–79); slot 95 is the primary `/`, and the remaining extra slots are dead.
  See [KEYMAP.md](KEYMAP.md).
- Firmware update, bootloader, flash and macro/keymap writes remain out of
  scope.

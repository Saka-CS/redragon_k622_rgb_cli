# Redragon K622 RGB — Linux control project

Research notes and a pure-stdlib Linux CLI for the per-key RGB lighting of the
**Redragon K622 (Horus TKL)** keyboard.

## Documents

| Document | Contents |
|---|---|
| [FINDINGS.md](FINDINGS.md) | Device identification, official-software analysis, hardware recon evidence, open questions |
| [PROTOCOL.md](PROTOCOL.md) | USB/HID details, declared reports, verified read/write paths, config mailbox |
| [RGB_MODES.md](RGB_MODES.md) | All 20 effects, Self-define/OFF, brightness/speed, palette, per-key frames |
| [KEYMAP.md](KEYMAP.md) | Main-key LED map, duplicate/dead slots, extra-key finding |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | Phased plan, architecture, CLI, testing, acceptance criteria |

## Status

- Research: complete.
- Read-only hardware recon: **verified** on the physical K622.
- Lighting-write capture: **complete** (13 full `09 cc` → `09 d0` → `03 c6`
  updates in a binary usbmon capture).
- Per-key writes: **implemented and verified on hardware**.
- Colour groups: **implemented locally** (vendor `Define1..5` import, presets,
  `group apply`, and `set --group` overlays); they reuse the verified `09 cc`
  frame and need no new protocol.
- `09 d0` game byte: **experimental** (`set --game-flag`). The tool reads the
  current companion frame, changes one byte (default `payload[0] = 1`), backs
  up all tables and sends it. The byte offset is unverified; probe it with
  `--game-flag-offset`/`--game-flag-value`.
- Built-in effects, brightness/speed, effect palette and Self-define/OFF:
  **implemented and verified on hardware** (config `03 c6` round trip,
  `08 c8` palette write, `05 83 c6`/`05 88 c8` reads).
- Official UI: **verified under Wine 11** (mode list, sliders, colour picker).
- Extra keys: **not RGB**. G1-G4, MR, the RGB toggle and the media buttons
  stayed dark in both Fixed_on and Self-define modes. `Cfg.ini` has no `[KEY]`
  entries for them.
- Packet-slot map: **verified by a full 126-slot sweep and a key-name verify
  pass**. The RGB set is the 87 main keys plus three addressable Redragon logo
  zones (`LogoLeft`, `LogoCenter`, `LogoRight`). There are no aliases and 36
  dead slots. The corrected bottom row puts `Z` at 86, `X` at 87, `C` at 88,
  and `/` at 95.
- Remaining work: dynamic/reactive effects, a daemon, or a GUI.
- Commits: hardware gate passed.

## Short version

- Keyboard: USB `258a:0049`, Sinowealth controller.
- Control interface: IF1 (`/dev/hidraw6` at research time, never hardcode it).
- Declared vendor reports: feature `0x05` (5 bytes) and feature `0x06`
  (1031 bytes). **There is no report `0x08`.**
- Read path verified: report `0x05` returns `05 01 02 00 00 00`.
- Config read: `05 83 c6 00 00 00` → report 6 → 262 bytes; the 136-byte
  writable block is at offset `0x08`.
- Palette read: `05 88 c8 00 00 00` → report 6 → 1032 bytes; the 441-byte
  palette is at offset `0x08`.
- Config write: report `0x06`, header `06 03 c6 00 40`, then 136 config bytes.
- Palette write: report `0x06`, header `06 08 c8 00 40`, then 441 palette bytes.
- Per-key write: report `0x06`, header `06 09 cc 00 40`, 1024 payload bytes.
- 20 effects + Self-define + OFF; brightness `0–9`; speed `1–4`; random or
  one of seven palette colours per effect.
- Safety: only declared reports and captured K622 frames; no firmware,
  bootloader, macro or keymap writes. Every config/palette write backs up
  first.

## Commands

```bash
./bin/k622rgb info            # descriptor + declared report table
./bin/k622rgb check           # discovery, permissions, descriptor hash
./bin/k622rgb dump --report 5 --out /tmp/k622/rep5.bin
./bin/k622rgb config show     # current mode, parameters and palette
./bin/k622rgb config dump     # full lighting backup (config, palette, frames)
./bin/k622rgb config restore ./backup
./bin/k622rgb mode list       # all 20 effects + Self-define + OFF
./bin/k622rgb mode set static --color ff0000 --brightness 9
./bin/k622rgb mode set breathing --color 0000ff --brightness 7 --speed 1
./bin/k622rgb mode set rainbow --speed 3 --brightness 9
./bin/k622rgb mode set neon-stream --random
./bin/k622rgb color set ripples-shining 2 00ffff
./bin/k622rgb mode set ripples-shining --color-index 2
./bin/k622rgb mode set per-key
./bin/k622rgb set --dry-run --no-state Esc=red           # print exact frame
./bin/k622rgb set --from-device 1=green                  # additive from device
./bin/k622rgb set --no-activate Esc=red                  # leave the current mode
./bin/k622rgb set Esc=red                                # write (hash checked)
./bin/k622rgb set 1=green                                 # additive with saved frame
./bin/k622rgb set --off                                   # all LEDs off
./bin/k622rgb off                                         # built-in OFF mode
./bin/k622rgb profile save gaming                         # local lighting profile
./bin/k622rgb profile load gaming
./bin/k622rgb profile list
./bin/k622rgb group list                                  # vendor groups + presets
./bin/k622rgb group import Cfg.ini                        # read-only local import
./bin/k622rgb group set 1=red 2=green 3=blue 4=yellow 5=cyan
./bin/k622rgb group apply                                 # paint + Self-define
./bin/k622rgb set --group fps=ff0000 Esc=ffffff           # group overlay
./bin/k622rgb list                                        # main-key LED map
```

## Extra keys

The K622's G1–G4, MR, RGB toggle, Previous, Play/Pause, Next, Mute and volume
roller **do not have individually addressable RGB LEDs**. They stayed dark in
both Fixed_on and Self-define modes while the main keys changed colour, and
`Cfg.ini` has no `[KEY]` entries for them. The RGB set is the 87 main keys
plus the three addressable logo zones.

The full sweep also found three addressable Redragon logo zones at packet
slots 77, 78 and 79. They are exposed as `LogoLeft`, `LogoCenter` and
`LogoRight`. The remaining extra slots are dead.

The numeric `slot:N` escape remains useful for diagnostics:

```bash
./bin/k622rgb set slot:6=ffffff         # lights F5 on the K622
./bin/k622rgb set slot:105=ffffff       # lights LCtrl
./bin/k622rgb set slot:95=ffffff        # lights /
```

`k622rgb set G1=red`, `MR=blue`, etc. are not meaningful on this board.

The key-name verify pass corrected the bottom row: `Z` is packet 86, `X` is
87, `C` is 88, and `/` is 95. Packet 85 is a dead gap.

## Factory reset and mode notes

- `Fn+Esc` resets the keyboard and changes the stored config layout: the
  `5a a5` marker moves from `0x46` to `0x81`. The tool accepts both layouts,
  so `mode`, `color`, `config` and `set` keep working after a reset.
- Per-key `09 cc` frames are ignored while an effect mode is active. `set`
  therefore switches to **Self-define** mode by default; use
  `set --no-activate` if you want to leave the current effect running.
- The K622's G1-G4, MR, RGB/media keys and volume roller are not RGB. There is
  no extra-key calibration command; the RGB set is the 87 main keys plus the
  three addressable logo zones (`LogoLeft`, `LogoCenter`, `LogoRight`).

## Profiles

`profile save NAME` captures the exact config block, effect palette and the
custom per-key frame as JSON under `~/.config/k622rgb/profiles` (respecting
`XDG_CONFIG_HOME`; override with `--dir` or `K622RGB_PROFILE_DIR`).
`profile load NAME` backs up the current lighting, then restores the palette,
the optional per-key frame and the config. These are local **lighting**
profiles; the keyboard's keymap/macro table is never written.

```bash
./bin/k622rgb profile save gaming
./bin/k622rgb profile load gaming
./bin/k622rgb profile show gaming
./bin/k622rgb profile list
./bin/k622rgb profile delete gaming
```

Colour groups mirror the official **Color Group → Define1..5** feature.
`group import Cfg.ini` reads `GaoshouKey1..5` and the `[KEY]` VK labels without
touching the device; `group set` stores colours and optional custom key lists;
`group apply` and `set --group NAME=COLOR` paint them through the normal
per-key frame. The group store is `~/.config/k622rgb/groups.json`.

`info`, `dump`, `check`, and `list` are read-only. `set` sends the captured
`09 cc` report-6 frame and switches to Self-define mode by default (use
`--no-activate` to skip that). `mode`, `color`, `config` and `off` use the
verified configuration mailbox (`05 83 c6` / `05 88 c8`) and the captured
`03 c6` / `08 c8` write shapes. Every config/palette write saves a full backup
first. `set` saves the frame it last wrote under the XDG state directory so
successive calls are additive; `set --from-device` instead reads the custom
frame back from the keyboard.

`dump --report 6` still fails with `EPIPE` when sent without the vendor
handshake. The mailbox commands above are the supported read path; the tool
never sends an arbitrary report-5 command.

## Quick facts

| Property | Value |
|---|---|
| USB VID:PID | `258a:0049` |
| Manufacturer / product | `BY Tech` / `Gaming Keyboard` |
| Boot keyboard interface | IF0, boot keyboard |
| Vendor control interface | IF1, usage page `0xFF00` |
| Vendor reports | feature `0x05` (5 B), feature `0x06` (1031 B) |
| Report `0x08` | does not exist |
| Config read | `05 83 c6 00 00 00` → report 6, 262 B (config at `0x08`) |
| Palette read | `05 88 c8 00 00 00` → report 6, 1032 B (palette at `0x08`) |
| Config write | report `0x06`, `03 c6 00 40`, 136 config bytes |
| Palette write | report `0x06`, `08 c8 00 40`, 441 palette bytes |
| Lighting write frame | report `0x06`, `09 cc 00 40`, 1032 B incl. report ID |
| Colour planes | R `8..133`, G `134..259`, B `260..385` |
| Modes | 20 effects + Self-define (21) + OFF (0) |
| Brightness / speed | `0–9` / `1–4`, per mode |
| Effect palette | 21 blocks × 7 RGB triples (blocks 1–20 used) |
| Template sha256 | `5d922916bdeadf7bfc3676a00855b8c0b9e05562e083d344d67dd58c73e4626a` |
| Key/zone LED slots | 87 keys + 3 logo zones; 36 dead slots; 0 aliases |
| Packet vs Cfg slot | packet = `row*21+col`; Cfg = `col*6+row` |
| RGB order | R, G, B |
| Descriptor sha256 | `32771137a995e90b6fa9d210761c23ce61e60a21accd033b86f484f198a5061c` |
| Reference project | <https://github.com/kn4oqw-clint/redragon-ks82b-rgb> |

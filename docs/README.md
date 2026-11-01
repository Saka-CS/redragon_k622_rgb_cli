# Redragon K622 RGB — Linux control project

Research notes and a pure-stdlib Linux CLI for the per-key RGB lighting of the
**Redragon K622 (Horus TKL)** keyboard.

## Documents

| Document | Contents |
|---|---|
| [FINDINGS.md](FINDINGS.md) | Device identification, official-software analysis, hardware recon evidence, open questions |
| [PROTOCOL.md](PROTOCOL.md) | USB/HID details, declared reports, verified read path, write-capture gate |
| [KEYMAP.md](KEYMAP.md) | Full 126-slot LED map, dead slots, calibration template |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | Phased plan, architecture, CLI, testing, acceptance criteria |

## Status

- Research: complete.
- Read-only hardware recon: **verified** on the physical K622.
- Lighting-write capture: **complete** (13 full `09 cc` → `09 d0` → `03 c6`
  updates in a binary usbmon capture).
- Lighting writes: **implemented and verified on hardware**. The captured
  `09 cc` colour frame is sufficient; the `09 d0`/`03 c6` companions are not
  needed.
- Remaining work: calibrate slots `102–125` and decide on effects/profiles.
- Commits: hardware gate passed.

## Short version

- Keyboard: USB `258a:0049`, Sinowealth controller.
- Control interface: IF1 (`/dev/hidraw6` at research time, never hardcode it).
- Declared vendor reports: feature `0x05` (5 bytes) and feature `0x06`
  (1031 bytes). **There is no report `0x08`.**
- Read path verified: report `0x05` returns `05 01 02 00 00 00`.
- Report `0x06` `GetFeature` stalls (`EPIPE`); the official read handshake
  (`05 83 c6 00 00 00` → report 6) is captured but not sent by this tool.
- Captured lighting frame: report `0x06`, header `06 09 cc 00 40 00 00 00`,
  then 126-byte R, G, B planes at offsets 8, 134, 260.
- The official app follows the colour frame with `09 d0` (latch) and `03 c6`
  (config). This tool currently sends **only** the colour frame.
- Main 87 keys: LED slots `0–101`, taken from the official `Cfg.ini`.
- Extra G/MR/media keys: slots `102–125`, to be discovered by calibration.
- Safety: only declared reports are touched; no firmware/bootloader commands.

## Commands

```bash
./bin/k622rgb info            # descriptor + declared report table
./bin/k622rgb check           # discovery, permissions, descriptor hash
./bin/k622rgb dump --report 5 --out /tmp/k622/rep5.bin
./bin/k622rgb dump --report 6 --out /tmp/k622/rep6.bin   # currently EPIPE
./bin/k622rgb set --dry-run --no-state Esc=red           # print exact frame
./bin/k622rgb set Esc=red                                 # write (hash checked)
./bin/k622rgb set 1=green                                 # additive with saved frame
./bin/k622rgb set --off                                   # all LEDs off
```

`info`, `dump`, and `check` are read-only. `set` is the only write command and
only sends the captured `09 cc` report-6 frame. `dump --report 6` still fails
with `EPIPE`; the official read handshake is captured but not sent by the tool.
`set` saves the frame it last wrote under the XDG state directory so successive
calls are additive; this is a local record, not a device read-back.

## Quick facts

| Property | Value |
|---|---|
| USB VID:PID | `258a:0049` |
| Manufacturer / product | `BY Tech` / `Gaming Keyboard` |
| Boot keyboard interface | IF0, boot keyboard |
| Vendor control interface | IF1, usage page `0xFF00` |
| Vendor reports | feature `0x05` (5 B), feature `0x06` (1031 B) |
| Report `0x08` | does not exist |
| Lighting write frame | report `0x06`, `09 cc 00 40`, 1032 B incl. report ID |
| Colour planes | R `8..133`, G `134..259`, B `260..385` |
| Template sha256 | `5d922916bdeadf7bfc3676a00855b8c0b9e05562e083d344d67dd58c73e4626a` |
| Main key LED slots | `0–101` (87 keys, 15 dead slots) |
| Extra LED slots | `102–125` (unknown, calibration required) |
| RGB order | R, G, B |
| Descriptor sha256 | `32771137a995e90b6fa9d210761c23ce61e60a21accd033b86f484f198a5061c` |
| Reference project | <https://github.com/kn4oqw-clint/redragon-ks82b-rgb> |

# Redragon K622 RGB — Linux control project

Research notes and implementation plan for a Linux CLI that controls the
per-key RGB lighting of the **Redragon K622 (Horus TKL)** keyboard.

## Documents

| Document | Contents |
|---|---|
| [FINDINGS.md](FINDINGS.md) | Device identification, official-software analysis, environment, evidence, open questions |
| [PROTOCOL.md](PROTOCOL.md) | USB/HID details and the expected 382-byte LED feature report |
| [KEYMAP.md](KEYMAP.md) | Full 126-slot LED map, dead slots, calibration template |
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | Phased plan, architecture, CLI, testing, acceptance criteria |

## Status

- Research: complete.
- Hardware verification: **pending** (Phase 0).
- Implementation: not started.

## Short version

- Keyboard: USB `258a:0049`, Sinowealth controller.
- LED control: feature report `0x08`, 382 bytes, on interface 1 (`/dev/hidraw6`).
- Main 87 keys: LED slots `0–101`, taken from the official `Cfg.ini`.
- Extra G/MR/media keys: slots `102–125`, to be discovered by calibration.
- Safety: only the LED report is sent; no firmware/bootloader commands.

> The report ID `0x08` is not declared in the HID descriptor. It is used by the
> reference project on the same controller family and is strongly implied by the
> official K622 software, but it has not yet been verified on this exact board.
> Phase 0 is the go/no-go gate.

## Quick facts

| Property | Value |
|---|---|
| USB VID:PID | `258a:0049` |
| Manufacturer / product | `BY Tech` / `Gaming Keyboard` |
| Boot keyboard interface | `/dev/hidraw5` (IF0, boot keyboard) |
| Vendor control interface | `/dev/hidraw6` (IF1, usage page `0xFF00`) |
| LED packet | 382-byte HID feature report, report ID `0x08` |
| Main key LED slots | `0–101` (87 keys, 15 dead slots) |
| Extra LED slots | `102–125` (unknown, calibration required) |
| RGB order | R, G, B |
| Reference project | <https://github.com/kn4oqw-clint/redragon-ks82b-rgb> |

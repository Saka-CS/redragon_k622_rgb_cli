# Implementation plan — `k622rgb`

Linux CLI for per-key RGB control of the **Redragon K622 Horus TKL RGB**
keyboard, modeled on
[redragon-ks82b-rgb](https://github.com/kn4oqw-clint/redragon-ks82b-rgb).

> **Current state (2026-11-04): implemented.** `k622rgb` `0.5.0` provides
> per-key frames, colour groups, all 20 built-in effects plus Self-define/OFF,
> the effect palette, config/palette backups and restore, and local profiles.
> The suite has 288 passing unit tests. The command reference is section 5;
> the phase plan in section 10 is historical. Hardware writes are governed by
> [SAFETY.md](SAFETY.md); the 2026-11-03 `09 d0` sweep is recorded in
> [INCIDENT-2026-11-03.md](INCIDENT-2026-11-03.md).

> **Status note (2026-11-01): the original premises are superseded.**
> The K622's IF1 descriptor declares only feature reports `0x05` (5 B) and
> `0x06` (1031 B); report `0x08` does not exist. Read-only recon is complete:
> report `0x05` reads `05 01 02 00 00 00`, while report `0x06` GET stalls with
> `EPIPE`. A binary usbmon capture of the official app is also complete: the
> lighting frame is the captured `09 cc` report-6 packet with three 126-byte
> colour planes. The `set` command implements that frame behind an allowlist,
> a descriptor-hash check, `--dry-run`, and a local last-frame record. Hardware
> verification passed: `set Esc=red` lit Esc red, a second `set 1=green` kept
> both, and `set --off` cleared the board. The `09 d0` latch is not needed for
> per-key colours, and `03 c6` is used separately for mode/config writes. See
> [PROTOCOL.md](PROTOCOL.md) sections 6.3 and 13.
> Treat the phase plan below as historical where it mentions report `0x08`.
>
> **Phase 2 removed (2026-11-01).** Hardware testing showed that the K622's
> G1–G4/MR/RGB/media keys have no individually addressable RGB LEDs. The
> historical calibration command and `layout.json` loading were removed.
>
> **Packet-slot correction (2026-11-01).** The `Cfg.ini` LED slot is not the
> report-0x06 packet index. The packet is row-major
> (`packet = row*21 + col`); `Cfg.ini` is column-major
> (`cfg = col*6 + row`). A full 126-slot sweep plus a key-name verify pass
> confirmed 87 keys, three addressable logo zones (`LogoLeft`, `LogoCenter`,
> `LogoRight` at packet slots 77–79), no alias slots, and 36 dead slots. The
> corrected bottom row is `84 LShift, 85 dead, 86 Z, 87 X, 88 C, 89 V, 90 B,
> 91 N, 92 M, 93 comma, 94 period, 95 slash, 96 dead, 97 RShift`. See
> [KEYMAP.md](KEYMAP.md).
>
> **Phase 3 status (2026-11-01): implemented.** The built-in effects are driven
> by the keyboard itself, not host-side animation: `mode`, `color`, `config`
> and `off` use the verified `83 c6`/`03 c6` config mailbox and the
> `88 c8`/`08 c8` effect palette. Brightness `0–9`, speed `1–4`, random or one
> of seven per-mode colours, Self-define and OFF all work on hardware. Every
> write is preceded by a full config/palette backup unless `--no-backup` is
> given; `config restore` is the recovery path. See [RGB_MODES.md](RGB_MODES.md).

## 1. Confirmed scope

- **Core CLI + onboard effects + profiles** — no daemon, GUI, MQTT, or systemd
  service.
- **The RGB set is the 87 main keys plus three addressable logo zones**
  (`LogoLeft`, `LogoCenter`, `LogoRight`). The G/MR/media keys are not RGB;
  slot calibration and `layout.json` were removed after hardware testing.
- **Pure Python standard library** + `bin/k622rgb` launcher — no pip, venv, or
  third-party runtime modules.
- **Wired USB, US QWERTY K622 only.**
- **Safety:** only the declared feature reports and captured K622 frames; no
  firmware, bootloader, macro or keymap writes.

## 2. Non-goals

- No firmware update, bootloader, flash, or guessed vendor opcodes.
- No macro or keymap remapping.
- No Bluetooth/2.4 GHz or ISO-layout variants.
- No daemon, GUI, MQTT, plugin system, ambient/system-monitor modes, or
  notification overlays.
- No keymap, macro or profile-table writes. The captured config/palette
  commands do persist lighting settings, and that persistence is confirmed
  across a power cycle.

## 3. Architecture

```text
k622rgb/
├── bin/
│   └── k622rgb                 # launcher; runs python3 -m k622rgb
├── k622rgb/
│   ├── __init__.py
│   ├── __main__.py             # python -m k622rgb
│   ├── cli.py                  # argparse, command dispatch, output
│   ├── controller.py           # discovery, report codecs, ioctl, frame builders
│   ├── layout.py               # slot→key/zone lookup, aliases, dead slots
│   ├── keymap_data.py          # generated packet-slot tables
│   ├── groups.py               # Define1..5, presets, Cfg.ini import
│   ├── colors.py               # hex / named / r,g,b parsing and scaling
│   ├── profiles.py             # local lighting profile storage
│   ├── state.py                # last-frame and backup storage
│   └── data/
│       └── template_color.bin  # captured 1032-byte report-0x06 template
├── tools/
│   └── keymap_probe.py         # interactive slot probe / keymap generator
├── udev/
│   └── 60-k622rgb.rules
├── tests/
│   ├── __init__.py
│   ├── data/
│   │   └── k622-if1-descriptor.bin
│   ├── test_cli.py
│   ├── test_colors.py
│   ├── test_controller.py
│   ├── test_descriptor.py
│   ├── test_groups.py
│   ├── test_keymap_data.py
│   ├── test_keymap_probe.py
│   ├── test_layout.py
│   ├── test_modes.py
│   ├── test_packet.py
│   └── test_profiles.py
├── docs/
│   ├── README.md
│   ├── FINDINGS.md
│   ├── PROTOCOL.md
│   ├── KEYMAP.md
│   ├── keymap-observed.json
│   ├── RGB_MODES.md
│   └── IMPLEMENTATION_PLAN.md
├── README.md
├── LICENSE                     # MIT
└── .gitignore
```

**Runtime:** Python 3.9+ (host: 3.14.8), standard library only. Tests use
`unittest`, so no `pytest` dependency.

### Module responsibilities

| Module | Responsibility |
|---|---|
| `controller.py` | Find IF1, parse/validate the descriptor, read the config/palette/frame mailboxes, and build/validate/send the captured report-0x06 write shapes. |
| `layout.py` | Loads the generated packet-slot tables (`keymap_data.py`): 87 keys, 3 logo zones, aliases and dead slots; resolves names to packet slots. |
| `keymap_data.py` | Generated `SLOT_NAMES`, `ZONE_NAMES`, `ALIAS_SLOTS`, `DEAD_SLOTS` and `UNLIT_KEYS` tables from `docs/keymap-observed.json`. |
| `groups.py` | Store, recolour and paint `Define1..5` and preset groups; import the vendor `GaoshouKey1..5` lists from `Cfg.ini` read-only. |
| `colors.py` | Parse `#RRGGBB`, `RRGGBB`, `#RGB`, `r,g,b`, named colors; scale brightness for `set`. |
| `profiles.py` | Read/write lighting profiles atomically; list/show/delete. |
| `state.py` | Store the last one-shot frame and timestamped config/palette backups atomically. |
| `cli.py` | Parse commands, route to modules, consistent errors/exit codes. |

### Data flow

```text
CLI command
   │
   ├─ colors.parse() ──► per-key colours
   ├─ layout.lookup() ─► slot indices
   │
   ▼
controller.build_color_packet() ──► 1032-byte report-0x06 frame
   │
   ▼
fcntl.ioctl(fd, HIDIOCSFEATURE(1032), packet)
   │
   ▼
/dev/hidrawN (IF1)

Config and palette writes use the same transport with the captured
`06 03 c6 00 40` / `06 08 c8 00 40` shapes.
```

## 4. Protocol implementation

The original report-0x08 hypothesis was disproven on hardware. The current,
verified protocol is documented in [PROTOCOL.md](PROTOCOL.md); this section
summarizes what the code implements.

### 4.1 Constants

```python
VENDOR_ID = 0x258A
PRODUCT_ID = 0x0049
CONTROL_INTERFACE = "01"
HID_ID_TOKEN = "HID_ID=0003:0000258A:00000049"
ALLOWED_FEATURE_REPORTS = {0x05: 5, 0x06: 1031}
NUM_SLOTS = 126
COLOR_REPORT_ID = 0x06
COLOR_PACKET_HEADER = bytes.fromhex("06 09 cc 00 40 00 00 00")
COLOR_PLANE_BASES = (8, 134, 260)   # R, G, B
CONFIG_WRITE_HEADER = bytes.fromhex("06 03 c6 00 40 00 00 00")
COLOR_WRITE_HEADER = bytes.fromhex("06 08 c8 00 40 00 00 00")
CUSTOM_HEADERS = {
    1: bytes.fromhex("06 09 cc 00 40 00 00 00"),
    2: bytes.fromhex("06 09 d0 00 40 00 00 00"),
}
CUSTOM_PAYLOAD_SIZE = 1024
PER_KEY_MODE = 21
OFF_MODE = 0
```

### 4.2 Discovery

```python
def find_device() -> str:
    for sysfs in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        uevent = read(os.path.join(sysfs, "device", "uevent")).upper()
        if HID_ID_TOKEN not in uevent:
            continue
        if interface_number(sysfs) == CONTROL_INTERFACE:
            return "/dev/" + os.path.basename(sysfs)
    raise DeviceError(...)
```

`interface_number()` walks up from `realpath(sysfs/device)` looking for
`bInterfaceNumber`, up to ~6 levels. Discovery is checked against the captured
IF1 descriptor hash before any write.

### 4.3 Frame codecs

```python
def build_color_packet(colors):
    packet = bytearray(load_color_template())   # captured 1032-byte frame
    for slot, (r, g, b) in colors.items():
        for base, value in zip(COLOR_PLANE_BASES, (r, g, b)):
            packet[base + slot] = value
    return bytes(packet)

def build_config_packet(config): ...          # 03 c6, 136 config bytes
def build_effect_palette_packet(palette): ... # 08 c8, 441 palette bytes
def build_custom_packet(payload, which): ...  # 09 cc / 09 d0 custom frames
```

`validate_color_packet()`, `validate_config()` and
`validate_effect_palette()` check the exact captured header, length and
trailer before a write is attempted.

### 4.4 Send

```python
def write_feature(fd: int, packet) -> int:
    # HIDIOCSFEATURE(len(packet)) after validation.
    # A writable bytearray is required for the 1032-byte frame.
    buffer = bytearray(packet)
    return fcntl.ioctl(fd, hidiocsfeature(len(buffer)), buffer)
```

### 4.5 Safety boundary

- The only writable report is report `0x06`.
- Reads use report `0x05` mailbox commands or report `0x06` responses.
- Only the exact captured `09 cc`, `03 c6`, `08 c8` and custom-frame shapes
  can be sent; there is no generic "send arbitrary feature report" entry
  point and no offset/value path.
- **No arbitrary `09 d0` writes.** Never write unknown/reserved offsets or a
  whole d0 table. `config restore --custom` is the only d0 writer; it requires
  a verified manifest, a descriptor match, `--yes`, and a pre-restore backup
  that includes the custom frames. `--no-backup` is refused with `--custom`,
  d0 is written last, and it is read back afterwards. Normal commands cannot
  reach it.
- Config/palette writes are preceded by a full read-back backup unless
  `--no-backup` is given.
- Errors are raised, never silently retried with a different report ID. Stop
  on the first `EPIPE`, disconnect or re-enumeration.
- No driver detach, no `libusb`, no root daemon.
- SHA-256 manifests are integrity checks, not provenance; `config seal`
  trusts the current directory contents. See [SAFETY.md](SAFETY.md).

## 5. CLI

### 5.1 Commands

| Command | Purpose |
|---|---|
| `k622rgb info` | Show the HID report descriptor and declared reports |
| `k622rgb dump --report {5,6}` | Read a declared feature report (read-only) |
| `k622rgb check` | Verify discovery, permissions and the descriptor hash |
| `k622rgb doctor` | Read-only device/backup health check and recovery ladder |
| `k622rgb list [--all]` | Print the main-key LED map with logo zones, aliases and dead slots |
| `k622rgb set [KEY=COLOR ...]` | Write a per-key frame (`--all`, `--off`, `--reset`, `--from-device`, `--no-activate`, `--brightness 0-9`, `--dry-run`, `--group NAME=COLOR`, `--file FILE`) |
| `k622rgb group list/set/apply/import` | Manage local colour groups, import vendor `GaoshouKey1..5`, and paint them into a per-key frame |
| `k622rgb off` | Select the built-in OFF mode |
| `k622rgb mode list/show/set` | Inspect or select the 20 built-in effects / Self-define / OFF, with brightness, speed, colour or random |
| `k622rgb color list/show/set` | Inspect or edit the seven-colour effect palette |
| `k622rgb config dump/show/restore/seal` | Back up, inspect, verify, seal or restore the lighting config, palette and frames (`restore --verify-only`, `--custom --yes`, `--allow-unverified`) |
| `k622rgb profile list/show/save/load/delete` | Manage local lighting profiles |

### 5.2 Global flags

| Flag | Meaning |
|---|---|
| `--device /dev/hidrawN` | Override auto-detection |
| `--dry-run` | Describe what would happen; do not open the device |
| `--verbose` | Print discovery details |
| `--version` | Print the tool version |

Some commands add their own flags (`set --state/--no-state/--hex`,
`config dump --out`, `profile ... --dir`, `--no-backup`, etc.).

### 5.3 Examples

```bash
./bin/k622rgb info
./bin/k622rgb check
./bin/k622rgb list

./bin/k622rgb set Esc=red
./bin/k622rgb set --all 0000ff --brightness 6
./bin/k622rgb set --from-device 1=00ff00
./bin/k622rgb set --off
./bin/k622rgb set --group fps=ff0000 --group arrows=00ff00 Esc=ffffff
./bin/k622rgb off

./bin/k622rgb group list
./bin/k622rgb group import Cfg.ini
./bin/k622rgb group set 1=red 2=green 3=blue 4=yellow 5=cyan
./bin/k622rgb group apply

./bin/k622rgb mode list
./bin/k622rgb mode set breathing --color 0000ff --brightness 7 --speed 1
./bin/k622rgb mode set rainbow --speed 3 --brightness 9
./bin/k622rgb mode set per-key
./bin/k622rgb color set ripples-shining 2 00ffff

./bin/k622rgb config show
./bin/k622rgb config dump
./bin/k622rgb config seal ./backup          # add hashes to a legacy backup
./bin/k622rgb config restore ./backup
./bin/k622rgb config restore --verify-only ./backup
./bin/k622rgb config restore --custom ./backup --yes
./bin/k622rgb config restore --custom ./legacy --allow-unverified --yes

./bin/k622rgb profile save gaming
./bin/k622rgb profile load gaming
./bin/k622rgb profile list
```

### 5.4 Exit codes

| Code | Meaning |
|---:|---|
| `0` | Success |
| `1` | Device/protocol/runtime error |
| `2` | Usage error (bad arguments, unknown key, invalid color) |
| `130` | Interrupted (`SIGINT` / Ctrl-C) |

## 6. Layout

`layout.py` loads the generated packet-slot tables from
`k622rgb/keymap_data.py`. The full 126-slot sweep found 87 main keys, three
addressable logo zones (`LogoLeft`, `LogoCenter`, `LogoRight` at packet slots
77–79), no alias slots, and 36 dead slots. The numeric
`slot:N` escape remains available for diagnostics.

The G1–G4/MR/RGB/media keys and volume roller have no individually addressable
LEDs. The interactive calibration command and `layout.json` loading were
removed; `list` reports the key, zone, alias and dead-slot map instead.

## 7. Profiles and state

### 7.1 Paths

Profiles respect `XDG_CONFIG_HOME`; the default is
`~/.config/k622rgb/profiles/` (override with `K622RGB_PROFILE_DIR` or
`profile ... --dir`). The last-frame record and config backups use the XDG
state directory, `~/.local/state/k622rgb/` (override with
`K622RGB_STATE_DIR` / `K622RGB_STATE_FILE`).

```text
~/.config/k622rgb/
└── profiles/
    ├── gaming.json
    └── rainbow.json

~/.local/state/k622rgb/
├── last-frame.bin
└── backups/
    └── 20261101-132700/
        ├── meta.json
        ├── config-response.bin
        ├── colors-response.bin
        ├── custom1-response.bin
        ├── custom2-response.bin
        └── profile-response.bin
```

The full set above is what `config dump` writes. `meta.json` is version 2 and
contains a `files` map with each file's size and SHA-256; `config seal` adds
that map to a legacy backup. The automatic backup taken before an ordinary
write contains only `meta.json`, `config-response.bin` and
`colors-response.bin`; a `config restore --custom` pre-restore backup also
includes `custom1-response.bin` and `custom2-response.bin`.

### 7.2 Profile schema

A profile stores the exact device lighting state, not key names:

```json
{
  "version": 1,
  "name": "gaming",
  "created": "2026-11-01T13:27:00Z",
  "config": "<136 bytes, hex>",
  "palette": "<441 bytes, hex>",
  "custom_frame": "<1024 bytes, hex, optional>"
}
```

- The config block carries the mode, brightness/speed and per-mode parameters.
- The palette is the 21 × 21-byte effect palette.
- `custom_frame` is optional (`profile save --no-frame`).
- Writes are atomic (temp file + `os.replace`), and loading validates every
  blob length and version.

### 7.3 State

`last-frame.bin` stores the last `09 cc` frame written by `set`, so successive
calls are additive. `set --from-device` instead reads the custom frame back
from the keyboard, `--no-state` bypasses the local record, and `--reset`
starts from black. Config/palette backups are timestamped directories written
before every write unless `--no-backup` is given.

## 8. Effects

The K622 runs its effects in firmware; the host does not animate frames. The
CLI selects a mode and writes its parameters through the config mailbox.

| Concept | Support |
|---|---|
| Built-in effects | 20 modes (see [RGB_MODES.md](RGB_MODES.md)) |
| Per-key | Self-define mode plus `set` frames |
| Off | Mode OFF (`k622rgb off`) or `set --off` |
| Brightness | `mode set --brightness 0-9` (onboard); `set --brightness 0-9` (software scaling) |
| Speed | `mode set --speed 1-4` (some modes ignore it) |
| Colour | `mode set --color`, `--color-index 0-6`, or `--random` |
| Palette | `color list/show/set` |

Per-key `09 cc` frames are ignored while an effect is active, so `set` switches
to Self-define by default. `profile save/load` captures and restores the whole
lighting configuration. Host-side breathing/rainbow/wave animation, `--fps`
and reactive effects are not implemented.

## 9. Permissions and udev

### 9.1 Recommended rule

`udev/60-k622rgb.rules`:

```udev
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="258a", ATTRS{idProduct}=="0049", TAG+="uaccess"
```

Install:

```bash
sudo cp udev/60-k622rgb.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw
# replug the keyboard
```

### 9.2 Fallback

If `uaccess` does not grant access (e.g., no seat or a non-graphical session),
use the reference-style rule:

```udev
KERNEL=="hidraw*", SUBSYSTEMS=="usb", ATTRS{idVendor}=="258a", ATTRS{idProduct}=="0049", MODE="0666"
```

`MODE="0666"` makes the node world-writable. On a single-user desktop the worst
case is another local user changing LED colors. A dedicated group with
`MODE="0660"` is the stricter alternative, but requires re-login.

### 9.3 Without udev

For a quick test:

```bash
sudo ./bin/k622rgb check
# or temporarily:
sudo chmod 666 /dev/hidrawN   # resets on replug; never hardcode the number
```

`check` reports which case applies.

## 10. Phases

> **Historical record.** The phases below document the original plan. Phase 0
> and Phase 1 were implemented against report `0x06` after report `0x08` was
> disproven. Phase 2 (calibration) was removed because the K622 has no extra
> RGB keys. Phase 3 was implemented with the keyboard's built-in effects
> (`mode`/`color`/`config`) instead of host-side animation. Use the current
> command reference in section 5 and [README.md](../README.md).

### Phase 0 — Hardware protocol probe (gate)

**Deliverables (historical):**

- ~~Minimal `controller.py` with discovery, frame builder, and
  `send_led_frame()`.~~ `controller.py` exists, but the shipped API is
  `build_color_packet()` / `write_feature()`.
- ~~`k622rgb probe` command.~~ Never implemented.
- Unit tests for packet length/header and discovery with fake sysfs.
- Updated verification table in `PROTOCOL.md`.

**Probe sequence:**

1. All off.
2. Packet slot 0 red (Esc).
3. Packet slot 22 green (`1`).
4. Packet slot 121 blue (Right).
5. Packet slot 6 white (F5).
6. Packet slot 0 red → green → blue (RGB order).
7. Sweep all 126 packet slots; the final sweep found logo zones at 77–79
   and dead slots elsewhere. A key-name verify pass corrected the bottom row.

**Exit criteria (historical; superseded):**

- ~~Board responds to report `0x08`.~~ Report `0x08` does not exist; the write
  path is report `0x06` (`09 cc`).
- Main-key slots match the official map.
- Typing is unaffected; no disconnect.
- Extra-slot observations recorded.

**If it fails (historical guidance; do not follow):** stop. Do not try report
`0x06`. Investigate with a USB capture of the official Windows software or
further static analysis. *This guidance was overturned:* report `0x08` failed,
and the capture showed report `0x06` is the correct path.

### Phase 1 — Core CLI (MVP)

**Deliverables (historical):**

- Package skeleton and launcher.
- `controller.py`, `layout.py`, `colors.py`, `doctor.py`.
- ~~Commands: `list`, `info`, `doctor`, `set`, `off`, `key`, `keys`, `fill`,
  `brightness`, `install-udev`.~~ Only `list`, `info`, `set`, `off` shipped
  from this list; the other names were never implemented. Later phases added
  `group`, `mode`, `color`, `config` and `profile`.
- ~~Global flags: `--device`, `--dry-run`, `--verbose`, `--json`.~~ `--device`,
  `--dry-run`, `--verbose` and `--version` exist; `--json` was never
  implemented.
- `udev/60-k622rgb.rules`.
- Unit tests for packet, layout, colors, controller (mocked ioctl), CLI parsing.
- `README.md` quick start.

**Exit criteria (historical; superseded):**

- ~~`set`, `key`, `keys`, `fill`, `off`, `brightness`, `list`, `doctor` work on
  hardware.~~ Only the commands listed in section 5 exist and were verified.
- ~~`--dry-run` prints a valid 382-byte packet.~~ The captured frame is
  **1032 bytes** (report ID plus 1031 data bytes); `--dry-run` prints that.
- Permission errors produce actionable messages.
- Unit tests pass with `python3 -m unittest discover -s tests -v`.

### Phase 2 — Calibration (removed)

The G/MR/media keys have no addressable RGB LEDs. The full sweep replaced the
old calibration command with the generated packet-slot map: 87 keys, three
logo zones, no aliases and 36 dead slots. The `layout.json` support and
extra-key aliases were removed.

### Phase 3 — Profiles and effects (implemented with onboard effects)

**Deliverables (as implemented):**

- `profiles.py` with atomic JSON writes.
- `state.py` last-frame tracking and timestamped config/palette backups.
- `mode list/show/set` for the 20 built-in effects, Self-define and OFF.
- `color list/show/set` for the effect palette.
- `config dump/show/restore` as the backup/recovery path.
- Brightness `0–9`, speed `1–4`, palette colour or random per mode.
- Tests for protocol codecs, profile round-trip, state and CLI parsing.

**Exit criteria (as implemented):**

- `profile save/load/list/show/delete` round-trips.
- All 20 effects, Self-define and OFF work on hardware.
- Brightness/speed/colour/random work on hardware.
- Config and palette survive a power cycle.
- `config restore` recovers a previous state.

### Phase 4 — Polish and acceptance

**Deliverables:**

- Root `README.md` (install, udev, usage, key names, profiles, effects,
  troubleshooting, limitations) plus the detailed `docs/` set.
- `docs/PROTOCOL.md`, `docs/KEYMAP.md` and `docs/RGB_MODES.md` updated with
  hardware results.
- `check` diagnostics: device, IF1, permissions, ioctl, descriptor and packet
  size. The udev rule is shipped in `udev/`.
- MIT `LICENSE`, `.gitignore`.
- Manual hardware test checklist.

**Exit criteria:**

- Fresh clone + udev rule + `./bin/k622rgb set Esc=red` works from the README
  alone.
- All acceptance criteria below are met.

## 11. Testing

### 11.1 Unit tests (no hardware)

| Test file | Coverage |
|---|---|
| `test_packet.py` | Captured template, 1032-byte length, header, RGB planes, zero fill, slot offsets, validation |
| `test_layout.py` | 87 keys, zones, dead/alias slots, numeric slots, rejected extra-key names |
| `test_keymap_data.py` | Generated tables match `docs/keymap-observed.json` (keys, zones, dead slots) |
| `test_keymap_probe.py` | Probe map/report/apply helpers and generated-table formatting |
| `test_groups.py` | Group store, presets, `Cfg.ini` import, merge precedence, env/`--file` overrides |
| `test_colors.py` | Hex (3/6 digit), named, `r,g,b`, invalid input, formatting |
| `test_profiles.py` | Round-trip, atomic write, invalid JSON, missing/invalid fields |
| `test_modes.py` | Mode table, config parse/build/validate, palette, factory-reset layout, CLI mode paths |
| `test_controller.py` | Discovery with fake sysfs, descriptor checks, ioctl numbers, read/write feature shapes, errors |
| `test_descriptor.py` | Captured descriptor fixture, parser, declared report sizes |
| `test_state.py` | Backup manifests, verification (size/hash/descriptor), legacy unverified handling, sealing |
| `test_cli.py` | Command parsing, exit codes, `set` frames, config/profile commands, custom-restore safeguards, `--dry-run` |

Run:

```bash
python3 -m unittest discover -s tests -v
```

### 11.2 Hardware tests (manual)

- `check` on a fresh session.
- `set Esc=red`, `set --all 00aaff`, `set --off`, `off`.
- Per-key sweep: every main key individually.
- Dead-slot check: slots `1, 17, 18, 19, 20, ...` produce no light (full list
  in [KEYMAP.md](KEYMAP.md)). Slots `6` (`F5`) and `23` (`2`) are live.
- `list` and `slot:N` diagnostics.
- All 20 effects with brightness/speed/colour/random; check flicker and typing.
- `config dump` / `config restore` round-trip.
- `config restore --verify-only` on a known backup, with no device open.
- Do **not** test `config restore --custom` on hardware unless a verified
  backup and an ISP/RMA recovery path exist. See [SAFETY.md](SAFETY.md).
- `profile save` / `profile load` round-trip.
- Replug and power cycle: discovery and persisted config still work.
- Permission-denied path: unplug rule or use a non-udev session.
- Concurrent access: second instance reports a clear error.

### 11.3 Fuzzing / edge cases

- Invalid key names, empty assignment list, duplicate keys.
- Colors with missing `#`, 3-digit hex (accepted and expanded), out-of-range `r,g,b`.
- Device disconnect mid-write: stop with a clear error, no traceback.
- Short/long or malformed packets: rejected before ioctl.
- Unknown descriptor hash: writes refused before the device is opened.

## 12. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Unknown descriptor or firmware revision | Descriptor hash check; writes refused before opening the device |
| Malformed/unsupported write shape | Only exact captured `09 cc`, `03 c6`, `08 c8` and custom-frame packets; validated first |
| Arbitrary `09 d0` write | No offset/value path; `config restore --custom` only, with verified manifest, descriptor match, `--yes`, pre-restore custom-frame backup, read-back and one rollback. See [SAFETY.md](SAFETY.md) |
| Accidental keymap/macro write | Those report shapes are never built or sent |
| Extra keys not addressable | Documented limitation; the 87 main keys plus three logo zones still work |
| Built-in effect overrides per-key frame | `set` switches to Self-define by default; `--no-activate` leaves the mode alone |
| udev/uaccess not applied | `check` reports it; fallback `MODE="0666"` documented |
| Bad config write | Full read-back backup before every write unless `--no-backup`; `config restore` |
| Multiple writers | Detect busy device; clear error |
| Label typos | Normalize `SrcLock` → `ScrLk`; keep aliases |

## 13. Acceptance criteria

- Fresh clone + udev rule + `./bin/k622rgb set Esc=red` works from the README
  alone.
- All 87 main keys are mapped and light correctly; the key-name verify pass
  covers every key.
- The RGB set is the 87 main keys plus three addressable logo zones; the
  G/MR/media keys have no addressable RGB LEDs.
- All 20 built-in effects, Self-define and OFF work, with brightness/speed/
  colour/random, without disturbing typing.
- `check` gives a clear fix for every common discovery/permission failure.
- No code path can send a firmware, bootloader, keymap or macro write.
- Profiles round-trip and survive a restart.
- Colour groups round-trip locally, `group import` never touches the device,
  and `set --group` precedence is explicit key > group > base.
- Config/palette persistence across a power cycle is documented; only the
  captured config/palette/frame writes are used.
- Unit tests pass without hardware.
- `--dry-run` produces a valid frame for every command that writes LEDs.

## 14. Future work

Out of scope for this plan, but natural next steps:

- Daemon + Unix-socket IPC + systemd user service.
- Reactive keypress effects (read `/dev/input/event*`; user is in `input` group).
- Ambient/system-monitor modes (CPU, audio VU).
- GUI/tray.
- MQTT/Home Assistant integration.
- ~~Investigating the `GaoshouKey*` game-mode highlighting, if it turns out to
  be an RGB feature on this model.~~ Resolved: it is a per-key RGB feature
  (Color Group → Define1..5) that reuses the `09 cc` frame; see
  [FINDINGS.md](FINDINGS.md) §12. Implemented as `k622rgb group`
  (`list`, `set`, `apply`, `import`) and `set --group NAME=COLOR`.
- ~~Confirming the `09 d0` game byte.~~ Attempted on 2026-11-03 with the
  experimental `set --game-flag` path across Self-define, three nonzero payload
  regions (`6`, `384`, `784`), values `0`/`1`/`255`, d0-only and cc+d0
  sequences, plus a mode switch and replug. No visible rendering, persistence
  or group change was found. The sweep was then widened to roughly
  330 offset/value combinations and left a board non-enumerating, so the
  experimental command and its probe tools were removed. Arbitrary `09 d0`
  writes are forbidden; only `config restore --custom` writes d0, with a
  verified backup, descriptor match, `--yes`, and a pre-restore backup. The
  remaining open question is whether the byte affects game-input (key-press)
  behaviour rather than RGB output. See [INCIDENT-2026-11-03.md](INCIDENT-2026-11-03.md)
  and [SAFETY.md](SAFETY.md).
- Keymap/macro editing, if a safe and captured protocol appears.
- Wireless (Bluetooth/2.4 GHz) and ISO variants.
- Plugin system for effects.

## 15. Getting started

1. Install the udev rule from `udev/60-k622rgb.rules` and replug the keyboard.
2. Run `./bin/k622rgb check` and `./bin/k622rgb info`.
3. Run `./bin/k622rgb set Esc=red` or `./bin/k622rgb mode list`.
4. Read [PROTOCOL.md](PROTOCOL.md) before extending the write paths.

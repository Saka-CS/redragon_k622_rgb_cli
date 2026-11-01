# Implementation plan — `k622rgb`

Linux CLI for per-key RGB control of the **Redragon K622 Horus TKL RGB**
keyboard, modeled on
[redragon-ks82b-rgb](https://github.com/kn4oqw-clint/redragon-ks82b-rgb).

> **Status note (2026-11-01): the original premises are superseded.**
> The K622's IF1 descriptor declares only feature reports `0x05` (5 B) and
> `0x06` (1031 B); report `0x08` does not exist. Read-only recon is complete:
> report `0x05` reads `05 01 02 00 00 00`, while report `0x06` GET stalls with
> `EPIPE`. A binary usbmon capture of the official app is also complete: the
> lighting frame is the captured `09 cc` report-6 packet with three 126-byte
> colour planes. The `set` command implements that frame behind an allowlist,
> a descriptor-hash check, `--dry-run`, and a local last-frame record. Hardware
> verification passed: `set Esc=red` lit Esc red, a second `set 1=green` kept
> both, and `set --off` cleared the board. The `09 d0`/`03 c6` companions are
> not required. See [PROTOCOL.md](PROTOCOL.md) sections 6.3 and 13.
> Treat the phase plan below as historical where it mentions report `0x08`.

## 1. Confirmed scope

- **Core CLI + effects + profiles** — no daemon, GUI, MQTT, or systemd service.
- **Interactive calibration** for the G/MR/media LED slots.
- **Pure Python standard library** + `bin/k622rgb` launcher — no pip, venv, or
  third-party runtime modules.
- **Wired USB, US QWERTY K622 only.**
- **Safety:** only the LED feature report is sent; no firmware/bootloader path.

## 2. Non-goals

- No firmware update, bootloader, flash, or guessed vendor opcodes.
- No macro or keymap remapping.
- No Bluetooth/2.4 GHz or ISO-layout variants.
- No daemon, GUI, MQTT, plugin system, ambient/system-monitor modes, or
  notification overlays.
- No onboard profile persistence unless Phase 0 proves it is safe and stable.

## 3. Architecture

```text
keyboard_RGB_controller/
├── bin/
│   └── k622rgb                 # launcher; runs python3 -m k622rgb
├── k622rgb/
│   ├── __init__.py
│   ├── __main__.py             # python -m k622rgb
│   ├── cli.py                  # argparse, command dispatch, output
│   ├── controller.py           # discovery, ioctl, packet builder
│   ├── layout.py               # slot→key map, aliases, dead slots
│   ├── colors.py               # hex / named / r,g,b parsing
│   ├── profiles.py             # profile + state JSON storage
│   ├── effects.py              # static/breathing/rainbow/wave
│   ├── calibrate.py            # interactive slot discovery
│   └── doctor.py               # diagnostics
├── udev/
│   └── 60-k622rgb.rules
├── tests/
│   ├── test_descriptor.py
│   ├── test_layout.py
│   ├── test_colors.py
│   ├── test_profiles.py
│   ├── test_effects.py
│   ├── test_controller.py
│   └── test_cli.py
├── docs/
│   ├── README.md
│   ├── FINDINGS.md
│   ├── PROTOCOL.md
│   ├── KEYMAP.md
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
| `controller.py` | Find IF1, open hidraw, build/validate the 382-byte frame, send `HIDIOCSFEATURE`. Only public write API is `send_led_frame()`. |
| `layout.py` | Static map for slots `0–101`; load calibrated extras from `layout.json`; key alias lookup; dead-slot handling. |
| `colors.py` | Parse `#RRGGBB`, `RRGGBB`, `r,g,b`, named colors; apply brightness; HSV helpers for effects. |
| `profiles.py` | Read/write profile JSON and `state.json` atomically; list/save/load/delete. |
| `effects.py` | Generate a 126-slot frame for a given time; run the foreground frame loop. |
| `calibrate.py` | Interactive slot-by-slot discovery; write `layout.json`; verify mode. |
| `doctor.py` | Check device presence, permissions, ioctl, descriptor, packet size, udev rule. |
| `cli.py` | Parse commands, route to modules, consistent errors/exit codes. |

### Data flow

```text
CLI command
   │
   ├─ colors.parse() ──► per-key colors
   ├─ layout.lookup() ─► slot indices
   │
   ▼
controller.build_frame(colors) ──► 382-byte packet
   │
   ▼
fcntl.ioctl(fd, HIDIOCSFEATURE(382), packet)
   │
   ▼
/dev/hidrawN (IF1)
```

## 4. Protocol implementation

### 4.1 Constants

```python
VENDOR_ID = 0x258A
PRODUCT_ID = 0x0049
CONTROL_INTERFACE = "01"
HID_ID_TOKEN = "HID_ID=0003:0000258A:00000049"
PACKET_HEADER = bytes([0x08, 0x0A, 0x7A, 0x01])
NUM_SLOTS = 126
PACKET_LENGTH = 382
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
`bInterfaceNumber`, up to ~6 levels.

### 4.3 Packet builder

```python
def build_frame(colors: dict[int, tuple[int, int, int]]) -> bytes:
    packet = bytearray(PACKET_HEADER)
    for slot in range(NUM_SLOTS):
        r, g, b = colors.get(slot, (0, 0, 0))
        packet.extend((r & 0xFF, g & 0xFF, b & 0xFF))
    assert len(packet) == PACKET_LENGTH
    return bytes(packet)
```

### 4.4 Send

```python
def send_led_frame(fd: int, packet: bytes) -> None:
    if len(packet) != PACKET_LENGTH or packet[:4] != PACKET_HEADER:
        raise ValueError("invalid LED frame")
    fcntl.ioctl(fd, hidiocsfeature(PACKET_LENGTH), packet)
```

### 4.5 Safety boundary

- `controller.py` exposes **no** generic `send_feature()`.
- Report `0x06` is not referenced anywhere in the codebase.
- The packet length and header are validated before every send.
- Errors are raised, never silently retried with a different report ID.
- No driver detach, no `libusb`, no root daemon.

## 5. CLI

### 5.1 Commands

| Command | Purpose |
|---|---|
| `k622rgb list` | Print slot→key map, dead slots, calibration status |
| `k622rgb info` | Device path, interface, permissions, packet size |
| `k622rgb doctor` | Diagnose device/udev/ioctl problems |
| `k622rgb set <color>` | Set all keys |
| `k622rgb off` | All LEDs off |
| `k622rgb key <key> <color>` | Set one key |
| `k622rgb keys K=C ...` | Set multiple keys |
| `k622rgb fill <color> [--except ...]` | Fill all except listed keys |
| `k622rgb brightness <0-100>` | Software brightness scaling |
| `k622rgb profile save <name>` | Save current state |
| `k622rgb profile load <name>` | Apply a profile |
| `k622rgb profile list` | List profiles |
| `k622rgb profile show <name>` | Print profile JSON |
| `k622rgb profile delete <name>` | Delete a profile |
| `k622rgb effect static --color <c>` | Static color |
| `k622rgb effect breathing --color <c> --speed <n>` | Breathing |
| `k622rgb effect rainbow --speed <n>` | Rainbow |
| `k622rgb effect wave --speed <n>` | Spatial wave |
| `k622rgb calibrate` | Interactive extra-slot discovery |
| `k622rgb calibrate --verify` | Light each mapped key in sequence |
| `k622rgb probe ...` | Phase 0 hardware probe (kept as a diagnostic command) |
| `k622rgb install-udev` | Print the udev rule and install commands |

### 5.2 Global flags

| Flag | Meaning |
|---|---|
| `--device /dev/hidrawN` | Override auto-detection |
| `--dry-run` | Print packet hex; do not open the device |
| `--verbose` | Debug logging |
| `--json` | Machine-readable output for scripts |
| `--no-color` | Disable ANSI color in output |

### 5.3 Examples

```bash
k622rgb set red
k622rgb set '#00aaff' --brightness 60
k622rgb key W red
k622rgb keys W=#ff0000,E=#00ff00,Space=#0000ff
k622rgb fill blue --except W,A,S,D
k622rgb off
k622rgb brightness 40

k622rgb profile save gaming
k622rgb profile load gaming
k622rgb profile list

k622rgb effect breathing --color cyan --speed 1.2
k622rgb effect rainbow --speed 0.8
k622rgb effect wave --speed 1.0

k622rgb calibrate
k622rgb calibrate --verify
k622rgb doctor
```

### 5.4 Exit codes

| Code | Meaning |
|---:|---|
| `0` | Success |
| `1` | Device/protocol/runtime error |
| `2` | Usage error (bad arguments, unknown key, invalid color) |

## 6. Layout and calibration

### 6.1 Static map

`layout.py` contains the 87-key map for slots `0–101` from
[KEYMAP.md](KEYMAP.md). Dead slots are explicit. Key lookup is case-insensitive
and accepts aliases.

### 6.2 Calibrated extras

`layout.py` loads `~/.config/k622rgb/layout.json` if present:

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
    "111": "Mute"
  }
}
```

- Missing slot → uncalibrated (treated as dead for rendering).
- `""` → explicitly dead.
- The file is optional; without it, only `0–101` are addressable.

### 6.3 Interactive calibration

For each slot in `102–125`:

1. Set all slots to black.
2. Set the target slot to bright white.
3. Ask: `Which key lit up?`
4. Accept `G1`, `G2`, `G3`, `G4`, `MR`, `RGB`, `Prev`, `Play`, `Next`, `Mute`,
   `Volume`, `none`, `skip`, `undo`, `quit`.
5. Save progress after each answer (so a quit does not lose work).
6. At the end, optionally run `--verify` to light each mapped key in sequence.

Edge cases:

- A slot may light more than one key; allow a comma-separated answer.
- A key may light from more than one slot; allow the user to note it.
- `none` marks the slot dead.
- `undo` re-prompts the previous slot.
- `quit` saves and exits.

## 7. Profiles and state

### 7.1 Paths

Respect `XDG_CONFIG_HOME`; default to `~/.config/k622rgb/`.

```text
~/.config/k622rgb/
├── config.json          # optional defaults (brightness, fps)
├── layout.json          # calibrated extra slots
├── state.json           # last one-shot frame
└── profiles/
    ├── gaming.json
    └── rainbow.json
```

### 7.2 Profile schema

```json
{
  "version": 1,
  "name": "gaming",
  "brightness": 100,
  "effect": {"type": "static"},
  "colors": {
    "W": [255, 0, 0],
    "A": [0, 255, 0],
    "Space": [0, 0, 255]
  }
}
```

- Colors are keyed by canonical key name, not slot, so profiles survive layout
  changes.
- `brightness` is 0–100.
- `effect` is optional; profiles may describe a static frame or an effect.
- Writes are atomic (temp file + `os.replace`).

### 7.3 State

`state.json` stores the last one-shot frame (pre-brightness colors), so:

- `brightness` can re-render the current colors.
- `profile save` can capture the current state.
- Effects do not write every frame; they write at start/stop if needed.

## 8. Effects

| Effect | Behavior |
|---|---|
| `static` | One color for all keys, or per-key overrides |
| `breathing` | Single color, sinusoidal brightness |
| `rainbow` | Whole-board hue rotation |
| `wave` | Spatial hue gradient moving across the layout |

- Default 30 FPS; `--fps` configurable.
- `--speed` scales animation time.
- `--brightness` scales output.
- Each tick builds a full 382-byte frame and sends it.
- `Ctrl-C` behavior: `--on-exit restore|off|keep` (default `restore`).
- Effects run in the foreground. When the terminal closes, the effect stops and
  the board keeps the last frame.
- No reactive keypress effects in this scope.

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
sudo ./bin/k622rgb probe ...
# or temporarily:
sudo chmod 666 /dev/hidraw6   # resets on replug
```

`doctor` reports which case applies.

## 10. Phases

### Phase 0 — Hardware protocol probe (gate)

**Deliverables:**

- Minimal `controller.py` with discovery, frame builder, and `send_led_frame()`.
- `k622rgb probe` command.
- Unit tests for packet length/header and discovery with fake sysfs.
- Updated verification table in `PROTOCOL.md`.

**Probe sequence:**

1. All off.
2. Slot 0 red (Esc).
3. Slot 7 green (`1`).
4. Slot 101 blue (Right).
5. Slot 6 white (dead).
6. Slot 0 red → green → blue (RGB order).
7. Slots `102–125` one at a time (record extra keys).

**Exit criteria:**

- Board responds to report `0x08`.
- Main-key slots match the official map.
- Typing is unaffected; no disconnect.
- Extra-slot observations recorded.

**If it fails:** stop. Do not try report `0x06`. Investigate with a USB capture
of the official Windows software or further static analysis.

### Phase 1 — Core CLI (MVP)

**Deliverables:**

- Package skeleton and launcher.
- `controller.py`, `layout.py`, `colors.py`, `doctor.py`.
- Commands: `list`, `info`, `doctor`, `set`, `off`, `key`, `keys`, `fill`,
  `brightness`, `install-udev`.
- Global flags: `--device`, `--dry-run`, `--verbose`, `--json`.
- `udev/60-k622rgb.rules`.
- Unit tests for packet, layout, colors, controller (mocked ioctl), CLI parsing.
- `README.md` quick start.

**Exit criteria:**

- `set`, `key`, `keys`, `fill`, `off`, `brightness`, `list`, `doctor` work on
  hardware.
- `--dry-run` prints a valid 382-byte packet.
- Permission errors produce actionable messages.
- Unit tests pass with `python3 -m unittest discover`.

### Phase 2 — Calibration

**Deliverables:**

- `calibrate.py` with interactive slot discovery.
- `layout.json` loading/merging.
- `calibrate --verify`.
- Extra-key aliases (`G1`–`G4`, `MR`, `RGB`, `Prev`, `Play`, `Next`, `Mute`,
  `Volume`).
- Tests for layout merge and alias lookup.

**Exit criteria:**

- Every addressable extra key is mapped.
- Dead extra slots are recorded.
- `k622rgb key G1 red` works if G1 is addressable.
- `list` shows calibration status.

### Phase 3 — Profiles and effects

**Deliverables:**

- `profiles.py` with atomic JSON writes.
- `state.json` tracking.
- `effect static|breathing|rainbow|wave`.
- `--fps`, `--speed`, `--brightness`, `--on-exit`.
- `Ctrl-C` handling.
- Tests for profile round-trip, state, and deterministic effect frames.

**Exit criteria:**

- `profile save/load/list/show/delete` round-trips.
- Effects run smoothly at 30 FPS.
- Typing remains unaffected.
- `Ctrl-C` restores or turns off as requested.

### Phase 4 — Polish and acceptance

**Deliverables:**

- Full `README.md` (install, udev, usage, key names, calibration, profiles,
  effects, troubleshooting, limitations).
- `docs/PROTOCOL.md` updated with Phase 0 results.
- `docs/KEYMAP.md` updated with calibrated extra slots.
- `doctor` checks: device, IF1, permissions, ioctl, descriptor, packet size,
  udev rule.
- Optional shell completion.
- MIT `LICENSE`, `.gitignore`.
- Manual hardware test checklist.

**Exit criteria:**

- Fresh clone + udev rule + `./bin/k622rgb set red` works from the README alone.
- All acceptance criteria below are met.

## 11. Testing

### 11.1 Unit tests (no hardware)

| Test file | Coverage |
|---|---|
| `test_packet.py` | 382-byte length, header, RGB order, zero fill, slot offsets |
| `test_layout.py` | 87 keys, dead slots, aliases, calibration merge, duplicates |
| `test_colors.py` | Hex, named, `r,g,b`, invalid input, brightness scaling |
| `test_profiles.py` | Round-trip, atomic write, invalid JSON, missing fields |
| `test_effects.py` | Deterministic frames for a given time; speed/brightness |
| `test_controller.py` | Discovery with fake sysfs; ioctl called with 382; errors |
| `test_cli.py` | Command parsing, exit codes, `--dry-run` |

Run:

```bash
python3 -m unittest discover -s tests -v
```

### 11.2 Hardware tests (manual)

- `doctor` on a fresh session.
- `set red`, `set '#00aaff'`, `off`.
- Per-key sweep: every main key individually.
- Dead-slot check: slots `6, 23, ...` produce no light.
- Calibration and `--verify`.
- Effects for 60 seconds each; check flicker and typing.
- Replug: discovery still works.
- Permission-denied path: unplug rule or use a non-udev session.
- Concurrent access: second instance reports a clear error.

### 11.3 Fuzzing / edge cases

- Invalid key names, empty `keys` list, duplicate keys.
- Colors with missing `#`, 3-digit hex (decide: reject or expand), out-of-range
  `r,g,b`.
- Device disconnect mid-effect: stop with a clear error, no traceback.
- Short/long packet in `send_led_frame()`: rejected before ioctl.

## 12. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Report `0x08` rejected by K622 | Phase 0 gate; stop and investigate, never try `0x06` |
| Extra keys not addressable | Document limitation; main 87 keys still work |
| Built-in effect overrides frame | Phase 0 test; investigate a mode-select command if needed |
| udev/uaccess not applied | `doctor` detects; fallback `MODE="0666"` |
| Flicker at 30 FPS | Tune FPS; skip unchanged frames |
| Lighting resets on power cycle | Document; profiles applied on demand |
| Multiple writers | Detect busy device; clear error |
| Shared K618/K622 config | Calibration resolves actual extras; don't trust G5 blindly |
| Label typos | Normalize `SrcLock` → `ScrLk`; keep aliases |

## 13. Acceptance criteria

- Fresh clone + udev rule + `./bin/k622rgb set red` works from the README alone.
- All 87 main keys are individually addressable.
- Calibration resolves the extra keys that actually have LEDs.
- Effects run at 30 FPS without disturbing typing.
- `doctor` gives a clear fix for every common failure.
- No code path can send report `0x06` or any firmware command.
- Profiles round-trip and survive a restart.
- Lighting is documented as volatile; no onboard writes.
- Unit tests pass without hardware.
- `--dry-run` produces a valid packet for every command that writes LEDs.

## 14. Future work

Out of scope for this plan, but natural next steps:

- Daemon + Unix-socket IPC + systemd user service.
- Reactive keypress effects (read `/dev/input/event*`; user is in `input` group).
- Ambient/system-monitor modes (CPU, audio VU).
- GUI/tray.
- MQTT/Home Assistant integration.
- Onboard profile persistence, if Phase 0 proves it safe.
- Wireless (Bluetooth/2.4 GHz) and ISO variants.
- Plugin system for effects.

## 15. First steps

1. Create the package skeleton and `bin/k622rgb`.
2. Implement `controller.py` (discovery, frame builder, ioctl).
3. Implement `probe` and unit tests.
4. Ask the user to install the udev rule (or run with sudo) and execute the
   Phase 0 probe.
5. Record the results, update `PROTOCOL.md`, and proceed to Phase 1.

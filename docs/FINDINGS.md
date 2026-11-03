# Research findings — Redragon K622 RGB on Linux

- **Research date:** 2026-11-01
- **Hardware:** Redragon K622 Horus TKL RGB, wired USB
- **USB ID:** `258a:0049`
- **Host:** Linux, Python 3.14.8, Hyprland/Omarchy desktop
- **Status:** per-key writes, built-in effects, brightness/speed, effect
  palette and config backup/restore are implemented and verified on the
  physical K622. The extra G/MR/media keys are **not RGB**. Only optional work
  remains.

> **2026-11-01 correction — packet-slot sweep.** The `Cfg.ini` LED slot is not
> the report-0x06 packet index. The packet is row-major
> (`packet = row*21 + col`); `Cfg.ini` is column-major
> (`cfg = col*6 + row`). The full 126-slot sweep plus a key-name verify pass
> confirmed 87 keys, three addressable logo zones at packet slots 77–79, no
> alias slots, and 36 dead slots. The corrected bottom row is
> `84 LShift, 85 dead, 86 Z, 87 X, 88 C, 89 V, 90 B, 91 N, 92 M, 93 comma,
> 94 period, 95 slash, 96 dead, 97 RShift`. See [KEYMAP.md](KEYMAP.md) and
> [keymap-observed.json](keymap-observed.json).

## 1. Objective

Build a Linux CLI that controls the per-key RGB lighting of the K622, modeled
on the Redragon KS82-B project:

- <https://github.com/kn4oqw-clint/redragon-ks82b-rgb>

The K622 has no official Linux software. The vendor tool is Windows-only, and
OpenRGB's Sinowealth keyboard driver is disabled. The reference project shows
that the same Sinowealth controller family can be driven safely from Linux with
a pure-stdlib CLI.

## 2. Device identification

### 2.1 `lsusb`

```text
Bus 001 Device 011: ID 258a:0049 BY Tech Gaming Keyboard
```

The bus/device number and `/dev/hidrawN` numbers are not stable across replugs.
The tool must discover the device by VID/PID and interface number, not by path.

### 2.2 USB descriptors

| Field | Value |
|---|---|
| `idVendor` | `0x258a` (BY Tech) |
| `idProduct` | `0x0049` |
| `bcdUSB` | 2.00 |
| `bcdDevice` | 1.01 |
| `bDeviceClass` | 0 (defined per interface) |
| `bNumConfigurations` | 1 |
| `bNumInterfaces` | 2 |
| `bmAttributes` | `0xa0` (bus-powered, remote wakeup) |
| `MaxPower` | 500 mA |

Current sysfs path:

```text
/sys/devices/pci0000:00/0000:00:14.0/usb1/1-6/1-6.4/
```

### 2.3 Interfaces

| Interface | hidraw | Usage page/usage | Class/subclass/protocol | Endpoint | Purpose |
|---|---|---|---|---|---|
| IF0 | `/dev/hidraw5` | `0x01` / `0x06` | `3` / `1` / `1` | `0x81`, 8-byte interrupt | Boot keyboard (normal typing) |
| IF1 | `/dev/hidraw6` | `0xFF00` / `0x01` | `3` / `0` / `0` | `0x82`, 16-byte interrupt | Vendor control (LEDs, extra keys, mouse) |

sysfs details:

```text
IF0: /sys/devices/pci0000:00/0000:00:14.0/usb1/1-6/1-6.4/1-6.4:1.0/0003:258A:0049.000D
IF1: /sys/devices/pci0000:00/0000:00:14.0/usb1/1-6/1-6.4/1-6.4:1.1/0003:258A:0049.000E
```

HID uevent (annotated; `HID_PHYS` differs per interface):

```text
DRIVER=hid-generic
HID_ID=0003:0000258A:00000049
HID_NAME=BY Tech Gaming Keyboard
HID_PHYS=usb-0000:00:14.0-6.4/input0   (IF0)
HID_PHYS=usb-0000:00:14.0-6.4/input1   (IF1)
MODALIAS=hid:b0003g0001v0000258Ap00000049
```

### 2.4 Input nodes

```text
/dev/input/by-id/usb-BY_Tech_Gaming_Keyboard-event-kbd        -> ../event9
/dev/input/by-id/usb-BY_Tech_Gaming_Keyboard-event-if01       -> ../event11
/dev/input/by-id/usb-BY_Tech_Gaming_Keyboard-if01-event-mouse -> ../event13
/dev/input/by-id/usb-BY_Tech_Gaming_Keyboard-if01-mouse       -> ../mouse1
```

These are not needed for the chosen scope. They are recorded here because a
future reactive/ambient mode could read key events directly from
`/dev/input/event*` without `python-evdev` (the user is in the `input` group).

### 2.5 Permissions

At research time:

```text
crw------- 1 root root 243, 5 ... /dev/hidraw5
crw------- 1 root root 243, 6 ... /dev/hidraw6
```

- No udev rule matching `258a`, `sinowealth`, or `redragon` exists in
  `/etc/udev/rules.d` or `/usr/lib/udev/rules.d`.
- The user `saka` is in groups `saka`, `uinput`, `ollama`, `docker`, `input`,
  `wheel`, but is not root.
- Passwordless sudo is not available.
- A one-time udev rule install (or a root-run probe) is required.

## 3. HID report descriptors

### 3.1 Sizes

| Interface | Descriptor length | Notes |
|---|---:|---|
| IF0 | 67 bytes (`0x43`) | Boot keyboard |
| IF1 | 227 bytes (`0xE3`) | Vendor control + extra keyboard + mouse |

### 3.2 Report IDs on IF1

| ID | Type | Size | Usage | Notes |
|---:|---|---|---|---|
| `0x01` | Input | 3 bits + 5 pad = 1 B | `0x01` / `0x80` | System control (power/sleep/wake) |
| `0x02` | Input | 16-bit array = 2 B | `0x0C` / `0x01` | Consumer control |
| `0x03` | Input | 3 bytes | `0xFF00` / `0x2F` | Vendor |
| `0x04` | Input | 120 bits = 15 B | `0x01` / `0x06` | Keyboard report for extra keys |
| `0x05` | Feature | 5 bytes | `0xFF00` / `0x01` | Vendor mailbox/status |
| `0x06` | Feature | **1031 bytes** | `0xFF00` / `0x01` | Vendor payload; 1032 with report ID |
| `0x07` | Input | Mouse, 7 B | `0x01` / `0x02` | 5 buttons, X/Y, wheel, AC pan |
| `0x08` | — | **not declared** | — | Does not exist on this board |

The report descriptor is stored at `tests/data/k622-if1-descriptor.bin`
(227 bytes, sha256
`32771137a995e90b6fa9d210761c23ce61e60a21accd033b86f484f198a5061c`) and is
parsed by `k622rgb/controller.py`.

The earlier project premise that a 382-byte feature report `0x08` could be sent
is **false for the K622**. Report `0x08` is absent from the descriptor; sending
it made `HIDIOCSFEATURE` block for 5 seconds and fail with `ETIMEDOUT`.

### 3.3 Hardware read recon (2026-11-01)

Run against the physical K622 with `/dev/hidraw6` (IF1):

| Command | Result |
|---|---|
| `./bin/k622rgb info` | descriptor 227 B, known hash, 7 reports, no `0x08` |
| `./bin/k622rgb check` | open read-only OK; descriptor and sizes OK |
| `./bin/k622rgb dump --report 5` | `05 01 02 00 00 00` (6 bytes) |
| `./bin/k622rgb dump --report 6` | **`EPIPE`** — the device stalls the GET |

The report-5 read is stable across retries. The report-6 GET stall means report
`0x06` cannot be read in isolation; the official app first sends a report-5
command (`83 c6 00 00 00`), sleeps 20 ms, then reads report `0x06`. That
handshake is implemented: `05 83 c6` returns a 262-byte config, `05 88 c8`
returns the effect palette, `05 89 cc`/`05 89 d0` return the custom frames,
and `05 84 d8` returns the profile table.

Full descriptor hex dumps are in [PROTOCOL.md](PROTOCOL.md).

### 3.4 Lighting-write capture (2026-11-01)

A binary usbmon capture of the official Windows app changing colours contains
13 complete lighting updates. Each update is three report-6 `SetFeature`
writes in this order:

| Order | Payload prefix | Length | Varies with colour? |
|---:|---|---:|---|
| 1 | `06 09 cc 00 40` | 1032 B | **yes** |
| 2 | `06 09 d0 00 40` | 1032 B | no |
| 3 | `06 03 c6 00 00` | 1032 B | no |

Only the `09 cc` frame changes. Its bytes 8..133 are the red plane, 134..259
the green plane, and 260..385 the blue plane, each with slot 0 first. Bytes
386..1031 are byte-for-byte constant. The all-off frame is stored at
`k622rgb/data/template_color.bin` (sha256
`5d922916bdeadf7bfc3676a00855b8c0b9e05562e083d344d67dd58c73e4626a`).

The tool builds a frame by copying that template, writing the three planes,
and checking the header and tail before `HIDIOCSFEATURE(1032)`. It sends only
the `09 cc` frame.

### 3.5 Hardware write verification (2026-11-01)

| Step | Command | Observed |
|---|---|---|
| Single colour frame | `set --no-state Esc=red` | Esc red, everything else dark |
| Additive frame | `set Esc=red`, then `set 1=green` | Esc red **and** `1` green |
| Clear | `set --off` | all LEDs dark; saved frame hash = template hash |

The colour frame alone is sufficient. The constant `09 d0` and `03 c6`
companions captured alongside it are **not required** for per-key colours and
remain unsent. The slot/plane mapping derived from `Cfg.ini` and the capture
matches the physical board.

Implementation note: CPython's `fcntl` refuses an immutable `bytes` ioctl
argument over 1024 bytes (`ValueError: ioctl argument 3 is too long`). Passing
a writable `bytearray` avoids the cap; the 1032-byte `HIDIOCSFEATURE` transfer
then succeeds without a stall.

## 4. Official K622 software

### 4.1 Installer

| Field | Value |
|---|---|
| Filename | `Redragon_K622-RGB_Setup_V1.6.6_20211105.exe` |
| Size | 2,890,226 bytes |
| Format | PE32, Inno Setup 5.3.3 |
| Source | Redragon CDN (`cdn.shopify.com/s/files/1/0012/4957/4961/files/...`) |
| Executed? | **No** — inspected statically only |

Extracted with `innoextract 1.9`:

```bash
innoextract -e -d extracted Redragon_K622-RGB_Setup_V1.6.6_20211105.exe
```

### 4.2 Extracted files of interest

| Path | Purpose |
|---|---|
| `app/Cfg.ini` | Official key→LED-slot map, VID/PID, RGB order |
| `app/KeyboardDrv.exe` | MFC configuration UI |
| `app/Lowerdev.dll` | HID wrapper (`HidParse.dll`) |
| `app/InitSetup.dll` | Setup helper |
| `app/MenuEx.dll` | UI helper |
| `app/skins/keyimg.png` | Accurate keyboard layout image |
| `app/skins/main_nr.png` | UI skin (1000×640) |
| `app/skins/main_mask2.png` | UI mask (1000×640) |
| `app/Text/en/text.xml` | UI strings, LED mode names, media names |

The `KeyboardDrv.exe` PDB path is `\K618-RGB\Debug\KeyboardDrv.pdb`, and the UI
strings mention K618/K622. This is a shared Sinowealth platform; some config
entries may not apply to every variant.

### 4.3 `Cfg.ini`

The file has 345 lines and three sections: `[OPT]`, `[FN]`, `[KEY]`.

Relevant `[OPT]` values:

```ini
Title=Redragon K622-RGB
appdir=K622RGB
VID= 0x258A
PID= 0x0049
DefLedIndex=10
LEDParam=07,29,07,29,...   ; 20 pairs
rcLED=285,342,660,190
ptLEDMode=120,35
MacroBufferNum=12
RGBIndex=0,1,2
GameRGBIndex=0,1,2
```

`RGBIndex=0,1,2` confirms packet channel order **R, G, B**.

`[KEY]` line format:

```ini
K58=266,148,288,173, 0x02,0x4A,0x00,45,70
```

Fields:

| Field | Example | Meaning |
|---|---:|---|
| `x1,y1,x2,y2` | `266,148,288,173` | Key rectangle in the UI |
| type | `0x02` | Key type |
| usage | `0x4A` | Windows virtual-key (VK) code (J) |
| modifier | `0x00` | Modifier byte |
| **LED slot** | **`45`** | **Index in the 126-slot LED packet** |
| key index | `70` | Separate internal index (0–121), not the LED slot |

The `usage` column is a Windows **VK code**, not a HID usage code: `0x4A` is
`VK_J` and `0x70` is `VK_F1` (HID usage `0x0D`/`0x3A` respectively). The
`GaoshouKey*` group lists in §12 use the same VK code space.

The `[KEY]` section contains **87 entries**, using `Cfg.ini` LED slots
`0–101` with 15 gaps. These are *Cfg.ini* slots, not report-0x06 packet slots;
the packet index is the transpose described in [KEYMAP.md](KEYMAP.md).

`[FN]` maps G1–G5 to `K88–K92` with macro IDs `16,17,18,19,24`:

```ini
K88=0x02,0x70,0x00,16   ; G1
K89=0x02,0x71,0x00,17   ; G2
K90=0x02,0x72,0x00,18   ; G3
K91=0x02,0x73,0x00,19   ; G4
K92=0x02,0x74,0x00,24   ; G5
```

These are macro IDs, not confirmed LED slots. The physical board shows G1–G4 and
MR, not a separate G5. Hardware testing later showed these keys have no
addressable RGB LEDs, so the IDs do not map to extra RGB slots.

`[KEY]` has **no entries** for G1–G4, MR, or the media buttons.

### 4.4 `KeyboardDrv.exe` disassembly

The driver contains repeated constants and loops consistent with a 126-slot,
378-byte RGB buffer:

- `0x7E` = 126
- `0x17A` = 378
- `push 0x7e` and `push 0x17a` appear around buffer setup.
- A loop increments by 3 (`add ..., 3`) and compares against the slot count.

This confirms the official software sends **126 RGB triples**, matching the
reference project's 382-byte packet (4 header bytes + 378 color bytes). The
exact report ID/header is not a contiguous immediate in the binary; it is likely
built at runtime. The reference project supplies `08 0A 7A 01`.

### 4.5 `Lowerdev.dll`

Exports:

```text
FindHidDevice
OpenHidDevice
SetFeature
GetFeature
SetOutputReport
GetInputReport
```

Imports from `HID.DLL` / `KERNEL32`:

```text
HidD_GetHidGuid
HidD_GetPreparsedData
HidP_GetCaps
HidD_SetFeature
HidD_GetFeature
HidD_SetOutputReport
HidD_GetInputReport
HidD_GetProductString
HidD_GetManufacturerString
HidD_GetSerialNumberString
HidD_GetAttributes
CreateFileW
WriteFile
```

The official tool uses `HidD_SetFeature` (a Windows `SET_REPORT`) through this
wrapper. That is the same class of transfer as Linux `HIDIOCSFEATURE`.

### 4.6 `text.xml`

The UI exposes 22 LED modes:

```text
Fixed_on, Respire, Rainbow, Flash_away, Raindrops, Rainbow_wheel,
Ripples_shining, Stars_twinkle, Shadow_disappear, Retro_snake,
Neon_stream, Reaction, Sine_wave, Retinue scanning, Rotating windmill,
Colorful waterfall, Blossoming, Rotating storm, Collision, Perfect,
Self-define, OFF
```

Media strings include `Play/Pause`, `Stop`, `Previous`, `Next`,
`Volume up`, `Volume down`, `Mute`, and `RGB On/Off`.

### 4.7 `keyimg.png`

The 611×252 layout image shows:

- Top-left: **G1, G2, G3, G4, MR** (5 round keys)
- Top-right: **5 round media buttons** — RGB On/Off, Previous, Play/Pause,
  Next, Mute
- **3 small red status LEDs** (not RGB addressable keys)
- **Volume roller** (a wheel, not a key)
- 87-key TKL main block: Esc, F1–F12, PrtSc/ScrLk/Pause, Ins/Home/PgUp,
  Del/End/PgDn, arrows, full alpha/number/modifier block

## 5. Physical layout and LED map

### 5.1 Main keys

- 87 keys, US QWERTY, TKL, low-profile.
- `Cfg.ini` LED slots `0–101` with 15 gaps.
- Packet slots are the row-major transpose; the full observed map is in
  [KEYMAP.md](KEYMAP.md).
- 36 dead packet slots and 3 logo zones were found by the full sweep; there
  are no alias slots.

### 5.2 Extra keys

| Key | Notes |
|---|---|
| G1–G4 | Left edge, macro keys |
| MR | Macro-record key |
| RGB | RGB on/off button |
| Prev | Previous track |
| Play | Play/Pause |
| Next | Next track |
| Mute | Mute |
| Volume roller | Wheel; no addressable RGB LED observed |

These are **not** in `Cfg.ini`'s `[KEY]` section, and hardware testing on
2026-11-01 showed they have **no individually addressable RGB LEDs**: G1–G4,
MR, the RGB toggle, Previous, Play/Pause, Next and Mute stayed dark in both
Fixed_on and Self-define modes while the main keys changed colour. The volume
roller also has no addressable LED. The full packet-slot sweep found three
addressable logo zones at packet slots 77–79; the other extra slots are dead.
Packet slot 105 lights LCtrl and slot 6 lights F5 because of the Cfg→packet
transpose, not because `Cfg.ini` slots 105/6 are special.

### 5.3 G5 ambiguity

`Cfg.ini`'s `[FN]` section lists G1–G5, but the physical board shows G1–G4 plus
MR. Since these keys are not RGB on the K622, there is no LED slot to resolve.
G5 remains a sibling-variant/macro alias only.

### 5.4 Label normalization

`Cfg.ini` uses a few labels that differ from the reference project and from
common CLI conventions:

| `Cfg.ini` | CLI name |
|---|---|
| `CapsLock` | `Caps` |
| `LWin` | `Win` |
| `App` | `Menu` |
| `Backspace` | `Bksp` |
| `Insert` | `Ins` |
| `Delete` | `Del` |
| `SrcLock` (typo) | `ScrLk` |
| `` ` `` | `` ` `` (also `Grave`, `Backtick`) |

The CLI will accept both the official label and the normalized name as aliases.

## 6. Protocol evidence and confidence

### 6.1 Reference project

The KS82-B project uses:

```text
USB ID:        258a:0049
Interface:     IF1, usage page 0xFF00, usage 0x01
Packet:        382-byte feature report
Report ID:     0x08
Header:        0x0A 0x7A 0x01
Payload:       126 × RGB triples (378 bytes)
Transport:     HIDIOCSFEATURE ioctl on /dev/hidrawN
```

Its discovery code checks `HID_ID=0003:0000258A:00000049` and
`bInterfaceNumber == "01"`. Its `custom-layout.json` for slots `0–101` matches
the K622 `Cfg.ini` map (labels differ slightly).

The reference project only sends the LED report. It explicitly avoids
firmware/bootloader commands and cites OpenRGB's disabled Sinowealth driver as
a reason to stay on the LED path.

**However, its report ID `0x08` is not transferable to the K622.** The K622
descriptor (and the reference document's own verbatim descriptor) declares only
feature reports `0x05` and `0x06`; report `0x08` does not exist. Attempting it
on the K622 produced the 5-second `ETIMEDOUT` that motivated this pivot.

### 6.2 Official software corroboration

- `Cfg.ini` maps 87 keys to LED slots `0–101` exactly like the reference.
- `RGBIndex=0,1,2` confirms R,G,B order.
- `KeyboardDrv.exe` builds a 126-slot / 378-byte RGB buffer and uses 126-byte
  planes (`imul ..., 0x7e`).
- Big vendor transfers use a 1032-byte buffer: report `0x06` plus 1031 data
  bytes, matching the descriptor's `96 07 04`.
- Short commands use report `0x05` (5 data bytes).
- Captured report-6 lighting sequence: `09 cc 00 40` (colour), `09 d0 00 40`
  (constant latch/effect), `03 c6 00 00` (constant config).
- Other captured report-6 writes: `04 d8 00 40` (profile apply/read-back pair),
  `09 00 40` + 1024 data bytes, and `03 c6` + 136 config bytes.
- The official read path is `SetFeature(report 5, 83 C6 00 00 00)` → 20 ms →
  `GetFeature(report 6, 1032)`; the capture shows a 262-byte config response
  starting `06 83 c6 ...`, while `84 d8` returns 1032 bytes.
- `Lowerdev.dll` wraps `HidD_SetFeature` / `HidD_GetFeature`.

### 6.3 Confidence table

| Claim | Confidence | Basis |
|---|---|---|
| USB VID/PID and interface layout | **Confirmed** | `lsusb`, sysfs, `udevadm` |
| IF1 declares only reports 1–7, no `0x08` | **Confirmed** | Live descriptor parse + fixture hash |
| Report `0x05` readable | **Confirmed** | Hardware: `05 01 02 00 00 00` |
| Report `0x06` GET stalls | **Confirmed** | Hardware: `EPIPE` |
| Official read handshake (`83 C6` → report 6) | **Confirmed by capture** | usbmon: `06 83 c6 …`, 262 B |
| Packet-slot key map | **Confirmed** | Full sweep + verify: 87 keys, 3 logo zones, 0 aliases, 36 dead |
| 126-slot / 126-byte planes | **Confirmed by capture** | R `8`, G `134`, B `260` |
| RGB channel order R,G,B | **Confirmed** | `Cfg.ini` `RGBIndex=0,1,2` |
| Report-6 lighting write packet | **Captured** | `09 cc` + 13 complete updates |
| Write implementation (`set`, allowlist, state) | **Implemented, unit-tested** | 163 tests; `--dry-run` |
| Hardware write (`set Esc=red`) | **Confirmed** | Esc red; `1` green; `--off` clears |
| Additive saved-frame behaviour | **Confirmed on hardware** | Second `set` kept the first colour |
| `09 d0` / `03 c6` companions | **Not required for per-key colours** | Colour frame alone works; `03 c6` is used for mode config; single-byte `09 d0` probe showed no observable effect (2026-11-03) |
| Config read (`05 83 c6` → 136 B at response `0x08`) | **Confirmed** | Hardware read + no-op write round trip |
| Effect palette (`05 88 c8` / `08 c8`, 441 B) | **Confirmed** | Hardware write/read round trip |
| 20 effects + Self-define + OFF | **Confirmed** | Mode sweep on hardware + official UI under Wine 11 |
| Brightness 0–9 / speed 1–4 | **Confirmed** | Config pair write/read; UI sliders |
| Direction control | **Not present / not exposed** | Manual: `Fn+←/→` = speed; UI: no direction; bit-3 test produced a static colour, not a reversal |
| Read-back backup for report 6 | **Confirmed** | `05 89 cc` returns the custom frame; `set --from-device` uses it |
| Extra keys (G/MR/media) | **Not RGB** | Stayed dark in Fixed_on and Self-define; `Cfg.ini` has no `[KEY]` entries |
| Packet-slot sweep + verify | **Confirmed** | 87 keys, 3 logo zones (77–79), 0 aliases, 36 dead; corrected bottom row: Z 86, X 87, C 88 … / 95 |
| Lighting persistence across power cycle | **Confirmed** | Settings survived an unplug/replug power cycle |
| Built-in effect override behavior | **Confirmed** | A `09 cc` frame is ignored while an effect is active; `set` switches to Self-define by default |
| Volume roller addressability | **No RGB** | No addressable LED observed |

## 7. Host environment

| Item | Value |
|---|---|
| Python | 3.14.8 |
| `hid` module | Not installed |
| `evdev` module | Not installed |
| OpenRGB | Not installed |
| User groups | `saka`, `uinput`, `ollama`, `docker`, `input`, `wheel` |
| Passwordless sudo | No |
| hidraw permissions | Root-only |
| udev rule for keyboard | None |

Implications:

- Use pure Python stdlib (`fcntl`, `os`, `glob`, `json`, `argparse`,
  `colorsys`, `time`). No `hidapi`, `libusb`, or `python-evdev`.
- A one-time udev rule install (with sudo) or a root-run probe is required.
- The user is in the `input` group, so future key-event reading is possible
  without extra packages, but it is out of the current scope.

## 8. Reference project comparison

| Aspect | Reference (KS82-B) | This project (K622) |
|---|---|---|
| USB ID | `258a:0049` | `258a:0049` |
| Controller | Sinowealth | Sinowealth |
| Descriptor | Documented, identical to K622 | Identical to reference |
| Layout | Full-size, 108 LEDs | TKL, 87 RGB main keys; extra keys not RGB |
| Packet | 382-byte feature report `0x08` (not valid on K622) | Captured report `0x06` `09 cc`, 1032 B |
| Language | Pure Python stdlib | Same |
| CLI | `ks82rgb` | `k622rgb` |
| Features | CLI, effects, profiles, daemon, GUI, MQTT, plugins, ambient modes | Core CLI + effects + profiles only |
| Udev | `MODE="0666"` | `TAG+="uaccess"` preferred; `MODE="0666"` fallback |
| License | MIT | MIT (default) |

The reference project is much broader than the confirmed scope. The K622
implementation deliberately stops at the core CLI, local profiles, and the
keyboard's 20 built-in effects plus Self-define and OFF. Daemon/IPC, GUI, MQTT,
reactive key effects, and ambient modes are future work.

## 9. Open questions and risks

1. **Report-6 write packet** — Resolved. The captured `09 cc` frame alone sets
   per-key colours on hardware; the `09 d0` latch and `03 c6` config packets
   are not needed and remain unsent.
2. **Read-back backup** — Report `0x06` GET stalls in isolation. The captured
   handshake returns the config, not the colour buffer, so a true read-back is
   still unavailable. The CLI stores the frame it last wrote as a local
   write-ahead record instead.
3. **Extra-key addressability** — Resolved. The K622's G/MR/media keys have no
   individually addressable RGB LEDs. The full sweep found only the three
   logo zones (packet 77–79) among the extra slots; the rest are dead.
4. **Built-in effect override** — Resolved. A per-key `09 cc` frame is ignored
   while an effect mode is active; `k622rgb set` now switches the board to
   Self-define mode by default.
5. **Persistence** — Resolved. The config and effect palette survive an
   unplug/replug power cycle. The tool still never writes the keymap, macro or
   profile-table memory; only the captured config/palette/frame shapes are sent.
6. **udev/uaccess timing** — `TAG+="uaccess"` depends on the login seat. If the
   ACL does not appear, fall back to `MODE="0666"` or a dedicated group.
7. **Frame rate/flicker** — 30 FPS over hidraw should be fine, but the board may
   tear or flicker. Tune FPS and consider skipping unchanged frames.
8. **Regional/wireless variants** — US QWERTY wired only. ISO, Bluetooth, and
   2.4 GHz variants are out of scope.
9. **Shared K618/K622 config** — Some `Cfg.ini` entries (e.g., G5) may belong to
   a sibling variant. The full sweep found no G/MR/media RGB keys; the only
   extra LEDs are the three logo zones at packet slots 77–79.
10. **Label typo** — `SrcLock` in `Cfg.ini` is normalized to `ScrLk`.
11. **Multiple keyboards/concurrency** — Another tool (official software in a
    VM, OpenRGB, a second instance) could fight for the device. The CLI should
    detect and report a busy/invalid device rather than silently corrupt frames.

## 10. Reproduction and artifacts

### 10.1 Commands used

```bash
lsusb
lsusb -d 258a:0049 -v
for d in /dev/hidraw*; do udevadm info -q property -n "$d"; done
od -An -v -tx1 /sys/class/hidraw/hidraw6/device/report_descriptor
cat /sys/class/hidraw/hidraw6/device/uevent
ls -l /dev/input/by-id
id
python3 --version
python3 -c 'import hid'
python3 -c 'import evdev'
grep -ri '258a\|sinowealth\|redragon' /etc/udev/rules.d /usr/lib/udev/rules.d
```

### 10.2 Temporary artifacts

The installer and extracted files live under `/tmp/opencode/k622/`:

```text
/tmp/opencode/k622/k622_setup.exe
/tmp/opencode/k622/extracted/app/Cfg.ini
/tmp/opencode/k622/extracted/app/KeyboardDrv.exe
/tmp/opencode/k622/extracted/app/Lowerdev.dll
/tmp/opencode/k622/extracted/app/skins/keyimg.png
/tmp/opencode/k622/extracted/app/Text/en/text.xml
/tmp/k622/usbmon.jsonl                 # binary usbmon capture
/tmp/k622/template_color.bin           # all-off 09 cc frame
/tmp/k622/template_latch.bin           # constant 09 d0 frame
/tmp/k622/template_config.bin          # constant 03 c6 frame
```

The all-off colour template is also committed as
`k622rgb/data/template_color.bin` because the tool verifies it by hash before
every write.

These are research artifacts and are **not** part of the repository. The
installer was downloaded from the official Redragon CDN and was never executed.

### 10.3 Sources

- Reference project: <https://github.com/kn4oqw-clint/redragon-ks82b-rgb>
- Reference protocol writeup: <https://github.com/kn4oqw-clint/redragon-ks82b-rgb/blob/main/docs/openrgb-4106-report.md>
- OpenRGB issue #4106: <https://gitlab.com/CalcProgrammer1/OpenRGB/-/issues/4106>
- Redragon K622 product page: <https://redragonshop.com/products/horus-k622-tkl-low-profile-keyboard>
- Redragon software page: <https://redragonshop.com/pages/software>
- Official installer: `https://cdn.shopify.com/s/files/1/0012/4957/4961/files/Redragon_K622-RGB_Setup_V1.6.6_20211105.exe`
- Linux kernel raw-request path: `drivers/hid/hidraw.c`,
  `drivers/hid/hid-core.c`, `drivers/hid/usbhid/hid-core.c`


## 11. Follow-up (2026-11-01): modes, palette and config

The official app was also run under **Wine 11** (Flatpak) with the physical
keyboard. Its lighting tab exposed exactly the expected option set:

- 20 effects in the `text.xml` order, plus **Self-define** and **OFF**;
- brightness slider `0–9`;
- speed slider `1–4`;
- an **RGB** checkbox (the firmware random palette);
- a custom colour picker (written to palette entry 0);
- no direction control.

The config mailbox was decoded and verified on hardware:

```text
read  05 83 c6 00 00 00 -> report 6, 262 bytes (config at 0x08)
write 06 03 c6 00 40    -> 136-byte config block
```

The 136-byte block holds the current mode at `0x0D`, the per-key flag at
`0x0C`, and 20 two-byte effect parameter pairs at `0x1E`. Each pair is
`[colour, (speed << 4) | brightness]`, with colour `7` meaning random.

The effect palette is a separate 441-byte table read with `05 88 c8` and
written with `06 08 c8 00 40`: 21 blocks of 21 bytes (block 0 OFF, blocks 1–20
effects, each seven RGB triples). The custom per-key frame is readable with
`05 89 cc`; its 1024-byte payload matches the `09 cc` write payload exactly.

`Cfg.ini`'s `LedOpt1..LedOpt20` rows supply the per-mode feature flags
(speed, brightness, random, colour). The `GaoshouKey*` / `GameGpMask` rows
are a per-key RGB feature; see §12.

## 12. Follow-up (2026-11-02): game-mode key groups (`GaoshouKey*`)

The `GaoshouKey*` entries are a **per-key RGB colouring feature**, not a
keymap/macro feature. The official app exposes them in the key-assignment
view, not the Lighting tab:

- right-click a key → **Color Group** → **Define1..5**
  (`tc_msg28`, `tc_game_mode1..5`; menu command IDs `0xfb` and `0x10f..0x113`).

`Cfg.ini` defines five groups. Each list holds **Windows virtual-key (VK)
codes**, the same code space as the `usage` column of `[KEY]`:

```ini
GaoshouIndex=20
GaoshouKey1=1b,57,41,53,44,26,28,25,27
GaoshouKey2=70,71,72,31,32,33,34,35,9,51,57,45,52,41,53,44,47,10,42,11,12,20,2c,21,22,24,23
GaoshouKey3=31,32,33,34,35,36,37,51,57,45,52,54,41,53,44,46,47,10,43,56,11
GaoshouKey4=31,32,33,34,35,36,37,51,57,45,52,41,53,44,46
GaoshouKey5=57,52,41,53,44,10,11,12,26,28,25,27
```

Decoded defaults:

| Group | Keys |
|---|---|
| 1 | Esc, W, A, S, D, ↑, ↓, ←, → |
| 2 | F1–F3, 1–5, Tab, Q, W, E, R, A, S, D, G, Shift, B, Ctrl, Alt, Space, PrtSc, PgUp/PgDn/Home/End |
| 3 | 1–7, Q, W, E, R, T, A, S, D, F, G, Shift, C, V, Ctrl |
| 4 | 1–7, QWER, ASD, F |
| 5 | W, R, A, S, D, Shift, Ctrl, Alt, arrows |

The group lists use generic `0x10`/`0x11`/`0x12` modifier VKs; `k622rgb group
import` expands those to both left and right Shift/Ctrl/Alt keys.

`GaoshouKeyColor1..5` is a parallel byte-per-key list. `0` uses the global
`clrGaoshou` (default `0xff`); `1..8` select the standard palette (red, green,
blue, magenta, cyan, yellow, white, orange). `GameRGBIndex=0,1,2` gives the
channel order.

### How it is rendered

- `0x4428a0` builds the frame: for each group it maps every VK code to a key
  slot via `0x442200`, then writes that group's colour into a per-key colour
  array.
- `GaoshouIndex` is compared with the current LED mode at `0x4112b0`. The
  app's mode index is 0-based (`0x411010` indexes the `LedOpt` table with it,
  and `0x41ceda` uses it as a `LedMask` bit), so `GaoshouIndex=20` is UI mode
  **21, Self-define**.
- In that mode the app skips the plain per-key payload, sets the "game" flag in
  the `09 d0` packet, and sends `09 cc` + `09 d0` (`0x411659`/`0x4116a9`) —
  the same opcodes `k622rgb` already uses. This is a static-analysis
  inference; the hardware matrix below did not reproduce a single-byte game
  flag.

The feature therefore needs **no new protocol**. `k622rgb set` writes an
equivalent `09 cc` per-key frame, and the firmware shows it in mode 21. The
`09 d0` game flag is not required for ordinary per-key colours; the group menu
is simply one way for the official app to generate the frame. `GaoshouAddr`
(default `0xAC`) and `GameGpMask` (default `0`) are loaded, but their use was
not exercised in the captured paths.

`k622rgb group` implements this as a local convenience layer:
`group import Cfg.ini` reads `GaoshouKey1..5` and maps VK codes through the
`[KEY]` labels, `group set` stores colours and optional key lists, and
`group apply` / `set --group NAME=COLOR` generate the same `09 cc` frame. No
`09 d0` write is needed.

### The `09 d0` "game" byte (experimental, tested negative)

The app's lighting routine has exactly one `09 cc`/`09 d0` writer
(`0x445920`), called from `0x411150`. The `09 d0` payload is sourced from
`[esp+0xcc4]`; in the normal path that stack region is zeroed at `0x411448`
and only the `09 cc` colour planes are filled. No explicit write of a
"game" byte into the `09 d0` payload was found in `KeyboardDrv.exe` V1.6.6.
The game-mode comparison at `0x4112b0` (`GaoshouIndex` vs. current mode)
branches into an `08 c8` palette write and then falls through to the normal
`09 cc` → `09 d0` send.

A live `05 89 d0` read-back from the K622 is **not** all zero and does **not**
match the latch hash recorded in §6.3 (`ce6cd1…`), so the captured latch
artifact is not reproducible from the current state. The payload has the shape
of a 1024-byte table with several 126-byte key masks at offsets `0x000`,
`0x180` and `0x310`; the meaning of those regions is not known.

Because the byte location is unknown, `set --game-flag` is an opt-in
experiment:

- it reads the current `09 d0` frame from the keyboard (no hard-coded
  template);
- it changes one byte (`--game-flag-offset`, default `0`) to
  `--game-flag-value` (default `1`);
- it sends `09 cc`, then `09 d0`, then `03 c6` only when Self-define
  activation is needed;
- it backs up the config, palette, `09 cc` and `09 d0` tables first;
- it prints the old/new byte and the resulting payload hash.

#### Hardware validation (2026-11-03)

Conditions: mode 21 (Self-define) with the per-key flag set, confirmed by
`mode show`; a visibly confirmed solid-blue baseline and a solid-red `09 cc`
baseline; isolated XDG/state directories; a full config/palette/`09 cc`/`09 d0`
backup before the first write.

Tested, with a read-back and a repeat for each condition:

- offsets `0` (default), `6`, `0x180` (decimal `384`) and `0x310` (decimal
  `784`);
- values `0x00`, `0x01` and `0xFF`, including writing `0xFF` into a zero byte;
- d0-only writes (no `09 cc`) and cc+d0 writes;
- a normal `set`, a Rainbow → Self-define switch, and a physical replug.

Result: every write changed exactly the requested byte and nothing else, and
`config restore --custom` restored all four tables byte-for-byte. **No visual,
persistence or group difference was observed.** The mode and flag survived a
normal `set`, a mode switch and a replug, but the display stayed the plain
`09 cc` frame. Key-press/game-input behaviour was not tested, so this does not
rule out a non-RGB meaning for the byte.

The default offset remains a hypothesis, not a confirmed protocol field. To
test a different byte, pass `--game-flag-offset`; to clear it, pass
`--game-flag-value 0`. The 2026-11-03 matrix above found no observable effect,
so the "single `09 d0` byte enables game mode" hypothesis is unsupported for
RGB rendering. The feature is kept as a diagnostic. Recovery is
`config restore --custom BACKUP`.

# Research findings — Redragon K622 RGB on Linux

- **Research date:** 2026-11-01
- **Hardware:** Redragon K622 Horus TKL RGB, wired USB
- **USB ID:** `258a:0049`
- **Host:** Linux, Python 3.14.8, Hyprland/Omarchy desktop
- **Status:** research complete; hardware protocol verification pending (Phase 0)

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
| `0x01` | Input | 3 bits + 5 pad | `0x01` / `0x80` | System control (power/sleep/wake) |
| `0x02` | Input | 16-bit array | `0x0C` / `0x01` | Consumer control |
| `0x03` | Input | 3 bytes | `0xFF00` / `0x2F` | Vendor |
| `0x04` | Input | 120 bits (15 B) | `0x01` / `0x06` | Keyboard report for extra keys |
| `0x05` | Feature | 5 bytes | `0xFF00` / `0x01` | Vendor |
| `0x06` | Feature | **1031 bytes** | `0xFF00` / `0x01` | Vendor; **never touch** (firmware/config risk) |
| `0x07` | Input | Mouse | `0x01` / `0x02` | 5 buttons, X/Y, wheel, AC pan |
| `0x08` | **Not declared** | 382 bytes used | — | LED frame; accepted by this controller family |

The LED report `0x08` is not in the descriptor. The reference project uses it on
a board whose descriptor is byte-for-byte identical, and the official K622
software builds a 126-slot RGB payload. The kernel's raw-request path does not
require the report ID to be declared:

- `hidraw` passes `buf[0]` as the report number to `__hid_hw_raw_request()`.
- `__hid_hw_raw_request()` forwards it to the transport's `raw_request()`.
- `usbhid_set_raw_report()` builds a class `SET_REPORT` control transfer with
  `((rtype + 1) << 8) | reportnum`.

The device firmware, not the kernel, decides whether to accept the undeclared
report. Hardware verification is still required.

Full descriptor hex dumps are in [PROTOCOL.md](PROTOCOL.md).

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
| usage | `0x4A` | HID usage code (J) |
| modifier | `0x00` | Modifier byte |
| **LED slot** | **`45`** | **Index in the 126-slot LED packet** |
| key index | `70` | Separate internal index (0–121), not the LED slot |

The `[KEY]` section contains **87 entries**, using LED slots `0–101` with 15
dead slots. The slot values match the reference KS82-B map exactly.

`[FN]` maps G1–G5 to `K88–K92` with macro IDs `16,17,18,19,24`:

```ini
K88=0x02,0x70,0x00,16   ; G1
K89=0x02,0x71,0x00,17   ; G2
K90=0x02,0x72,0x00,18   ; G3
K91=0x02,0x73,0x00,19   ; G4
K92=0x02,0x74,0x00,24   ; G5
```

These are macro IDs, not confirmed LED slots. The physical board shows G1–G4 and
MR, not a separate G5. Calibration will resolve the naming.

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
- LED slots `0–101`.
- 15 dead slots: `6, 23, 29, 41, 47, 70, 71, 75, 76, 77, 87, 88, 93, 99, 100`.
- Full table in [KEYMAP.md](KEYMAP.md).

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
| Volume roller | Wheel; addressability unknown |

These are **not** in `Cfg.ini`'s `[KEY]` section. They likely occupy some of the
unused slots `102–125`, but the packet may also contain dead slots for other
variants of the same controller. Interactive calibration is required.

### 5.3 G5 ambiguity

`Cfg.ini`'s `[FN]` section lists G1–G5, but the physical board shows G1–G4 plus
MR. Possibilities:

- G5 is an alias for MR.
- G5 exists only on a related variant (K618/K622 family).
- The MR key reports as G5 in macro mode.

Calibration and user confirmation will resolve this. The CLI can support both
`G5` and `MR` aliases pointing to the same slot if needed.

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

### 6.2 Official software corroboration

- `Cfg.ini` maps 87 keys to LED slots `0–101` exactly like the reference.
- `RGBIndex=0,1,2` confirms R,G,B order.
- `KeyboardDrv.exe` builds a 126-slot / 378-byte RGB buffer.
- `Lowerdev.dll` uses `HidD_SetFeature`, the Windows equivalent of
  `HIDIOCSFEATURE`.
- The K622's IF1 descriptor is byte-for-byte identical to the KS82-B descriptor
  documented by the reference project.

### 6.3 Confidence table

| Claim | Confidence | Basis |
|---|---|---|
| USB VID/PID and interface layout | **Confirmed** | `lsusb`, sysfs, `udevadm` |
| Main 87 keys on slots `0–101` | **Confirmed** | Official `Cfg.ini` + reference map |
| 126-slot / 378-byte RGB payload | **Confirmed** | Official driver constants/loops |
| RGB channel order R,G,B | **Confirmed** | `Cfg.ini` `RGBIndex=0,1,2` |
| Report `0x08` + header `0A 7A 01` accepted | **Strong inference** | Reference on identical descriptor; official payload size; not hardware-tested |
| Extra keys on slots `102–125` | **Unknown** | Not in `Cfg.ini`; calibration required |
| Lighting persistence across power cycle | **Unknown** | Not tested |
| Built-in effect override behavior | **Unknown** | Not tested |
| Volume roller addressability | **Unknown** | Not a key; may have no LED |

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
| Layout | Full-size, 108 LEDs | TKL, 87 main keys + extras |
| Packet | 382-byte feature report `0x08` | Same expected |
| Language | Pure Python stdlib | Same |
| CLI | `ks82rgb` | `k622rgb` |
| Features | CLI, effects, profiles, daemon, GUI, MQTT, plugins, ambient modes | Core CLI + effects + profiles only |
| Udev | `MODE="0666"` | `TAG+="uaccess"` preferred; `MODE="0666"` fallback |
| License | MIT | MIT (default) |

The reference project is much broader than the confirmed scope. The K622
implementation will deliberately stop at the core CLI, profiles, and four
effects. Daemon/IPC, GUI, MQTT, reactive key effects, and ambient modes are
future work.

## 9. Open questions and risks

1. **Report `0x08` acceptance** — The descriptor is identical and the official
   payload size matches, but the K622 firmware has not been tested. Phase 0 is
   the gate.
2. **Extra-key addressability** — Slots `102–125` may contain G/MR/media LEDs,
   dead slots, or a mix. Calibration is required.
3. **Built-in effect override** — If the board is in a hardware effect, a
   single per-key frame may be ignored or overridden. Phase 0 will show whether
   a mode-select command is needed.
4. **Persistence** — Lighting likely resets on power cycle. The tool will not
   write onboard memory unless proven safe.
5. **udev/uaccess timing** — `TAG+="uaccess"` depends on the login seat. If the
   ACL does not appear, fall back to `MODE="0666"` or a dedicated group.
6. **Frame rate/flicker** — 30 FPS over hidraw should be fine, but the board may
   tear or flicker. Tune FPS and consider skipping unchanged frames.
7. **Regional/wireless variants** — US QWERTY wired only. ISO, Bluetooth, and
   2.4 GHz variants are out of scope.
8. **Shared K618/K622 config** — Some `Cfg.ini` entries (e.g., G5) may belong to
   a sibling variant. Calibration resolves what this board actually has.
9. **Label typo** — `SrcLock` in `Cfg.ini` is normalized to `ScrLk`.
10. **Multiple keyboards/concurrency** — Another tool (official software in a
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
```

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

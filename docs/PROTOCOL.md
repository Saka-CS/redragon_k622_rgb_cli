# Protocol — Redragon K622 RGB LED control

- **Device:** Redragon K622 Horus TKL RGB (wired USB)
- **USB ID:** `258a:0049`
- **Control interface:** IF1, usage page `0xFF00`, usage `0x01`
- **LED transport:** HID feature report `0x08`, 382 bytes
- **Status:** strongly inferred from the reference project and the official
  software; **hardware verification pending**

## 1. Summary

The keyboard exposes two HID interfaces:

- **IF0** — normal boot keyboard, used for typing.
- **IF1** — vendor control interface. The LED frame is sent here as a HID
  **feature report** with `HIDIOCSFEATURE`.

The expected LED frame is:

```text
byte 0       : 0x08                 report ID
bytes 1..3   : 0x0A 0x7A 0x01       command header
bytes 4..381 : 126 × RGB triples    per-slot colors (378 bytes)
total        : 382 bytes
```

Only this LED report is ever sent. Report `0x06` (the 1031-byte vendor feature
report) is **never** used. There is no firmware, bootloader, flash, macro, or
keymap path.

## 2. USB identity

| Field | Value |
|---|---|
| `idVendor` | `0x258a` |
| `idProduct` | `0x0049` |
| Manufacturer string | `BY Tech` |
| Product string | `Gaming Keyboard` |
| `bcdUSB` | 2.00 |
| `bcdDevice` | 1.01 |
| `bNumInterfaces` | 2 |
| `bmAttributes` | `0xa0` (bus-powered, remote wakeup) |
| `MaxPower` | 500 mA |

`lsusb`:

```text
Bus 001 Device 011: ID 258a:0049 BY Tech Gaming Keyboard
```

The bus/device and `/dev/hidrawN` numbers are not stable. Discover by VID/PID
and interface number.

## 3. Interfaces

| Interface | hidraw | Usage page/usage | Class/subclass/protocol | Endpoint | Purpose |
|---|---|---|---|---|---|
| IF0 | `/dev/hidraw5` | `0x01` / `0x06` | `3` / `1` / `1` | `0x81`, 8-byte interrupt | Boot keyboard |
| IF1 | `/dev/hidraw6` | `0xFF00` / `0x01` | `3` / `0` / `0` | `0x82`, 16-byte interrupt | Vendor control |

sysfs paths at research time:

```text
IF0: /sys/devices/pci0000:00/0000:00:14.0/usb1/1-6/1-6.4/1-6.4:1.0/0003:258A:0049.000D
IF1: /sys/devices/pci0000:00/0000:00:14.0/usb1/1-6/1-6.4/1-6.4:1.1/0003:258A:0049.000E
```

`uevent` for both:

```text
DRIVER=hid-generic
HID_ID=0003:0000258A:00000049
HID_NAME=BY Tech Gaming Keyboard
MODALIAS=hid:b0003g0001v0000258Ap00000049
```

## 4. Report descriptors

### 4.1 IF0 — boot keyboard (67 bytes, `0x43`)

```text
05 01 09 06 a1 01 05 07 19 e0 29 e7 15 00 25 01
95 08 75 01 81 02 95 01 75 08 81 03 95 06 75 08
15 00 26 ff 00 05 07 19 00 2a ff 00 81 00 25 01
95 05 75 01 05 08 19 01 29 05 91 02 95 01 75 03
91 03 c0
```

- No report ID.
- 8 modifier bits, 1 reserved byte, 6 keycodes.
- 5 LED output bits (Num/Caps/Scroll/Compose/Kana).
- This is the normal typing interface. The tool never writes to it.

### 4.2 IF1 — vendor control (227 bytes, `0xE3`)

```text
06 01 00 09 80 a1 01 85 01 19 81 29 83 15 00 25
01 95 03 75 01 81 02 95 01 75 05 81 01 c0 05 0c
09 01 a1 01 85 02 19 00 2a ff 02 15 00 26 ff 7f
95 01 75 10 81 00 c0 06 00 ff 09 01 a1 01 85 03
15 00 26 ff 00 09 2f 75 08 95 03 81 02 c0 05 01
09 06 a1 01 85 04 05 07 19 04 29 70 15 00 25 01
75 01 95 78 81 02 c0 06 00 ff 09 01 a1 01 85 05
15 00 26 ff 00 19 01 29 02 75 08 95 05 b1 02 c0
06 00 ff 09 01 a1 01 85 06 15 00 26 ff 00 19 01
29 02 75 08 96 07 04 b1 02 c0 05 01 09 02 a1 01
85 07 09 01 a1 00 05 09 15 00 25 01 19 01 29 05
75 01 95 05 81 02 95 03 81 01 05 01 16 00 80 26
ff 7f 09 30 09 31 75 10 95 02 81 06 15 81 25 7f
09 38 75 08 95 01 81 06 05 0c 0a 38 02 95 01 81
06 c0 c0
```

### 4.3 IF1 report IDs

| ID | Type | Size | Usage | Notes |
|---:|---|---|---|---|
| `0x01` | Input | 3 bits + 5 pad | `0x01` / `0x80` | System control (power/sleep/wake) |
| `0x02` | Input | 16-bit array | `0x0C` / `0x01` | Consumer control |
| `0x03` | Input | 3 bytes | `0xFF00` / `0x2F` | Vendor |
| `0x04` | Input | 120 bits (15 B) | `0x01` / `0x06` | Keyboard report for extra keys |
| `0x05` | Feature | 5 bytes | `0xFF00` / `0x01` | Vendor |
| `0x06` | Feature | **1031 bytes** | `0xFF00` / `0x01` | Vendor; **do not touch** |
| `0x07` | Input | Mouse | `0x01` / `0x02` | 5 buttons, X/Y, wheel, AC pan |
| `0x08` | **Not declared** | 382 bytes used | — | LED frame |

### 4.4 Why an undeclared report can work

The kernel's hidraw raw-request path does not validate the report ID against
the descriptor:

- `hidraw` passes `buf[0]` as the report number to `__hid_hw_raw_request()`.
- `__hid_hw_raw_request()` forwards it to the transport's `raw_request()`.
- `usbhid_set_raw_report()` sends a class `SET_REPORT` control transfer with:

  ```c
  ((rtype + 1) << 8) | reportnum
  ```

The device firmware, not the kernel, decides whether to accept report `0x08`.
The reference project confirms acceptance on a board with an identical
descriptor. The K622 still needs a hardware test.

## 5. LED feature report

### 5.1 Layout

| Offset | Length | Value | Meaning |
|---:|---:|---|---|
| 0 | 1 | `0x08` | Report ID |
| 1 | 1 | `0x0A` | Header byte 1 |
| 2 | 1 | `0x7A` | Header byte 2 |
| 3 | 1 | `0x01` | Header byte 3 |
| 4 | 378 | 126 × `R G B` | Per-slot colors |

Total: `4 + 378 = 382` bytes.

### 5.2 Examples

All LEDs off:

```text
08 0A 7A 01 00 00 00 ... 00     (378 zero bytes after the header)
```

Esc (slot 0) red:

```text
08 0A 7A 01 FF 00 00 00 ... 00  (375 zero bytes after the red triple)
```

Slot `7` (the `1` key) green:

```text
08 0A 7A 01 [21 zero bytes] 00 FF 00 [354 zero bytes]
```

The packet always contains all 126 slots. Unmapped/dead slots are zero-filled.

### 5.3 Color order

`Cfg.ini` contains:

```ini
RGBIndex=0,1,2
GameRGBIndex=0,1,2
```

This means the packet order is **R, G, B**, not B, G, R. The probe will confirm
visually.

## 6. Transport

### 6.1 Open

```python
fd = os.open(node, os.O_RDWR)
```

The reference project uses `O_RDWR` without `O_NONBLOCK`. The LED ioctl is
synchronous.

### 6.2 ioctl

```python
def hidiocsfeature(length: int) -> int:
    # _IOC(READ|WRITE, 'H', 0x06, length)
    return (3 << 30) | (length << 16) | (ord("H") << 8) | 0x06

fcntl.ioctl(fd, hidiocsfeature(382), packet)
```

For 382 bytes this is:

```text
0xC17E4806
```

### 6.3 Buffer rules

- `packet` is exactly 382 bytes.
- `packet[0]` is the report ID (`0x08`), included in the ioctl length.
- `packet[1:4]` is the header.
- `packet[4:]` is 378 bytes of RGB data.
- Never send a shorter or longer buffer.
- Never send report `0x06`.

### 6.4 Errors

| Error | Likely cause | Action |
|---|---|---|
| `ENOENT` | Device not present / wrong node | Re-scan; ask user to replug |
| `EACCES` / `EPERM` | hidraw is root-only | Install udev rule or run as root |
| `EINVAL` | ioctl/report rejected | Stop; do not guess other reports |
| `EPIPE` / `ENODEV` | Device disconnected mid-write | Re-scan; retry once |
| `EBUSY` | Another process owns the device | Report and exit |

## 7. Discovery

Algorithm:

```text
for each /sys/class/hidraw/hidraw*:
    read device/uevent
    if "HID_ID=0003:0000258A:00000049" is not present:
        continue
    walk up from realpath(device) looking for bInterfaceNumber
    if bInterfaceNumber == "01":
        return "/dev/" + basename(hidraw)
```

Reference implementation:

```python
_HID_ID_TOKEN = "HID_ID=0003:0000258A:00000049"
CONTROL_INTERFACE = "01"
```

Notes:

- `uevent` is case-sensitive in the file but the reference uppercases it before
  matching; either is fine if consistent.
- `bInterfaceNumber` lives on the USB interface parent, not the HID device
  directory. Walk up up to ~6 levels.
- If multiple matching devices exist, list them and require `--device`.
- Do not hardcode `/dev/hidraw6`; it changes on replug.

## 8. Slot map

| Range | Contents |
|---|---|
| `0–101` | 87 main keys (15 dead slots) |
| `102–125` | Unknown; G/MR/media candidates and/or dead slots |

Main-key dead slots:

```text
6, 23, 29, 41, 47, 70, 71, 75, 76, 77, 87, 88, 93, 99, 100
```

Full table: [KEYMAP.md](KEYMAP.md).

## 9. Safety rules

1. **Only report `0x08` is sent.** The controller exposes a single
   `send_led_frame()` function; there is no generic feature-report API.
2. **Never send report `0x06`.** It is the 1031-byte vendor feature report and
   is the most likely firmware/config path.
3. **No firmware/bootloader/flash commands.** The tool cannot brick the board
   through a firmware path because it has no such code.
4. **No driver detach.** hidraw coexists with `usbhid`; typing is unaffected.
5. **No macro/keymap changes.** The tool only writes LED colors.
6. **Validate the frame.** Length must be 382, header must be
   `08 0A 7A 01`, and every color byte must be 0–255.
7. **Lighting is volatile.** Do not promise persistence unless Phase 0 proves
   the board stores it.
8. **Stop on protocol errors.** If `EINVAL` occurs, do not try other report IDs
   blindly. Investigate first.

## 10. Verification status

| Item | Status |
|---|---|
| USB IDs, interfaces, descriptors | Confirmed |
| Main key slots `0–101` | Confirmed from official `Cfg.ini` |
| 126-slot / 378-byte payload | Confirmed from official driver |
| RGB order R,G,B | Confirmed from `Cfg.ini` |
| Report `0x08` + header accepted by K622 | **Pending hardware test** |
| Extra slots `102–125` | **Pending calibration** |
| Persistence | **Unknown** |
| Built-in effect override | **Unknown** |

## 11. Minimal probe sequence

Phase 0 will run this sequence and record the visual result:

1. **All off** — `08 0A 7A 01` + 378 zeros.
   - Expected: board goes dark.
   - If not: report may be rejected, or the board is in a hardware effect that
     overrides per-key data.
2. **Slot 0 red** — Esc red, all else off.
3. **Slot 7 green** — `1` key green.
4. **Slot 101 blue** — Right arrow blue.
5. **Slot 6 white** — dead slot; nothing should light.
6. **RGB order** — slot 0 red, then green, then blue.
7. **Extra slots** — slots `102–125` one at a time; record which key lights up.

Pass criteria:

- The board responds to the frame.
- Main-key slots match the official map.
- Typing is unaffected.
- No disconnect or error.

If the probe fails, do **not** try report `0x06`. Investigate with a USB capture
of the official Windows software (e.g., in a VM) or further static analysis of
`KeyboardDrv.exe` / `Lowerdev.dll`.

## 12. References

- Reference implementation:
  <https://github.com/kn4oqw-clint/redragon-ks82b-rgb>
- Reference protocol writeup:
  <https://github.com/kn4oqw-clint/redragon-ks82b-rgb/blob/main/docs/openrgb-4106-report.md>
- OpenRGB issue #4106:
  <https://gitlab.com/CalcProgrammer1/OpenRGB/-/issues/4106>
- Linux kernel:
  `drivers/hid/hidraw.c`, `drivers/hid/hid-core.c`,
  `drivers/hid/usbhid/hid-core.c`

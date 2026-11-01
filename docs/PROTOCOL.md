# Protocol — Redragon K622 RGB

- **Device:** Redragon K622 Horus TKL RGB (wired USB)
- **USB ID:** `258a:0049`
- **Control interface:** IF1, usage page `0xFF00`, usage `0x01`
- **Declared vendor reports:** feature `0x05` (5 bytes), feature `0x06` (1031 bytes)
- **Status:** read and write paths **verified on hardware**. The captured
  `09 cc` colour frame is sufficient; `09 d0`/`03 c6` are not needed.

## 1. Summary

The keyboard exposes two HID interfaces:

- **IF0** — normal boot keyboard, used for typing.
- **IF1** — vendor control interface, accessed through `/dev/hidrawN`.

IF1's report descriptor declares exactly seven reports and **no report `0x08`**:

| ID | Type | Payload | Meaning |
|---:|---|---:|---|
| `0x01` | Input | 1 byte | System control |
| `0x02` | Input | 2 bytes | Consumer control |
| `0x03` | Input | 3 bytes | Vendor |
| `0x04` | Input | 15 bytes | Extra keyboard keys |
| `0x05` | Feature | 5 bytes | Vendor mailbox/status |
| `0x06` | Feature | **1031 bytes** | Vendor configuration / LED state |
| `0x07` | Input | 7 bytes | Mouse |

Earlier revisions of this project sent a 382-byte feature report `0x08`. That
report does not exist on this board; `HIDIOCSFEATURE` blocked for 5 seconds and
failed with `ETIMEDOUT`. It is no longer referenced anywhere in the tool.

The official `KeyboardDrv.exe` uses report `0x06` for the big vendor payload and
report `0x05` for short commands. The 126-slot LED data is carried inside
report `0x06` as 126-byte planes, matching `RGBIndex=0,1,2` in `Cfg.ini`.

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

| Interface | Usage page/usage | Class/subclass/protocol | Endpoint | Purpose |
|---|---|---|---|---|
| IF0 | `0x01` / `0x06` | `3` / `1` / `1` | `0x81`, 8-byte interrupt | Boot keyboard |
| IF1 | `0xFF00` / `0x01` | `3` / `0` / `0` | `0x82`, 16-byte interrupt | Vendor control |

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
- Normal typing interface; the tool never writes to it.

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

The fixture is stored at `tests/data/k622-if1-descriptor.bin`:

```text
size:   227 bytes
sha256: 32771137a995e90b6fa9d210761c23ce61e60a21accd033b86f484f198a5061c
```

The tool parses the descriptor itself and refuses to touch a feature report whose
declared size differs from the captured sizes. A different descriptor hash is
reported as `UNKNOWN` and blocks writes.

### 4.3 IF1 report IDs

| ID | Type | Size | Notes |
|---:|---|---:|---|
| `0x01` | Input | 3 bits + 5 pad = 1 B | System control |
| `0x02` | Input | 16-bit array = 2 B | Consumer control |
| `0x03` | Input | 3 × 8 bits = 3 B | Vendor |
| `0x04` | Input | 120 bits = 15 B | Extra keyboard keys |
| `0x05` | Feature | 5 × 8 bits = 5 B | Vendor mailbox/status |
| `0x06` | Feature | 1031 × 8 bits = **1031 B** | Vendor payload |
| `0x07` | Input | 1 + 32 + 8 + 8 = 7 B | Mouse |
| `0x08` | — | **not declared** | Does not exist on this board |

The reference KS82-B document's prose claims report 6 is 1796 bytes, but its own
verbatim descriptor (`96 07 04`) says 1031. The captured K622 descriptor agrees:
1031 payload bytes, 1032 with the report ID.

## 5. Read path — verified on hardware

Reads use `HIDIOCGFEATURE(length)` where `length = 1 + payload_size`. The buffer
must contain the report ID in byte 0 on entry; the kernel returns the report ID
in byte 0 followed by the payload.

| Report | Request | Buffer | Result on K622 |
|---|---:|---:|---|
| `0x05` | `0xC0064807` | 6 B | OK: `05 01 02 00 00 00` |
| `0x06` | `0xC4084807` | 1032 B | **`EPIPE`** — the device stalls this GET |

Report `0x06` is therefore **not readable in isolation**. The binary usbmon
capture confirms the official read handshake: the app writes report 5
`05 83 c6 00 00 00`, waits 20 ms, then reads report 6 and receives a 262-byte
response starting `06 83 c6 ...`. A profile read uses `05 84 d8 00 00 00` and
returns 1032 bytes starting `06 84 d8 ...`. The tool does **not** send either
report-5 command yet.

## 6. Lighting write — captured from the official software

A binary `usbmon` capture of the official Windows app changing colours
(2026-11-01) contains 13 complete lighting updates. Every update is three
report-6 `SetFeature` transfers in this order:

| # | Report-6 payload prefix | Length | Meaning |
|---:|---|---:|---|
| 1 | `06 09 cc 00 40` | 1032 B | 126-slot RGB colour frame |
| 2 | `06 09 d0 00 40` | 1032 B | constant latch/effect frame |
| 3 | `06 03 c6 00 00` | 1032 B | constant config frame |

Only the first packet varies with the chosen colours. Across all 13 captures:

- bytes `0..7` are `06 09 cc 00 40 00 00 00`;
- bytes `8..133` are the **red** plane, slots 0..125;
- bytes `134..259` are the **green** plane, slots 0..125;
- bytes `260..385` are the **blue** plane, slots 0..125;
- bytes `386..1031` are byte-for-byte constant (the latch/config tail).

The all-off frame is stored at `k622rgb/data/template_color.bin` (1032 bytes,
sha256 `5d922916bdeadf7bfc3676a00855b8c0b9e05562e083d344d67dd58c73e4626a`).
The tool copies it, writes only the three planes, and verifies that the header
and the tail still match before `HIDIOCSFEATURE(1032)`.

Current implementation: **only the `09 cc` frame is sent**, and the hardware
test below shows that this is sufficient. It is the only packet that can be
built from user colours, and it is the only packet the write allowlist accepts.
`09 d0` and `03 c6` are captured and understood, but they are not sent.

### 6.1 Capture sequence

```text
SET5  05 83 c6 00 00 00          # ask for the config
GET6  06 83 c6 ... (262 bytes)   # config read-back
SET6  06 09 cc 00 40 ...         # colour frame (the only write this tool sends)
SET6  06 09 d0 00 40 ...         # constant latch/effect frame
SET6  06 03 c6 00 00 ...         # constant config frame
```

The `09 d0` frame has sha256
`ce6cd105d2b32142618f999ab961b99338bc55c2b4c3e2430cf0a1968bedd5fc`; the
`03 c6` frame has sha256
`ef5419a4b85f7aa6734506baf662b22d5f7cfe22f646db842b1872478a2d480e`.
Both are byte-for-byte constant in the capture.

### 6.2 Read-back

The colour buffer cannot be read back. A standalone `GetFeature(0x06)` stalls
with `EPIPE`, and the captured read handshake returns the 262-byte config, not
the colour frame. The CLI therefore keeps a local **write-ahead record** of the
last frame it sent (`$XDG_STATE_HOME/k622rgb/last-frame.bin`, or
`~/.local/state/k622rgb/last-frame.bin`). This is not a device read-back; it
only makes successive `set` calls additive. Use `--reset` to ignore it and
start from the captured all-off frame.

### 6.3 Hardware verification (2026-11-01)

Performed on the physical K622 through `/dev/hidraw6` with the udev `uaccess`
rule in place. Every step succeeded on the first attempt:

| Step | Command | Observed |
|---|---|---|
| Single colour frame | `k622rgb set --no-state Esc=red` | Esc turned red; all other LEDs stayed off |
| Additive frame | `k622rgb set Esc=red` then `k622rgb set 1=green` | Esc stayed red and `1` turned green |
| Clear | `k622rgb set --off` | all LEDs off; saved frame hash equals the captured template |

This confirms:

- the `09 cc` colour frame alone changes the lighting — the captured `09 d0`
  latch and `03 c6` config packets are **not** required for per-key colours;
- the plane order and slot mapping (R `8`, G `134`, B `260`, `slot = col*6 +
  row`) match the physical board;
- the local write-ahead record correctly makes successive `set` calls additive.

One implementation detail found during verification: CPython's `fcntl` module
rejects an immutable `bytes` ioctl argument larger than 1024 bytes with
`ValueError: ioctl argument 3 is too long`. A 1032-byte frame must be passed as
a writable `bytearray`, which takes the unbounded direct-buffer path. The
device accepted the 1032-byte `HIDIOCSFEATURE` transfer with no stall or
timeout.

## 7. Official software evidence (static analysis)

`KeyboardDrv.exe` (32-bit) and `Lowerdev.dll`:

- Big vendor transfers use a 1032-byte buffer: report ID `0x06` plus 1031 data
  bytes (`96 07 04` in the descriptor).
- LED colour planes are 126 bytes each (`imul ..., 0x7e`), one plane per
  channel, matching `RGBIndex=0,1,2`.
- Report-6 write headers observed in the disassembly: `04 D8 00 40` (apply
  profile), `09 00 40` + 1024 bytes of data, and `03 C6` + 136 bytes of config.
- Report-5 mailbox command: `83 C6` followed by zeros, used before a report-6
  read.
- `HidD_SetFeature` / `HidD_GetFeature` are resolved through `Lowerdev.dll`;
  the wrapper object is at `this+0x2628`, the send helper at `0x4454f0`, the
  profile write at `0x4459d0` / `0x411150`, and the read helper at `0x445830`.

The 2026-11-01 usbmon capture confirms the 1032-byte buffer, the three
126-byte planes, the `09 cc` colour header, and the repeated
`09 cc` → `09 d0` → `03 c6` sequence. The remaining gates are hardware
verification of the write and calibration of slots `102–125`.

## 8. Transport

### 8.1 Open

```python
fd = os.open(node, os.O_RDONLY)   # info / dump / check
fd = os.open(node, os.O_RDWR)     # set (the captured lighting frame)
```

### 8.2 ioctl numbers

```python
def hidiocgfeature(length: int) -> int:
    # _IOC(READ|WRITE, 'H', 0x07, length)
    return (3 << 30) | (length << 16) | (ord("H") << 8) | 0x07

def hidiocsfeature(length: int) -> int:
    # _IOC(READ|WRITE, 'H', 0x06, length)
    return (3 << 30) | (length << 16) | (ord("H") << 8) | 0x06
```

| Call | Request number |
|---|---:|
| `HIDIOCGFEATURE(6)` | `0xC0064807` |
| `HIDIOCGFEATURE(1032)` | `0xC4084807` |
| `HIDIOCSFEATURE(1032)` | `0xC4084806` |

`fcntl.ioctl` mutates a `bytearray` in place for `HIDIOCGFEATURE` and returns
the number of bytes copied (the full buffer length on success). For
`HIDIOCSFEATURE` the frame is passed as an immutable `bytes` object; a
non-negative return means the kernel accepted the transfer.

### 8.3 Errors

| Error | Likely cause | Action |
|---|---|---|
| `ENOENT` | Device not present / wrong node | Re-scan; ask user to replug |
| `EACCES` / `EPERM` | hidraw is root-only | Install udev rule or run as root |
| `EINVAL` | Report not declared / wrong length | Stop; do not guess reports |
| `EPIPE` | Device stalled the control request | Record it; do not retry blindly |
| `ETIMEDOUT` | Device did not answer | Replug; retry once |
| `ENODEV` | Disconnected mid-transfer | Re-scan; retry once |
| `EBUSY` | Another process owns the device | Report and exit |

## 9. Discovery

```text
for each /sys/class/hidraw/hidraw*:
    read device/uevent
    if "HID_ID=0003:0000258A:00000049" is not present:
        continue
    walk up from realpath(device) looking for bInterfaceNumber
    if bInterfaceNumber == "01":
        return "/dev/" + basename(hidraw)
```

- `bInterfaceNumber` lives on the USB interface parent; walk up to ~6 levels.
- If multiple matching devices exist, list them and require `--device`.
- Never hardcode `/dev/hidraw6`; it changes on replug.

## 10. Slot map

| Range | Contents |
|---|---|
| `0–101` | 87 main keys (15 dead slots) |
| `102–125` | Unknown; G/MR/media candidates and/or dead slots |

Main-key dead slots:

```text
6, 23, 29, 41, 47, 70, 71, 75, 76, 77, 87, 88, 93, 99, 100
```

Full table: [KEYMAP.md](KEYMAP.md). The usbmon capture confirms the plane order
inside report `0x06`: red at offset 8, green at 134, blue at 260, each 126
bytes, with slot 0 first in each plane.

## 11. Safety rules

1. **Only declared feature reports `0x05` and `0x06` may be used.** Report
   `0x08` does not exist; never send it.
2. **`info`, `dump`, and `check` are read-only.** `dump --report 6` still stalls
   with `EPIPE`; these commands never write.
3. **`set` writes exactly one captured frame shape:** report `0x06`, header
   `06 09 cc 00 40 00 00 00`, three 126-byte colour planes, and the captured
   tail. `controller.write_feature()` refuses every other header or tail, and
   there is no generic feature-write API.
4. **Writes require the captured descriptor hash.** A different descriptor is
   reported as `UNKNOWN` and refused before the device is opened.
5. **`--dry-run` prints the complete 1032-byte frame and opens no device.**
   Nothing is written and the local last-frame record is not changed.
6. **Never send profile-save, firmware, bootloader, flash, macro, or keymap
   opcodes.** The captured `04 d8` profile-write packet and the `09 d0`/`03 c6`
   companion packets are deliberately not sent; hardware verification showed
   they are not needed for per-key colours.
7. **No driver detach.** hidraw coexists with `usbhid`; typing is unaffected.
8. **Stop on unexpected errors.** `EPIPE`/`EINVAL` are findings, not invitations
   to try other report IDs.

## 12. Verification status

| Item | Status |
|---|---|
| USB IDs, interfaces, raw descriptors | Confirmed |
| IF1 descriptor parse (7 reports, no `0x08`) | Confirmed |
| Descriptor hash fixture | Confirmed (`32771137…`) |
| Report `0x05` `GetFeature` | Confirmed: `05 01 02 00 00 00` |
| Report `0x06` `GetFeature` | Confirmed **stalled** (`EPIPE`) |
| Official app read handshake (`83 C6` → report 6) | **Captured** (`06 83 c6 …`, 262 B) |
| Main key slots `0–101` | Confirmed from `Cfg.ini` |
| 126-slot / 126-byte planes | **Confirmed on hardware** (R `8`, G `134`, B `260`) |
| RGB order R,G,B | Confirmed from `Cfg.ini` |
| Report-6 LED write packet | **Captured:** `09 cc` + 13 complete updates |
| Write implementation (`set`, allowlist, state) | **Implemented; unit-tested** |
| Hardware write test (`set Esc=red`) | **Confirmed:** Esc red, `1` green, `--off` clears |
| Additive saved-frame behaviour | **Confirmed on hardware** |
| `09 d0` / `03 c6` companions | Not required for per-key colours; still not sent |
| Read-back backup for report 6 | **Blocked by the stalled GET**; local write-ahead record only |
| Extra slots `102–125` | **Pending calibration** |
| Persistence / built-in effect override | Unknown |

## 13. Next steps

The capture and hardware-write gates are closed. Remaining work:

1. Calibrate slots `102–125` (G/MR/media keys) by writing `slot:N=ffffff` and
   recording which physical key lights.
2. Decide whether to expose effects/profiles; the current CLI only sets static
   per-key colours plus `--off`.
3. Optionally investigate the read handshake for profile/config read-back; the
   colour buffer itself still cannot be read.

Do not send `09 d0`, `03 c6`, or `04 d8` unless a new, captured need appears.

## 14. References

- Reference implementation:
  <https://github.com/kn4oqw-clint/redragon-ks82b-rgb>
- Reference protocol writeup:
  <https://github.com/kn4oqw-clint/redragon-ks82b-rgb/blob/main/docs/openrgb-4106-report.md>
- OpenRGB issue #4106:
  <https://gitlab.com/CalcProgrammer1/OpenRGB/-/issues/4106>
- Linux kernel: `drivers/hid/hidraw.c`, `drivers/hid/hid-core.c`,
  `drivers/hid/usbhid/hid-core.c`

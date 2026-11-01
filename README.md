# k622rgb

Linux CLI for the per-key RGB lighting of the **Redragon K622 Horus TKL RGB**
keyboard (`258a:0049`, Sinowealth controller).

The tool is pure Python standard library — no pip, virtualenv or third-party
runtime dependencies. It talks to the keyboard through the vendor control
interface (IF1) using only the HID feature reports declared by the device and
the exact report shapes captured from the official software.

## Status

Everything below is implemented and was verified on the physical keyboard:

- Per-key colours through the captured report-0x06 `09 cc` frame.
- All 20 built-in effects, Self-define and OFF through the `03 c6` config
  mailbox, including brightness `0–9`, speed `1–4`, palette colour and random.
- The 21 × 7-colour effect palette through `08 c8`.
- Local lighting profiles, timestamped config/palette backups and restore.
- Read-back of the config, palette and custom per-key frame.
- Factory-reset config layouts (`5a a5` marker at `0x46` or `0x81`).

The K622's G1–G4, MR, RGB toggle, media buttons and volume roller **do not have
individually addressable RGB LEDs**. The 87 main keys are the complete RGB set.
Slots `102–125` are duplicate/dead matrix positions; there is no calibration
command.

## Requirements

- Linux with hidraw support.
- Python 3.9 or newer.
- The keyboard connected by USB (wired). Bluetooth, 2.4 GHz and ISO variants
  are not supported.
- Permission to open the IF1 `/dev/hidrawN` node. Install the bundled udev rule
  once (below).

## Install

```bash
git clone git@github.com:Saka-CS/redragon_k622_rgb_cli.git
cd redragon_k622_rgb_cli

sudo cp udev/60-k622rgb.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw
# replug the keyboard
```

The udev rule grants the active desktop user access with `TAG+="uaccess"`. If
`uaccess` does not apply in your session, see
[docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) section 9 for the
`MODE="0666"` fallback.

No installation step is needed for the CLI itself:

```bash
./bin/k622rgb --help
# or
python3 -m k622rgb --help
```

## Quick start

```bash
./bin/k622rgb check                 # discovery, permissions, descriptor hash
./bin/k622rgb info                  # descriptor and declared reports
./bin/k622rgb list                  # main-key LED map

./bin/k622rgb set Esc=red           # per-key colour
./bin/k622rgb set 1=00ff00 Space=0000ff
./bin/k622rgb set --off             # clear the per-key frame
./bin/k622rgb off                   # select the built-in OFF mode
```

Per-key writes are additive: `set` keeps the frame it last wrote under the XDG
state directory and uses it as the base for the next call. Use `set --reset` to
start from black, `set --no-state` to bypass the record, or `set --from-device`
to read the custom frame back from the keyboard.

```bash
./bin/k622rgb set --all 0000ff                  # fill every slot
./bin/k622rgb set --all 0000ff --brightness 6   # software-scale the frame
./bin/k622rgb set --from-device 1=00ff00        # additive from the device
./bin/k622rgb set --dry-run Esc=red             # print the frame, no write
```

`set` switches the keyboard to **Self-define** mode by default, because
per-key frames are ignored while an effect is active. Use `--no-activate` to
leave the current effect running.

## Built-in effects

The K622 runs its effects in firmware; the CLI selects a mode and updates its
parameters.

```bash
./bin/k622rgb mode list        # all 20 effects + Self-define + OFF
./bin/k622rgb mode show        # current mode and parameters
./bin/k622rgb mode set breathing --color 0000ff --brightness 7 --speed 1
./bin/k622rgb mode set rainbow --speed 3 --brightness 9
./bin/k622rgb mode set neon-stream --random
./bin/k622rgb mode set per-key
./bin/k622rgb off
```

Each effect has seven palette entries:

```bash
./bin/k622rgb color list
./bin/k622rgb color show ripples-shining
./bin/k622rgb color set ripples-shining 2 00ffff
./bin/k622rgb mode set ripples-shining --color-index 2
```

Every config or palette write is preceded by a full read-back backup unless
`--no-backup` is given. `config restore` is the recovery path.

## Backups and profiles

```bash
./bin/k622rgb config show                 # current config and palette
./bin/k622rgb config dump                 # timestamped full backup
./bin/k622rgb config dump --out ./backup
./bin/k622rgb config restore ./backup     # restore config + palette
./bin/k622rgb config restore ./backup --custom  # also restore frames

./bin/k622rgb profile save gaming
./bin/k622rgb profile load gaming
./bin/k622rgb profile list
./bin/k622rgb profile show gaming
./bin/k622rgb profile delete gaming
```

Profiles are local lighting snapshots (config, palette and optionally the
custom per-key frame), stored under `~/.config/k622rgb/profiles` and respecting
`XDG_CONFIG_HOME`. The keyboard's keymap, macro and profile tables are never
written.

## Key names

Keys are case-insensitive. The K622 is a TKL board, so there are no numpad
keys. The 87 mapped names are:

`Esc`, `` ` ``, `1`–`0`, `-`, `=`, `Bksp`, `Tab`, `Q`–`P`, `[`, `]`, `\`,
`Caps`, `A`–`L`, `;`, `'`, `Enter`, `LShift`, `Z`–`M`, `,`, `.`, `/`,
`RShift`, `LCtrl`, `Win`, `LAlt`, `Space`, `RAlt`, `RCtrl`, `Menu`, `Fn`,
`F1`–`F12`, `PrtSc`, `ScrLk`, `Pause`, `Ins`, `Home`, `PgUp`, `Del`, `End`,
`PgDn`, `Left`, `Up`, `Down` and `Right`.

Aliases are accepted for common spellings: `Escape`→`Esc`,
`CapsLock`→`Caps`, `Super`/`Meta`/`Win`→`Win`, `Backspace`→`Bksp`,
`Insert`→`Ins`, `Delete`→`Del`, `ScrollLock`/`ScrLk`→`ScrLk`,
`PrintScreen`→`PrtSc`, `Return`→`Enter`, `Spacebar`→`Space`,
`Minus`/`Hyphen`→`-`, `Equals`→`=`, `ArrowUp`/`ArrowDown`/`ArrowLeft`/
`ArrowRight`→`Up`/`Down`/`Left`/`Right`, and `App`→`Menu`.

Dead matrix positions can be addressed numerically for diagnostics only:

```bash
./bin/k622rgb set slot:6=ffffff         # lights F5 on the K622
./bin/k622rgb set slot:105=ffffff       # lights LCtrl
```

See [docs/KEYMAP.md](docs/KEYMAP.md) for the full map.

## Safety

- The only writable report is report `0x06`, and only the exact captured
  `09 cc`, `03 c6`, `08 c8` and custom-frame shapes can be sent.
- Reads use declared report `0x05` mailbox commands or report `0x06`
  responses.
- Writes are refused unless the IF1 descriptor matches the captured K622 hash.
- No firmware update, bootloader, flash, keymap or macro path exists.
- Config/palette writes back up the current state first.

## Troubleshooting

| Problem | Fix |
|---|---|
| `permission denied` opening `/dev/hidrawN` | Install `udev/60-k622rgb.rules`, reload udev and replug the keyboard; check with `./bin/k622rgb check` |
| `device is busy` | Close the official software, OpenRGB or another `k622rgb` instance |
| `UNKNOWN descriptor` / writes refused | The connected device is not the captured K622 IF1; do not force writes |
| `dump --report 6` stalls with `EPIPE` | Report 6 GET needs the vendor handshake; use `config show`/`config dump` instead |
| Per-key colours do not appear | An effect is active; `set` activates Self-define by default, or run `./bin/k622rgb mode set per-key` |
| Settings changed after `Fn+Esc` | Factory reset moves the config marker; both layouts are accepted, rerun `mode`/`set` |

## Documentation

- [docs/README.md](docs/README.md) — project status and command overview
- [docs/PROTOCOL.md](docs/PROTOCOL.md) — USB/HID reports, mailbox commands, verified write paths
- [docs/RGB_MODES.md](docs/RGB_MODES.md) — all effects, palette and parameter bytes
- [docs/KEYMAP.md](docs/KEYMAP.md) — slot map, dead slots and aliases
- [docs/FINDINGS.md](docs/FINDINGS.md) — reverse-engineering notes and hardware evidence
- [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) — architecture, testing and acceptance criteria

## License

MIT — see [LICENSE](LICENSE).

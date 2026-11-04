# k622rgb

Linux CLI for the per-key RGB lighting of the **Redragon K622 Horus TKL RGB**
keyboard (`258a:0049`, Sinowealth controller).

The tool is pure Python standard library — no pip, virtualenv or third-party
runtime dependencies. It talks to the keyboard through the vendor control
interface (IF1) using only the HID feature reports declared by the device and
the exact report shapes captured from the official software.

## Status

Current release: `k622rgb` `0.5.0` (288 unit tests pass with
`python3 -m unittest discover -s tests -v`).

Everything below is implemented and was verified on the physical keyboard:

- Per-key colours through the captured report-0x06 `09 cc` frame.
- Named colour groups, including the vendor `Define1..5` groups imported from
  `Cfg.ini`, shipped presets and `set --group` overlays.
- All 20 built-in effects, Self-define and OFF through the `03 c6` config
  mailbox, including brightness `0–9`, speed `1–4`, palette colour and random.
- The 21 × 7-colour effect palette through `08 c8`.
- Local lighting profiles, timestamped config/palette backups and restore.
- Read-back of the config, palette and custom per-key frame.
- Factory-reset config layouts (`5a a5` marker at `0x46` or `0x81`).

The K622's G1–G4, MR, RGB toggle, media buttons and volume roller **do not have
individually addressable RGB LEDs**. The RGB set is the 87 main keys plus three
addressable Redragon logo zones: `LogoLeft`, `LogoCenter` and `LogoRight`.

Packet slots are row-major 21-column indices. The official `Cfg.ini` uses a
different column-major numbering; the full map and the conversion formula are
in [docs/KEYMAP.md](docs/KEYMAP.md). The bottom row was corrected by a
key-name verify pass: `X` is packet slot `87`, `Z` is `86`, and slot `85` is
a dead gap. There are no alias slots and no unlit keys.

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
./bin/k622rgb doctor                # device/backup health and recovery steps
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

## Colour groups

The official app's **Color Group → Define1..5** feature is a per-key colour
layer. `k622rgb group` stores the same idea locally and paints it through the
normal `09 cc` frame; no new protocol is used.

```bash
./bin/k622rgb group list
./bin/k622rgb group import Cfg.ini       # read-only; no device access
./bin/k622rgb group set 1=red 2=green 3=blue 4=yellow 5=cyan
./bin/k622rgb group apply                # paint define1..5 + Self-define
```

The five define groups are seeded with project defaults, so `group list` works
before an import:

| Group | Keys |
|---|---|
| `define1` | `W`, `A`, `S`, `D` |
| `define2` | `Esc`, `F1`–`F12` |
| `define3` | `PrtSc`, `ScrLk`, `Pause`, `Ins`, `Home`, `PgUp`, `Del`, `End`, `PgDn`, arrows |
| `define4` | `` ` ``, `Tab`, `Caps`, both Shifts/Ctrls/Alts, `Win`, `Space`, `Fn`, `Menu`, `\`, `Enter`, `Bksp` |
| `define5` | `A`–`Z`, `0`–`9`, `-`, `=`, `[`, `]`, `;`, `'`, `,`, `.`, `/` |

`define5` is the broad letter/number/symbol layer. It overlaps `define1` on
WASD by design. `group apply` paints `define5` first and then `define1..define4`,
so WASD keeps its own colour. `group import` reads `GaoshouKey1..5` and maps the
Windows VK codes using the labels and `[KEY]` table in the same file. It
replaces the built-in definitions with the real vendor groups, never modifies
`Cfg.ini`, and never opens the keyboard.

`group set` can recolour an existing group, define a custom group from a key
list, or update several groups at once:

```bash
./bin/k622rgb group set fps=ff0000
./bin/k622rgb group set mygroup=00ff00 W A S D Up Down Left Right
./bin/k622rgb group set 1=red 2=green
```

Shipped presets: `wasd`, `arrows`, `fps`, `moba`, `mmo` and `typing`. Groups
are stored in `~/.config/k622rgb/groups.json` (respecting `XDG_CONFIG_HOME`;
override with `--file` or `K622RGB_GROUP_FILE`). The `group` subcommands and
`set --group` all honour the same override.

Groups are also reusable overlays in `set`:

```bash
./bin/k622rgb set --group fps=ff0000 --group arrows=00ff00 Esc=ffffff
./bin/k622rgb set --all 0000ff --group moba=00ff00 Q=ffffff
./bin/k622rgb set --file ~/alt-groups.json --group fps=ff0000 Esc=ffffff
```

Precedence is: `--all`/`--off`/saved/device base, then `--group` layers in
command-line order (later wins), then explicit `KEY=COLOR` assignments.
`group apply` starts from the same saved frame and saves the final frame to the
same state file as `set`. Groups without a colour are skipped with a warning.
With no names it applies `define5` first, then `define1..define4`, so `define1`
keeps its WASD colour; later groups win on overlapping keys. Optional names are
applied in the order given.

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
`--no-backup` is given. `config restore` is the recovery path. `--no-backup`
is rejected with `--custom`, and a custom restore also takes a pre-restore
backup that includes both custom frames.

## Backups and profiles

```bash
./bin/k622rgb config show                 # current config and palette
./bin/k622rgb config dump                 # timestamped full backup
./bin/k622rgb config dump --out ./backup
./bin/k622rgb config seal ./backup        # add hashes to a legacy backup
./bin/k622rgb config restore ./backup     # restore config + palette
./bin/k622rgb config restore --verify-only ./backup
./bin/k622rgb config restore --custom ./backup --yes  # d0 last
./bin/k622rgb config restore --custom ./legacy --allow-unverified --yes

./bin/k622rgb profile save gaming
./bin/k622rgb profile load gaming
./bin/k622rgb profile list
./bin/k622rgb profile show gaming
./bin/k622rgb profile delete gaming
```

`--verify-only` reports a legacy backup without a manifest as `unverified` and
returns nonzero unless `--allow-unverified` is given; it never opens the
device. `config seal` writes only `meta.json` and also never opens the device;
use `config seal --force` to replace an existing manifest. New backups use
`meta.json` version 2 with a `files` map of each file's size and SHA-256. The pre-restore backup for `--custom` contains
`config-response.bin`, `colors-response.bin`, `custom1-response.bin` and
`custom2-response.bin`.

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

The three addressable logo zones have their own names:

```bash
./bin/k622rgb set LogoLeft=0000ff
./bin/k622rgb set LogoCenter=0000ff
./bin/k622rgb set LogoRight=0000ff
```

Raw packet slots remain available for diagnostics:

```bash
./bin/k622rgb set slot:6=ffffff         # lights F5 on the K622
./bin/k622rgb set slot:105=ffffff       # lights LCtrl
./bin/k622rgb set slot:95=ffffff        # lights /
```

See [docs/KEYMAP.md](docs/KEYMAP.md) for the full map, including the corrected
bottom row and the 36 dead slots.

## Safety

- The only report used for lighting/config data is report `0x06`; report `0x05`
  is limited to the captured mailbox read commands. Only the exact captured
  `09 cc`, `03 c6`, `08 c8` and custom-frame shapes can be sent. There is no
  generic feature-write or offset/value API.
- **Never write arbitrary `09 d0` bytes or unknown/reserved offsets.** The
  `09 d0` table is persistent, undocumented firmware state; the 2026-11-03
  broad sweep left a board non-enumerating. See
  [docs/INCIDENT-2026-11-03.md](docs/INCIDENT-2026-11-03.md).
- `config restore --custom` is the **only** d0 writer. It requires a verified
  per-file manifest, a descriptor match, `--yes`, and a pre-restore backup
  that includes both custom frames. `--no-backup` is refused with `--custom`.
  d0 is written last and read back; on mismatch exactly one custom-frame-2
  rollback is attempted. Normal commands (`set`, `group apply`, `mode set`,
  `off`, `color set`, `profile load`) cannot reach the d0 writer.
- Stop on the first `EPIPE`, disconnect or re-enumeration; do not retry a
  failed write. A successful flash is not a compatibility check.
- Keep a verified, durable backup outside `/tmp` before any write, and know
  the recovery path (ISP/programmer or RMA) before writing. Application-level
  backups cannot restore a board that no longer enumerates.
- Reads use declared report `0x05` mailbox commands or report `0x06`
  responses.
- Writes are refused unless the IF1 descriptor matches the captured K622 hash.
- No firmware update, bootloader, flash, keymap or macro path exists. **Do not
  flash K621 firmware onto a K622.**
- Config/palette writes back up the current state first (unless `--no-backup`
  is given).
- SHA-256 manifests and `config seal` are integrity checks, not provenance;
  sealing trusts the current directory contents. See
  [docs/SAFETY.md](docs/SAFETY.md) for the full policy and recovery ladder.

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
- [docs/SAFETY.md](docs/SAFETY.md) — hardware write policy, restore safeguards and recovery ladder
- [docs/INCIDENT-2026-11-03.md](docs/INCIDENT-2026-11-03.md) — the `09 d0` sweep incident record

## License

MIT — see [LICENSE](LICENSE).

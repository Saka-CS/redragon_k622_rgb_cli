# Hardware safety policy — K622 writes

This policy applies to every command that can change persistent state in the
Redragon K622. It exists because an unvalidated `09 d0` sweep left a board
unable to enumerate; the record is in
[INCIDENT-2026-11-03.md](INCIDENT-2026-11-03.md).

If a proposed change conflicts with this document, this document wins.

## 1. Scope: exact captured shapes only

The only report used for lighting data is feature report `0x06`; report `0x05`
is limited to the captured mailbox read commands. Only the exact shapes
captured from the official software may be sent:

- `09 cc` — per-key colour frame (1024-byte payload, three 126-byte planes);
- `03 c6` — 136-byte config block;
- `08 c8` — 441-byte effect palette;
- the two custom-frame shapes (`09 cc` / `09 d0`) used by an explicit,
  verified restore.

There is no generic feature-write API, no arbitrary report ID, and no
"diagnostic" path that accepts an offset and a value. Builders reject wrong
lengths, headers and config markers before any transfer is sent.

**Never write unknown or reserved offsets, and never write arbitrary `09 d0`
bytes.** In particular, do not:

- re-add `set --game-flag` or any offset/value option;
- add a `debug d0`, `poke`, region-write or `0xFF`-fill command;
- construct a `09 d0` payload by editing a byte of the current table;
- write a whole 1024-byte table "to see what happens".

The `09 d0` table is persistent, undocumented firmware state. "No visible
change" is not evidence of safety; the 2026-11-03 sweep produced no visible
effect until the board stopped enumerating.

## 2. The only `09 d0` writer

`config restore --custom` is the **only** path that writes custom frame 2
(`09 d0`). It calls the dedicated restore writer, not the generic custom-frame
writer. Normal commands cannot reach it:

`set`, `group apply`, `mode set`, `off`, `color set` and `profile load` write
only `09 cc`, `03 c6` or `08 c8` shapes. A regression test asserts that the d0
writer is not called by those commands.

A custom restore is allowed only when **all** of these are true:

1. **Verified backup.** `meta.json` has a per-file SHA-256 manifest for the
   required files, and every size and hash matches. A legacy backup without
   hashes is refused unless `--allow-unverified` is given, which prints a
   loud warning and still requires `--yes`.
2. **Descriptor match.** The backup's `descriptor_sha256` equals the live IF1
   descriptor hash (`32771137…`). A backup from another board or interface is
   refused.
3. **Explicit confirmation.** `--yes` is present. Without it the tool prints
   the four files it would write and the exact command to re-run, then exits
   with an error.
4. **Pre-restore backup.** The tool takes a fresh read-back backup before
   writing. For `--custom` it includes
   `config-response.bin`, `colors-response.bin`,
   `custom1-response.bin` and `custom2-response.bin`.
   `--no-backup` is rejected with `--custom`.
5. **A known recovery path.** An ISP/programmer route or RMA is available
   before the first write (section 8). If the board cannot be recovered, do
   not write d0 to it.

The required files for `--custom` are the four above. `profile-response.bin`
is optional; it is never written.

Use `config restore --verify-only <DIR>` before touching hardware. It prints
the files, sizes, hashes and descriptor, never opens the device, and returns
nonzero for a legacy backup that has no manifest, unless `--allow-unverified`
is given. `config seal <DIR>` adds hashes to a legacy backup; it writes only
`meta.json` and never opens the device.

## 3. Write discipline

For an allowed custom restore the order is fixed:

```text
palette (08 c8) → config (03 c6) → custom frame 1 (09 cc) → custom frame 2 (09 d0) last
```

- **One forward `09 d0` write per process.** A process may attempt at most one
  rollback write after that, and only the rollback described below. No bulk
  sweeps, no loops, no retries.
- After the d0 write, read `09 d0` back with the mailbox (`05 89 d0`). Report
  success only after the read-back matches the payload that was written.
- Keep the inter-write delay; do not shorten it to make a test faster.
- Do not run two writers concurrently. Close the official software, OpenRGB
  and any other `k622rgb` instance first.

## 4. Stop conditions

Stop immediately, do not retry the write, and print the pre-restore backup
path plus the recovery text on any of:

- `EPIPE` or another `DeviceError`/`OSError` during a write;
- a disconnect or the hidraw node disappearing;
- USB re-enumeration, a descriptor change, or `UNKNOWN descriptor`;
- a read-back that does not match: do not retry the failed write, and follow
  the single rollback rule in section 5;
- `KeyboardInterrupt` during a restore.

A transport error is a finding, not an invitation to try again or switch
report IDs. The first `EPIPE` in the incident was ignored; the sweep continued
and the board was lost.

## 5. Failure semantics and rollback

On a d0 read-back mismatch the tool attempts **exactly one** rollback of
custom frame 2 from the pre-restore backup, then reads it back again.

This is deliberately narrow:

- palette, config and custom frame 1 are **not** automatically rolled back;
- a successful custom-frame-2 rollback does not restore the full original
  state;
- the tool reports the failure and exits nonzero even when the rollback
  matches.

Do not describe the result as "original state recovered". To return fully to
the previous state, if the device still enumerates and the pre-restore backup
is verified, run a new `config restore --custom <pre-restore-backup> --yes`
using that backup. If the board does not enumerate, no application-level
restore is possible.

## 6. Backup requirements

Before any persistent write:

- take a fresh read-back backup of the state that is about to change;
- verify its manifest and descriptor; know which files it contains;
- store it outside `/tmp`, on durable storage, and keep a second copy if the
  change is risky;
- for a d0 restore, confirm the pre-restore backup includes all four custom
  restore files, not just config and palette;
- never use `/tmp` as the only backup location.

A backup is not a substitute for a recovery path. It is only usable while the
keyboard enumerates.

## 7. Integrity is not provenance

The per-file SHA-256 manifest and `config seal` detect corruption, truncation
and accidental substitution. They do **not** prove where a backup came from.

- `config seal` trusts the current contents of the directory. It hashes what
  is there; it does not compare against the device.
- A crafted or self-consistent directory can therefore pass verification.
- `--allow-unverified` accepts even less: it skips the hashes entirely.
- The descriptor field ties a backup to the interface shape, not to a
  trustworthy author.

Only restore backups you created yourself, or whose provenance you otherwise
trust. Never seal or restore a directory from an unknown source just because
the hashes match.

## 8. Recovery ladder

Try these in order. Application-level repair comes only after enumeration is
confirmed.

1. **Cable/port/orientation.** Use a known USB-C **data** cable, another port,
   and both connector orientations.
2. **Keyboard reset.** Press `Fn+Esc`.
3. **`doctor`.** Run `./bin/k622rgb doctor` to check whether a K622 is
   present, inspect recent backups, and print this ladder. It is read-only.
4. **App-level restore — only if the device enumerates.** Use a verified
   backup:
   `./bin/k622rgb config restore --custom <verified-backup> --yes`.
   `--verify-only` first; never restore an unverified or wrong-descriptor
   backup.
5. **Sinowealth ISP / Arduino.** MCU is SH68F90A / BYK916, USB `258a:0049`,
   64 KB flash. Use `gashtaan/sinowealth-fw-disabler` (Arduino D2/D3 to USB
   D+/D−, D4 to +5 V), then `sinowisp`
   (`cargo install --locked sinowisp`).
6. **Official K622 updater.** `Update_KB_K622RGB.exe` (Brazil package
   `K622-RGB software e reset.rar`) plus the matching `.hex`. Match the
   layout (US/UK/ABNT2) to the board.
7. **Redragon RMA/support.** `support@redragonshop.com`; ask for the
   US-layout K622 updater/firmware.

**Never flash K621 firmware onto a K622.** It is model-specific and is
reported to break keys and LEDs. It is not a K622 recovery path.

## 9. Experiments

- Prefer a sacrificial board that you can lose. Do not run unknown-state
  experiments on your only keyboard.
- Start with reads. Confirm the descriptor, the mailbox and the current
  payload before writing.
- Change one variable at a time, with an operator present and an external
  stop.
- Define the maximum number of writes before starting. For d0 the maximum is
  one forward write per process.
- If the device stalls, stop the experiment. Do not "just try one more
  offset".

## 10. References

- [INCIDENT-2026-11-03.md](INCIDENT-2026-11-03.md) — full incident record.
- [PROTOCOL.md](PROTOCOL.md) — report shapes, mailbox commands and the
  `09 d0` / `09 cc` distinction.
- [FINDINGS.md](FINDINGS.md) — reverse-engineering evidence and the removed
  experiment.
- `gashtaan/sinowealth-fw-disabler` — ISP forcing.
- `sinowisp` — Sinowealth ISP flashing tool.

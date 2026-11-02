#!/usr/bin/env python3
"""Interactive visual probe for the experimental ``09 d0`` game byte.

This script is for answering the question the automated test cannot answer:
*does changing a byte in the ``09 d0`` companion change what the keyboard
does?*  It writes one byte at a time and asks you to look at the keyboard.

Show the current frame without writing::

    python3 tools/game_flag_visual.py

Probe the first six payload bytes::

    python3 tools/game_flag_visual.py --write --offsets 0,1,2,3,4,5

Probe only byte 0 with value 1::

    python3 tools/game_flag_visual.py --write --offset 0 --value 1

Every run with ``--write`` takes a full config/palette/custom-frame backup
first and restores the original ``09 d0`` payload on exit (including Ctrl-C).
The keyboard may re-enumerate after a write; the script waits for it.

Suggested things to look at after each write:

* Does the current lighting change or switch to the stored per-key frame?
* Does a key press / group key behave differently?
* Does the change survive an unplug/replug?
* Run ``./bin/k622rgb mode show`` and ``config dump`` after a power cycle to
  see whether anything persisted.
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from k622rgb import controller  # noqa: E402

CLI = os.path.join(ROOT, "bin", "k622rgb")


def read_state(retries=20, delay=1.0):
    last_error = None
    for _ in range(retries):
        try:
            fd = controller.open_device(controller.find_device())
            try:
                return {
                    "config": controller.read_config(fd),
                    "custom1": controller.read_custom_frame(fd, 1),
                    "custom2": controller.read_custom_frame(fd, 2),
                }
            finally:
                os.close(fd)
        except controller.DeviceError as exc:
            last_error = exc
            print("waiting for the keyboard: %s" % exc)
            time.sleep(delay)
    raise controller.DeviceError("keyboard unavailable: %s" % last_error)


def write_d0(payload, retries=20, delay=1.0):
    last_error = None
    for _ in range(retries):
        try:
            fd = controller.open_device(controller.find_device(), writable=True)
            try:
                controller.write_custom_frame(fd, payload, 2)
                return
            finally:
                os.close(fd)
        except controller.DeviceError as exc:
            last_error = exc
            print("write stalled; waiting for the keyboard: %s" % exc)
            time.sleep(delay)
    raise controller.DeviceError("could not write 09 d0: %s" % last_error)


def make_backup():
    path = tempfile.mkdtemp(prefix="k622rgb-game-flag-visual-")
    result = subprocess.run(
        [sys.executable, CLI, "config", "dump", "--out", path],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "backup failed:\n%s\n%s" % (result.stdout, result.stderr)
        )
    return path


def parse_offsets(args):
    if args.offsets:
        values = []
        for token in args.offsets.split(","):
            token = token.strip()
            if token:
                values.append(int(token, 0))
        return values
    return [args.offset]


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Interactively probe one byte of the 09 d0 frame."
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="actually write the candidate bytes (without this it is read-only)",
    )
    parser.add_argument(
        "--offset",
        type=lambda text: int(text, 0),
        default=controller.GAME_FLAG_OFFSET,
        help="single byte offset (default: %(default)s)",
    )
    parser.add_argument(
        "--offsets",
        metavar="N,N,...",
        help="comma-separated offsets; overrides --offset",
    )
    parser.add_argument(
        "--value",
        type=lambda text: int(text, 0),
        default=controller.GAME_FLAG_ON,
        help="byte value to write (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    offsets = parse_offsets(args)
    for offset in offsets:
        controller.validate_game_flag(offset, args.value)

    baseline = read_state()
    base_d0 = baseline["custom2"]
    print("device: %s" % controller.find_device())
    print(
        "baseline: d0 sha256 %s, byte[%s] = %s"
        % (
            controller.descriptor_sha256(base_d0)[:16],
            ", ".join(str(offset) for offset in offsets),
            ", ".join("0x%02X" % base_d0[offset] for offset in offsets),
        )
    )
    print(
        "current mode: %d (per-key flag %d)"
        % (
            baseline["config"][controller.CONFIG_MODE_INDEX],
            baseline["config"][controller.CONFIG_PER_KEY_INDEX],
        )
    )
    if not args.write:
        print("\nRead-only. Re-run with --write to probe the keyboard.")
        return 0

    backup = make_backup()
    print("backup: %s" % backup)
    print(
        "Probing payload[%s] = 0x%02X. Watch the keyboard after each write."
        % (", ".join(str(offset) for offset in offsets), args.value)
    )
    observed = {}
    restore_failed = False
    try:
        for offset in offsets:
            payload = controller.set_game_flag(base_d0, args.value, offset)
            print("\nwriting payload[%d] = 0x%02X ..." % (offset, args.value))
            write_d0(payload)
            time.sleep(0.5)
            try:
                after = read_state()
                print(
                    "read-back: payload[%d] = 0x%02X, d0 sha256 %s"
                    % (
                        offset,
                        after["custom2"][offset],
                        controller.descriptor_sha256(after["custom2"])[:16],
                    )
                )
            except controller.DeviceError as exc:
                print("read-back unavailable: %s" % exc)

            answer = input(
                "Did anything change? [y]es / [n]o / [r]epeat / [q]uit: "
            ).strip().lower()
            if answer == "r":
                write_d0(payload)
                answer = input(
                    "Did anything change after the repeat? "
                    "[y]es / [n]o / [q]uit: "
                ).strip().lower()
            if answer in ("y", "n"):
                observed[offset] = answer
            if answer == "q":
                break
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        print("\nrestoring the baseline 09 d0 frame ...")
        try:
            write_d0(base_d0)
            restored = read_state()
        except controller.DeviceError as exc:
            print("restore: FAILED: %s" % exc)
            restore_failed = True
        else:
            if restored["custom2"] == base_d0:
                print("restore: ok")
            else:
                print(
                    "restore: FAILED; backup is at %s\n"
                    "run: ./bin/k622rgb config restore --custom %s --no-backup"
                    % (backup, backup)
                )
                restore_failed = True

    if restore_failed:
        return 1

    if observed:
        print("\nobservations:")
        for offset in sorted(observed):
            print("  payload[%d] = 0x%02X: %s" % (
                offset,
                args.value,
                "changed" if observed[offset] == "y" else "no visible change",
            ))
    print("\nbackup: %s" % backup)
    return 0


if __name__ == "__main__":
    sys.exit(main())

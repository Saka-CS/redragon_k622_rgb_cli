#!/usr/bin/env python3
"""End-to-end test for the experimental ``set --game-flag`` feature.

Safe default (no device access)::

    python3 tools/test_game_flag.py

That runs the game-flag unit tests, the CLI ``--dry-run`` check and the
argument-validation checks.  Nothing is opened or written.

Hardware test::

    python3 tools/test_game_flag.py --hardware

That additionally:

* verifies the K622 descriptor and opens the control interface;
* dumps a full config/palette/custom-frame backup;
* reads the current ``09 d0`` frame;
* runs ``set --game-flag`` twice (set and clear) against the keyboard;
* verifies the byte changed and the rest of the frame did not;
* verifies the backup contains ``custom2-response.bin``;
* restores the original config, palette and both custom frames;
* verifies the restored state byte-for-byte.

The restore always runs, including on failure or Ctrl-C.  If the keyboard
re-enumerates (the K622 does this after some rapid feature writes), the script
waits for it and retries the restore.

Options::

    --offset N      09 d0 payload byte to probe (default: 0)
    --value N       value to write first (default: 1; the script picks the
                    opposite value if the byte already has that value)
    --backup DIR    write the backup to DIR instead of the XDG state dir
    --keep          do not restore the device (the backup path is printed)
    --no-unit       skip the unit-test step
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from k622rgb import controller  # noqa: E402

CLI = os.path.join(ROOT, "bin", "k622rgb")

PASS = "PASS"
FAIL = "FAIL"


class TestFailure(RuntimeError):
    pass


class Runner:
    def __init__(self):
        self.failures = []

    def check(self, name, condition, detail=""):
        if condition:
            print("  [%s] %s" % (PASS, name))
            return True
        print("  [%s] %s%s" % (FAIL, name, (": " + detail) if detail else ""))
        self.failures.append(name)
        return False

    def run(self, args, expect=0, timeout=120):
        command = [sys.executable, CLI] + list(args)
        print("  $ k622rgb " + " ".join(args))
        result = subprocess.run(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        if result.returncode != expect:
            raise TestFailure(
                "command exited %d (expected %d)\nstdout:\n%s\nstderr:\n%s"
                % (result.returncode, expect, result.stdout, result.stderr)
            )
        return result


def run_unit_tests():
    print("\n== Unit tests ==")
    command = [
        sys.executable,
        "-m",
        "unittest",
        "tests.test_packet.GameFlagTests",
        "tests.test_cli.CliTests",
    ]
    result = subprocess.run(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if result.returncode != 0:
        print(result.stdout)
        raise TestFailure("unit tests failed")
    last = [line for line in result.stdout.splitlines() if line.startswith("Ran ")]
    print("  [%s] %s" % (PASS, last[-1] if last else "unit tests passed"))


def test_dry_run(runner, offset, value):
    print("\n== CLI dry-run (no device access) ==")
    result = runner.run(
        [
            "set",
            "--dry-run",
            "--no-state",
            "--no-activate",
            "--game-flag",
            "--game-flag-offset",
            str(offset),
            "--game-flag-value",
            str(value),
            "Esc=red",
        ]
    )
    expected = "set payload[%d] = 0x%02X" % (offset, value)
    runner.check(
        "dry-run describes the d0 byte change",
        expected in result.stdout,
        "missing %r" % expected,
    )
    runner.check(
        "dry-run did not claim a write",
        "wrote 09 d0 companion" not in result.stdout,
    )
    runner.check(
        "dry-run printed the 09 cc frame",
        "06 09 cc 00 40 00 00 00" in result.stdout,
    )
    runner.check(
        "dry-run did not open the device",
        "device not opened" in result.stdout,
    )


def test_validation(runner):
    print("\n== Argument validation ==")
    result = runner.run(
        [
            "set",
            "--no-state",
            "--no-activate",
            "--game-flag-offset",
            "3",
            "Esc=red",
        ],
        expect=2,
    )
    runner.check(
        "offset without --game-flag is rejected",
        "requires --game-flag" in result.stderr,
    )

    result = runner.run(
        [
            "set",
            "--no-state",
            "--no-activate",
            "--game-flag",
            "--game-flag-offset",
            "1024",
            "Esc=red",
        ],
        expect=2,
    )
    runner.check(
        "out-of-range offset is rejected",
        "0..1023" in result.stderr,
    )


def read_state():
    node = controller.find_device()
    fd = controller.open_device(node)
    try:
        return {
            "node": node,
            "config": controller.read_config(fd),
            "custom1": controller.read_custom_frame(fd, 1),
            "custom2": controller.read_custom_frame(fd, 2),
        }
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def wait_for_device(timeout=20.0, reader=None):
    """Wait until the K622 can be opened and a custom frame can be read."""
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            state = read_state() if reader is None else reader()
            return state
        except controller.DeviceError as exc:
            last_error = exc
            print("  ... waiting for the keyboard: %s" % exc)
            time.sleep(1.0)
    raise TestFailure(
        "keyboard did not come back within %.0fs: %s" % (timeout, last_error)
    )


def dump_backup(runner, backup_dir):
    print("\n== Backup ==")
    result = runner.run(["config", "dump", "--out", backup_dir])
    runner.check(
        "backup directory was created",
        os.path.isdir(backup_dir),
        backup_dir,
    )
    for name in (
        "config-response.bin",
        "colors-response.bin",
        "custom1-response.bin",
        "custom2-response.bin",
    ):
        path = os.path.join(backup_dir, name)
        runner.check(
            "backup contains %s" % name,
            os.path.isfile(path) and os.path.getsize(path) > 0,
        )
    return result


def response_payload(path, size=controller.CUSTOM_PAYLOAD_SIZE):
    with open(path, "rb") as handle:
        data = handle.read()
    return data[
        controller.CONFIG_RESPONSE_OFFSET:
        controller.CONFIG_RESPONSE_OFFSET + size
    ]


def hw_set(runner, offset, value):
    return runner.run(
        [
            "set",
            "--no-activate",
            "--no-state",
            "--game-flag",
            "--game-flag-offset",
            str(offset),
            "--game-flag-value",
            str(value),
            "Esc=red",
        ]
    )


def restore(runner, backup_dir, baseline, attempts=4):
    print("\n== Restore ==")
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            runner.run(
                [
                    "config",
                    "restore",
                    "--custom",
                    backup_dir,
                    "--no-backup",
                ],
                timeout=180,
            )
            break
        except (TestFailure, subprocess.TimeoutExpired) as exc:
            last_error = exc
            print(
                "  restore attempt %d/%d failed; waiting for the keyboard"
                % (attempt, attempts)
            )
            time.sleep(2.0)
            wait_for_device()
    else:
        raise TestFailure("restore failed after %d attempts: %s" % (
            attempts, last_error
        ))

    current = wait_for_device()
    runner.check(
        "restored 09 d0 frame matches the baseline",
        current["custom2"] == baseline["custom2"],
    )
    runner.check(
        "restored 09 cc frame matches the baseline",
        current["custom1"] == baseline["custom1"],
    )
    runner.check(
        "restored config matches the baseline",
        current["config"] == baseline["config"],
    )


def hardware_tests(runner, offset, value, backup_dir, keep):
    print("\n== Device check ==")
    result = runner.run(["check"])
    runner.check(
        "descriptor hash is the captured K622 IF1 descriptor",
        "known K622 IF1 descriptor" in result.stdout,
    )

    baseline = wait_for_device()
    base_d0 = baseline["custom2"]
    print(
        "  baseline: mode=%d, d0 sha256=%s, d0[%d]=0x%02X"
        % (
            baseline["config"][controller.CONFIG_MODE_INDEX],
            controller.descriptor_sha256(base_d0)[:16],
            offset,
            base_d0[offset],
        )
    )
    runner.check(
        "baseline 09 d0 payload is 1024 bytes",
        len(base_d0) == controller.CUSTOM_PAYLOAD_SIZE,
    )

    if value is None:
        value = 1 if base_d0[offset] != 1 else 0
    other = 0 if value else 1

    try:
        print("\n== Hardware write: payload[%d] = 0x%02X ==" % (offset, value))
        result = hw_set(runner, offset, value)
        runner.check(
            "CLI reported the new game byte",
            "game byte payload[%d] = 0x%02X" % (offset, value) in result.stdout,
            result.stdout,
        )
        after_set = wait_for_device()
        runner.check(
            "read-back 09 d0 byte matches",
            after_set["custom2"][offset] == value,
            "got 0x%02X" % after_set["custom2"][offset],
        )
        runner.check(
            "only the requested d0 byte changed",
            after_set["custom2"] == _with_byte(base_d0, offset, value),
        )

        print("\n== Hardware write: payload[%d] = 0x%02X ==" % (offset, other))
        result = hw_set(runner, offset, other)
        runner.check(
            "CLI reported the cleared game byte",
            "game byte payload[%d] = 0x%02X" % (offset, other) in result.stdout,
            result.stdout,
        )
        after_clear = wait_for_device()
        runner.check(
            "read-back 09 d0 byte matches the second value",
            after_clear["custom2"][offset] == other,
            "got 0x%02X" % after_clear["custom2"][offset],
        )

        print("\n== Backup contents ==")
        custom2_backup = os.path.join(backup_dir, "custom2-response.bin")
        runner.check(
            "backup 09 d0 payload matches the baseline",
            response_payload(custom2_backup) == base_d0,
        )
    finally:
        if keep:
            print("\n--keep: leaving the device in its current state")
            print("backup: %s" % backup_dir)
            print("restore with:")
            print(
                "  ./bin/k622rgb config restore --custom %s --no-backup"
                % backup_dir
            )
        else:
            restore(runner, backup_dir, baseline)


def _with_byte(payload, offset, value):
    modified = bytearray(payload)
    modified[offset] = value
    return bytes(modified)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Test the experimental k622rgb set --game-flag feature."
    )
    parser.add_argument(
        "--hardware",
        action="store_true",
        help="run the write/read-back/restore test on the connected K622",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=controller.GAME_FLAG_OFFSET,
        help="09 d0 payload byte to probe (default: %(default)s)",
    )
    parser.add_argument(
        "--value",
        type=int,
        default=None,
        help="first value to write (default: 1, or the opposite of the "
             "current byte)",
    )
    parser.add_argument(
        "--backup",
        metavar="DIR",
        help="write the hardware backup to DIR (default: a temp directory)",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="do not restore the device after the hardware test",
    )
    parser.add_argument(
        "--no-unit",
        action="store_true",
        help="skip the unit-test step",
    )
    args = parser.parse_args(argv)

    controller.validate_game_flag(args.offset, 1)
    if args.value is not None:
        controller.validate_game_flag(args.offset, args.value)
    if args.offset < 0 or args.offset >= controller.CUSTOM_PAYLOAD_SIZE:
        parser.error("--offset must be 0..%d" % (controller.CUSTOM_PAYLOAD_SIZE - 1))

    runner = Runner()
    temp_dir = None
    backup_dir = args.backup
    cleanup_backup = False
    try:
        if not args.no_unit:
            run_unit_tests()
        test_dry_run(runner, args.offset, 1 if args.value is None else args.value)
        test_validation(runner)

        if args.hardware:
            if backup_dir is None:
                temp_dir = tempfile.mkdtemp(prefix="k622rgb-game-flag-")
                backup_dir = temp_dir
            dump_backup(runner, backup_dir)
            hardware_tests(
                runner, args.offset, args.value, backup_dir, args.keep
            )
        else:
            print(
                "\nSafe checks complete. Re-run with --hardware to exercise "
                "the keyboard."
            )

        if runner.failures:
            print("\nFAILED checks:")
            for name in runner.failures:
                print("  - %s" % name)
            return 1
        cleanup_backup = temp_dir is not None and not args.keep
        print("\nAll checks passed.")
        return 0
    except TestFailure as exc:
        print("\nERROR: %s" % exc)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception:
        traceback.print_exc()
        return 1
    finally:
        if temp_dir is not None:
            if cleanup_backup:
                shutil.rmtree(temp_dir, ignore_errors=True)
            else:
                print("backup kept for recovery: %s" % temp_dir)


if __name__ == "__main__":
    sys.exit(main())

import contextlib
import io
import os
import shutil
import unittest
from pathlib import Path
from unittest import mock

from k622rgb import cli, controller, groups, layout

FIXTURE = Path(__file__).parent / "data" / "k622-if1-descriptor.bin"


def build_feature_descriptor(report_id, count, size=8):
    return bytes(
        (
            0x06, 0x00, 0xFF,
            0x09, 0x01,
            0xA1, 0x01,
            0x85, report_id,
            0x95, count,
            0x75, size,
            0xB1, 0x02,
            0xC0,
        )
    )


class CliTests(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.node = str(self.root / "hidraw6")
        self.node_path = self.root / "hidraw6"
        self.node_path.write_bytes(b"")
        self.sysfs = self.root / "sysfs"
        self.descriptor = self.sysfs / "device" / "report_descriptor"
        self.descriptor.parent.mkdir(parents=True)
        shutil.copyfile(FIXTURE, self.descriptor)
        self.info = controller.DeviceInfo(
            node=self.node,
            sysfs=str(self.sysfs),
            interface="01",
            hid_id="0003:0000258A:00000049",
        )

    def run_cli(
        self,
        argv,
        read_response=None,
        read_error=None,
        open_error=None,
        write_error=None,
        read_custom=None,
        write_custom_error=None,
        backup_error=None,
    ):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(
                mock.patch("k622rgb.cli.controller.iter_devices", return_value=[self.info])
            )
            opener = stack.enter_context(
                mock.patch(
                    "k622rgb.cli.controller.open_device",
                    return_value=-1,
                    side_effect=open_error,
                )
            )
            reader = stack.enter_context(
                mock.patch(
                    "k622rgb.cli.controller.read_feature",
                    return_value=read_response,
                    side_effect=read_error,
                )
            )
            writer = stack.enter_context(
                mock.patch(
                    "k622rgb.cli.controller.write_feature",
                    return_value=1032,
                    side_effect=write_error,
                )
            )
            self.custom_reader = stack.enter_context(
                mock.patch(
                    "k622rgb.cli.controller.read_custom_frame",
                    return_value=(
                        bytes(controller.CUSTOM_PAYLOAD_SIZE)
                        if read_custom is None
                        else read_custom
                    ),
                )
            )
            self.custom_writer = stack.enter_context(
                mock.patch(
                    "k622rgb.cli.controller.write_custom_frame",
                    return_value=1032,
                    side_effect=write_custom_error,
                )
            )
            self.backup = stack.enter_context(
                mock.patch(
                    "k622rgb.cli._save_lighting_backup",
                    return_value=str(self.root / "backup"),
                    side_effect=backup_error,
                )
            )
            stack.enter_context(
                mock.patch.dict(
                    os.environ,
                    {
                        "XDG_STATE_HOME": str(self.root / "state"),
                        "XDG_CONFIG_HOME": str(self.root / "config"),
                    },
                )
            )
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = cli.main(argv)
        return code, stdout.getvalue(), stderr.getvalue(), opener, reader, writer

    def report6(self):
        return bytes((0x06,)) + bytes(1031)

    # -- info ------------------------------------------------------------

    def test_info_lists_declared_reports(self):
        code, out, _err, opener, reader, _writer = self.run_cli(
            ["info", "--device", self.node]
        )
        self.assertEqual(code, 0)
        self.assertIn("known K622 IF1 descriptor", out)
        self.assertIn(controller.K622_DESCRIPTOR_SHA256, out)
        self.assertIn("descriptor: 227 bytes", out)
        self.assertIn("0x06 1031 bytes", out)
        self.assertIn("0x05 5 bytes", out)
        self.assertIn("HIDIOCGFEATURE(1032) = 0xC4084807", out)
        self.assertIn("report 0x08: not declared", out)
        opener.assert_not_called()
        reader.assert_not_called()

    def test_info_marks_unknown_descriptor(self):
        self.descriptor.write_bytes(bytes(227))
        code, out, err, _opener, _reader, _writer = self.run_cli(
            ["info", "--device", self.node]
        )
        self.assertEqual(code, 0)
        self.assertIn("UNKNOWN descriptor", out)
        self.assertIn("Do not trust writes", err)

    def test_info_missing_descriptor_fails(self):
        self.descriptor.unlink()
        code, _out, err, _opener, _reader, _writer = self.run_cli(
            ["info", "--device", self.node]
        )
        self.assertEqual(code, 1)
        self.assertIn("report_descriptor", err)

    # -- dump ------------------------------------------------------------

    def test_dump_report6_to_file(self):
        out_path = self.root / "nested" / "rep6.bin"
        code, out, _err, opener, reader, _writer = self.run_cli(
            ["dump", "--report", "6", "--out", str(out_path), "--device", self.node],
            read_response=self.report6(),
        )
        self.assertEqual(code, 0)
        self.assertEqual(out_path.read_bytes(), self.report6())
        self.assertIn("wrote 1032 bytes", out)
        opener.assert_called_once_with(self.node)
        reader.assert_called_once_with(-1, 0x06, 1031)

    def test_dump_report5_prints_hex(self):
        response = bytes((0x05, 0x01, 0x02, 0x03, 0x04, 0x05))
        code, out, _err, _opener, reader, _writer = self.run_cli(
            ["dump", "--report", "5", "--device", self.node],
            read_response=response,
        )
        self.assertEqual(code, 0)
        self.assertIn("report 0x05: 6 bytes returned", out)
        self.assertIn("05 01 02 03 04 05", out)
        reader.assert_called_once_with(-1, 0x05, 5)

    def test_dump_out_with_hex_prints_both(self):
        out_path = self.root / "rep5.bin"
        response = bytes((0x05, 9, 9, 9, 9, 9))
        code, out, _err, _opener, _reader, _writer = self.run_cli(
            ["dump", "--report", "5", "--out", str(out_path), "--hex",
             "--device", self.node],
            read_response=response,
        )
        self.assertEqual(code, 0)
        self.assertEqual(out_path.read_bytes(), response)
        self.assertIn("wrote 6 bytes", out)
        self.assertIn("05 09 09 09 09 09", out)

    def test_dump_dry_run_touches_nothing(self):
        code, out, _err, opener, reader, _writer = self.run_cli(
            ["dump", "--report", "6", "--dry-run"]
        )
        self.assertEqual(code, 0)
        self.assertIn("dry run", out)
        self.assertIn("HIDIOCGFEATURE(0xC4084807)", out)
        opener.assert_not_called()
        reader.assert_not_called()

    def test_dump_rejects_report8_at_parse_time(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["dump", "--report", "8"])
        self.assertEqual(ctx.exception.code, 2)

    def test_dump_refuses_undeclared_report_size(self):
        self.descriptor.write_bytes(build_feature_descriptor(0x06, 5))
        code, _out, err, opener, reader, _writer = self.run_cli(
            ["dump", "--report", "6", "--device", self.node],
            read_response=b"",
        )
        self.assertEqual(code, 1)
        self.assertIn("declared as 5 bytes", err)
        opener.assert_not_called()
        reader.assert_not_called()

    def test_dump_permission_failure_has_hints(self):
        code, _out, err, _opener, _reader, _writer = self.run_cli(
            ["dump", "--report", "6", "--device", self.node],
            open_error=controller.PermissionDenied(
                controller.permission_hint(self.node)
            ),
        )
        self.assertEqual(code, 1)
        self.assertIn("udev", err)

    def test_dump_read_error_is_reported(self):
        code, _out, err, _opener, _reader, _writer = self.run_cli(
            ["dump", "--report", "6", "--device", self.node],
            read_error=controller.ProtocolError("device said no"),
        )
        self.assertEqual(code, 1)
        self.assertIn("device said no", err)

    # -- check -----------------------------------------------------------

    def test_check_success_reads_no_reports(self):
        code, out, err, opener, reader, _writer = self.run_cli(
            ["check", "--device", self.node]
        )
        self.assertEqual(code, 0)
        self.assertIn("known K622 IF1 descriptor", out)
        self.assertIn("report 0x06: declared feature report, 1031 bytes", out)
        self.assertIn("report 0x05: declared feature report, 5 bytes", out)
        self.assertIn("report 0x08: not declared", out)
        self.assertIn("device open: ok (read-only)", out)
        self.assertIn("check: ok", out)
        opener.assert_called_once_with(self.node)
        reader.assert_not_called()
        self.assertEqual(err, "")

    def test_check_fails_on_descriptor_hash_mismatch(self):
        self.descriptor.write_bytes(bytes(227))
        code, out, _err, _opener, _reader, _writer = self.run_cli(
            ["check", "--device", self.node]
        )
        self.assertEqual(code, 1)
        self.assertIn("UNKNOWN descriptor", out)

    def test_check_dry_run_does_not_open(self):
        code, out, _err, opener, _reader, _writer = self.run_cli(
            ["check", "--device", self.node, "--dry-run"]
        )
        self.assertEqual(code, 0)
        self.assertIn("dry run: not opening", out)
        opener.assert_not_called()

    def test_check_permission_failure(self):
        code, _out, err, _opener, _reader, _writer = self.run_cli(
            ["check", "--device", self.node],
            open_error=controller.PermissionDenied(
                controller.permission_hint(self.node)
            ),
        )
        self.assertEqual(code, 1)
        self.assertIn("udev", err)

    # -- set -------------------------------------------------------------

    def state_file(self):
        return str(self.root / "explicit-frame.bin")

    def test_set_dry_run_builds_red_esc_frame(self):
        code, out, err, opener, _reader, writer = self.run_cli(
            ["set", "--dry-run", "--no-state", "Esc=red"]
        )
        self.assertEqual(code, 0)
        self.assertIn("set: Esc (slot 0) = #ff0000", out)
        self.assertIn("HIDIOCSFEATURE(1032) = 0xC4084806", out)
        self.assertIn("06 09 cc 00 40 00 00 00 ff", out)
        opener.assert_not_called()
        writer.assert_not_called()
        self.assertEqual(err, "")

    def test_set_dry_run_does_not_create_state(self):
        state_path = self.root / "state" / "k622rgb" / "last-frame.bin"
        code, _out, _err, _opener, _reader, _writer = self.run_cli(
            ["set", "--dry-run", "Esc=red"]
        )
        self.assertEqual(code, 0)
        self.assertFalse(state_path.exists())

    def test_set_sends_frame_and_saves_state(self):
        state_path = self.state_file()
        code, out, _err, opener, _reader, writer = self.run_cli(
            ["set", "--no-activate", "--state", state_path, "Esc=red"]
        )
        self.assertEqual(code, 0)
        self.assertIn("sent 1032-byte report 0x06 lighting frame", out)
        self.assertIn("saved frame to", out)
        opener.assert_called_once_with(self.node, writable=True)
        writer.assert_called_once()
        fd, packet = writer.call_args.args
        self.assertEqual(fd, -1)
        self.assertEqual(len(packet), 1032)
        self.assertEqual(packet[0], 0x06)
        self.assertEqual(packet[8], 255)
        self.assertEqual(Path(state_path).read_bytes(), packet)

    def test_set_accumulates_from_saved_frame(self):
        state_path = self.state_file()
        self.run_cli(["set", "--no-activate", "--state", state_path, "Esc=red"])
        _code, _out, _err, _opener, _reader, writer = self.run_cli(
            ["set", "--no-activate", "--state", state_path, "1=green"]
        )
        _fd, packet = writer.call_args.args
        self.assertEqual(packet[8], 255)          # Esc red kept
        self.assertEqual(packet[8 + 22], 0)       # 1 is not red
        self.assertEqual(packet[134 + 22], 255)   # 1 is green

    def test_set_off_clears_saved_frame(self):
        state_path = self.state_file()
        self.run_cli(["set", "--no-activate", "--state", state_path, "Esc=red"])
        _code, _out, _err, _opener, _reader, writer = self.run_cli(
            ["set", "--no-activate", "--state", state_path, "--off"]
        )
        _fd, packet = writer.call_args.args
        self.assertEqual(packet[8:386], bytes(378))
        self.assertEqual(packet[386:], controller.load_color_template()[386:])

    def test_set_reset_ignores_saved_frame(self):
        state_path = self.state_file()
        self.run_cli(["set", "--no-activate", "--state", state_path, "Esc=red"])
        _code, _out, _err, _opener, _reader, writer = self.run_cli(
            ["set", "--no-activate", "--state", state_path, "--reset", "1=green"]
        )
        _fd, packet = writer.call_args.args
        self.assertEqual(packet[8], 0)            # Esc red dropped
        self.assertEqual(packet[134 + 22], 255)   # 1 is green

    def test_set_all_fills_every_slot(self):
        code, out, _err, _opener, _reader, writer = self.run_cli(
            ["set", "--no-activate", "--no-state", "--all", "0000ff"]
        )
        self.assertEqual(code, 0)
        _fd, packet = writer.call_args.args
        self.assertEqual(packet[8:386], bytes(252) + bytes([255]) * 126)
        self.assertIn("filled with #0000ff", out)

    def test_set_allows_override_of_fill(self):
        _code, _out, _err, _opener, _reader, writer = self.run_cli(
            ["set", "--no-activate", "--no-state", "--all", "0000ff", "Esc=red"]
        )
        _fd, packet = writer.call_args.args
        self.assertEqual(packet[8], 255)
        self.assertEqual(packet[260], 0)
        self.assertEqual(packet[8 + 1], 0)
        self.assertEqual(packet[260 + 1], 255)

    def test_set_numeric_slot_syntax(self):
        code, _out, _err, _opener, _reader, writer = self.run_cli(
            ["set", "--no-activate", "--no-state", "slot:6=ffffff"]
        )
        self.assertEqual(code, 0)
        _fd, packet = writer.call_args.args
        self.assertEqual(packet[8 + 6], 255)
        self.assertEqual(packet[134 + 6], 255)
        self.assertEqual(packet[260 + 6], 255)

    def test_set_accepts_logo_zone(self):
        code, out, _err, _opener, _reader, writer = self.run_cli(
            ["set", "--no-activate", "--no-state", "LogoLeft=0000ff"]
        )
        self.assertEqual(code, 0)
        _fd, packet = writer.call_args.args
        self.assertEqual(packet[260 + 77], 255)
        self.assertIn("set: LogoLeft (slot 77)", out)

    def test_set_x_lights_slot_87(self):
        code, out, err, _opener, _reader, writer = self.run_cli(
            ["set", "--no-activate", "--no-state", "X=red"]
        )
        self.assertEqual(code, 0)
        self.assertIn("set: X (slot 87)", out)
        self.assertNotIn("did not light during calibration", err)
        _fd, packet = writer.call_args.args
        self.assertEqual(packet[8 + 87], 255)

    def test_set_activate_default_and_opt_out(self):
        parser = cli.build_parser()
        self.assertTrue(parser.parse_args(["set", "Esc=red"]).activate)
        self.assertFalse(
            parser.parse_args(["set", "--no-activate", "Esc=red"]).activate
        )
        self.assertTrue(
            parser.parse_args(["set", "--activate", "Esc=red"]).activate
        )

    def test_set_requires_something_to_do(self):
        code, _out, err, opener, _reader, writer = self.run_cli(
            ["set", "--no-state"]
        )
        self.assertEqual(code, 2)
        self.assertIn("nothing to set", err)
        opener.assert_not_called()
        writer.assert_not_called()

    def test_set_rejects_unknown_key(self):
        code, _out, err, opener, _reader, writer = self.run_cli(
            ["set", "--no-state", "Bogus=red"]
        )
        self.assertEqual(code, 2)
        self.assertIn("unknown key", err)
        opener.assert_not_called()
        writer.assert_not_called()

    def test_set_rejects_invalid_color(self):
        code, _out, err, opener, _reader, writer = self.run_cli(
            ["set", "--no-state", "Esc=#zzzzzz"]
        )
        self.assertEqual(code, 2)
        self.assertIn("invalid color", err)
        opener.assert_not_called()
        writer.assert_not_called()

    def test_set_rejects_missing_assignment(self):
        code, _out, err, opener, _reader, writer = self.run_cli(
            ["set", "--no-state", "Esc"]
        )
        self.assertEqual(code, 2)
        self.assertIn("expected KEY=COLOR", err)
        opener.assert_not_called()
        writer.assert_not_called()

    def test_set_rejects_all_and_off_together(self):
        code, _out, err, opener, _reader, writer = self.run_cli(
            ["set", "--no-state", "--all", "red", "--off"]
        )
        self.assertEqual(code, 2)
        self.assertIn("mutually exclusive", err)
        opener.assert_not_called()
        writer.assert_not_called()

    def test_set_rejects_state_and_no_state_together(self):
        code, _out, err, opener, _reader, writer = self.run_cli(
            ["set", "--state", "x", "--no-state", "--off"]
        )
        self.assertEqual(code, 2)
        self.assertIn("mutually exclusive", err)
        opener.assert_not_called()
        writer.assert_not_called()

    def test_set_refuses_unknown_descriptor(self):
        self.descriptor.write_bytes(bytes(227))
        code, _out, err, opener, _reader, writer = self.run_cli(
            ["set", "--no-state", "Esc=red"]
        )
        self.assertEqual(code, 1)
        self.assertIn("refusing to write", err)
        opener.assert_not_called()
        writer.assert_not_called()

    def test_set_refuses_corrupt_saved_frame(self):
        state_path = self.state_file()
        Path(state_path).write_bytes(b"garbage")
        code, _out, err, opener, _reader, writer = self.run_cli(
            ["set", "--no-activate", "--state", state_path, "Esc=red"]
        )
        self.assertEqual(code, 1)
        self.assertIn("--reset", err)
        opener.assert_not_called()
        writer.assert_not_called()

    def test_set_write_error_is_reported(self):
        code, _out, err, _opener, _reader, _writer = self.run_cli(
            ["set", "--no-activate", "--no-state", "Esc=red"],
            write_error=controller.ProtocolError("keyboard said no"),
        )
        self.assertEqual(code, 1)
        self.assertIn("keyboard said no", err)

    def test_set_open_error_is_reported(self):
        code, _out, err, _opener, _reader, _writer = self.run_cli(
            ["set", "--no-state", "Esc=red"],
            open_error=controller.PermissionDenied(
                controller.permission_hint(self.node)
            ),
        )
        self.assertEqual(code, 1)
        self.assertIn("udev", err)

    def test_set_hex_prints_full_frame(self):
        code, out, _err, _opener, _reader, _writer = self.run_cli(
            ["set", "--no-activate", "--no-state", "--hex", "Esc=red"]
        )
        self.assertEqual(code, 0)
        self.assertIn("packet: 1032 bytes", out)
        self.assertIn("00000400", out)

    def test_set_dry_run_does_not_save_frame(self):
        state_path = self.state_file()
        code, _out, _err, _opener, _reader, _writer = self.run_cli(
            ["set", "--dry-run", "--state", state_path, "Esc=red"]
        )
        self.assertEqual(code, 0)
        self.assertFalse(Path(state_path).exists())

    def test_set_game_flag_dry_run_describes_the_companion(self):
        code, out, err, opener, _reader, writer = self.run_cli(
            [
                "set", "--dry-run", "--no-state", "--no-activate",
                "--game-flag", "--game-flag-offset", "3",
                "--game-flag-value", "90", "Esc=red",
            ]
        )
        self.assertEqual(code, 0)
        self.assertIn(
            "would read the current 09 d0 companion and set payload[3] = 0x5A",
            out,
        )
        opener.assert_not_called()
        writer.assert_not_called()
        self.custom_reader.assert_not_called()
        self.custom_writer.assert_not_called()
        self.assertEqual(err, "")

    def test_set_game_flag_writes_the_companion_after_the_colour_frame(self):
        base = bytearray(controller.CUSTOM_PAYLOAD_SIZE)
        base[3] = 0x11
        base[9] = 0x22
        code, out, _err, _opener, _reader, writer = self.run_cli(
            [
                "set", "--no-activate", "--no-state",
                "--game-flag", "--game-flag-offset", "3",
                "--game-flag-value", "90", "Esc=red",
            ],
            read_custom=bytes(base),
        )
        self.assertEqual(code, 0)
        writer.assert_called_once()
        self.custom_reader.assert_called_once_with(-1, 2)
        self.custom_writer.assert_called_once()
        fd, payload, which = self.custom_writer.call_args.args
        self.assertEqual(fd, -1)
        self.assertEqual(which, 2)
        self.assertEqual(len(payload), controller.CUSTOM_PAYLOAD_SIZE)
        self.assertEqual(payload[3], 0x5A)
        self.assertEqual(payload[9], 0x22)       # untouched
        self.assertIn("game flag: 09 d0 payload[3] 0x11 -> 0x5A", out)
        self.assertIn("wrote 09 d0 companion; game byte payload[3] = 0x5A", out)
        self.backup.assert_called_once()
        self.assertTrue(self.backup.call_args.kwargs.get("custom"))

    def test_set_game_flag_can_clear_the_byte(self):
        base = bytearray(controller.CUSTOM_PAYLOAD_SIZE)
        base[controller.GAME_FLAG_OFFSET] = 1
        code, _out, _err, _opener, _reader, _writer = self.run_cli(
            ["set", "--no-activate", "--no-state", "--game-flag",
             "--game-flag-value", "0", "Esc=red"],
            read_custom=bytes(base),
        )
        self.assertEqual(code, 0)
        _fd, payload, _which = self.custom_writer.call_args.args
        self.assertEqual(payload[controller.GAME_FLAG_OFFSET], 0)

    def test_set_game_flag_requires_the_flag(self):
        for extra in (["--game-flag-offset", "3"], ["--game-flag-value", "1"]):
            with self.subTest(extra=extra):
                code, _out, err, opener, _reader, writer = self.run_cli(
                    ["set", "--no-activate", "--no-state"] + extra + ["Esc=red"]
                )
                self.assertEqual(code, 2)
                self.assertIn("requires --game-flag", err)
                opener.assert_not_called()
                writer.assert_not_called()

    def test_set_game_flag_rejects_bad_offset(self):
        code, _out, err, opener, _reader, writer = self.run_cli(
            ["set", "--no-activate", "--no-state", "--game-flag",
             "--game-flag-offset", "1024", "Esc=red"]
        )
        self.assertEqual(code, 2)
        self.assertIn("0..1023", err)
        opener.assert_not_called()
        writer.assert_not_called()

    def test_set_game_flag_reports_companion_write_failure(self):
        code, _out, err, _opener, _reader, writer = self.run_cli(
            ["set", "--no-activate", "--no-state", "--game-flag", "Esc=red"],
            write_custom_error=controller.ProtocolError("d0 stalled"),
        )
        self.assertEqual(code, 1)
        writer.assert_called_once()
        self.assertIn("09 d0 game-flag write failed", err)
        self.assertIn("d0 stalled", err)
        self.assertIn("config restore --custom", err)

    def test_set_game_flag_hex_still_prints_the_colour_frame(self):
        code, out, _err, _opener, _reader, _writer = self.run_cli(
            ["set", "--no-activate", "--no-state", "--game-flag", "--hex",
             "Esc=red"]
        )
        self.assertEqual(code, 0)
        self.assertIn("packet: 1032 bytes", out)
        self.assertIn("06 09 cc 00 40 00 00 00 ff", out)

    def test_set_group_overlay_precedence_in_frame(self):
        group_file = self.root / "config" / "k622rgb" / "groups.json"
        local = {}
        groups.update_local_group(local, "fps", (255, 0, 0))
        groups.save_local_groups(local, str(group_file))

        code, _out, _err, _opener, _reader, writer = self.run_cli(
            [
                "set", "--no-activate", "--no-state",
                "--all", "blue",
                "--group", "fps=ff0000",
                "Esc=white",
            ]
        )
        self.assertEqual(code, 0)
        _fd, packet = writer.call_args.args
        # FPS paints W red; the --all blue base survives elsewhere.
        self.assertEqual(packet[8 + 44], 255)     # W red
        self.assertEqual(packet[134 + 44], 0)
        self.assertEqual(packet[260 + 44], 0)
        # Explicit Esc=white wins over the group/base.
        self.assertEqual(packet[8], 255)
        self.assertEqual(packet[134], 255)
        self.assertEqual(packet[260], 255)
        # F1 is not in the FPS group, so it keeps the blue base.
        self.assertEqual(packet[260 + 2], 255)
        self.assertEqual(packet[8 + 2], 0)

    def test_plain_set_ignores_corrupt_group_store(self):
        group_file = self.root / "config" / "k622rgb" / "groups.json"
        group_file.parent.mkdir(parents=True)
        group_file.write_text("{not json", encoding="utf-8")
        code, out, _err, _opener, _reader, _writer = self.run_cli(
            ["set", "--dry-run", "--no-state", "Esc=red"]
        )
        self.assertEqual(code, 0)
        self.assertIn("set: Esc (slot 0) = #ff0000", out)

    def test_group_apply_writes_frame_and_saves_state(self):
        group_file = str(self.root / "groups.json")
        state_path = str(self.root / "group-frame.bin")
        local = {}
        groups.update_local_group(local, "define1", (255, 0, 0))
        groups.save_local_groups(local, group_file)

        code, out, _err, opener, _reader, writer = self.run_cli(
            [
                "group", "apply", "1",
                "--file", group_file,
                "--no-activate",
                "--state", state_path,
            ]
        )
        self.assertEqual(code, 0)
        self.assertIn("group: define1 = #ff0000", out)
        self.assertIn("saved frame to", out)
        opener.assert_called_once_with(self.node, writable=True)
        writer.assert_called_once()
        _fd, packet = writer.call_args.args
        self.assertEqual(packet[8 + 44], 255)    # W
        self.assertEqual(packet[134 + 44], 0)
        self.assertEqual(packet[260 + 44], 0)
        self.assertEqual(packet[8], 0)           # Esc is not in define1
        self.assertEqual(Path(state_path).read_bytes(), packet)

    # -- list ------------------------------------------------------------

    def test_list_shows_map_summary(self):
        code, out, err, opener, reader, writer = self.run_cli(["list"])
        self.assertEqual(code, 0)
        self.assertIn("87 mapped, 3 logo zones, 0 aliases, 36 dead", out)
        self.assertIn(
            "logo zones: LogoLeft=77, LogoCenter=78, LogoRight=79", out
        )
        self.assertNotIn("unlit during calibration", out)
        self.assertIn("no individually addressable RGB LEDs", out)
        opener.assert_not_called()
        reader.assert_not_called()
        writer.assert_not_called()
        self.assertEqual(err, "")

    def test_list_all_prints_packet_slots(self):
        code, out, _err, _opener, _reader, _writer = self.run_cli(
            ["list", "--all"]
        )
        self.assertEqual(code, 0)
        self.assertIn("packet slots:", out)
        self.assertIn("Esc", out)
        self.assertIn("LogoLeft", out)
        self.assertIn("dead", out)
        self.assertIn("85  -            dead", out)
        self.assertIn("87  X            key", out)
        self.assertIn("95  /            key", out)

    def test_set_rejects_extra_key(self):
        code, _out, err, opener, _reader, writer = self.run_cli(
            ["set", "--dry-run", "--no-state", "G1=red"]
        )
        self.assertEqual(code, 2)
        self.assertIn("not", err.lower())
        opener.assert_not_called()
        writer.assert_not_called()

    # -- argparse --------------------------------------------------------

    def test_unknown_command_is_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as ctx:
                cli.main(["frobnicate"])
        self.assertEqual(ctx.exception.code, 2)

    def test_global_flags_work_before_and_after_subcommand(self):
        for argv in (
            ["--dry-run", "dump", "--report", "6"],
            ["dump", "--dry-run", "--report", "6"],
        ):
            with self.subTest(argv=argv):
                code, out, _err, opener, _reader, _writer = self.run_cli(argv)
                self.assertEqual(code, 0)
                self.assertIn("dry run", out)
                opener.assert_not_called()

    def test_hex_report_argument_accepts_0x_prefix(self):
        code, out, _err, _opener, _reader, _writer = self.run_cli(
            ["dump", "--report", "0x05", "--device", self.node],
            read_response=bytes(6),
        )
        self.assertEqual(code, 0)
        self.assertIn("report 0x05", out)


if __name__ == "__main__":
    unittest.main()

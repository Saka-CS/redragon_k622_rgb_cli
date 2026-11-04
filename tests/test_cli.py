import contextlib
import io
import json
import os
import shutil
import unittest
from pathlib import Path
from unittest import mock

from k622rgb import cli, controller, groups, layout, state

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
        backup_error=None,
        backup_return=None,
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
            self.backup = stack.enter_context(
                mock.patch(
                    "k622rgb.cli._save_lighting_backup",
                    return_value=(
                        backup_return
                        if backup_return is not None
                        else str(self.root / "backup")
                    ),
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

    def test_set_group_overlay_honours_file_override(self):
        group_file = self.root / "custom-groups.json"
        local = {}
        groups.update_local_group(local, "mygroup", (255, 0, 0), ["W", "A"])
        groups.save_local_groups(local, str(group_file))

        code, out, err, opener, _reader, writer = self.run_cli(
            [
                "set", "--dry-run", "--no-state",
                "--file", str(group_file),
                "--group", "mygroup=ff0000",
                "Esc=white",
            ]
        )
        self.assertEqual(code, 0)
        self.assertIn("group: mygroup = #ff0000", out)
        self.assertIn("set: Esc (slot 0) = #ffffff", out)
        self.assertEqual(err, "")
        opener.assert_not_called()
        writer.assert_not_called()

    def test_set_group_overlay_without_file_ignores_custom_store(self):
        group_file = self.root / "custom-groups.json"
        local = {}
        groups.update_local_group(local, "mygroup", (255, 0, 0), ["W", "A"])
        groups.save_local_groups(local, str(group_file))

        code, _out, err, opener, _reader, writer = self.run_cli(
            ["set", "--dry-run", "--no-state", "--group", "mygroup=ff0000"]
        )
        self.assertEqual(code, 2)
        self.assertIn("unknown group 'mygroup'", err)
        opener.assert_not_called()
        writer.assert_not_called()

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

    # -- config backups --------------------------------------------------

    def make_legacy_backup(self):
        path = self.root / "legacy-backup"
        path.mkdir()
        files = {
            "config-response.bin": bytes((0x06,)) + bytes(261),
            "colors-response.bin": bytes((0x06,)) + bytes(1031),
        }
        for name, data in files.items():
            (path / name).write_bytes(data)
        meta = {
            "kind": "config dump",
            "descriptor_sha256": "abc123",
            "created": "2026-01-01T00:00:00Z",
            "tool": "k622rgb test",
        }
        (path / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        return path, files, meta

    def test_config_seal_adds_hashes_and_preserves_metadata(self):
        path, files, meta = self.make_legacy_backup()

        code, out, err, opener, _reader, _writer = self.run_cli(
            ["config", "seal", str(path)]
        )

        self.assertEqual(code, 0)
        self.assertIn("warning", err)
        self.assertIn("sealed:", out)
        opener.assert_not_called()
        sealed = json.loads((path / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(sealed["version"], 2)
        self.assertEqual(sealed["files"], state.files_manifest(files))
        for key, value in meta.items():
            self.assertEqual(sealed[key], value)
        verified_meta, verified_files = state.verify_backup_dir(
            str(path),
            required=tuple(files),
            descriptor_sha256="abc123",
        )
        self.assertEqual(verified_meta["descriptor_sha256"], "abc123")
        self.assertEqual(verified_files, files)

    def test_config_seal_requires_force_to_reseal(self):
        path, files, _meta = self.make_legacy_backup()
        self.run_cli(["config", "seal", str(path)])

        (path / "config-response.bin").write_bytes(b"changed")
        code, _out, err, _opener, _reader, _writer = self.run_cli(
            ["config", "seal", str(path)]
        )
        self.assertEqual(code, 2)
        self.assertIn("--force", err)
        with self.assertRaises(state.BackupError):
            state.verify_backup_dir(str(path))

        code, out, _err, _opener, _reader, _writer = self.run_cli(
            ["config", "seal", str(path), "--force"]
        )
        self.assertEqual(code, 0)
        self.assertIn("sealed:", out)
        changed = dict(files)
        changed["config-response.bin"] = b"changed"
        sealed = json.loads((path / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(sealed["files"], state.files_manifest(changed))
        state.verify_backup_dir(str(path), required=tuple(changed))

    def test_config_seal_does_not_open_device(self):
        path, _files, _meta = self.make_legacy_backup()

        code, _out, _err, opener, reader, writer = self.run_cli(
            ["config", "seal", str(path)]
        )

        self.assertEqual(code, 0)
        opener.assert_not_called()
        reader.assert_not_called()
        writer.assert_not_called()

    def test_config_dump_manifest_has_hashes(self):
        out_dir = self.root / "dump"
        config_response = bytes((0x06,)) + bytes(range(255)) + bytes(6)

        def fake_mailbox_read(_fd, command, *args, **kwargs):
            return bytes((0x06,)) + command + bytes(1032 - 1 - len(command))

        expected = {
            "config-response.bin",
            "colors-response.bin",
            "custom1-response.bin",
            "custom2-response.bin",
            "profile-response.bin",
        }
        with mock.patch(
            "k622rgb.cli.controller.read_config_response",
            return_value=config_response,
        ), mock.patch(
            "k622rgb.cli.controller.mailbox_read",
            side_effect=fake_mailbox_read,
        ), mock.patch(
            "k622rgb.cli.os.close"
        ):
            code, out, err, opener, _reader, _writer = self.run_cli(
                ["config", "dump", "--out", str(out_dir), "--device", self.node]
            )

        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("dump:", out)
        opener.assert_called_once_with(self.node, writable=True)
        meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["version"], 2)
        self.assertEqual(set(meta["files"]), expected)
        self.assertEqual(
            meta["descriptor_sha256"], controller.K622_DESCRIPTOR_SHA256
        )
        _verified_meta, files = state.verify_backup_dir(
            str(out_dir),
            required=tuple(expected),
            descriptor_sha256=controller.K622_DESCRIPTOR_SHA256,
        )
        self.assertEqual(set(files), expected)
        self.assertEqual(files["config-response.bin"], config_response)

    # -- config restore --------------------------------------------------

    def make_config_block(self):
        config = bytearray(controller.CONFIG_SIZE)
        config[0x08:0x0A] = b"\x03\x03"
        config[
            controller.CONFIG_TRAILER_INDEX:
            controller.CONFIG_TRAILER_INDEX + 2
        ] = controller.CONFIG_TRAILER
        return bytes(config)

    def make_restore_backup(
        self, name="restore-backup", verified=True, descriptor=None,
        custom=True,
    ):
        path = self.root / name
        path.mkdir()
        files = {
            "config-response.bin": bytes(8) + self.make_config_block(),
            "colors-response.bin": bytes(8) + bytes(controller.COLOR_TABLE_SIZE),
        }
        if custom:
            files["custom1-response.bin"] = bytes(8) + b"\x11" * 1024
            files["custom2-response.bin"] = bytes(8) + b"\x22" * 1024
        for filename, data in files.items():
            (path / filename).write_bytes(data)
        meta = {
            "kind": "config dump",
            "descriptor_sha256": (
                descriptor
                if descriptor is not None
                else controller.K622_DESCRIPTOR_SHA256
            ),
            "created": "2026-01-01T00:00:00Z",
            "tool": "k622rgb test",
        }
        if verified:
            meta["version"] = 2
            meta["files"] = state.files_manifest(files)
        (path / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        return path, files, meta

    def run_restore(
        self,
        argv,
        backup_return=None,
        write_palette_effect=None,
        write_config_effect=None,
        write_custom_effect=None,
        read_custom_return=None,
        read_custom_side_effect=None,
    ):
        with mock.patch(
            "k622rgb.cli.controller.write_effect_palette",
            side_effect=write_palette_effect,
        ) as write_palette, mock.patch(
            "k622rgb.cli.controller.write_config",
            side_effect=write_config_effect,
        ) as write_config, mock.patch(
            "k622rgb.cli.controller.write_custom_frame",
            side_effect=write_custom_effect,
        ) as write_custom, mock.patch(
            "k622rgb.cli.controller.read_custom_frame",
            return_value=read_custom_return,
            side_effect=read_custom_side_effect,
        ) as read_custom, mock.patch(
            "k622rgb.cli.time.sleep"
        ), mock.patch(
            "k622rgb.cli.os.close"
        ):
            code, out, err, opener, _reader, _writer = self.run_cli(
                argv, backup_return=backup_return
            )
        return {
            "code": code,
            "out": out,
            "err": err,
            "opener": opener,
            "write_palette": write_palette,
            "write_config": write_config,
            "write_custom": write_custom,
            "read_custom": read_custom,
        }

    def test_config_restore_custom_requires_manifest(self):
        path, _files, _meta = self.make_restore_backup(verified=False)

        result = self.run_restore(
            ["config", "restore", "--custom", "--yes", str(path)]
        )

        self.assertEqual(result["code"], 2)
        self.assertIn("manifest", result["err"])
        self.assertIn("--allow-unverified", result["err"])
        result["opener"].assert_not_called()

    def test_config_restore_custom_rejects_hash_mismatch(self):
        path, _files, _meta = self.make_restore_backup()
        (path / "custom2-response.bin").write_bytes(
            bytes(8) + b"\x33" * 1024
        )

        result = self.run_restore(
            ["config", "restore", "--custom", "--yes", str(path)]
        )

        self.assertEqual(result["code"], 2)
        self.assertIn("sha256 mismatch", result["err"])
        result["opener"].assert_not_called()

    def test_config_restore_custom_rejects_descriptor_mismatch(self):
        path, _files, _meta = self.make_restore_backup(descriptor="0" * 64)

        result = self.run_restore(
            ["config", "restore", "--custom", "--yes", str(path)]
        )

        self.assertEqual(result["code"], 1)
        self.assertIn("descriptor", result["err"])
        result["opener"].assert_called_once_with(self.node, writable=True)
        result["write_palette"].assert_not_called()
        result["write_config"].assert_not_called()
        result["write_custom"].assert_not_called()

    def test_config_restore_custom_requires_descriptor(self):
        path, files, meta = self.make_restore_backup()
        del meta["descriptor_sha256"]
        (path / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

        result = self.run_restore(
            ["config", "restore", "--custom", "--yes", str(path)]
        )

        self.assertEqual(result["code"], 2)
        self.assertIn("descriptor_sha256", result["err"])
        result["opener"].assert_not_called()

    def test_config_restore_custom_requires_yes(self):
        path, _files, _meta = self.make_restore_backup()

        result = self.run_restore(
            ["config", "restore", "--custom", str(path)]
        )

        self.assertEqual(result["code"], 2)
        self.assertIn("refusing to write 09 d0 without --yes", result["err"])
        self.assertIn("%s --yes" % path, result["err"])
        self.assertIn("custom2-response.bin", result["out"])
        result["opener"].assert_not_called()

    def test_config_restore_custom_rejects_no_backup(self):
        path, _files, _meta = self.make_restore_backup()

        result = self.run_restore(
            [
                "config", "restore", "--custom", "--yes", "--no-backup",
                str(path),
            ]
        )

        self.assertEqual(result["code"], 2)
        self.assertIn("--no-backup", result["err"])
        self.assertIn("09 d0", result["err"])
        result["opener"].assert_not_called()

    def test_config_restore_custom_prebackup_includes_custom_frames(self):
        config_response = bytes(8) + self.make_config_block()
        palette_response = bytes(8) + bytes(controller.COLOR_TABLE_SIZE)
        custom1 = bytes(8) + b"\xaa" * 1024
        custom2 = bytes(8) + b"\xbb" * 1024
        descriptor = FIXTURE.read_bytes()

        with mock.patch.dict(
            os.environ, {"XDG_STATE_HOME": str(self.root / "state")}
        ), mock.patch(
            "k622rgb.cli.controller.read_config_response",
            return_value=config_response,
        ), mock.patch(
            "k622rgb.cli.controller.mailbox_read",
            side_effect=[palette_response, custom1, custom2],
        ):
            path = cli._save_lighting_backup(
                -1, descriptor, "restore", custom=True
            )

        meta, files = state.verify_backup_dir(
            path,
            required=("custom1-response.bin", "custom2-response.bin"),
            descriptor_sha256=controller.descriptor_sha256(descriptor),
        )
        self.assertEqual(meta["kind"], "restore")
        self.assertEqual(files["custom1-response.bin"], custom1)
        self.assertEqual(files["custom2-response.bin"], custom2)

    def test_config_restore_writes_d0_last(self):
        path, files, _meta = self.make_restore_backup()
        order = []

        def write_palette(_fd, _palette):
            order.append("palette")

        def write_config(_fd, _config):
            order.append("config")

        def write_custom(_fd, _payload, which):
            order.append("custom%d" % which)

        expected = files["custom2-response.bin"][8:]
        result = self.run_restore(
            ["config", "restore", "--custom", "--yes", str(path)],
            backup_return=str(self.root / "prebackup"),
            write_palette_effect=write_palette,
            write_config_effect=write_config,
            write_custom_effect=write_custom,
            read_custom_return=expected,
        )

        self.assertEqual(result["code"], 0)
        self.assertEqual(order, ["palette", "config", "custom1", "custom2"])
        self.assertIn("restored:", result["out"])

    def test_config_restore_readback_mismatch_rolls_back(self):
        path, _files, _meta = self.make_restore_backup()
        prebackup = self.root / "prebackup"
        prebackup.mkdir()
        rollback_payload = b"\xaa" * 1024
        (prebackup / "custom2-response.bin").write_bytes(
            bytes(8) + rollback_payload
        )
        d0_payloads = []

        def write_custom(_fd, payload, which):
            if which == 2:
                d0_payloads.append(payload)

        result = self.run_restore(
            ["config", "restore", "--custom", "--yes", str(path)],
            backup_return=str(prebackup),
            write_custom_effect=write_custom,
            read_custom_side_effect=[b"\x00" * 1024, rollback_payload],
        )

        self.assertEqual(result["code"], 1)
        self.assertEqual(len(d0_payloads), 2)
        self.assertEqual(d0_payloads[0], b"\x22" * 1024)
        self.assertEqual(d0_payloads[1], rollback_payload)
        self.assertEqual(result["read_custom"].call_count, 2)
        self.assertIn("rolled back", result["err"])
        self.assertIn("not rolled back", result["err"])
        self.assertIn("To return fully", result["err"])
        self.assertNotIn("original state recovered", result["err"])

    def test_config_restore_epipe_stops_without_retry(self):
        path, _files, _meta = self.make_restore_backup()
        calls = []

        def write_custom(_fd, _payload, which):
            calls.append(which)
            raise controller.DeviceError("broken pipe (EPIPE)")

        result = self.run_restore(
            ["config", "restore", "--custom", "--yes", str(path)],
            backup_return=str(self.root / "prebackup"),
            write_custom_effect=write_custom,
        )

        self.assertEqual(result["code"], 1)
        self.assertEqual(calls, [1])
        self.assertEqual(result["write_custom"].call_count, 1)
        self.assertEqual(result["write_config"].call_count, 1)
        self.assertIn("broken pipe", result["err"])
        self.assertIn("pre-restore backup", result["err"])
        self.assertIn("before the 09 d0 write", result["err"])
        self.assertNotIn("did not respond after the 09 d0", result["err"])
        result["read_custom"].assert_not_called()

    def test_config_restore_epipe_on_d0_prints_recovery(self):
        path, _files, _meta = self.make_restore_backup()
        calls = []

        def write_custom(_fd, _payload, which):
            calls.append(which)
            if which == 2:
                raise controller.DeviceError("broken pipe (EPIPE)")

        result = self.run_restore(
            ["config", "restore", "--custom", "--yes", str(path)],
            backup_return=str(self.root / "prebackup"),
            write_custom_effect=write_custom,
        )

        self.assertEqual(result["code"], 1)
        self.assertEqual(calls, [1, 2])
        self.assertIn("did not respond after the 09 d0", result["err"])
        self.assertIn("docs/SAFETY.md", result["err"])
        result["read_custom"].assert_not_called()

    def test_config_restore_readback_failure_does_not_rollback(self):
        path, _files, _meta = self.make_restore_backup()
        d0_payloads = []

        def write_custom(_fd, payload, which):
            if which == 2:
                d0_payloads.append(payload)

        result = self.run_restore(
            ["config", "restore", "--custom", "--yes", str(path)],
            backup_return=str(self.root / "prebackup"),
            write_custom_effect=write_custom,
            read_custom_side_effect=controller.DeviceError("read failed"),
        )

        self.assertEqual(result["code"], 1)
        self.assertEqual(len(d0_payloads), 1)
        self.assertEqual(result["read_custom"].call_count, 1)
        self.assertIn("read-back failed", result["err"])
        self.assertIn("docs/SAFETY.md", result["err"])

    def test_config_restore_interrupt_stops_without_further_writes(self):
        path, _files, _meta = self.make_restore_backup()
        calls = []

        def write_custom(_fd, _payload, which):
            calls.append(which)
            raise KeyboardInterrupt

        result = self.run_restore(
            ["config", "restore", "--custom", "--yes", str(path)],
            backup_return=str(self.root / "prebackup"),
            write_custom_effect=write_custom,
        )

        self.assertEqual(result["code"], 130)
        self.assertEqual(calls, [1])
        self.assertIn("interrupted", result["err"])
        result["read_custom"].assert_not_called()

    def test_config_restore_verify_only_does_not_open_device(self):
        path, files, _meta = self.make_restore_backup()

        result = self.run_restore(
            ["config", "restore", "--verify-only", str(path)]
        )

        self.assertEqual(result["code"], 0)
        self.assertIn("kind: config dump", result["out"])
        self.assertIn("created: 2026-01-01T00:00:00Z", result["out"])
        self.assertIn(
            "descriptor: %s" % controller.K622_DESCRIPTOR_SHA256,
            result["out"],
        )
        self.assertIn("config-response.bin", result["out"])
        self.assertIn("verified: 4 files", result["out"])
        self.assertIn(
            state.files_manifest(files)["config-response.bin"]["sha256"],
            result["out"],
        )
        result["opener"].assert_not_called()

    def test_config_restore_verify_only_legacy_reports_unverified(self):
        path, _files, _meta = self.make_restore_backup(verified=False)

        result = self.run_restore(
            ["config", "restore", "--verify-only", str(path)]
        )

        self.assertEqual(result["code"], 1)
        self.assertIn("unverified", result["out"])
        self.assertIn("contents cannot be verified", result["err"])
        result["opener"].assert_not_called()

    def test_config_restore_verify_only_custom_requires_descriptor(self):
        path, _files, meta = self.make_restore_backup()
        del meta["descriptor_sha256"]
        (path / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

        result = self.run_restore(
            ["config", "restore", "--custom", "--verify-only", str(path)]
        )

        self.assertEqual(result["code"], 1)
        self.assertIn("descriptor_sha256", result["err"])
        result["opener"].assert_not_called()

    def test_config_restore_verify_only_allow_unverified(self):
        path, _files, _meta = self.make_restore_backup(verified=False)

        result = self.run_restore(
            [
                "config", "restore", "--verify-only", "--allow-unverified",
                str(path),
            ]
        )

        self.assertEqual(result["code"], 0)
        self.assertIn("unverified", result["out"])
        self.assertIn("--allow-unverified was given", result["err"])
        result["opener"].assert_not_called()

    def test_config_restore_allow_unverified_legacy_custom(self):
        path, files, _meta = self.make_restore_backup(verified=False)
        expected = files["custom2-response.bin"][8:]

        result = self.run_restore(
            [
                "config", "restore", "--custom", "--yes",
                "--allow-unverified", str(path),
            ],
            backup_return=str(self.root / "prebackup"),
            read_custom_return=expected,
        )

        self.assertEqual(result["code"], 0)
        self.assertIn("legacy backup has no hashes", result["err"])
        self.assertEqual(result["write_custom"].call_count, 2)
        self.assertIn("restored:", result["out"])

    def test_config_restore_custom_accepts_verified_backup(self):
        path, files, _meta = self.make_restore_backup()
        expected = files["custom2-response.bin"][8:]

        result = self.run_restore(
            ["config", "restore", "--custom", "--yes", str(path)],
            backup_return=str(self.root / "prebackup"),
            read_custom_return=expected,
        )

        self.assertEqual(result["code"], 0)
        self.assertIn("restored: %s" % path, result["out"])
        self.assertEqual(result["write_custom"].call_count, 2)
        self.assertEqual(
            result["write_custom"].call_args_list[0].args[2], 1
        )
        self.assertEqual(
            result["write_custom"].call_args_list[1].args[2], 2
        )

    def test_config_restore_plain_directory_still_works(self):
        path, _files, _meta = self.make_restore_backup(
            name="plain-backup", custom=False
        )

        result = self.run_restore(["config", "restore", str(path)])

        self.assertEqual(result["code"], 0)
        self.assertEqual(result["write_config"].call_count, 1)
        result["write_custom"].assert_not_called()
        self.assertIn("restored: %s" % path, result["out"])

    def test_config_restore_plain_single_file_still_works(self):
        path = self.root / "config.bin"
        path.write_bytes(self.make_config_block())

        result = self.run_restore(["config", "restore", str(path)])

        self.assertEqual(result["code"], 0)
        self.assertEqual(result["write_config"].call_count, 1)
        result["write_palette"].assert_not_called()
        result["write_custom"].assert_not_called()
        self.assertIn("restored: %s" % path, result["out"])

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

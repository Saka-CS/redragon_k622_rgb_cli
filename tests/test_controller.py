import errno
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from k622rgb import controller

K622_ID = "0003:0000258A:00000049"
OTHER_ID = "0003:0000046D:0000C548"


class FakeSysfs:
    """Builds a fake /sys/class/hidraw tree for discovery tests."""

    def __init__(self, root):
        self.root = Path(root)
        self.sysfs_root = self.root / "sys"
        self.dev_root = self.root / "dev"
        self.dev_root.mkdir(parents=True, exist_ok=True)

    def add(
        self,
        name,
        hid_id=K622_ID,
        interface="01",
        levels=1,
        write_uevent=True,
    ):
        device = self.sysfs_root / "class" / "hidraw" / name / "device"
        device.mkdir(parents=True, exist_ok=True)
        if write_uevent:
            (device / "uevent").write_text(
                "DRIVER=hid-generic\n"
                "HID_ID=%s\n"
                "HID_NAME=BY Tech Gaming Keyboard\n" % hid_id,
                encoding="utf-8",
            )
        if interface is not None:
            parent = device
            for _ in range(levels):
                parent = parent.parent
            (parent / "bInterfaceNumber").write_text(
                interface + "\n", encoding="utf-8"
            )
        return device

    def find(self):
        return controller.find_device(
            sysfs_root=str(self.sysfs_root), dev_root=str(self.dev_root)
        )

    def devices(self):
        return controller.iter_devices(
            sysfs_root=str(self.sysfs_root), dev_root=str(self.dev_root)
        )


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fake = FakeSysfs(self.tmp.name)

    def test_finds_control_interface(self):
        self.fake.add("hidraw5", interface="00")
        self.fake.add("hidraw6", interface="01")
        node = self.fake.find()
        self.assertEqual(os.path.basename(node), "hidraw6")
        self.assertEqual(node, str(self.fake.dev_root / "hidraw6"))

    def test_ignores_other_vendors(self):
        self.fake.add("hidraw3", hid_id=OTHER_ID, interface="01")
        with self.assertRaises(controller.DeviceNotFound):
            self.fake.find()

    def test_no_control_interface_is_an_error(self):
        self.fake.add("hidraw5", interface="00")
        with self.assertRaises(controller.DeviceNotFound) as ctx:
            self.fake.find()
        self.assertIn("control interface", str(ctx.exception))

    def test_never_falls_back_to_keyboard_interface(self):
        self.fake.add("hidraw5", interface="00")
        with self.assertRaises(controller.DeviceNotFound):
            self.fake.find()

    def test_unknown_interface_single_candidate_is_accepted(self):
        self.fake.add("hidraw6", interface=None)
        self.assertEqual(os.path.basename(self.fake.find()), "hidraw6")

    def test_multiple_control_interfaces_require_device_flag(self):
        self.fake.add("hidraw6", interface="01")
        self.fake.add("hidraw9", interface="01")
        with self.assertRaises(controller.MultipleDevices) as ctx:
            self.fake.find()
        message = str(ctx.exception)
        self.assertIn("hidraw6", message)
        self.assertIn("hidraw9", message)
        self.assertIn("--device", message)

    def test_missing_uevent_is_skipped(self):
        self.fake.add("hidraw6", write_uevent=False)
        with self.assertRaises(controller.DeviceNotFound):
            self.fake.find()

    def test_lowercase_uevent_matches(self):
        self.fake.add("hidraw6", hid_id=K622_ID.lower(), interface="01")
        self.assertEqual(os.path.basename(self.fake.find()), "hidraw6")

    def test_interface_walk_crosses_multiple_levels(self):
        self.fake.add("hidraw6", interface="01", levels=2)
        self.assertEqual(os.path.basename(self.fake.find()), "hidraw6")

    def test_iter_devices_reports_both_interfaces(self):
        self.fake.add("hidraw5", interface="00")
        self.fake.add("hidraw6", interface="01")
        devices = self.fake.devices()
        self.assertEqual([d.interface for d in devices], ["00", "01"])
        self.assertTrue(all(d.hid_id == "0003:0000258A:00000049" for d in devices))

    def test_empty_sysfs_raises(self):
        with self.assertRaises(controller.DeviceNotFound):
            self.fake.find()


class DescriptorLoadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.device = Path(self.tmp.name) / "hidraw6" / "device"
        self.device.mkdir(parents=True)

    def test_loads_descriptor_from_sysfs(self):
        payload = b"\x06\x01\x00"
        (self.device / "report_descriptor").write_bytes(payload)
        self.assertEqual(
            controller.load_descriptor(str(self.device.parent)), payload
        )

    def test_missing_descriptor_is_a_device_error(self):
        with self.assertRaises(controller.DeviceError) as ctx:
            controller.load_descriptor(str(self.device.parent))
        self.assertIn("report_descriptor", str(ctx.exception))

    def test_empty_descriptor_is_a_device_error(self):
        (self.device / "report_descriptor").write_bytes(b"")
        with self.assertRaises(controller.DeviceError) as ctx:
            controller.load_descriptor(str(self.device.parent))
        self.assertIn("empty", str(ctx.exception))

    def test_sysfs_dir_for_node(self):
        self.assertEqual(
            controller.sysfs_dir_for_node("/dev/hidraw6", sysfs_root="/sys"),
            "/sys/class/hidraw/hidraw6",
        )
        self.assertEqual(
            controller.descriptor_path("/sys/class/hidraw/hidraw6"),
            "/sys/class/hidraw/hidraw6/device/report_descriptor",
        )


class IoctlNumberTests(unittest.TestCase):
    def test_getfeature_ioctl_for_1032_bytes(self):
        self.assertEqual(controller.hidiocgfeature(1032), 0xC4084807)

    def test_getfeature_ioctl_for_six_bytes(self):
        self.assertEqual(controller.hidiocgfeature(6), 0xC0064807)

    def test_size_field_round_trips(self):
        for length in (1, 6, 64, 1032):
            with self.subTest(length=length):
                number = controller.hidiocgfeature(length)
                self.assertEqual((number >> 16) & 0x3FFF, length)
                self.assertEqual(chr((number >> 8) & 0xFF), "H")
                self.assertEqual(number & 0xFF, 0x07)
                self.assertEqual(number >> 30, 3)

    def test_rejects_invalid_lengths(self):
        for length in (0, -1, 0x4000, 1.5, "1032", True):
            with self.subTest(length=length):
                with self.assertRaises(ValueError):
                    controller.hidiocgfeature(length)

    def test_setfeature_ioctl_for_1032_bytes(self):
        self.assertEqual(controller.hidiocsfeature(1032), 0xC4084806)

    def test_setfeature_ioctl_for_six_bytes(self):
        self.assertEqual(controller.hidiocsfeature(6), 0xC0064806)

    def test_setfeature_size_field_round_trips(self):
        for length in (1, 6, 64, 1032):
            with self.subTest(length=length):
                number = controller.hidiocsfeature(length)
                self.assertEqual((number >> 16) & 0x3FFF, length)
                self.assertEqual(chr((number >> 8) & 0xFF), "H")
                self.assertEqual(number & 0xFF, 0x06)
                self.assertEqual(number >> 30, 3)

    def test_setfeature_rejects_invalid_lengths(self):
        for length in (0, -1, 0x4000, 1.5, "1032", True):
            with self.subTest(length=length):
                with self.assertRaises(ValueError):
                    controller.hidiocsfeature(length)


class WriteFeatureTests(unittest.TestCase):
    def setUp(self):
        controller.load_color_template.cache_clear()
        self.addCleanup(controller.load_color_template.cache_clear)
        self.packet = controller.build_color_packet({0: (255, 0, 0)})

    def test_sends_the_captured_lighting_frame(self):
        with mock.patch(
            "k622rgb.controller.fcntl.ioctl", return_value=1032
        ) as ioctl:
            result = controller.write_feature(7, self.packet)
        self.assertEqual(result, 1032)
        args = ioctl.call_args.args
        self.assertEqual(args[0], 7)
        self.assertEqual(args[1], controller.hidiocsfeature(1032))
        # Must be a writable buffer: fcntl rejects immutable bytes > 1024.
        self.assertIsInstance(args[2], bytearray)
        self.assertEqual(bytes(args[2]), self.packet)

    def test_write_uses_a_buffer_above_the_fcntl_bytes_limit(self):
        with mock.patch(
            "k622rgb.controller.fcntl.ioctl", return_value=1032
        ) as ioctl:
            controller.write_feature(7, self.packet)
        buffer = ioctl.call_args.args[2]
        self.assertGreater(len(buffer), 1024)
        self.assertNotIsInstance(buffer, bytes)

    def test_accepts_zero_return_value(self):
        with mock.patch("k622rgb.controller.fcntl.ioctl", return_value=0):
            self.assertEqual(controller.write_feature(7, self.packet), 0)

    def test_rejects_wrong_report_id_before_ioctl(self):
        bad = bytearray(self.packet)
        bad[0] = 0x08
        with mock.patch("k622rgb.controller.fcntl.ioctl") as ioctl:
            with self.assertRaises(controller.ProtocolError):
                controller.write_feature(7, bytes(bad))
        ioctl.assert_not_called()

    def test_rejects_latch_header_before_ioctl(self):
        bad = bytearray(self.packet)
        bad[2] = 0xD0
        with mock.patch("k622rgb.controller.fcntl.ioctl") as ioctl:
            with self.assertRaises(controller.ProtocolError):
                controller.write_feature(7, bytes(bad))
        ioctl.assert_not_called()

    def test_rejects_modified_tail_before_ioctl(self):
        bad = bytearray(self.packet)
        bad[388] = 0
        with mock.patch("k622rgb.controller.fcntl.ioctl") as ioctl:
            with self.assertRaises(controller.ProtocolError):
                controller.write_feature(7, bytes(bad))
        ioctl.assert_not_called()

    def test_rejects_short_packet_before_ioctl(self):
        with mock.patch("k622rgb.controller.fcntl.ioctl") as ioctl:
            with self.assertRaises(controller.ProtocolError):
                controller.write_feature(7, self.packet[:382])
        ioctl.assert_not_called()

    def test_eacces_is_permission_error(self):
        error = OSError(errno.EACCES, "Permission denied")
        with mock.patch("k622rgb.controller.fcntl.ioctl", side_effect=error):
            with self.assertRaises(controller.PermissionDenied):
                controller.write_feature(7, self.packet)

    def test_einval_is_protocol_error(self):
        error = OSError(errno.EINVAL, "Invalid argument")
        with mock.patch("k622rgb.controller.fcntl.ioctl", side_effect=error):
            with self.assertRaises(controller.ProtocolError) as ctx:
                controller.write_feature(7, self.packet)
        self.assertIn("EINVAL", str(ctx.exception))

    def test_epipe_is_protocol_error(self):
        error = OSError(errno.EPIPE, "Broken pipe")
        with mock.patch("k622rgb.controller.fcntl.ioctl", side_effect=error):
            with self.assertRaises(controller.ProtocolError) as ctx:
                controller.write_feature(7, self.packet)
        self.assertIn("stalled", str(ctx.exception))

    def test_timeout_is_protocol_error(self):
        error = OSError(errno.ETIMEDOUT, "Timed out")
        with mock.patch("k622rgb.controller.fcntl.ioctl", side_effect=error):
            with self.assertRaises(controller.ProtocolError) as ctx:
                controller.write_feature(7, self.packet)
        self.assertIn("Timed out", str(ctx.exception))

    def test_disconnect_is_a_device_error(self):
        error = OSError(errno.ENODEV, "No such device")
        with mock.patch("k622rgb.controller.fcntl.ioctl", side_effect=error):
            with self.assertRaises(controller.DeviceError) as ctx:
                controller.write_feature(7, self.packet)
        self.assertNotIsInstance(ctx.exception, controller.ProtocolError)
        self.assertIn("disconnected", str(ctx.exception))

    def test_busy_is_a_device_error(self):
        error = OSError(errno.EBUSY, "Device or resource busy")
        with mock.patch("k622rgb.controller.fcntl.ioctl", side_effect=error):
            with self.assertRaises(controller.DeviceError) as ctx:
                controller.write_feature(7, self.packet)
        self.assertIn("busy", str(ctx.exception))

    def test_unknown_errno_is_protocol_error(self):
        error = OSError(errno.EIO, "I/O error")
        with mock.patch("k622rgb.controller.fcntl.ioctl", side_effect=error):
            with self.assertRaises(controller.ProtocolError):
                controller.write_feature(7, self.packet)


class ReadFeatureTests(unittest.TestCase):
    def _fake_ioctl(self, payload_size, report_id=0x06, returned_id=None):
        captured = {}

        def fake_ioctl(fd, request, buffer):
            captured["fd"] = fd
            captured["request"] = request
            captured["length"] = len(buffer)
            captured["report"] = buffer[0]
            buffer[1:] = bytes(payload_size)
            if returned_id is not None:
                buffer[0] = returned_id
            return len(buffer)

        return fake_ioctl, captured

    def test_reads_report_six(self):
        fake, captured = self._fake_ioctl(1031)
        with mock.patch("k622rgb.controller.fcntl.ioctl", side_effect=fake):
            result = controller.read_feature(7, 0x06, 1031)
        self.assertEqual(captured["fd"], 7)
        self.assertEqual(captured["request"], 0xC4084807)
        self.assertEqual(captured["length"], 1032)
        self.assertEqual(captured["report"], 0x06)
        self.assertEqual(len(result), 1032)
        self.assertEqual(result[0], 0x06)

    def test_reads_report_five(self):
        fake, captured = self._fake_ioctl(5, report_id=0x05)
        with mock.patch("k622rgb.controller.fcntl.ioctl", side_effect=fake):
            result = controller.read_feature(7, 0x05, 5)
        self.assertEqual(captured["request"], 0xC0064807)
        self.assertEqual(len(result), 6)
        self.assertEqual(result, bytes((0x05, 0, 0, 0, 0, 0)))

    def test_rejects_wrong_returned_report_id(self):
        fake, _captured = self._fake_ioctl(5, report_id=0x06, returned_id=0x07)
        with mock.patch("k622rgb.controller.fcntl.ioctl", side_effect=fake):
            with self.assertRaises(controller.ProtocolError) as ctx:
                controller.read_feature(7, 0x06, 5)
        self.assertIn("report ID", str(ctx.exception))

    def test_rejects_short_response(self):
        with mock.patch(
            "k622rgb.controller.fcntl.ioctl", return_value=1031
        ):
            with self.assertRaises(controller.ProtocolError) as ctx:
                controller.read_feature(7, 0x06, 1031)
        self.assertIn("expected 1032", str(ctx.exception))

    def test_rejects_bad_arguments_before_ioctl(self):
        with mock.patch("k622rgb.controller.fcntl.ioctl") as ioctl:
            for args in ((7, 0x00, 5), (7, 0x100, 5), (7, 0x06, 0),
                         (7, 0x06, -1), (7, True, 5)):
                with self.subTest(args=args):
                    with self.assertRaises(ValueError):
                        controller.read_feature(*args)
        ioctl.assert_not_called()

    def test_einval_is_protocol_error(self):
        error = OSError(errno.EINVAL, "Invalid argument")
        with mock.patch("k622rgb.controller.fcntl.ioctl", side_effect=error):
            with self.assertRaises(controller.ProtocolError) as ctx:
                controller.read_feature(7, 0x06, 1031)
        self.assertIn("EINVAL", str(ctx.exception))
        self.assertIn("do not guess", str(ctx.exception))

    def test_epipe_is_protocol_error(self):
        error = OSError(errno.EPIPE, "Broken pipe")
        with mock.patch("k622rgb.controller.fcntl.ioctl", side_effect=error):
            with self.assertRaises(controller.ProtocolError) as ctx:
                controller.read_feature(7, 0x06, 1031)
        self.assertIn("stalled", str(ctx.exception))

    def test_timeout_is_protocol_error(self):
        error = OSError(errno.ETIMEDOUT, "Timed out")
        with mock.patch("k622rgb.controller.fcntl.ioctl", side_effect=error):
            with self.assertRaises(controller.ProtocolError) as ctx:
                controller.read_feature(7, 0x06, 1031)
        self.assertIn("Timed out", str(ctx.exception))

    def test_eacces_is_permission_error(self):
        error = OSError(errno.EACCES, "Permission denied")
        with mock.patch("k622rgb.controller.fcntl.ioctl", side_effect=error):
            with self.assertRaises(controller.PermissionDenied):
                controller.read_feature(7, 0x06, 1031)

    def test_disconnect_is_not_a_protocol_error(self):
        error = OSError(errno.ENODEV, "No such device")
        with mock.patch("k622rgb.controller.fcntl.ioctl", side_effect=error):
            with self.assertRaises(controller.DeviceError) as ctx:
                controller.read_feature(7, 0x06, 1031)
        self.assertNotIsInstance(ctx.exception, controller.ProtocolError)
        self.assertIn("disconnected", str(ctx.exception))

    def test_enotty_is_a_device_error(self):
        error = OSError(errno.ENOTTY, "Inappropriate ioctl")
        with mock.patch("k622rgb.controller.fcntl.ioctl", side_effect=error):
            with self.assertRaises(controller.DeviceError) as ctx:
                controller.read_feature(7, 0x06, 1031)
        self.assertIn("hidraw", str(ctx.exception))

    def test_unknown_errno_is_protocol_error(self):
        error = OSError(errno.EIO, "I/O error")
        with mock.patch("k622rgb.controller.fcntl.ioctl", side_effect=error):
            with self.assertRaises(controller.ProtocolError):
                controller.read_feature(7, 0x06, 1031)


class CustomFrameWriteTests(unittest.TestCase):
    def setUp(self):
        self.payload = bytes(range(256)) * 4

    def test_write_custom_frame_rejects_d0_before_ioctl(self):
        with mock.patch("k622rgb.controller.fcntl.ioctl") as ioctl:
            with self.assertRaises(ValueError) as ctx:
                controller.write_custom_frame(7, self.payload, 2)
        ioctl.assert_not_called()
        self.assertIn("restore_custom_frame", str(ctx.exception))
        self.assertIn("09 d0", str(ctx.exception))

    def test_write_custom_frame_sends_the_09_cc_packet(self):
        with mock.patch(
            "k622rgb.controller.fcntl.ioctl", return_value=1032
        ) as ioctl:
            result = controller.write_custom_frame(7, self.payload, 1)
        self.assertEqual(result, 1032)
        args = ioctl.call_args.args
        self.assertEqual(args[0], 7)
        self.assertEqual(args[1], controller.hidiocsfeature(1032))
        self.assertEqual(
            bytes(args[2]), controller.build_custom_packet(self.payload, 1)
        )
        self.assertEqual(bytes(args[2])[:4], bytes.fromhex("06 09 cc 00"))

    def test_restore_custom_frame_sends_the_09_d0_packet(self):
        with mock.patch(
            "k622rgb.controller.fcntl.ioctl", return_value=1032
        ) as ioctl:
            result = controller.restore_custom_frame(7, self.payload)
        self.assertEqual(result, 1032)
        args = ioctl.call_args.args
        self.assertEqual(args[1], controller.hidiocsfeature(1032))
        self.assertEqual(
            bytes(args[2]), controller.build_custom_packet(self.payload, 2)
        )
        self.assertEqual(bytes(args[2])[:4], bytes.fromhex("06 09 d0 00"))

    def test_restore_custom_frame_maps_write_errors(self):
        error = OSError(errno.EACCES, "Permission denied")
        with mock.patch("k622rgb.controller.fcntl.ioctl", side_effect=error):
            with self.assertRaises(controller.PermissionDenied):
                controller.restore_custom_frame(7, self.payload)


class OpenDeviceTests(unittest.TestCase):
    def test_opens_read_only_by_default(self):
        with mock.patch("k622rgb.controller.os.open", return_value=9) as opener:
            self.assertEqual(controller.open_device("/dev/hidraw6"), 9)
        opener.assert_called_once_with("/dev/hidraw6", os.O_RDONLY)

    def test_can_open_read_write(self):
        with mock.patch("k622rgb.controller.os.open", return_value=9) as opener:
            self.assertEqual(controller.open_device("/dev/hidraw6", writable=True), 9)
        opener.assert_called_once_with("/dev/hidraw6", os.O_RDWR)

    def test_permission_denied_has_hints(self):
        error = OSError(errno.EACCES, "Permission denied")
        with mock.patch("k622rgb.controller.os.open", side_effect=error):
            with self.assertRaises(controller.PermissionDenied) as ctx:
                controller.open_device("/dev/hidraw6")
        message = str(ctx.exception)
        self.assertIn("udev", message)
        self.assertIn("chmod 666", message)
        self.assertIn("sudo", message)

    def test_missing_node(self):
        error = OSError(errno.ENOENT, "No such file or directory")
        with mock.patch("k622rgb.controller.os.open", side_effect=error):
            with self.assertRaises(controller.DeviceNotFound):
                controller.open_device("/dev/hidraw6")

    def test_busy_node(self):
        error = OSError(errno.EBUSY, "Device or resource busy")
        with mock.patch("k622rgb.controller.os.open", side_effect=error):
            with self.assertRaises(controller.DeviceError) as ctx:
                controller.open_device("/dev/hidraw6")
        self.assertIn("busy", str(ctx.exception))

    def test_rejects_empty_path(self):
        with self.assertRaises(ValueError):
            controller.open_device("")


if __name__ == "__main__":
    unittest.main()

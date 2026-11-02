import os
import tempfile
import unittest
from unittest import mock

from k622rgb import controller

RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)


class TemplateTests(unittest.TestCase):
    def setUp(self):
        controller.load_color_template.cache_clear()
        self.addCleanup(controller.load_color_template.cache_clear)

    def test_template_is_the_captured_all_off_frame(self):
        template = controller.load_color_template()
        self.assertEqual(len(template), 1032)
        self.assertEqual(len(template), controller.COLOR_TEMPLATE_SIZE)
        self.assertEqual(template[:8], controller.COLOR_PACKET_HEADER)
        self.assertEqual(
            controller.descriptor_sha256(template),
            controller.COLOR_TEMPLATE_SHA256,
        )
        self.assertEqual(template[8:386], bytes(378))
        self.assertNotEqual(template[386:], bytes(len(template) - 386))

    def test_header_is_the_captured_lighting_header(self):
        self.assertEqual(
            controller.COLOR_PACKET_HEADER,
            bytes.fromhex("06 09 cc 00 40 00 00 00"),
        )
        self.assertEqual(controller.COLOR_REPORT_ID, 0x06)
        self.assertEqual(controller.COLOR_PLANE_BASES, (8, 134, 260))
        self.assertEqual(controller.COLOR_REGION_START, 8)
        self.assertEqual(controller.COLOR_REGION_END, 386)

    def test_corrupt_template_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "template_color.bin")
            with open(path, "wb") as handle:
                handle.write(bytes(1032))
            with mock.patch(
                "k622rgb.controller._data_path", return_value=path
            ):
                with self.assertRaises(controller.ProtocolError) as ctx:
                    controller.load_color_template()
        self.assertIn("sha256", str(ctx.exception))

    def test_short_template_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "template_color.bin")
            with open(path, "wb") as handle:
                handle.write(b"\x06\x09\xcc")
            with mock.patch(
                "k622rgb.controller._data_path", return_value=path
            ):
                with self.assertRaises(controller.ProtocolError) as ctx:
                    controller.load_color_template()
        self.assertIn("expected 1032", str(ctx.exception))

    def test_missing_template_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "missing.bin")
            with mock.patch(
                "k622rgb.controller._data_path", return_value=path
            ):
                with self.assertRaises(controller.ProtocolError) as ctx:
                    controller.load_color_template()
        self.assertIn("cannot read", str(ctx.exception))


class BuildColorPacketTests(unittest.TestCase):
    def setUp(self):
        controller.load_color_template.cache_clear()
        self.addCleanup(controller.load_color_template.cache_clear)
        self.template = controller.load_color_template()

    def test_no_colors_is_the_template(self):
        self.assertEqual(controller.build_color_packet(), self.template)
        self.assertEqual(controller.build_color_packet({}), self.template)

    def test_red_at_esc_uses_the_red_plane(self):
        packet = controller.build_color_packet({0: RED})
        self.assertEqual(packet[8], 255)
        self.assertEqual(packet[134], 0)
        self.assertEqual(packet[260], 0)
        self.assertEqual(packet[9], 0)

    def test_green_at_one_uses_the_green_plane(self):
        packet = controller.build_color_packet({7: GREEN})
        self.assertEqual(packet[8 + 7], 0)
        self.assertEqual(packet[134 + 7], 255)
        self.assertEqual(packet[260 + 7], 0)

    def test_blue_at_right_uses_the_blue_plane(self):
        packet = controller.build_color_packet({101: BLUE})
        self.assertEqual(packet[8 + 101], 0)
        self.assertEqual(packet[134 + 101], 0)
        self.assertEqual(packet[260 + 101], 255)

    def test_all_three_channels_are_independent(self):
        packet = controller.build_color_packet({100: (1, 2, 3)})
        self.assertEqual(packet[8 + 100], 1)
        self.assertEqual(packet[134 + 100], 2)
        self.assertEqual(packet[260 + 100], 3)

    def test_header_and_tail_are_preserved(self):
        packet = controller.build_color_packet({0: RED, 125: BLUE})
        self.assertEqual(packet[:8], self.template[:8])
        self.assertEqual(packet[386:], self.template[386:])

    def test_invalid_slots_are_rejected(self):
        for slot in (-1, 126, 1000):
            with self.subTest(slot=slot):
                with self.assertRaises(ValueError):
                    controller.build_color_packet({slot: RED})

    def test_non_integer_slots_are_rejected(self):
        for slot in (True, "0", 1.0, None):
            with self.subTest(slot=slot):
                with self.assertRaises(ValueError):
                    controller.build_color_packet({slot: RED})  # type: ignore[dict-item]

    def test_invalid_colors_are_rejected(self):
        for color in ((256, 0, 0), (0, -1, 0), (0, 0, 1.5),
                      (0, 0), (0, 0, 0, 0), "red", None):
            with self.subTest(color=color):
                with self.assertRaises(ValueError):
                    controller.build_color_packet({0: color})  # type: ignore[dict-item]

    def test_boolean_channels_are_rejected(self):
        with self.assertRaises(ValueError):
            controller.build_color_packet({0: (True, 0, 0)})


class ValidatePacketTests(unittest.TestCase):
    def setUp(self):
        controller.load_color_template.cache_clear()
        self.addCleanup(controller.load_color_template.cache_clear)
        self.packet = controller.build_color_packet({0: RED})

    def test_accepts_bytes_bytearray_and_memoryview(self):
        for value in (self.packet, bytearray(self.packet), memoryview(self.packet)):
            with self.subTest(kind=type(value).__name__):
                self.assertEqual(controller.validate_color_packet(value), self.packet)

    def test_rejects_non_bytes(self):
        for value in (None, "packet", [0x06]):
            with self.subTest(value=value):
                with self.assertRaises(TypeError):
                    controller.validate_color_packet(value)

    def test_rejects_wrong_length(self):
        for value in (self.packet[:-1], self.packet + b"\x00", b""):
            with self.subTest(length=len(value)):
                with self.assertRaises(controller.ProtocolError):
                    controller.validate_color_packet(value)

    def test_rejects_latch_header(self):
        bad = bytearray(self.packet)
        bad[2] = 0xD0
        with self.assertRaises(controller.ProtocolError) as ctx:
            controller.validate_color_packet(bad)
        self.assertIn("09 d0", " ".join(str(ctx.exception).split()))

    def test_rejects_config_header(self):
        bad = bytearray(self.packet)
        bad[1:5] = bytes.fromhex("03 c6 00 00")
        with self.assertRaises(controller.ProtocolError):
            controller.validate_color_packet(bad)

    def test_rejects_report_id_eight(self):
        bad = bytearray(self.packet)
        bad[0] = 0x08
        with self.assertRaises(controller.ProtocolError):
            controller.validate_color_packet(bad)

    def test_rejects_modified_tail(self):
        bad = bytearray(self.packet)
        bad[388] = 0
        with self.assertRaises(controller.ProtocolError) as ctx:
            controller.validate_color_packet(bad)
        self.assertIn("captured template", str(ctx.exception))

    def test_rejects_modified_header_gap(self):
        bad = bytearray(self.packet)
        bad[7] = 1
        with self.assertRaises(controller.ProtocolError):
            controller.validate_color_packet(bad)

    def test_allows_any_colour_in_the_region(self):
        packet = bytearray(self.packet)
        packet[8:386] = bytes([0xA5]) * 378
        self.assertEqual(controller.validate_color_packet(packet), bytes(packet))


class ColorsFromPacketTests(unittest.TestCase):
    def setUp(self):
        controller.load_color_template.cache_clear()
        self.addCleanup(controller.load_color_template.cache_clear)

    def test_round_trip(self):
        colors = {0: (1, 2, 3), 7: GREEN, 101: BLUE, 125: (10, 20, 30)}
        packet = controller.build_color_packet(colors)
        extracted = controller.colors_from_packet(packet)
        self.assertEqual(len(extracted), 126)
        for slot in range(126):
            with self.subTest(slot=slot):
                self.assertEqual(extracted[slot], colors.get(slot, (0, 0, 0)))

    def test_rejects_invalid_packet(self):
        with self.assertRaises(controller.ProtocolError):
            controller.colors_from_packet(b"\x06\x09\xcc")

    def test_lit_slots(self):
        colors = {0: RED, 7: GREEN, 101: BLUE}
        self.assertEqual(controller.lit_slots(colors), [0, 7, 101])
        self.assertEqual(controller.lit_slots({}), [])
        self.assertEqual(controller.lit_slots({6: (0, 0, 0)}), [])


class GameFlagTests(unittest.TestCase):
    def test_default_offset_is_the_first_payload_byte(self):
        payload = bytes(controller.CUSTOM_PAYLOAD_SIZE)
        self.assertEqual(controller.read_game_flag(payload), 0)
        modified = controller.set_game_flag(payload)
        self.assertEqual(modified[controller.GAME_FLAG_OFFSET], 1)
        self.assertEqual(controller.read_game_flag(modified), 1)

    def test_sets_and_clears_a_custom_offset(self):
        payload = bytes(controller.CUSTOM_PAYLOAD_SIZE)
        modified = controller.set_game_flag(payload, 0x5A, 17)
        self.assertEqual(modified[17], 0x5A)
        self.assertEqual(modified[:17], payload[:17])
        self.assertEqual(modified[18:], payload[18:])
        self.assertEqual(controller.read_game_flag(modified, 17), 0x5A)
        cleared = controller.set_game_flag(modified, controller.GAME_FLAG_OFF, 17)
        self.assertEqual(cleared[17], 0)

    def test_rejects_wrong_payload_length(self):
        for payload in (b"", bytes(1023), bytes(1025)):
            with self.subTest(length=len(payload)):
                with self.assertRaises(controller.ConfigError):
                    controller.set_game_flag(payload)

    def test_rejects_non_bytes(self):
        with self.assertRaises(TypeError):
            controller.set_game_flag([0] * controller.CUSTOM_PAYLOAD_SIZE)

    def test_rejects_out_of_range_offset_or_value(self):
        payload = bytes(controller.CUSTOM_PAYLOAD_SIZE)
        for offset in (-1, controller.CUSTOM_PAYLOAD_SIZE):
            with self.subTest(offset=offset):
                with self.assertRaises(ValueError):
                    controller.set_game_flag(payload, 1, offset)
        for value in (-1, 256):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    controller.set_game_flag(payload, value, 0)

    def test_custom_packet_uses_the_modified_payload(self):
        payload = controller.set_game_flag(
            bytes(controller.CUSTOM_PAYLOAD_SIZE), 1, 3
        )
        packet = controller.build_custom_packet(payload, 2)
        self.assertEqual(packet[:8], controller.CUSTOM_HEADERS[2])
        self.assertEqual(packet[8], 0)
        self.assertEqual(packet[11], 1)
        self.assertEqual(packet[8:], payload)


if __name__ == "__main__":
    unittest.main()

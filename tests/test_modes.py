"""Tests for the K622 mode/config protocol (no hardware)."""

import contextlib
import io
import os
import tempfile
import unittest

from k622rgb import cli, controller


def base_config(mode=21, per_key=True):
    """Build a synthetic config with the captured K622 markers."""
    config = bytearray(controller.CONFIG_SIZE)
    config[0x08:0x0C] = b"\x03\x03\x00\x00"
    config[controller.CONFIG_PER_KEY_INDEX] = 1 if per_key else 0
    config[controller.CONFIG_MODE_INDEX] = mode
    config[0x14:0x16] = b"\x55\x55"
    config[0x1C:0x1E] = b"\xff\xff"
    for index in range(controller.CONFIG_PAIR_COUNT):
        base = controller.CONFIG_PAIR_BASE + index * 2
        config[base] = controller.COLOR_RANDOM
        config[base + 1] = 0x39
    config[
        controller.CONFIG_TRAILER_INDEX:
        controller.CONFIG_TRAILER_INDEX + 2
    ] = controller.CONFIG_TRAILER
    config[0x81:0x83] = b"\x5a\xa5"
    config[0x86:0x88] = b"\x03\x03"
    return bytes(config)


def base_palette():
    palette = bytearray(controller.COLOR_TABLE_SIZE)
    for mode in range(1, 21):
        for index in range(7):
            base = mode * controller.COLOR_BLOCK_SIZE + index * 3
            palette[base:base + 3] = bytes((index * 10, mode, 255 - index))
    return bytes(palette)


class ModeTableTests(unittest.TestCase):
    def test_mode_ids_are_complete(self):
        values = [mode.value for mode in controller.MODES]
        self.assertEqual(values, list(range(0, 22)))
        self.assertEqual(len(set(values)), len(values))

    def test_names_and_aliases(self):
        self.assertEqual(controller.lookup_mode("rainbow").value, 3)
        self.assertEqual(controller.lookup_mode("Rainbow").value, 3)
        self.assertEqual(controller.lookup_mode("breathing").value, 2)
        self.assertEqual(controller.lookup_mode("per-key").value, 21)
        self.assertEqual(controller.lookup_mode("off").value, 0)
        self.assertEqual(controller.lookup_mode("3").value, 3)
        self.assertEqual(controller.lookup_mode(20).value, 20)
        with self.assertRaises(ValueError):
            controller.lookup_mode("not-a-mode")
        with self.assertRaises(ValueError):
            controller.lookup_mode(22)

    def test_parameter_flags_match_cfg(self):
        self.assertFalse(controller.lookup_mode("static").speed)
        self.assertTrue(controller.lookup_mode("static").brightness)
        self.assertTrue(controller.lookup_mode("static").color)
        self.assertFalse(controller.lookup_mode("rainbow").color)
        self.assertFalse(controller.lookup_mode("rainbow").random)
        self.assertFalse(controller.lookup_mode("per-key").brightness)


class ConfigTests(unittest.TestCase):
    def test_parse_and_roundtrip(self):
        config = base_config()
        state = controller.parse_config(config)
        self.assertEqual(state.mode, 21)
        self.assertTrue(state.per_key)
        self.assertEqual(state.raw, config)
        self.assertEqual(state.params("rainbow").color, controller.COLOR_RANDOM)
        self.assertEqual(state.params("rainbow").speed, 3)
        self.assertEqual(state.params("rainbow").brightness, 9)

    def test_build_mode_and_parameters(self):
        config = controller.build_config(
            base_config(),
            mode="rainbow",
            brightness=4,
            speed=1,
        )
        state = controller.parse_config(config)
        self.assertEqual(state.mode, 3)
        self.assertFalse(state.per_key)
        params = state.params("rainbow")
        self.assertEqual(params.brightness, 4)
        self.assertEqual(params.speed, 1)
        self.assertEqual(params.color, controller.COLOR_RANDOM)

    def test_build_per_key(self):
        config = controller.build_config(base_config(mode=3, per_key=False),
                                         mode="per-key")
        state = controller.parse_config(config)
        self.assertEqual(state.mode, 21)
        self.assertTrue(state.per_key)

    def test_colour_validation(self):
        with self.assertRaises(ValueError):
            controller.build_config(base_config(), mode=3, color=0)
        with self.assertRaises(ValueError):
            controller.build_config(base_config(), mode=1, color=8)
        with self.assertRaises(ValueError):
            controller.build_config(base_config(), mode=1, speed=5)
        with self.assertRaises(ValueError):
            controller.build_config(base_config(), mode=1, brightness=10)

    def test_validate_rejects_bad_markers(self):
        config = bytearray(base_config())
        config[controller.CONFIG_TRAILER_INDEX] = 0
        config[controller.CONFIG_TRAILER_INDEX_ALT] = 0
        with self.assertRaises(controller.ConfigError):
            controller.validate_config(bytes(config))

    def test_factory_default_marker_layout(self):
        config = bytearray(base_config())
        config[controller.CONFIG_TRAILER_INDEX] = 0
        config[controller.CONFIG_TRAILER_INDEX + 1] = 0
        config[controller.CONFIG_TRAILER_INDEX_ALT:
               controller.CONFIG_TRAILER_INDEX_ALT + 2] = b"\x5a\xa5"
        self.assertEqual(controller.validate_config(bytes(config)), bytes(config))
        with self.assertRaises(controller.ConfigError):
            controller.validate_config(base_config()[:100])

    def test_config_packet_shape(self):
        packet = controller.build_config_packet(base_config())
        self.assertEqual(len(packet), controller.PACKET_SIZE)
        self.assertEqual(packet[:8], controller.CONFIG_WRITE_HEADER)
        self.assertEqual(
            packet[8:8 + controller.CONFIG_SIZE], base_config()
        )
        self.assertFalse(any(packet[8 + controller.CONFIG_SIZE:]))


class PaletteTests(unittest.TestCase):
    def test_palette_roundtrip(self):
        palette = base_palette()
        self.assertEqual(
            controller.palette_color(palette, 1, 0),
            (0, 1, 255),
        )
        self.assertEqual(
            controller.palette_color(palette, 20, 6),
            (60, 20, 249),
        )

    def test_set_palette_color(self):
        palette = base_palette()
        updated = controller.set_palette_color(palette, 3, 2, (1, 2, 3))
        self.assertEqual(controller.palette_color(updated, 3, 2), (1, 2, 3))
        # neighbouring entries are untouched
        self.assertEqual(
            controller.palette_color(updated, 3, 1),
            controller.palette_color(palette, 3, 1),
        )
        self.assertEqual(
            controller.palette_color(updated, 4, 2),
            controller.palette_color(palette, 4, 2),
        )

    def test_palette_packet_shape(self):
        packet = controller.build_effect_palette_packet(base_palette())
        self.assertEqual(len(packet), controller.PACKET_SIZE)
        self.assertEqual(packet[:8], controller.COLOR_WRITE_HEADER)
        self.assertEqual(
            packet[8:8 + controller.COLOR_TABLE_SIZE], base_palette()
        )

    def test_custom_packet_shapes(self):
        for which, header in controller.CUSTOM_HEADERS.items():
            packet = controller.build_custom_packet(bytes(1024), which)
            self.assertEqual(len(packet), controller.PACKET_SIZE)
            self.assertEqual(packet[:8], header)
        with self.assertRaises(controller.ConfigError):
            controller.build_custom_packet(bytes(1023), 1)
        with self.assertRaises(ValueError):
            controller.build_custom_packet(bytes(1024), 3)


class CliModeTests(unittest.TestCase):
    def run_cli(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(argv)
        return code, out.getvalue()

    def test_mode_list(self):
        code, text = self.run_cli(["mode", "list"])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("Rainbow", text)
        self.assertIn("Self-define", text)
        self.assertIn("OFF", text)

    def test_mode_set_dry_run(self):
        code, text = self.run_cli([
            "mode", "set", "rainbow", "--brightness", "4",
            "--speed", "2", "--dry-run",
        ])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("mode=Rainbow (3)", text)
        self.assertIn("brightness=4", text)
        self.assertIn("speed=2", text)
        self.assertIn("device not opened", text)

    def test_mode_set_rejects_colour_for_rainbow(self):
        code, _text = self.run_cli([
            "mode", "set", "rainbow", "--color", "ff0000", "--dry-run"
        ])
        self.assertEqual(code, cli.EXIT_USAGE)

    def test_off_dry_run_needs_no_device(self):
        code, text = self.run_cli(["off", "--dry-run"])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("OFF mode", text)
        self.assertIn("device not opened", text)

    def test_config_restore_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.bin")
            with open(path, "wb") as handle:
                handle.write(base_config())
            code, text = self.run_cli(["config", "restore", path, "--dry-run"])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("would restore config", text)

    def test_set_dry_run_with_brightness(self):
        code, text = self.run_cli([
            "set", "--dry-run", "--reset", "--brightness", "4", "Esc=ffffff"
        ])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("brightness: software level 4/9", text)
        self.assertIn("packet: 1032 bytes", text)


if __name__ == "__main__":
    unittest.main()

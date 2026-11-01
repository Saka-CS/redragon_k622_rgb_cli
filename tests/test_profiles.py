"""Tests for local lighting profiles (no hardware)."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from k622rgb import cli, controller, profiles


def sample_config():
    config = bytearray(controller.CONFIG_SIZE)
    config[0x08:0x0C] = b"\x03\x03\x00\x00"
    config[controller.CONFIG_PER_KEY_INDEX] = 1
    config[controller.CONFIG_MODE_INDEX] = 21
    config[0x1C:0x1E] = b"\xff\xff"
    for index in range(controller.CONFIG_PAIR_COUNT):
        base = controller.CONFIG_PAIR_BASE + index * 2
        config[base] = 7
        config[base + 1] = 0x39
    config[0x46:0x48] = b"\x5a\xa5"
    config[0x84:0x86] = b"\x5a\xa5"
    config[0x86:0x88] = b"\x03\x03"
    return bytes(config)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name

    def test_roundtrip(self):
        config = sample_config()
        palette = bytes(range(256)) * 2
        palette = (palette + bytes(441))[:441]
        frame = bytes(range(256)) * 4
        path = profiles.save_profile(
            "gaming", config, palette, frame[:1024], self.dir
        )
        self.assertTrue(os.path.exists(path))
        entry = profiles.load_profile("gaming", self.dir)
        self.assertEqual(entry["config"], config)
        self.assertEqual(entry["palette"], palette)
        self.assertEqual(entry["custom_frame"], frame[:1024])

    def test_without_frame(self):
        profiles.save_profile("plain", sample_config(), bytes(441), None, self.dir)
        entry = profiles.load_profile("plain", self.dir)
        self.assertIsNone(entry["custom_frame"])

    def test_list_and_delete(self):
        profiles.save_profile("one", sample_config(), bytes(441), None, self.dir)
        profiles.save_profile("two", sample_config(), bytes(441), None, self.dir)
        names = [entry["name"] for entry in profiles.list_profiles(self.dir)]
        self.assertEqual(names, ["one", "two"])
        profiles.delete_profile("one", self.dir)
        self.assertEqual(
            [entry["name"] for entry in profiles.list_profiles(self.dir)],
            ["two"],
        )

    def test_invalid_name(self):
        for name in ("", " ", "../escape", "a/b", ".."):
            with self.assertRaises(profiles.ProfileError):
                profiles.profile_path(name, self.dir)

    def test_missing_profile(self):
        with self.assertRaises(profiles.ProfileError):
            profiles.load_profile("missing", self.dir)

    def test_bad_json(self):
        path = Path(self.dir) / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(profiles.ProfileError):
            profiles.load_profile("bad", self.dir)

    def test_wrong_version(self):
        path = Path(self.dir) / "old.json"
        path.write_text(json.dumps({"version": 99}), encoding="utf-8")
        with self.assertRaises(profiles.ProfileError):
            profiles.load_profile("old", self.dir)

    def test_bad_hex(self):
        path = Path(self.dir) / "hex.json"
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "config": "zz",
                    "palette": "00",
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(profiles.ProfileError):
            profiles.load_profile("hex", self.dir)

    def test_cli_list_empty(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main(["profile", "list", "--dir", self.dir])
        self.assertEqual(code, cli.EXIT_OK)
        self.assertIn("no profiles saved", out.getvalue())


if __name__ == "__main__":
    unittest.main()

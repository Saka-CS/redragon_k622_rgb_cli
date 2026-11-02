"""Tests for local named colour groups (no hardware)."""

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from k622rgb import cli, groups


def cfg_ini_text(extra_group1=""):
    """Build a small Cfg.ini with the [OPT] and [KEY] fields we parse."""
    key_lines = [
        ("Esc", 0x1B, 0),
        ("F1", 0x70, 12),
        ("F2", 0x71, 18),
        ("F3", 0x72, 24),
        ("PrtSc", 0x2C, 84),
        ("PgUp", 0x21, 97),
        ("PgDn", 0x22, 98),
        ("Home", 0x24, 91),
        ("End", 0x23, 92),
        ("1", 0x31, 7),
        ("2", 0x32, 13),
        ("3", 0x33, 19),
        ("4", 0x34, 25),
        ("5", 0x35, 31),
        ("6", 0x36, 37),
        ("7", 0x37, 43),
        ("Tab", 0x09, 2),
        ("Q", 0x51, 8),
        ("W", 0x57, 14),
        ("E", 0x45, 20),
        ("R", 0x52, 26),
        ("T", 0x54, 32),
        ("A", 0x41, 9),
        ("S", 0x53, 15),
        ("D", 0x44, 21),
        ("F", 0x46, 27),
        ("G", 0x47, 33),
        ("B", 0x42, 34),
        ("C", 0x43, 22),
        ("V", 0x56, 28),
        ("X", 0x58, 16),
        ("Space", 0x20, 35),
        ("Up", 0x26, 94),
        ("Down", 0x28, 95),
        ("Left", 0x25, 89),
        ("Right", 0x27, 101),
        ("SrcLock", 0x91, 90),
    ]
    lines = [
        "[OPT]",
        "GaoshouIndex=20",
        "GaoshouKey1=1b,57,41,53,44,26,28,25,27" + extra_group1,
        "GaoshouKey2=31,32,33,10,11,12",
        "GaoshouKey3=58,43,91",
        "GaoshouKey4=31,32,33,34,35,36,37,51,57,45,52,41,53,44,46",
        "GaoshouKey5=57,52,41,53,44,10,11,12,26,28,25,27",
        "",
        "[KEY]",
    ]
    for index, (label, vk, cfg_slot) in enumerate(key_lines, start=1):
        lines.append(";%s" % label)
        lines.append(
            "K%d=0,0,0,0, 0x02,0x%02X,0x00,%d,%d"
            % (index, vk, cfg_slot, index)
        )
    lines.append("")
    return "\n".join(lines)


class GroupModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.group_file = self.root / "groups.json"
        self.cfg_file = self.root / "Cfg.ini"
        self.cfg_file.write_text(cfg_ini_text(), encoding="utf-8")

    def test_builtins_and_aliases(self):
        effective = groups.effective_groups()
        expected = {
            "define1": ("W", "A", "S", "D"),
            "define2": ("Esc",) + tuple("F%d" % index for index in range(1, 13)),
            "define3": (
                "PrtSc", "ScrLk", "Pause",
                "Ins", "Home", "PgUp", "Del", "End", "PgDn",
                "Up", "Down", "Left", "Right",
            ),
            "define4": (
                "`", "Tab", "Caps", "LShift", "RShift",
                "LCtrl", "RCtrl", "Win", "LAlt", "RAlt",
                "Space", "Fn", "Menu", "\\", "Enter", "Bksp",
            ),
            "define5": tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") + (
                "-", "=", "[", "]", ";", "'", ",", ".", "/",
            ),
        }
        for name, keys in expected.items():
            with self.subTest(name=name):
                self.assertEqual(effective[name]["keys"], keys)
                self.assertEqual(len(keys), len(set(keys)))

        names = list(expected)
        overlaps = []
        for index, first in enumerate(names):
            for second in names[index + 1:]:
                shared = set(expected[first]) & set(expected[second])
                if shared:
                    overlaps.append((first, second, shared))
        self.assertEqual(
            overlaps,
            [("define1", "define5", {"W", "A", "S", "D"})],
        )

        self.assertEqual(effective["fps"]["keys"][:4], ("W", "A", "S", "D"))
        self.assertEqual(effective["fps"]["color"], (255, 0, 0))
        for alias in ("1", "group1", "DEFINE1"):
            self.assertEqual(groups.canonical_group_name(alias), "define1")
        self.assertIn("moba", groups.effective_groups())
        self.assertIn("mmo", groups.effective_groups())
        self.assertIn("typing", groups.effective_groups())

    def test_roundtrip_and_local_override(self):
        local = {}
        groups.update_local_group(local, "fps", (1, 2, 3))
        groups.update_local_group(
            local, "custom", (4, 5, 6), ["W", "Escape", "w"]
        )
        path = groups.save_local_groups(local, str(self.group_file))
        self.assertTrue(os.path.exists(path))

        loaded = groups.load_local_groups(str(self.group_file))
        self.assertEqual(loaded["fps"]["color"], (1, 2, 3))
        self.assertEqual(loaded["fps"]["keys"][:3], ("W", "A", "S"))
        self.assertEqual(loaded["custom"]["keys"], ("W", "Esc"))
        effective = groups.effective_groups(loaded)
        self.assertEqual(effective["fps"]["color"], (1, 2, 3))
        self.assertEqual(effective["custom"]["keys"], ("W", "Esc"))

        payload = json.loads(self.group_file.read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], 1)
        self.assertEqual(payload["groups"]["fps"]["color"], "#010203")

    def test_update_unknown_group_without_keys_fails(self):
        with self.assertRaises(ValueError):
            groups.update_local_group({}, "missing", (1, 2, 3))

    def test_invalid_store_is_reported(self):
        cases = {
            "bad.json": "{not json",
            "version.json": json.dumps({"version": 99, "groups": {}}),
            "keys.json": json.dumps(
                {
                    "version": 1,
                    "groups": {
                        "bad": {"keys": ["Bogus"], "color": None},
                    },
                }
            ),
            "colour.json": json.dumps(
                {
                    "version": 1,
                    "groups": {
                        "bad": {"keys": ["Esc"], "color": "zzzzzz"},
                    },
                }
            ),
        }
        for filename, text in cases.items():
            with self.subTest(filename=filename):
                path = self.root / filename
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(groups.GroupError):
                    groups.load_local_groups(str(path))

    def test_parse_set_items(self):
        assignments, keys = groups.parse_set_items(["fps=red"])
        self.assertEqual(assignments, [("fps", (255, 0, 0))])
        self.assertIsNone(keys)

        assignments, keys = groups.parse_set_items(
            ["custom=#00ff00", "W", "A", "S", "D"]
        )
        self.assertEqual(assignments, [("custom", (0, 255, 0))])
        self.assertEqual(keys, ["W", "A", "S", "D"])

        assignments, keys = groups.parse_set_items(
            ["1=red", "2=green", "3=blue"]
        )
        self.assertEqual(
            assignments,
            [
                ("define1", (255, 0, 0)),
                ("define2", (0, 255, 0)),
                ("define3", (0, 0, 255)),
            ],
        )
        self.assertIsNone(keys)

        with self.assertRaises(ValueError):
            groups.parse_set_items(["1=red", "2=green", "W"])
        with self.assertRaises(ValueError):
            groups.parse_set_items(["W", "A"])
        with self.assertRaises(ValueError):
            groups.parse_set_items(["bad/name=red"])

    def test_resolve_group_layers_order_and_slots(self):
        local = {}
        groups.update_local_group(local, "first", (1, 2, 3), ["W", "A"])
        groups.update_local_group(local, "second", (4, 5, 6), ["A", "S"])
        groups.save_local_groups(local, str(self.group_file))
        layers = groups.resolve_group_layers(
            ["first=red", "second=green"], str(self.group_file)
        )
        self.assertEqual([layer[0] for layer in layers], ["first", "second"])
        self.assertIn(44, layers[0][2])  # W
        self.assertIn(64, layers[1][2])  # A
        with self.assertRaises(ValueError):
            groups.resolve_group_layers(["missing=red"], str(self.group_file))

    def test_import_cfg_ini_maps_vendor_groups(self):
        before = self.cfg_file.read_bytes()
        imported, warnings = groups.import_cfg_ini(str(self.cfg_file))
        self.assertEqual(warnings, [])
        self.assertEqual(
            imported["define1"]["keys"],
            ("Esc", "W", "A", "S", "D", "Up", "Down", "Left", "Right"),
        )
        self.assertEqual(
            imported["define2"]["keys"],
            (
                "1", "2", "3", "LShift", "RShift",
                "LCtrl", "RCtrl", "LAlt", "RAlt",
            ),
        )
        # Labels win over the old Cfg.ini slot numbering for the bottom row.
        self.assertEqual(imported["define3"]["keys"], ("X", "C", "ScrLk"))
        self.assertEqual(
            imported["define4"]["keys"],
            ("1", "2", "3", "4", "5", "6", "7", "Q", "W", "E", "R",
             "A", "S", "D", "F"),
        )
        self.assertEqual(
            imported["define5"]["keys"],
            (
                "W", "R", "A", "S", "D", "LShift", "RShift",
                "LCtrl", "RCtrl", "LAlt", "RAlt",
                "Up", "Down", "Left", "Right",
            ),
        )
        self.assertEqual(self.cfg_file.read_bytes(), before)

    def test_import_preserves_colours_and_warns_unknown_vks(self):
        self.cfg_file.write_text(cfg_ini_text(",ff"), encoding="utf-8")
        existing = {
            "define1": {"keys": ("Esc",), "color": (9, 8, 7)},
        }
        imported, warnings = groups.import_cfg_ini(str(self.cfg_file), existing)
        self.assertEqual(imported["define1"]["color"], (9, 8, 7))
        self.assertTrue(any("0xff" in warning for warning in warnings))
        self.assertIn("Esc", imported["define1"]["keys"])

    def test_import_requires_a_key_section(self):
        path = self.root / "no-key.ini"
        path.write_text("[OPT]\nGaoshouKey1=1b\n", encoding="utf-8")
        with self.assertRaises(groups.GroupError):
            groups.import_cfg_ini(str(path))


class GroupCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.group_file = str(self.root / "groups.json")
        self.cfg_file = self.root / "Cfg.ini"
        self.cfg_file.write_text(cfg_ini_text(), encoding="utf-8")

    def run_cli(self, argv, env=None):
        out = io.StringIO()
        err = io.StringIO()
        environ = {
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_STATE_HOME": str(self.root / "state"),
            "K622RGB_GROUP_FILE": self.group_file,
        }
        if env:
            environ.update(env)
        with mock.patch.dict(os.environ, environ):
            with mock.patch(
                "k622rgb.cli.controller.open_device"
            ) as opener:
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    code = cli.main(argv)
        return code, out.getvalue(), err.getvalue(), opener

    def test_list_does_not_open_device(self):
        code, out, err, opener = self.run_cli(["group", "list"])
        self.assertEqual(code, 0)
        self.assertIn("define groups:", out)
        self.assertIn("define1", out)
        self.assertRegex(out, r"define1\s+unset\s+W, A, S, D")
        self.assertIn("presets:", out)
        self.assertIn("fps", out)
        self.assertIn("local groups:", out)
        self.assertEqual(err, "")
        opener.assert_not_called()

    def test_set_and_apply(self):
        code, out, _err, opener = self.run_cli(
            ["group", "set", "1=red", "2=green"]
        )
        self.assertEqual(code, 0)
        self.assertIn("define1", out)
        self.assertIn("#ff0000", out)
        self.assertIn("saved groups to", out)
        opener.assert_not_called()

        code, out, _err, opener = self.run_cli(
            ["group", "apply", "--dry-run", "--no-state", "1"]
        )
        self.assertEqual(code, 0)
        self.assertIn("group: define1 = #ff0000", out)
        self.assertIn("dry run", out)
        opener.assert_not_called()

    def test_default_apply_order_puts_define5_before_define1(self):
        self.run_cli(["group", "set", "1=red", "5=cyan"])
        code, out, _err, opener = self.run_cli(
            ["group", "apply", "--dry-run", "--no-state"]
        )
        self.assertEqual(code, 0)
        self.assertLess(
            out.index("group: define5 = #00ffff"),
            out.index("group: define1 = #ff0000"),
        )
        opener.assert_not_called()

    def test_apply_skips_unset_and_errors_when_none_coloured(self):
        code, _out, err, _opener = self.run_cli(
            ["group", "apply", "--dry-run", "--no-state"]
        )
        self.assertEqual(code, 2)
        self.assertIn("no group colours configured", err)

        self.run_cli(["group", "set", "1=red"])
        code, out, err, _opener = self.run_cli(
            ["group", "apply", "--dry-run", "--no-state"]
        )
        self.assertEqual(code, 0)
        self.assertIn("group: define1 = #ff0000", out)
        self.assertIn("group define2 has no colour", err)

    def test_set_overlay_precedence(self):
        self.run_cli(["group", "set", "fps=red", "arrows=green"])
        code, out, _err, opener = self.run_cli(
            [
                "set", "--dry-run", "--no-state",
                "--all", "blue",
                "--group", "fps=ff0000",
                "--group", "arrows=00ff00",
                "Esc=white",
            ]
        )
        self.assertEqual(code, 0)
        self.assertIn("group: fps = #ff0000", out)
        self.assertIn("group: arrows = #00ff00", out)
        self.assertIn("set: Esc (slot 0) = #ffffff", out)
        opener.assert_not_called()

    def test_unknown_group_is_usage_error(self):
        code, _out, err, opener = self.run_cli(
            ["set", "--dry-run", "--no-state", "--group", "missing=red"]
        )
        self.assertEqual(code, 2)
        self.assertIn("unknown group", err)
        opener.assert_not_called()

    def test_import_via_cli_is_local_only(self):
        code, out, err, opener = self.run_cli(
            ["group", "import", str(self.cfg_file)]
        )
        self.assertEqual(code, 0)
        self.assertIn("imported:", out)
        self.assertIn("define1", out)
        self.assertEqual(err, "")
        opener.assert_not_called()
        self.assertTrue(Path(self.group_file).exists())

    def test_import_expands_tilde_in_path(self):
        code, out, _err, opener = self.run_cli(
            ["group", "import", "--dry-run", "~/Cfg.ini"],
            env={"HOME": str(self.root)},
        )
        self.assertEqual(code, 0)
        self.assertIn("from %s" % self.cfg_file, out)
        self.assertFalse(Path(self.group_file).exists())
        opener.assert_not_called()

        code, out, err, opener = self.run_cli(
            ["group", "import", "~/Cfg.ini"],
            env={"HOME": str(self.root)},
        )
        self.assertEqual(code, 0)
        self.assertIn("imported: %s" % self.cfg_file, out)
        self.assertEqual(err, "")
        opener.assert_not_called()
        self.assertTrue(Path(self.group_file).exists())

    def test_import_dry_run_does_not_write(self):
        code, out, _err, _opener = self.run_cli(
            ["group", "import", "--dry-run", str(self.cfg_file)]
        )
        self.assertEqual(code, 0)
        self.assertIn("dry run", out)
        self.assertFalse(Path(self.group_file).exists())

    def test_group_set_dry_run_does_not_write(self):
        code, out, _err, _opener = self.run_cli(
            ["group", "set", "--dry-run", "fps=red"]
        )
        self.assertEqual(code, 0)
        self.assertIn("dry run", out)
        self.assertFalse(Path(self.group_file).exists())


if __name__ == "__main__":
    unittest.main()

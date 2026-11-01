import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from k622rgb import controller, layout


class LayoutTestCase(unittest.TestCase):
    """Isolate every test from the user's real layout.json."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.layout_path = self.root / "layout.json"
        patcher = mock.patch.dict(
            os.environ, {layout.LAYOUT_FILE_ENV: str(self.layout_path)}
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        layout.clear_calibration_cache()
        self.addCleanup(layout.clear_calibration_cache)

    def write_layout(self, slots, version=layout.LAYOUT_VERSION):
        self.layout_path.write_text(
            json.dumps({"version": version, "slots": slots}), encoding="utf-8"
        )
        layout.clear_calibration_cache()


class SlotTableTests(LayoutTestCase):
    def test_has_eighty_seven_main_keys(self):
        self.assertEqual(len(layout.SLOT_NAMES), 87)

    def test_named_and_dead_slots_cover_the_main_block(self):
        self.assertEqual(
            set(layout.SLOT_NAMES) | set(layout.DEAD_SLOTS),
            set(range(102)),
        )
        self.assertFalse(set(layout.SLOT_NAMES) & set(layout.DEAD_SLOTS))

    def test_dead_slots_match_the_captured_map(self):
        self.assertEqual(
            set(layout.DEAD_SLOTS),
            {6, 23, 29, 41, 47, 70, 71, 75, 76, 77, 87, 88, 93, 99, 100},
        )

    def test_slot_count_matches_controller(self):
        self.assertEqual(controller.NUM_SLOTS, 126)

    def test_every_canonical_name_resolves(self):
        for slot, name in layout.SLOT_NAMES.items():
            with self.subTest(slot=slot, name=name):
                self.assertEqual(layout.resolve_key(name), slot)

    def test_every_alias_resolves_to_its_slot(self):
        for alias, canonical in layout.ALIASES.items():
            with self.subTest(alias=alias):
                expected = layout.resolve_key(canonical)
                self.assertEqual(layout.resolve_key(alias), expected)


class ResolveKeyTests(LayoutTestCase):
    def test_known_keys(self):
        cases = {
            "Esc": 0,
            "`": 1,
            "Tab": 2,
            "Caps": 3,
            "1": 7,
            "Q": 8,
            "A": 9,
            "Space": 35,
            "F1": 12,
            "F12": 78,
            "Bksp": 79,
            "Enter": 81,
            "PrtSc": 84,
            "ScrLk": 90,
            "Up": 94,
            "Right": 101,
        }
        for name, slot in cases.items():
            with self.subTest(name=name):
                self.assertEqual(layout.resolve_key(name), slot)

    def test_lookup_is_case_insensitive(self):
        self.assertEqual(layout.resolve_key("esc"), 0)
        self.assertEqual(layout.resolve_key("q"), 8)
        self.assertEqual(layout.resolve_key("ARROWRIGHT"), 101)

    def test_official_and_common_aliases(self):
        cases = {
            "Escape": 0,
            "CapsLock": 3,
            "LWin": 11,
            "Super": 11,
            "Meta": 11,
            "App": 65,
            "Application": 65,
            "Backspace": 79,
            "Back": 79,
            "Insert": 85,
            "Delete": 86,
            "SrcLock": 90,
            "ScrollLock": 90,
            "PrintScreen": 84,
            "Return": 81,
            "Spacebar": 35,
            "Grave": 1,
            "Backtick": 1,
            "Semicolon": 63,
            "Quote": 69,
            "Apostrophe": 69,
            "Comma": 52,
            "Period": 58,
            "Dot": 58,
            "Slash": 64,
            "Backslash": 80,
            "LeftBracket": 68,
            "RightBracket": 74,
            "Minus": 67,
            "Hyphen": 67,
            "Equals": 73,
            "ArrowUp": 94,
            "ArrowDown": 95,
            "ArrowLeft": 89,
            "ArrowRight": 101,
        }
        for name, slot in cases.items():
            with self.subTest(name=name):
                self.assertEqual(layout.resolve_key(name), slot)

    def test_numeric_slot_escape(self):
        self.assertEqual(layout.resolve_key("slot:0"), 0)
        self.assertEqual(layout.resolve_key("slot:6"), 6)
        self.assertEqual(layout.resolve_key("slot:125"), 125)
        self.assertEqual(layout.resolve_key("slot:0x7a"), 122)

    def test_slot_out_of_range_is_rejected(self):
        for text in ("slot:-1", "slot:126", "slot:999"):
            with self.subTest(text=text):
                with self.assertRaises(layout.UnknownKey):
                    layout.resolve_key(text)

    def test_bad_slot_syntax_is_rejected(self):
        for text in ("slot:", "slot:abc", "slot:1.5"):
            with self.subTest(text=text):
                with self.assertRaises(layout.UnknownKey):
                    layout.resolve_key(text)

    def test_unknown_key_is_rejected(self):
        for text in ("Bogus", "", "  ", "G1"):
            with self.subTest(text=text):
                with self.assertRaises(layout.UnknownKey):
                    layout.resolve_key(text)

    def test_unknown_key_is_a_value_error(self):
        self.assertTrue(issubclass(layout.UnknownKey, ValueError))

    def test_canonical_name(self):
        self.assertEqual(layout.canonical_name(0), "Esc")
        self.assertEqual(layout.canonical_name(101), "Right")
        self.assertEqual(layout.canonical_name(6), "slot:6")
        self.assertEqual(layout.canonical_name(102), "slot:102")


class CalibrationFileTests(LayoutTestCase):
    def test_missing_file_means_nothing_calibrated(self):
        self.assertEqual(layout.load_calibration(), {})

    def test_valid_file_maps_extra_slots(self):
        self.write_layout({"102": "G1", "103": "", "104": "Prev,Play"})
        self.assertEqual(
            layout.load_calibration(), {102: "G1", 103: "", 104: "Prev,Play"}
        )
        self.assertEqual(layout.resolve_key("G1"), 102)
        self.assertEqual(layout.resolve_key("g1"), 102)
        self.assertEqual(layout.resolve_key("Prev"), 104)
        self.assertEqual(layout.resolve_key("play"), 104)
        self.assertEqual(layout.canonical_name(102), "G1")
        self.assertEqual(layout.canonical_name(103), "slot:103")
        self.assertEqual(layout.canonical_name(104), "Prev,Play")

    def test_extra_aliases_resolve_after_calibration(self):
        self.write_layout({"102": "G1", "104": "Prev", "105": "Play"})
        cases = {
            "macro1": 102,
            "Macro1": 102,
            "previous": 104,
            "playpause": 105,
        }
        for name, slot in cases.items():
            with self.subTest(name=name):
                self.assertEqual(layout.resolve_key(name), slot)

    def test_uncalibrated_extra_has_actionable_message(self):
        with self.assertRaises(layout.UnknownKey) as ctx:
            layout.resolve_key("G1")
        self.assertIn("calibrate", str(ctx.exception))

    def test_dead_extra_slot_is_not_resolvable(self):
        self.write_layout({"103": ""})
        with self.assertRaises(layout.UnknownKey):
            layout.resolve_key("G1")
        self.assertEqual(layout.slot_status(103), "dead-calibrated")

    def test_slot_status(self):
        self.write_layout({"102": "G1", "103": "", "104": "Prev"})
        self.assertEqual(layout.slot_status(0), "main")
        self.assertEqual(layout.slot_status(6), "dead")
        self.assertEqual(layout.slot_status(102), "calibrated")
        self.assertEqual(layout.slot_status(103), "dead-calibrated")
        self.assertEqual(layout.slot_status(105), "uncalibrated")

    def test_duplicate_names_resolve_to_the_lowest_slot(self):
        self.write_layout({"110": "G1", "102": "G1"})
        self.assertEqual(layout.resolve_key("G1"), 102)

    def test_multi_key_slot_accepts_each_name(self):
        self.write_layout({"102": "G1,MR"})
        self.assertEqual(layout.resolve_key("G1"), 102)
        self.assertEqual(layout.resolve_key("MR"), 102)
        self.assertEqual(layout.canonical_name(102), "G1,MR")

    def test_malformed_json_is_a_layout_error(self):
        self.layout_path.write_text("{", encoding="utf-8")
        with self.assertRaises(layout.LayoutError):
            layout.load_calibration()

    def test_wrong_version_is_rejected(self):
        self.write_layout({"102": "G1"}, version=2)
        with self.assertRaises(layout.LayoutError) as ctx:
            layout.load_calibration()
        self.assertIn("version", str(ctx.exception))

    def test_main_slot_is_rejected(self):
        self.write_layout({"0": "G1"})
        with self.assertRaises(layout.LayoutError):
            layout.load_calibration()

    def test_out_of_range_slot_is_rejected(self):
        self.write_layout({"126": "G1"})
        with self.assertRaises(layout.LayoutError):
            layout.load_calibration()

    def test_main_key_name_is_accepted_as_a_note(self):
        self.write_layout({"110": "Esc"})
        self.assertEqual(layout.load_calibration(), {110: "Esc"})
        # The built-in main key still wins; the note does not shadow it.
        self.assertEqual(layout.resolve_key("Esc"), 0)
        self.assertEqual(layout.canonical_name(110), "Esc")
        self.assertEqual(layout.describe_value("Esc"), "Esc (main key!)")

    def test_arbitrary_name_is_accepted(self):
        self.write_layout({"102": "Bogus"})
        self.assertEqual(layout.load_calibration(), {102: "Bogus"})
        self.assertEqual(layout.resolve_key("Bogus"), 102)
        self.assertEqual(layout.describe_value("Bogus"), "Bogus (unexpected)")

    def test_labels_are_canonicalized_in_the_file(self):
        self.write_layout({"102": "escape", "104": "macro1", "105": "some label"})
        self.assertEqual(
            layout.load_calibration(),
            {102: "Esc", 104: "G1", 105: "some label"},
        )

    def test_builtin_key_wins_over_a_calibrated_note(self):
        self.write_layout({"110": "A"})
        self.assertEqual(layout.resolve_key("A"), 9)
        self.assertEqual(layout.resolve_key("a"), 9)
        self.assertEqual(layout.resolve_key("slot:110"), 110)

    def test_non_string_value_is_rejected(self):
        self.write_layout({"102": 1})
        with self.assertRaises(layout.LayoutError):
            layout.load_calibration()

    def test_save_round_trip(self):
        path = layout.save_calibration({102: "G1", 103: "", 110: "mute"})
        self.assertEqual(path, str(self.layout_path))
        document = json.loads(self.layout_path.read_text(encoding="utf-8"))
        self.assertEqual(document["version"], layout.LAYOUT_VERSION)
        self.assertEqual(
            document["slots"], {"102": "G1", "103": "", "110": "Mute"}
        )
        self.assertEqual(
            layout.load_calibration(), {102: "G1", 103: "", 110: "Mute"}
        )

    def test_save_rejects_invalid_slots(self):
        with self.assertRaises(layout.LayoutError):
            layout.save_calibration({0: "G1"})
        with self.assertRaises(layout.LayoutError):
            layout.save_calibration({"not-a-slot": "G1"})

    def test_save_accepts_arbitrary_labels(self):
        layout.save_calibration({102: "Esc", 103: "Bogus"})
        self.assertEqual(
            layout.load_calibration(), {102: "Esc", 103: "Bogus"}
        )

    def test_describe_value(self):
        self.assertEqual(layout.describe_value(None), "uncalibrated")
        self.assertEqual(layout.describe_value(""), "dead")
        self.assertEqual(layout.describe_value("G1"), "G1")
        self.assertEqual(layout.describe_value("G1,MR"), "G1, MR")
        self.assertEqual(layout.describe_value("Esc"), "Esc (main key!)")
        self.assertEqual(layout.describe_value("Bogus"), "Bogus (unexpected)")
        self.assertEqual(
            layout.describe_value("G1,Bogus"), "G1, Bogus (unexpected)"
        )

    def test_save_refreshes_the_cache(self):
        self.assertEqual(layout.load_calibration(), {})
        layout.save_calibration({102: "G1"})
        self.assertEqual(layout.resolve_key("G1"), 102)

    def test_default_path_uses_the_xdg_config_directory(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(layout.LAYOUT_FILE_ENV, None)
            os.environ[layout.CONFIG_DIR_ENV] = str(self.root / "cfg")
            self.assertEqual(
                layout.default_layout_path(),
                str(self.root / "cfg" / layout.LAYOUT_FILENAME),
            )


if __name__ == "__main__":
    unittest.main()

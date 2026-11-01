import unittest

from k622rgb import controller, layout


class SlotTableTests(unittest.TestCase):
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


class ResolveKeyTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

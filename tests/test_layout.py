import unittest

from k622rgb import controller, layout


class SlotTableTests(unittest.TestCase):
    def test_has_eighty_seven_main_keys(self):
        self.assertEqual(len(layout.SLOT_NAMES), 87)

    def test_slots_are_partitioned(self):
        groups = {
            "keys": set(layout.SLOT_NAMES),
            "aliases": set(layout.ALIAS_SLOTS),
            "zones": set(layout.ZONE_NAMES),
            "dead": set(layout.DEAD_SLOTS),
        }
        self.assertEqual(
            set().union(*groups.values()),
            set(range(controller.NUM_SLOTS)),
        )
        for left, left_slots in groups.items():
            for right, right_slots in groups.items():
                if left >= right:
                    continue
                self.assertFalse(
                    left_slots & right_slots,
                    "%s and %s overlap" % (left, right),
                )

    def test_dead_slots_match_the_observed_map(self):
        self.assertEqual(
            set(layout.DEAD_SLOTS),
            {
                1,
                17,
                18,
                19,
                20,
                38,
                39,
                40,
                41,
                59,
                60,
                61,
                62,
                75,
                80,
                81,
                82,
                83,
                85,
                96,
                98,
                100,
                101,
                102,
                103,
                104,
                108,
                109,
                111,
                112,
                116,
                117,
                122,
                123,
                124,
                125,
            },
        )

    def test_zone_slots(self):
        self.assertEqual(
            layout.ZONE_NAMES,
            {77: "LogoLeft", 78: "LogoCenter", 79: "LogoRight"},
        )
        for slot, name in layout.ZONE_NAMES.items():
            with self.subTest(slot=slot, name=name):
                self.assertEqual(layout.resolve_key(name), slot)
                self.assertEqual(layout.canonical_name(slot), name)
                self.assertEqual(layout.slot_kind(slot), "zone")

    def test_no_alias_slots(self):
        self.assertEqual(layout.ALIAS_SLOTS, {})
        self.assertEqual(layout.resolve_key("/"), 95)
        self.assertEqual(layout.canonical_name(95), "/")
        self.assertEqual(layout.slot_kind(95), "key")

    def test_no_unlit_keys(self):
        self.assertEqual(layout.UNLIT, frozenset())
        self.assertEqual(layout.resolve_key("X"), 87)
        self.assertEqual(layout.canonical_name(87), "X")

    def test_slot_count_matches_controller(self):
        self.assertEqual(controller.NUM_SLOTS, 126)

    def test_every_canonical_name_resolves(self):
        for slot, name in layout.SLOT_NAMES.items():
            with self.subTest(slot=slot, name=name):
                self.assertEqual(layout.resolve_key(name), slot)
        for slot, name in layout.ZONE_NAMES.items():
            with self.subTest(slot=slot, name=name):
                self.assertEqual(layout.resolve_key(name), slot)

    def test_every_alias_resolves_to_its_slot(self):
        aliases = list(layout.ALIASES.items()) + list(
            layout.ZONE_ALIASES.items()
        )
        for alias, canonical in aliases:
            with self.subTest(alias=alias):
                self.assertEqual(
                    layout.resolve_key(alias),
                    layout.resolve_key(canonical),
                )


class ResolveKeyTests(unittest.TestCase):
    def test_known_keys(self):
        cases = {
            "Esc": 0,
            "`": 21,
            "Tab": 42,
            "Caps": 63,
            "1": 22,
            "Q": 43,
            "A": 64,
            "Space": 110,
            "F1": 2,
            "F12": 13,
            "Bksp": 34,
            "Enter": 76,
            "PrtSc": 14,
            "ScrLk": 15,
            "Up": 99,
            "Right": 121,
            "W": 44,
            "Z": 86,
            "X": 87,
            "C": 88,
            "V": 89,
            "B": 90,
            "N": 91,
            "M": 92,
            ",": 93,
            ".": 94,
            "/": 95,
            "LogoLeft": 77,
            "LogoCenter": 78,
            "LogoRight": 79,
        }
        for name, slot in cases.items():
            with self.subTest(name=name):
                self.assertEqual(layout.resolve_key(name), slot)

    def test_lookup_is_case_insensitive(self):
        self.assertEqual(layout.resolve_key("esc"), 0)
        self.assertEqual(layout.resolve_key("q"), 43)
        self.assertEqual(layout.resolve_key("ARROWRIGHT"), 121)
        self.assertEqual(layout.resolve_key("logoleft"), 77)

    def test_official_and_common_aliases(self):
        cases = {
            "Escape": "Esc",
            "CapsLock": "Caps",
            "LWin": "Win",
            "Super": "Win",
            "Meta": "Win",
            "App": "Menu",
            "Application": "Menu",
            "Backspace": "Bksp",
            "Back": "Bksp",
            "Insert": "Ins",
            "Delete": "Del",
            "SrcLock": "ScrLk",
            "ScrollLock": "ScrLk",
            "PrintScreen": "PrtSc",
            "Return": "Enter",
            "Spacebar": "Space",
            "Grave": "`",
            "Backtick": "`",
            "Semicolon": ";",
            "Quote": "'",
            "Apostrophe": "'",
            "Comma": ",",
            "Period": ".",
            "Dot": ".",
            "Slash": "/",
            "Backslash": "\\",
            "LeftBracket": "[",
            "RightBracket": "]",
            "Minus": "-",
            "Hyphen": "-",
            "Equals": "=",
            "ArrowUp": "Up",
            "ArrowDown": "Down",
            "ArrowLeft": "Left",
            "ArrowRight": "Right",
            "logo1": "LogoLeft",
            "logo-center": "LogoCenter",
            "logo3": "LogoRight",
        }
        for alias, canonical in cases.items():
            with self.subTest(alias=alias):
                self.assertEqual(
                    layout.resolve_key(alias),
                    layout.resolve_key(canonical),
                )

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
        self.assertEqual(layout.canonical_name(121), "Right")
        self.assertEqual(layout.canonical_name(1), "slot:1")
        self.assertEqual(layout.canonical_name(77), "LogoLeft")
        self.assertEqual(layout.canonical_name(87), "X")
        self.assertEqual(layout.canonical_name(94), ".")
        self.assertEqual(layout.canonical_name(95), "/")
        self.assertEqual(layout.canonical_name(85), "slot:85")

    def test_slot_kind(self):
        self.assertEqual(layout.slot_kind(0), "key")
        self.assertEqual(layout.slot_kind(77), "zone")
        self.assertEqual(layout.slot_kind(87), "key")
        self.assertEqual(layout.slot_kind(95), "key")
        self.assertEqual(layout.slot_kind(85), "dead")
        self.assertEqual(layout.slot_kind(1), "dead")


if __name__ == "__main__":
    unittest.main()
